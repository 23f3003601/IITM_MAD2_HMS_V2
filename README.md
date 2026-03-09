# Hospital Management System — V2

A role-based Hospital Management System built with Flask, Vue.js 3, SQLite, Redis, and Celery.

---

## Prerequisites

Make sure the following are installed on your machine before running:

| Requirement | Version | Check Command |
|---|---|---|
| Python | 3.13+ | `python3 --version` |
| pip | latest | `pip --version` |
| Redis | any | `redis-cli ping` → should print `PONG` |
| Homebrew (macOS) | — | `brew --version` |

---

## Step 1 — Install Redis (if not installed)

**macOS:**
```bash
brew install redis
```

**Ubuntu/Debian:**
```bash
sudo apt-get install redis-server
```

**Windows:**
Download from https://github.com/microsoftarchive/redis/releases

---

## Step 2 — Start Redis

Open a terminal and run:

```bash
redis-server
```

Leave this terminal open. Redis must be running before you start the app.

To verify Redis is running, open another terminal and type:
```bash
redis-cli ping
```
You should see: `PONG`

---

## Step 3 — Clone / Navigate to the Project Folder

```bash
cd /path/to/App_Dev_2_HMS_V2_2
```

---

## Step 4 — Create a Virtual Environment

```bash
python3.13 -m venv venv
```

---

## Step 5 — Activate the Virtual Environment

**macOS / Linux:**
```bash
source venv/bin/activate
```

**Windows:**
```bash
venv\Scripts\activate
```

You should see `(venv)` appear in your terminal prompt.

---

## Step 6 — Install Dependencies

```bash
pip install -r requirements.txt
pip install "sqlalchemy>=2.0.35"
```

> **Note:** SQLAlchemy must be 2.0.35 or higher. Python 3.13 is incompatible with 2.0.23.
> The second pip command ensures the correct version is installed.

---

## Step 7 — Run the Application

```bash
python app.py
```

You should see output like:

```
Database initialized successfully!
 * Serving Flask app 'app'
 * Debug mode: on
 * Running on http://127.0.0.1:5002
```

The database (`instance/hms.db`) is created automatically on first run.
Demo users and availability slots are seeded automatically — no manual setup needed.

---

## Step 8 — Open in Browser

```
http://localhost:5002
```

---

## Demo Credentials

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `admin123` |
| Doctor | `dr_smith` | `doctor123` |
| Doctor | `dr_patel` | `doctor123` |
| Doctor | `dr_ali` | `doctor123` |
| Patient | `johndoe` | `password123` |
| Patient | `janesmith` | `password123` |

---

## Optional — Run Celery Worker (for scheduled jobs)

The CSV export works without Celery (uses Python threading). However, if you want the
daily reminder and monthly report jobs to actually execute, run the Celery worker and
beat scheduler in separate terminals:

**Terminal 2 — Celery Worker:**
```bash
source venv/bin/activate
celery -A app.celery worker --loglevel=info
```

**Terminal 3 — Celery Beat (scheduler):**
```bash
source venv/bin/activate
celery -A app.celery beat --loglevel=info
```

> **Note for demo:** Celery worker/beat are optional. All UI features, caching, and CSV
> export work without them. The scheduled jobs (daily email, monthly report) only run
> when the Celery worker is active.

---

## Optional — Configure Email (for reminders and reports)

Set these environment variables before running `python app.py` if you want emails to work:

```bash
export MAIL_USERNAME="your_gmail@gmail.com"
export MAIL_PASSWORD="your_app_password"
```

> Use a Gmail App Password (not your regular password).
> Generate one at: https://myaccount.google.com/apppasswords

---

## Project Structure

```
App_Dev_2_HMS_V2_2/
├── app.py              # Flask app — all API routes, caching, Celery tasks
├── models.py           # SQLAlchemy models — User, Doctor, Patient, Admin,
│                       # Department, DoctorAvailability, Appointment, Treatment
├── config.py           # App config — Redis, Celery beat schedule, Mail, SQLite
├── tasks.py            # Celery app factory
├── requirements.txt    # Python dependencies
├── README.md           # This file
├── PROJECT_REPORT.md   # Project report (fill in name/roll no before submitting)
├── templates/
│   └── index.html      # Vue.js 3 Single Page App — all components inline
├── static/             # Empty — all CSS/JS loaded via CDN
└── instance/
    └── hms.db          # SQLite database — auto-created on first run
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Port 5002 is in use` | Another instance is running. Kill it: `pkill -f "python app.py"` then retry |
| `redis.exceptions.ConnectionError` | Redis is not running. Run `redis-server` in a separate terminal |
| `sqlalchemy.exc.OperationalError: no such column` | DB schema is outdated. Delete `instance/hms.db` and restart — it will be recreated |
| `ModuleNotFoundError` | Virtual environment not activated. Run `source venv/bin/activate` |
| `Address already in use` on port 5002 | macOS AirPlay uses port 5000. This app uses 5002 to avoid that conflict |
| Blank white page after login | Clear browser cache / hard refresh with `Cmd+Shift+R` (Mac) or `Ctrl+Shift+R` (Windows) |
| Charts not showing | Ensure internet connection — Chart.js is loaded from CDN |

---

## Running Everything (Summary — 3 terminals)

```
Terminal 1:  redis-server
Terminal 2:  source venv/bin/activate && python app.py
Terminal 3:  (optional) source venv/bin/activate && celery -A app.celery worker --loglevel=info
```

Then open: **http://localhost:5002**
