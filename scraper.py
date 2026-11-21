# -*- coding: utf-8 -*-
"""
Open eClass deadline scraper -> SQLite
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests

if getattr(sys, "frozen", False):
  BASE_DIR = Path(sys.executable).resolve().parent
else:
  BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.json"

log = logging.getLogger("eclass")
LOCAL_TZ = ZoneInfo("Europe/Athens")

NUMERIC_DATE_RE = re.compile(
    r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})(?:\s*[-–]?\s*(\d{1,2}:\d{2}(?::\d{2})?))?"
)
DATE_FORMATS = ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y")

GREEK_MONTHS = {
    "\u03b9\u03b1\u03bd\u03bf\u03c5\u03b1\u03c1\u03af\u03bf\u03c5": 1,
    "\u03c6\u03b5\u03b2\u03c1\u03bf\u03c5\u03b1\u03c1\u03af\u03bf\u03c5": 2,
    "\u03bc\u03b1\u03c1\u03c4\u03af\u03bf\u03c5": 3,
    "\u03b1\u03c0\u03c1\u03b9\u03bb\u03af\u03bf\u03c5": 4,
    "\u03bc\u03b1\u0390\u03bf\u03c5": 5,
    "\u03bc\u03b1\u03b9\u03bf\u03c5": 5,
    "\u03b9\u03bf\u03c5\u03bd\u03af\u03bf\u03c5": 6,
    "\u03b9\u03bf\u03c5\u03bb\u03af\u03bf\u03c5": 7,
    "\u03b1\u03c5\u03b3\u03bf\u03cd\u03c3\u03c4\u03bf\u03c5": 8,
    "\u03c3\u03b5\u03c0\u03c4\u03b5\u03bc\u03b2\u03c1\u03af\u03bf\u03c5": 9,
    "\u03bf\u03ba\u03c4\u03c9\u03b2\u03c1\u03af\u03bf\u03c5": 10,
    "\u03bd\u03bf\u03b5\u03bc\u03b2\u03c1\u03af\u03bf\u03c5": 11,
    "\u03b4\u03b5\u03ba\u03b5\u03bc\u03b2\u03c1\u03af\u03bf\u03c5": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

TEXT_DATE_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z\u0370-\u03ff\u1f00-\u1fff]+)\s+(\d{4})"
    r"(?:\s*[-–]?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([πμΠΜ]\.?\s*[μΜ]\.?|am|pm)?)?",
    re.IGNORECASE,
)

DEADLINE_HEADERS = (
    "deadline",
    "due",
    "\u03c0\u03c1\u03bf\u03b8\u03b5\u03c3\u03bc\u03af\u03b1",
    "\u03bb\u03ae\u03be\u03b7",
    "\u03ad\u03c9\u03c2",
    "\u03ba\u03b1\u03c4\u03b1\u03bb\u03b7\u03ba\u03c4\u03b9\u03ba\u03ae",
    "\u03c5\u03c0\u03bf\u03b2\u03bf\u03bb\u03ae",
)

# Επικεφαλίδα στήλης "Έχει υποβληθεί" / "Submitted"
SUBMITTED_HEADERS = (
    "\u03c5\u03c0\u03bf\u03b2\u03bb\u03b7\u03b8\u03b5\u03af",
    "submitted",
)


@dataclass
class Config:
  base_url: str
  db_path: str
  timeout: int
  delay: float
  user_agent: str


def load_config(path: Path = CONFIG_PATH) -> Config:
  raw = {}
  if path.exists():
    with path.open(encoding="utf-8") as f:
      raw = json.load(f)
  if os.getenv("ECLASS_BASE_URL"):
    raw["url"] = os.environ["ECLASS_BASE_URL"]
  if "url" not in raw:
    sys.exit("config.json must contain the key 'url'.")
  db_path = Path(raw.get("db_path", "eclass.db"))
  if not db_path.is_absolute():
    db_path = BASE_DIR / db_path
  return Config(
      base_url=raw["url"].rstrip("/") + "/",
      db_path=str(db_path),
      timeout=int(raw.get("timeout", 20)),
      delay=float(raw.get("delay_seconds", 1.0)),
      user_agent=raw.get("user_agent", "Mozilla/5.0 (eclass-deadline-scraper)"),
  )


def load_credentials() -> tuple[str, str]:
  env_path = BASE_DIR / ".env"
  if not env_path.exists():
    sys.exit(f".env file not found: {env_path}")
  load_dotenv(env_path, encoding="utf-8")
  username = os.getenv("ECLASS_USERNAME")
  password = os.getenv("ECLASS_PASSWORD")
  if not username or not password:
    sys.exit("Set ECLASS_USERNAME and ECLASS_PASSWORD in the .env file.")
  return username, password


class EClassClient:

  def __init__(self, cfg: Config):
    self.cfg = cfg
    self.session = requests.Session()
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry = Retry(total=3, connect=3, read=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET"}))
    adapter = HTTPAdapter(max_retries=retry)
    self.session.mount("https://", adapter)
    self.session.mount("http://", adapter)
    self.session.headers.update({"User-Agent": cfg.user_agent})

  def _get(self, url: str) -> BeautifulSoup:
    resp = self.session.get(url, timeout=self.cfg.timeout)
    resp.raise_for_status()
    time.sleep(self.cfg.delay)
    return BeautifulSoup(resp.text, "html.parser")

  def login(self, username: str, password: str) -> None:
    self.session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    })

    cas_entry = urljoin(self.cfg.base_url, "modules/auth/cas.php")
    resp = self.session.get(cas_entry, timeout=self.cfg.timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    pwd_input = soup.find("input", {"type": "password"})
    form = pwd_input.find_parent("form") if pwd_input else soup.find("form")
    if not form:
      sys.exit("SSO Login error: Δεν βρέθηκε φόρμα σύνδεσης στη σελίδα CAS.")

    payload = {}
    for inp in form.find_all("input"):
      name = inp.get("name")
      if name:
        payload[name] = inp.get("value", "")

    payload["username"] = username
    payload["password"] = password

    action_url = urljoin(resp.url, form.get("action", ""))
    post_resp = self.session.post(
        action_url,
        data=payload,
        headers={"Referer": resp.url},
        timeout=self.cfg.timeout,
    )
    post_resp.raise_for_status()

    is_logged_in = (
        "sso.uowm.gr" not in post_resp.url
        and "portfolio.php" in post_resp.text
    )
    if not is_logged_in:
      sys.exit("SSO Login failed: check the credentials in the .env file.")

    log.info("SSO Login successful.")

  def discover_courses(self) -> dict[str, str]:
    soup = self._get(urljoin(self.cfg.base_url, "main/portfolio.php"))
    courses: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
      m = re.search(r"/courses/([A-Za-z0-9_-]+)/?", a["href"])
      if m and a.get_text(strip=True):
        courses.setdefault(m.group(1), a.get_text(strip=True))
    log.info("Found %d courses.", len(courses))
    return courses

  def fetch_assignments(self, course_code: str) -> list[dict]:
    url = urljoin(
        self.cfg.base_url, f"modules/work/index.php?course={course_code}"
    )
    soup = self._get(url)
    return parse_assignments(soup, url)


def parse_date(text: str) -> datetime | None:
  tm = TEXT_DATE_RE.search(text)
  if tm:
    day = int(tm.group(1))
    month_name = tm.group(2).lower()
    year = int(tm.group(3))
    month = GREEK_MONTHS.get(month_name)
    if month:
      hour = int(tm.group(4)) if tm.group(4) else 23
      minute = int(tm.group(5)) if tm.group(5) else 59
      second = int(tm.group(6)) if tm.group(6) else 0
      meridiem = (tm.group(7) or "").lower().replace(".", "").replace(" ", "")
      if meridiem in ("\u03c0\u03bc", "am"):
        if hour == 12:
          hour = 0
      elif meridiem in ("\u03bc\u03bc", "pm"):
        if hour != 12:
          hour += 12
      try:
        return datetime(year, month, day, hour, minute, second, tzinfo=LOCAL_TZ)
      except ValueError:
        pass

  m = NUMERIC_DATE_RE.search(text)
  if not m:
    return None
  date_part = re.sub(r"[/.]", "-", m.group(1))
  candidate = f"{date_part} {m.group(2)}" if m.group(2) else date_part
  for fmt in DATE_FORMATS:
    try:
      return datetime.strptime(candidate, fmt).replace(tzinfo=LOCAL_TZ)
    except ValueError:
      continue
  return None


def _is_cell_submitted(cell) -> bool:
  """Ελέγχει αν το κελί της στήλης 'Έχει υποβληθεί' δείχνει ολοκληρωμένη υποβολή."""
  html_str = str(cell).lower()
  text_str = cell.get_text(" ", strip=True).lower()

  # Αν έχει κλεψύδρα ή Χ, σίγουρα ΔΕΝ έχει υποβληθεί
  if any(k in html_str for k in ("hourglass", "fa-times", "fa-xmark", "danger")):
    return False

  # Αν έχει εικονίδιο check / πράσινο success ή θετικό κείμενο, έχει υποβληθεί
  if any(k in html_str for k in ("fa-check", "check-circle", "text-success", "success")):
    return True
  if text_str in ("\u03bd\u03b1\u03b9", "yes", "\u03c5\u03c0\u03bf\u03b2\u03bb\u03ae\u03b8\u03b7\u03ba\u03b5", "submitted"):
    return True

  return False


def parse_assignments(soup: BeautifulSoup, page_url: str) -> list[dict]:
  results = []
  for table in soup.find_all("table"):
    headers = [
        th.get_text(" ", strip=True).lower() for th in table.find_all("th")
    ]
    deadline_idx = next(
        (
            i
            for i, h in enumerate(headers)
            if any(k in h for k in DEADLINE_HEADERS)
        ),
        None,
    )
    submitted_idx = next(
        (
            i
            for i, h in enumerate(headers)
            if any(k in h for k in SUBMITTED_HEADERS)
        ),
        None,
    )

    for row in table.find_all("tr"):
      cells = row.find_all("td")
      if not cells:
        continue
      link = row.find("a", href=True)
      if not link:
        continue

      submitted = False
      if submitted_idx is not None and submitted_idx < len(cells):
        submitted = _is_cell_submitted(cells[submitted_idx])
      else:
        # Fallback: ελέγχουμε τα υπόλοιπα κελιά της γραμμής για check icon
        submitted = any(_is_cell_submitted(c) for c in cells)

      deadline = None
      if deadline_idx is not None and deadline_idx < len(cells):
        deadline = parse_date(cells[deadline_idx].get_text(" ", strip=True))

      if deadline is None:
        all_dates = [
            parse_date(c.get_text(" ", strip=True)) for c in cells
        ]
        valid_dates = [d for d in all_dates if d is not None]
        if valid_dates:
          deadline = valid_dates[-1]

      if deadline is None:
        continue

      results.append({
          "title": link.get_text(strip=True),
          "deadline": deadline.isoformat(timespec="minutes"),
          "url": urljoin(page_url, link["href"]),
          "submitted": submitted,
      })
  return results


SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    code  TEXT PRIMARY KEY,
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deadlines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT NOT NULL REFERENCES courses(code),
    title       TEXT NOT NULL,
    deadline    TEXT NOT NULL,
    url         TEXT,
    scraped_at  TEXT NOT NULL,
    UNIQUE (course_code, title, deadline)
);
CREATE INDEX IF NOT EXISTS idx_deadlines_deadline ON deadlines(deadline);
"""


def init_db(path: str) -> sqlite3.Connection:
  conn = sqlite3.connect(path)
  conn.executescript(SCHEMA)
  return conn


def save(
    conn: sqlite3.Connection, code: str, title: str, items: list[dict]
) -> tuple[int, int]:
  now = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")
  conn.execute(
      "INSERT INTO courses (code, title) VALUES (?, ?) "
      "ON CONFLICT(code) DO UPDATE SET title = excluded.title",
      (code, title),
  )
  new = 0
  removed = 0
  for it in items:
    if it.get("submitted"):
      # Αν έχει ήδη υποβληθεί, τη διαγράφουμε από τη βάση ώστε να εξαφανιστεί από το widget
      cur = conn.execute(
          "DELETE FROM deadlines WHERE course_code = ? AND title = ?",
          (code, it["title"]),
      )
      removed += cur.rowcount
    else:
      cur = conn.execute(
          "INSERT OR IGNORE INTO deadlines "
          "(course_code, title, deadline, url, scraped_at) VALUES (?, ?, ?, ?,"
          " ?)",
          (code, it["title"], it["deadline"], it["url"], now),
      )
      new += cur.rowcount
  conn.commit()
  return new, removed


def configure_output() -> None:
  for stream in (sys.stdout, sys.stderr):
    try:
      stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
      pass


def main(username: str | None = None, password: str | None = None) -> None:
  configure_output()
  logging.basicConfig(
      level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
  )
  cfg = load_config()
  if not username or not password:
    username, password = load_credentials()

  client = EClassClient(cfg)
  client.login(username, password)

  conn = init_db(cfg.db_path)
  total_new = 0
  total_removed = 0
  try:
    for code, title in client.discover_courses().items():
      try:
        items = client.fetch_assignments(code)
      except requests.RequestException as exc:
        log.warning("Skipping course %s: %s", code, exc)
        continue
      added, removed = save(conn, code, title, items)
      total_new += added
      total_removed += removed
      pending_count = sum(1 for i in items if not i.get("submitted"))
      log.info(
          "Course %s: %d pending (%d new, %d submitted/removed)",
          code,
          pending_count,
          added,
          removed,
      )
  finally:
    conn.close()

  log.info(
      "Done. New: %d, Removed submitted: %d -> %s",
      total_new,
      total_removed,
      cfg.db_path,
  )


if __name__ == "__main__":
  main()