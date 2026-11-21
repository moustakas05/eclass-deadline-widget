# -*- coding: utf-8 -*-
"""
Desktop deadline widget (CustomTkinter) for the eClass scraper database.
"""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys
import threading
import webbrowser

import customtkinter as ctk
import scraper

if getattr(sys, "frozen", False):
  BASE_DIR = Path(sys.executable).resolve().parent
else:
  BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "widget_state.json"

BG = "#0f172a"
HEADER_BG = "#111827"
CARD_BG = "#1e293b"
BORDER = "#334155"
TEXT = "#f1f5f9"
MUTED = "#94a3b8"
RED = "#ef4444"
ORANGE = "#f59e0b"
GREEN = "#22c55e"
ACCENT = "#3b82f6"

GLYPH_REFRESH = "\u21bb"
GLYPH_CLOSE = "\u2715"
GLYPH_BG = "\u25be"


@dataclass
class Settings:
  db_path: Path
  refresh_seconds: int
  purge_outdated: bool
  grace_minutes: int
  max_items: int
  width: int
  height: int
  opacity: float


def load_settings() -> Settings:
  raw: dict = {}
  if CONFIG_PATH.exists():
    try:
      with CONFIG_PATH.open(encoding="utf-8") as f:
        loaded = json.load(f)
        if isinstance(loaded, dict):
          raw = loaded
    except (OSError, ValueError):
      raw = {}
  w = raw.get("widget", {})
  if not isinstance(w, dict):
    w = {}
  db_path = Path(raw.get("db_path", "eclass.db"))
  if not db_path.is_absolute():
    db_path = BASE_DIR / db_path
  return Settings(
      db_path=db_path,
      refresh_seconds=max(5, int(w.get("refresh_seconds", 30))),
      purge_outdated=bool(w.get("purge_outdated", True)),
      grace_minutes=max(0, int(w.get("grace_minutes", 0))),
      max_items=max(1, int(w.get("max_items", 50))),
      width=int(w.get("width", 350)),
      height=int(w.get("height", 480)),
      opacity=min(1.0, max(0.3, float(w.get("opacity", 0.95)))),
  )


def load_state() -> dict:
  try:
    with STATE_PATH.open(encoding="utf-8") as f:
      data = json.load(f)
    return data if isinstance(data, dict) else {}
  except (OSError, ValueError):
    return {}


def save_state(state: dict) -> None:
  try:
    with STATE_PATH.open("w", encoding="utf-8") as f:
      json.dump(state, f)
  except OSError:
    pass


class WidgetError(Exception):
  """Raised with a user-friendly message when the data cannot be loaded."""


@dataclass
class Task:
  id: int
  course: str
  title: str
  deadline: datetime
  url: str


def load_tasks(settings: Settings, now: datetime) -> list[Task]:
  if not settings.db_path.exists():
    raise WidgetError(
        f"Database not found:\n{settings.db_path}\nRun scraper first."
    )
  cutoff = (now - timedelta(minutes=settings.grace_minutes)).isoformat(
      timespec="minutes"
  )
  uri = settings.db_path.resolve().as_uri() + "?mode=rw"
  try:
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
      if settings.purge_outdated:
        conn.execute("DELETE FROM deadlines WHERE deadline < ?", (cutoff,))
        conn.commit()
      rows = conn.execute(
          "SELECT d.id, COALESCE(c.title, d.course_code), d.title, "
          "d.deadline, COALESCE(d.url, '') "
          "FROM deadlines d LEFT JOIN courses c ON c.code = d.course_code "
          "WHERE d.deadline >= ? ORDER BY d.deadline ASC LIMIT ?",
          (cutoff, settings.max_items),
      ).fetchall()
  except sqlite3.Error as exc:
    raise WidgetError(f"Database error:\n{exc}") from exc

  tasks = []
  for row_id, course, title, deadline, url in rows:
    try:
      parsed = datetime.fromisoformat(deadline)
    except ValueError:
      continue
    tasks.append(Task(row_id, course, title, parsed, url))
  return tasks


def describe_deadline(deadline: datetime, now: datetime) -> tuple[str, str]:
  secs = int((deadline - now).total_seconds())
  if secs <= 0:
    return "due now", RED
  days, rem = divmod(secs, 86400)
  hours, rem = divmod(rem, 3600)
  minutes = rem // 60
  if days:
    text = f"{days}d {hours}h left"
  elif hours:
    text = f"{hours}h {minutes}m left"
  else:
    text = f"{minutes}m left"
  if secs < 86400:
    return text, RED
  if secs < 3 * 86400:
    return text, ORANGE
  return text, GREEN


class DeadlineWidget(ctk.CTk):

  def __init__(self, settings: Settings):
    super().__init__()
    self.settings = settings
    self.state_data = load_state()
    self.pinned = bool(self.state_data.get("pinned", False))
    self._signature = None
    self._cards: dict[int, tuple[Task, ctk.CTkLabel, ctk.CTkFrame]] = {}
    self._after_id = None
    self._drag_offset = (0, 0)
    self._is_syncing = False

    self._configure_window()
    self._build_layout()
    self._bind_focus_behavior()
    self.refresh()

  def _configure_window(self) -> None:
    s = self.settings
    self.title("Deadlines")
    self.overrideredirect(True)
    self.configure(fg_color=BG)
    try:
      self.attributes("-alpha", s.opacity)
    except Exception:
      pass
    self.attributes("-topmost", self.pinned)
    x = int(self.state_data.get("x", 60))
    y = int(self.state_data.get("y", 60))
    self.geometry(f"{s.width}x{s.height}+{x}+{y}")
    self.protocol("WM_DELETE_WINDOW", self.close)

  def _bind_focus_behavior(self) -> None:
    self.bind("<FocusOut>", self._on_focus_out)
    self.bind("<Button-1>", self._on_window_click, add="+")

  def _on_focus_out(self, _event) -> None:
    if not self.pinned:
      self.after(50, self._check_and_lower)

  def _win32_send_to_bottom(self) -> None:
    if sys.platform == "win32":
      try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
        HWND_BOTTOM = 1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        ctypes.windll.user32.SetWindowPos(
            hwnd,
            HWND_BOTTOM,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        return
      except Exception:
        pass
    self.lower()

  def _check_and_lower(self) -> None:
    try:
      if not self.pinned and self.focus_displayof() is None:
        self._win32_send_to_bottom()
    except Exception:
      pass

  def _on_window_click(self, _event) -> None:
    self.lift()
    self.focus_force()

  def send_to_background(self) -> None:
    if self.pinned:
      self.pinned = False
      self.attributes("-topmost", False)
      self._style_pin_button()
      self._persist_state()
    self._win32_send_to_bottom()

  def _build_layout(self) -> None:
    shell = ctk.CTkFrame(
        self, corner_radius=0, fg_color=BG, border_width=1, border_color=BORDER
    )
    shell.pack(fill="both", expand=True)

    header = ctk.CTkFrame(shell, corner_radius=0, fg_color=HEADER_BG, height=42)
    header.pack(fill="x")
    header.pack_propagate(False)

    title = ctk.CTkLabel(
        header,
        text="Deadlines",
        font=ctk.CTkFont(size=15, weight="bold"),
        text_color=TEXT,
    )
    title.pack(side="left", padx=(12, 6))
    self.count_label = ctk.CTkLabel(
        header, text="", font=ctk.CTkFont(size=12), text_color=MUTED
    )
    self.count_label.pack(side="left")

    close_btn = ctk.CTkButton(
        header,
        text=GLYPH_CLOSE,
        width=28,
        height=28,
        fg_color="transparent",
        hover_color=RED,
        text_color=TEXT,
        command=self.close,
    )
    close_btn.pack(side="right", padx=(0, 8))

    bg_btn = ctk.CTkButton(
        header,
        text=GLYPH_BG,
        width=28,
        height=28,
        fg_color="transparent",
        hover_color=BORDER,
        text_color=TEXT,
        font=ctk.CTkFont(size=14, weight="bold"),
        command=self.send_to_background,
    )
    bg_btn.pack(side="right", padx=2)

    self.sync_btn = ctk.CTkButton(
        header,
        text=f"{GLYPH_REFRESH} Sync",
        width=58,
        height=28,
        fg_color=CARD_BG,
        hover_color=ACCENT,
        text_color=TEXT,
        font=ctk.CTkFont(size=12, weight="bold"),
        command=self.manual_sync,
    )
    self.sync_btn.pack(side="right", padx=2)

    self.pin_btn = ctk.CTkButton(
        header,
        text="Pin",
        width=38,
        height=28,
        hover_color=BORDER,
        text_color=TEXT,
        command=self.toggle_pin,
    )
    self.pin_btn.pack(side="right", padx=2)
    self._style_pin_button()

    for draggable in (header, title, self.count_label):
      draggable.bind("<ButtonPress-1>", self._start_drag)
      draggable.bind("<B1-Motion>", self._on_drag)
      draggable.bind("<ButtonRelease-1>", self._end_drag)

    self.body = ctk.CTkScrollableFrame(shell, fg_color="transparent")
    self.body.pack(fill="both", expand=True, padx=4, pady=(6, 0))

    self.footer = ctk.CTkLabel(
        shell, text="", font=ctk.CTkFont(size=11), text_color=MUTED, height=22
    )
    self.footer.pack(fill="x", pady=(0, 4))

  def manual_sync(self) -> None:
    if self._is_syncing:
      return
    self._is_syncing = True
    self.sync_btn.configure(state="disabled", text="Syncing...")
    self.footer.configure(text="Syncing with eClass...", text_color=ACCENT)
    threading.Thread(target=self._run_sync_worker, daemon=True).start()

  def _run_sync_worker(self) -> None:
    error_msg = None
    try:
      scraper.main()
    except SystemExit as exc:
      error_msg = str(exc)
    except Exception as exc:
      error_msg = f"Sync error: {exc}"
    self.after(0, lambda: self._on_sync_complete(error_msg))

  def _on_sync_complete(self, error_msg: str | None) -> None:
    self._is_syncing = False
    self.sync_btn.configure(state="normal", text=f"{GLYPH_REFRESH} Sync")
    if error_msg:
      self.footer.configure(text=error_msg[:55], text_color=RED)
    else:
      self.refresh()
      now_str = datetime.now().strftime("%H:%M:%S")
      self.footer.configure(text=f"Synced at {now_str}", text_color=GREEN)

  def _start_drag(self, event) -> None:
    self._drag_offset = (
        event.x_root - self.winfo_x(),
        event.y_root - self.winfo_y(),
    )

  def _on_drag(self, event) -> None:
    dx, dy = self._drag_offset
    self.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

  def _end_drag(self, _event) -> None:
    self._persist_state()

  def toggle_pin(self) -> None:
    self.pinned = not self.pinned
    self.attributes("-topmost", self.pinned)
    if self.pinned:
      self.lift()
    self._style_pin_button()
    self._persist_state()

  def _style_pin_button(self) -> None:
    self.pin_btn.configure(fg_color=ACCENT if self.pinned else "transparent")

  def _persist_state(self) -> None:
    self.state_data.update(
        {"x": self.winfo_x(), "y": self.winfo_y(), "pinned": self.pinned}
    )
    save_state(self.state_data)

  def close(self) -> None:
    if self._after_id is not None:
      self.after_cancel(self._after_id)
    self._persist_state()
    self.destroy()

  def refresh(self) -> None:
    if self._after_id is not None:
      self.after_cancel(self._after_id)
    now = datetime.now()
    message = None
    tasks: list[Task] = []
    try:
      tasks = load_tasks(self.settings, now)
    except WidgetError as exc:
      message = str(exc)

    signature = (tuple((t.id, t.deadline) for t in tasks), message)
    if signature != self._signature:
      self._rebuild(tasks, message)
      self._signature = signature
    self._update_countdowns(now)

    self.count_label.configure(text=f"{len(tasks)} upcoming" if not message else "")
    if not self._is_syncing:
      self.footer.configure(
          text=f"Updated {now.strftime('%H:%M:%S')}", text_color=MUTED
      )
    self._after_id = self.after(
        self.settings.refresh_seconds * 1000, self.refresh
    )

  def _rebuild(self, tasks: list[Task], message: str | None) -> None:
    for child in self.body.winfo_children():
      child.destroy()
    self._cards.clear()

    if message or not tasks:
      ctk.CTkLabel(
          self.body,
          text=message or "No upcoming deadlines.",
          text_color=MUTED,
          wraplength=self.settings.width - 50,
          justify="center",
      ).pack(pady=40, padx=10)
      return
    for task in tasks:
      self._build_card(task)

  def _build_card(self, task: Task) -> None:
    wrap = self.settings.width - 70
    card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=CARD_BG)
    card.pack(fill="x", padx=4, pady=4)
    card.grid_columnconfigure(1, weight=1)

    accent = ctk.CTkFrame(card, width=5, corner_radius=3, fg_color=GREEN)
    accent.grid(row=0, column=0, sticky="ns", padx=(6, 0), pady=8)

    content = ctk.CTkFrame(card, fg_color="transparent")
    content.grid(row=0, column=1, sticky="ew", padx=10, pady=6)

    ctk.CTkLabel(
        content,
        text=task.course,
        font=ctk.CTkFont(size=11),
        text_color=MUTED,
        anchor="w",
        justify="left",
        wraplength=wrap,
    ).pack(fill="x")
    ctk.CTkLabel(
        content,
        text=task.title,
        font=ctk.CTkFont(size=14, weight="bold"),
        text_color=TEXT,
        anchor="w",
        justify="left",
        wraplength=wrap,
    ).pack(fill="x")

    bottom = ctk.CTkFrame(content, fg_color="transparent")
    bottom.pack(fill="x", pady=(2, 0))
    ctk.CTkLabel(
        bottom,
        text=task.deadline.strftime("%a %d %b, %H:%M"),
        font=ctk.CTkFont(size=12),
        text_color=MUTED,
    ).pack(side="left")
    countdown = ctk.CTkLabel(
        bottom, text="", font=ctk.CTkFont(size=12, weight="bold")
    )
    countdown.pack(side="right")

    self._bind_open(card, task.url)
    self._cards[task.id] = (task, countdown, accent)

  def _bind_open(self, widget, url: str) -> None:
    if not url:
      return
    widget.bind("<Double-Button-1>", lambda _e: webbrowser.open(url))
    for child in widget.winfo_children():
      self._bind_open(child, url)

  def _update_countdowns(self, now: datetime) -> None:
    for task, label, accent in self._cards.values():
      text, color = describe_deadline(task.deadline, now)
      label.configure(text=text, text_color=color)
      accent.configure(fg_color=color)


def main() -> None:
  ctk.set_appearance_mode("dark")
  ctk.set_default_color_theme("blue")
  app = DeadlineWidget(load_settings())
  app.mainloop()


if __name__ == "__main__":
  main()
