# Open eClass Deadline Widget (UOWM)

A Windows desktop widget for UOWM Open eClass. It signs in through university CAS, reads enrolled-course assignment deadlines, stores them in SQLite, and displays upcoming work.

## Requirements
- Python 3.10+
- An active UOWM eClass account and network access for synchronization

## Install from source
```bash
git clone https://github.com/moustakas05/eclass-deadline-widget.git
cd eclass-deadline-widget
python -m venv .venv
.venv\\Scripts\\Activate.ps1  # Windows PowerShell
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Credentials and configuration
Copy `.env.example` to `.env`; set `ECLASS_USERNAME` and `ECLASS_PASSWORD` to your own institutional credentials. `ECLASS_BASE_URL` is optional and defaults to `https://eclass.uowm.gr/`. Credentials are used by the scraper to authenticate through UOWM CAS and access courses. The widget can display cached deadlines without signing in.

Optional non-secret settings go in `config.json`; see `config.example.json`. Never commit `.env`, private config, cookies, tokens or database files. Local `.env` and `config.json` are ignored by Git.

## Run
Run `eclass-sync` to fetch deadlines and `eclass-widget` to open the widget. Alternatively use `python scraper.py` and `python widget.py`. The first successful sync creates `eclass.db`; the widget's Sync button also fetches updates.

## Local data and privacy
SQLite stores course names, assignment titles, deadlines, links and scrape timestamps. `widget_state.json` stores window position and pin state. Credentials remain in `.env`; sync requests go to the configured eClass/CAS host. Protect these files and your OS account. This project is not affiliated with the university.

## Tests
Run `pytest`. Tests use synthetic HTML and dates and do not contact eClass or need real credentials.

## Troubleshooting
- Login rejected: verify institutional credentials and the official CAS portal.
- Network failure: check connectivity/eClass availability and retry; cached data remains available.
- No deadlines: an empty result may be valid; check active assignments in the eClass portal.
- Missing database: run `eclass-sync` once before opening the widget.
- Dates are interpreted in `Europe/Athens` local time.

## Security
Never commit credentials, cookies, access tokens, local databases or logs. Rotate any secret that has been committed; removing it from the latest version is not enough.
