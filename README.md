# Psychological Counseling Scheduler

Internal web app for psychologist meeting scheduling.

## Features
- Public appointment request page
- Multiple psychologists with separate available slots
- Admin login and admin promotion
- Psychologist and slot management
- Request email delivery to psychologists
- Secure accept/refuse flow via opaque token links
- SQLite storage for simple internal deployment

## Quick start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python create_admin.py
gunicorn --bind 127.0.0.1:5004 wsgi:app
```

Then open `http://psychologicalcounseling`.

## Environment
- `PC_SECRET_KEY`
- `PC_BASE_URL`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`

## Routes
- `/` public request page
- `/admin/login` admin sign-in
- `/admin` admin dashboard
- `/appointment-response/<token>` psychologist decision page

## Notes
- The app auto-creates and auto-upgrades the SQLite schema on startup.
- Decision links contain only an opaque token, not sensitive employee data.
