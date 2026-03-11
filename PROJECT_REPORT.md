# Hospital Management System — V2
## Project Report | MAD-2

---

### Author

**Full Name:** `<< Your Full Name >>`
**Roll Number:** `<< Your Roll Number >>`
**Email:** `<< your@email.com >>`

I am a student of the IIT Madras BS in Data Science and Applications program. This report documents my MAD-2 project — a Hospital Management System web application built using Flask and Vue.js 3.

---

### AI / LLM Usage Declaration

**Tool Used:** Claude (Anthropic) — via OpenCode CLI

**Extent of Use:** AI assistance was used throughout the project for code generation, debugging Vue.js 3 compatibility issues (filters, optional chaining conflicts with Jinja2), and structuring API endpoints. All logic, architecture decisions, and feature mapping to requirements were guided by the student. The AI acted as a pair-programming tool.

**AI Usage Percentage (MAD-2 estimate):** ~85% of code was AI-assisted. The student was responsible for requirement mapping, testing, debugging runtime issues, and validating feature completeness against the project specification.

---

### Description

This project is a role-based Hospital Management System web application that allows three types of users — Admin, Doctor, and Patient — to interact with a shared hospital database. The Admin manages doctors, patients, and appointments. Doctors manage their schedules and patient treatment records. Patients register, search doctors, book appointments, and view their treatment history. The system uses a REST API backend (Flask) and a reactive single-page frontend (Vue.js 3), with Redis caching and Celery-based scheduled jobs for reminders and reports.

---

### Technologies Used

| Technology | Purpose |
|---|---|
| **Flask** | REST API backend — all routes, business logic, role-based access control |
| **Flask-Login** | Session-based authentication and user loading |
| **Flask-Mail** | Sending email reminders and monthly HTML reports |
| **Flask-CORS** | Cross-origin support for local development |
| **SQLAlchemy** | ORM for all database models and queries |
| **SQLite** | Lightweight relational database; created programmatically via `db.create_all()` |
| **Redis** | Caching for doctors, departments, and dashboard stats with TTL expiry |
| **Celery** | Async task queue; daily reminder and monthly report scheduled jobs via `celery beat` |
| **Python `threading`** | Fallback for CSV export async job (no Celery worker needed for demo) |
| **Vue.js 3 (CDN)** | Reactive single-page frontend; all UI rendered client-side using `defineComponent` |
| **Axios** | HTTP client in Vue for all API calls |
| **Bootstrap 5** | Responsive UI layout, tables, forms, modals, badges |
| **Bootstrap Icons** | Icon set used throughout the interface |
| **Chart.js** | Admin dashboard charts — appointments by status (doughnut) and doctors by specialization (bar) |
| **Werkzeug** | Password hashing (`generate_password_hash`, `check_password_hash`) |

---

### DB Schema Design

The database uses **SQLAlchemy single-table polymorphic inheritance** with a base `users` table and role-specific child tables.

#### Tables and Key Columns

**`users`** *(base table)*

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, auto-increment |
| username | String(80) | UNIQUE, NOT NULL |
| email | String(120) | UNIQUE, NOT NULL |
| password_hash | String(200) | NOT NULL |
| role | String(20) | NOT NULL — discriminator column (`admin`/`doctor`/`patient`) |
| is_blacklisted | Boolean | NOT NULL, DEFAULT False |
| created_at | DateTime | DEFAULT utcnow |

**`admins`** — FK to `users.id` (no extra columns)

**`doctors`**

| Column | Type | Notes |
|---|---|---|
| id | Integer | FK → users.id (PK) |
| specialization_id | Integer | FK → departments.id |
| phone, address, bio | String/Text | Optional profile fields |
| is_available | Boolean | Availability flag |

**`patients`**

| Column | Type | Notes |
|---|---|---|
| id | Integer | FK → users.id (PK) |
| phone, address | String/Text | Contact info |
| date_of_birth | Date | Optional |
| gender | String(10) | Optional |
| blood_group | String(10) | Optional |

**`departments`**

| Column | Type | Notes |
|---|---|---|
| id | Integer | PK |
| name | String(100) | UNIQUE, NOT NULL |
| description | Text | Optional |

**`doctor_availability`**

| Column | Type | Notes |
|---|---|---|
| id | Integer | PK |
| doctor_id | Integer | FK → users.id |
| date | Date | NOT NULL |
| start_time, end_time | Time | NOT NULL |
| is_available | Boolean | DEFAULT True |

**`appointments`**

| Column | Type | Notes |
|---|---|---|
| id | Integer | PK |
| patient_id | Integer | FK → patients.id, NOT NULL |
| doctor_id | Integer | FK → doctors.id, NOT NULL |
| appointment_date | Date | NOT NULL |
| appointment_time | Time | NOT NULL |
| status | String(20) | DEFAULT `Booked`; values: Booked / Completed / Cancelled |
| reason | Text | Optional |
| created_at, updated_at | DateTime | Auto timestamps |

**`treatments`**

| Column | Type | Notes |
|---|---|---|
| id | Integer | PK |
| appointment_id | Integer | FK → appointments.id, NOT NULL |
| diagnosis | Text | NOT NULL |
| prescription | Text | Optional |
| notes | Text | Optional |
| next_visit | Date | Optional |
| created_at, updated_at | DateTime | Auto timestamps |

#### ER Relationships

```
users (1) ──< doctors (1) ──< appointments >── (1) patients <── (1) users
                  |                  |
            departments         treatments
         (1) ──< availability
```

**Design rationale:** Single-table inheritance keeps all authentication in one `users` table.
Separate child tables avoid sparse columns. `appointments` is the central join table linking
doctors to patients. `treatments` is a 1:1 extension of a completed appointment.

---

### API Design

All APIs are JSON REST endpoints under `/api/`. Role-based access is enforced via the
`@role_required()` decorator. Session authentication uses Flask-Login cookies.

| Method | Endpoint | Role | Description |
|---|---|---|---|
| POST | `/api/register` | Public | Register new patient |
| POST | `/api/login` | Public | Login (all roles) |
| POST | `/api/logout` | Auth | Logout |
| GET | `/api/current-user` | Auth | Get logged-in user info |
| GET | `/api/departments` | Public | List all departments (cached 300s) |
| POST | `/api/departments` | Admin | Create department |
| GET | `/api/doctors` | Public | List doctors (search by name/specialization, cached) |
| POST | `/api/doctors` | Admin | Create doctor |
| PUT | `/api/doctors/<id>` | Admin/Doctor | Update doctor profile |
| DELETE | `/api/doctors/<id>` | Admin | Delete doctor |
| POST | `/api/doctors/<id>/blacklist` | Admin | Blacklist or reinstate doctor |
| GET | `/api/patients` | Admin | List patients (search by name/ID/contact) |
| GET | `/api/patients/<id>` | Admin/Doctor/Patient | Get patient detail |
| PUT | `/api/patients/<id>` | Admin/Patient | Update patient profile |
| DELETE | `/api/patients/<id>` | Admin | Delete patient |
| POST | `/api/patients/<id>/blacklist` | Admin | Blacklist or reinstate patient |
| GET | `/api/dashboard/stats` | Admin | Total counts (cached 60s) |
| GET | `/api/appointments` | Auth | List appointments (role-filtered) |
| POST | `/api/appointments` | Admin/Patient | Book appointment |
| PUT | `/api/appointments/<id>` | Admin/Doctor | Update appointment status |
| DELETE | `/api/appointments/<id>` | Admin/Patient/Doctor | Cancel appointment |
| PUT | `/api/appointments/<id>/reschedule` | Patient/Admin | Reschedule appointment |
| GET | `/api/treatments` | Auth | List treatments (role-filtered) |
| POST | `/api/treatments` | Doctor | Add treatment record |
| PUT | `/api/treatments/<id>` | Doctor | Update treatment record |
| GET | `/api/doctor/dashboard` | Doctor | Today + week appointments, patient count |
| GET | `/api/doctor/patients` | Doctor | All patients assigned to doctor |
| GET | `/api/availability` | Public | List availability slots (filterable) |
| POST | `/api/availability` | Doctor | Add single availability slot |
| POST | `/api/availability/bulk` | Doctor | Set availability for 7-day range |
| POST | `/api/export/csv` | Patient | Trigger async CSV export job |
| GET | `/api/export/status/<id>` | Patient | Poll export job status |
| POST | `/api/payments` | Patient | Submit dummy payment |

The YAML API definition file is included separately in the submission (`api.yaml`).

---

### Architecture and Features

**Project Structure:**

```
App_Dev_2_HMS_V2_2/
├── app.py              # All Flask routes, business logic, Celery tasks
├── models.py           # SQLAlchemy models (polymorphic User hierarchy)
├── config.py           # Config: Redis, Celery beat schedule, Mail, SQLite
├── tasks.py            # Celery app factory
├── requirements.txt    # Python dependencies
├── README.md           # Setup and run instructions
├── templates/
│   └── index.html      # Single-page Vue.js 3 app (~1000 lines)
├── static/             # Empty (all assets via CDN)
└── instance/
    └── hms.db          # SQLite database (auto-created on first run)
```

**Architecture:**
The backend is a pure REST API. Flask serves only one HTML page (the entry point), bypassing
Jinja2 rendering entirely to avoid conflicts with Vue's `?.` optional chaining template syntax —
the HTML is served as a raw `Response(open(path).read(), mimetype='text/html')`. All UI state
and rendering is handled client-side by Vue.js 3 using the Composition API (`setup()`, `ref`,
`computed`, `onMounted`). Components are defined inline via `defineComponent` and registered
on the root `createApp` instance to enable dynamic `<component :is="...">` rendering based on
the logged-in user's role. There is no Vue CLI, no build step, and no node_modules.

**Core Features Implemented:**

- **Authentication:** Role-based login for Admin, Doctor, Patient; patient self-registration;
  blacklist/reinstate any user (blocked at login with clear error message)
- **Admin:** Dashboard with ChartJS charts (status doughnut + specialization bar chart),
  full doctor/patient CRUD, appointment management with Upcoming/Past tab split and status filter
- **Doctor:** Day/week appointment dashboard with complete/cancel actions, treatment record
  entry (diagnosis, prescription, notes, next visit), 7-day availability scheduling, full
  patient history modal sorted by visit date
- **Patient:** Department browser, doctor availability table for next 7 days, appointment
  booking/reschedule/cancel with duplicate slot prevention, treatment history showing actual
  appointment dates with doctor name, CSV export (async background job via threading with
  polling), dummy payment portal with card form and GST breakdown

**Additional / Optional Features:**

- Redis caching with TTL expiry (300s for doctors/departments, 60s for dashboard stats)
  and cache invalidation on all write operations
- Celery beat schedule: daily email reminders at 8:00 AM (`crontab(hour=8, minute=0)`),
  monthly HTML activity reports to doctors on the 1st of each month
  (`crontab(hour=9, minute=0, day_of_month=1)`)
- ChartJS charts on admin dashboard
- HTML5 frontend form validation (`required`, `minlength`, `pattern`, `type=email`) on all forms
- Backend input validation with descriptive 400 error responses (no unhandled KeyErrors)
- `is_blacklisted` column on all users; blacklisted accounts return 403 at login

---

### Video

**Presentation Video Link:** `<< Paste your Google Drive video link here >>`

*(Video covers: introduction, approach, admin demo with charts, doctor demo, patient demo,
backend jobs explanation — approximately 5 minutes)*

---

> **Submission checklist:**
> - [ ] Fill in Author section (name, roll number, email)
> - [ ] Add Google Drive video link above
> - [ ] Convert this file to PDF (A4, 10pt font)
> - [ ] Include `api.yaml` in the ZIP
> - [ ] Include `README.md` in the ZIP with run instructions
