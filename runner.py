import os
from pathlib import Path
import subprocess
import sys
import traceback

from dotenv import load_dotenv
import login_ui
import scraper
import widget

if getattr(sys, "frozen", False):
  BASE_DIR = Path(sys.executable).resolve().parent
else:
  BASE_DIR = Path(__file__).resolve().parent


def has_saved_credentials() -> bool:
  env_path = BASE_DIR / ".env"
  if not env_path.exists():
    return False
  load_dotenv(env_path, override=True, encoding="utf-8")
  return bool(os.getenv("ECLASS_USERNAME") and os.getenv("ECLASS_PASSWORD"))


def main() -> None:
  if "--widget-only" in sys.argv:
    widget.main()
    return

  username = None
  password = None

  # Αν δεν υπάρχουν αποθηκευμένα στοιχεία, ζήτα τα με γραφικό παράθυρο
  if not has_saved_credentials():
    creds = login_ui.prompt_credentials()
    if not creds:
      sys.exit(0)
    username, password = creds

  while True:
    try:
      scraper.main(username=username, password=password)
      break
    except SystemExit as e:
      err_text = str(e)
      # Αν απέτυχε το login (π.χ. λάθος κωδικός), σβήσε το λάθος .env και ξαναζήτα στοιχεία
      if "Login failed" in err_text:
        env_path = BASE_DIR / ".env"
        if env_path.exists():
          env_path.unlink()
        creds = login_ui.prompt_credentials(
            error_msg="Λάθος στοιχεία σύνδεσης. Προσπαθήστε ξανά."
        )
        if not creds:
          sys.exit(0)
        username, password = creds
      else:
        print(f"\n[ΤΕΡΜΑΤΙΣΜΟΣ]: {err_text}")
        input("\nΠάτα ENTER για να κλείσει το παράθυρο...")
        return
    except Exception:
      print("\n[ΚΡΙΣΙΜΟ ΣΦΑΛΜΑ]:")
      traceback.print_exc()
      input("\nΠάτα ENTER για να κλείσει το παράθυρο...")
      return

  if getattr(sys, "frozen", False):
    cmd = [sys.executable, "--widget-only"]
  else:
    cmd = [sys.executable, __file__, "--widget-only"]

  creationflags = 0
  if sys.platform == "win32":
    creationflags = (
        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    )

  subprocess.Popen(cmd, creationflags=creationflags, close_fds=True)
  sys.exit(0)


if __name__ == "__main__":
  main()