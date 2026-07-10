# Placement Portal Application V2 (PPA-V2)

A campus recruitment management web application for **Modern Application Development II (MAD-II)** at IIT Madras BS.

Institutes use this portal to coordinate placement drives between companies and students—replacing spreadsheets and manual email workflows with a single role-based system.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend API | Flask |
| Frontend UI | Vue.js + Bootstrap |
| Database | SQLite (created programmatically) |
| Caching | Redis |
| Background jobs | Celery + Redis |

## User Roles

- **Admin (Institute)** — Pre-created superuser; approves companies and placement drives, manages users, views reports.
- **Company** — Registers profile, creates placement drives after approval, manages applications and interviews.
- **Student** — Self-registers, browses approved drives, applies for positions, tracks application status.

## Project Structure (planned)

```
backend/
  app.py            # Flask application entry point
  models.py         # SQLAlchemy models
  routes.py         # Auth and dashboard API routes
  admin_routes.py   # Admin management APIs (Milestone 3)
  company_routes.py # Company job/application APIs (Milestone 4)
  student_routes.py # Student profile/job/application APIs (Milestone 5)
  export_routes.py  # Async export/report endpoints (Milestone 7)
  celery_app.py     # Celery instance, beat schedule, Flask context (Milestone 7)
  tasks.py          # Background jobs: reminders, reports, CSV exports (Milestone 7)
  mail_utils.py     # Gmail SMTP sender with console fallback (Milestone 7)
  auth_utils.py     # JWT helpers and RBAC decorators
  config.py
  seed_admin.py     # Creates DB tables + pre-defined admin user
  instance/
    placement.db    # SQLite database
    exports/        # Generated CSV exports (gitignored)
    reports/        # Generated HTML/PDF reports (gitignored)
frontend/           # Vue.js SPA (Vite)
  src/views/        # Login, register, role dashboards
  src/services/     # API clients (auth, admin, company, student, exports)
```

## Backend Setup (Milestone 1)

```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
python seed_admin.py    # creates SQLite DB + admin user
python app.py           # starts API on http://127.0.0.1:5000
```

## Frontend Setup (Milestone 2)

```bash
cd frontend
npm install
npm run dev             # starts UI on http://127.0.0.1:5173
```

Run **both** backend and frontend for the full auth flow. Vite proxies `/api` requests to Flask.

### Authentication (Milestone 2)

| Role | Register | Login | Dashboard route |
|------|----------|-------|-----------------|
| Admin | No (pre-seeded) | Yes | `/admin/dashboard` |
| Company | Yes (pending approval) | Yes | `/company/dashboard` |
| Student | Yes | Yes | `/student/dashboard` |

JWT tokens are issued on login/register and sent as `Authorization: Bearer <token>`.

**API endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Login for all roles |
| POST | `/api/auth/register/student` | Student self-registration |
| POST | `/api/auth/register/company` | Company registration (status: pending) |
| GET | `/api/auth/me` | Current user profile (protected) |
| GET | `/api/admin/dashboard` | Admin-only dashboard data |
| GET | `/api/company/dashboard` | Company-only dashboard data |
| GET | `/api/student/dashboard` | Student-only dashboard data |

### Admin Management (Milestone 3)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/dashboard` | Stats: students, companies, jobs, applications |
| GET | `/api/admin/companies` | Search companies (`q`, `industry`, `status`) |
| PUT | `/api/admin/companies/:id/approve` | Approve company |
| PUT | `/api/admin/companies/:id/reject` | Reject company |
| PUT | `/api/admin/companies/:id/blacklist` | Blacklist company |
| DELETE | `/api/admin/companies/:id` | Remove company |
| GET | `/api/admin/students` | Search students (`q` = name/ID/contact) |
| PUT | `/api/admin/students/:id/blacklist` | Blacklist student |
| PUT | `/api/admin/students/:id/deactivate` | Deactivate student |
| PUT | `/api/admin/students/:id/activate` | Reactivate student |
| DELETE | `/api/admin/students/:id` | Remove student |
| GET | `/api/admin/jobs` | List job postings (`q`, `status`) |
| PUT | `/api/admin/jobs/:id/approve` | Approve placement drive |
| PUT | `/api/admin/jobs/:id/reject` | Reject/close drive |
| DELETE | `/api/admin/jobs/:id` | Remove job posting |
| GET | `/api/admin/applications` | View all applications |

Companies must be **approved by admin** before they can access the company dashboard.

### Company Management (Milestone 4)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/company/dashboard` | Company dashboard stats |
| GET | `/api/company/jobs` | List/search own job postings (`q`, `status`) |
| POST | `/api/company/jobs` | Create job posting (starts as `pending`) |
| PUT | `/api/company/jobs/:id` | Update own job details / set Active or Closed |
| GET | `/api/company/jobs/:id/applications` | View applicants for a specific job |
| GET | `/api/company/applications` | View all received applications (`status`) |
| PUT | `/api/company/applications/:id/status` | Shortlist/interview/offer/reject with feedback |

### Student Management (Milestone 5)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/student/dashboard` | Student dashboard stats |
| GET | `/api/student/profile` | View full student profile |
| PUT | `/api/student/profile` | Update education, skills, experience, CGPA, etc. |
| POST | `/api/student/profile/resume` | Upload resume file (pdf/doc/docx/txt) |
| GET | `/api/student/jobs` | Browse approved placement drives (`q`, `company`) |
| POST | `/api/student/jobs/:id/apply` | Apply for a job (eligibility + duplicate checks) |
| GET | `/api/student/applications` | List own applications with status/feedback |
| GET | `/api/student/applications/:id` | Application detail |
| GET | `/api/student/applications/:id/offer-letter` | Download offer letter for offer/placed status |

Students only see jobs from **approved companies** with job status **approved** or **active**. Duplicate applications to the same job are blocked.

### Application History & Status Tracking (Milestone 6)

Every application status change is recorded in an audit trail (`ApplicationStatusHistory`), producing a full timeline: **Applied → Shortlisted → Interview → Offer → Placed / Rejected**. Marking a candidate **Offer** or **Placed** creates a `Placement` record (position, salary, joining date).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/student/applications/:id` | Application detail **incl. status history** |
| GET | `/api/student/placements` | Student's own placement records |
| PUT | `/api/company/applications/:id/status` | Now also accepts `placed`; logs history, upserts placement (`position`, `salary`, `joining_date`) |
| GET | `/api/company/applications/:id` | Application detail + history + applicant profile |
| GET | `/api/company/students/:id` | View profile of a student who applied to the company's jobs |
| GET | `/api/company/placements` | Company's placement records |
| GET | `/api/admin/applications/:id` | Application detail + full history + student profile |
| GET | `/api/admin/students/:id` | Student profile + applications + placements |
| GET | `/api/admin/placements` | All placement records |

- **Complete history:** students, companies and admin can all view the full application timeline; students see their own records, companies see applicants to their own jobs, admin sees everything.
- **Placement records** are created/updated (never duplicated) when a candidate is offered or placed.
- Re-run `python seed_admin.py` once after pulling M6 to create the new `application_status_history` table (existing data is preserved).

### Background Jobs — Celery + Redis (Milestone 7)

Slow and periodic work runs outside the request cycle. Flask pushes a job onto **Redis**, returns a `task_id` immediately, and a **Celery worker** executes it; **Celery Beat** fires the scheduled jobs on a clock.

| Job | Type | Schedule |
|-----|------|----------|
| `send_interview_reminders` | Emails students whose interview is within 24h | Daily 09:00 IST |
| `generate_monthly_placement_reports` | Per-company HTML **+ PDF** report with stats & analytics, emailed to HR | 1st of month, 06:00 IST |
| `export_applications_csv` | User-triggered async CSV export | On demand |
| `export_placements_csv` | User-triggered async CSV export | On demand |

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/exports/applications` | Start async applications export → `202 {task_id}` |
| POST | `/api/exports/placements` | Start async placements export → `202 {task_id}` |
| GET | `/api/exports/status/:task_id` | Poll job state (`PENDING`/`SUCCESS`), returns `filename` when ready |
| GET | `/api/exports/download/:filename` | Download the generated CSV |
| POST | `/api/admin/reminders/interviews` | Run the reminder job now |
| POST | `/api/admin/reports/monthly` | Generate this period's reports for all companies |
| POST | `/api/admin/reports/company/:id` | Generate one company's report |
| GET | `/api/admin/reports` | List generated report files |
| GET | `/api/admin/reports/download/:filename` | Download a report (HTML/PDF) |

Downloads are guarded two ways: non-admins may only fetch files stamped with their own user id, and resolved paths must stay inside the export/report directory (blocks `../` traversal).

#### Running the background stack (WSL Ubuntu)

```bash
sudo apt install -y redis-server
sudo service redis-server start && redis-cli ping     # → PONG

cd backend && python app.py                                    # 1. API
cd backend && celery -A celery_app.celery worker --loglevel=info  # 2. worker
cd backend && celery -A celery_app.celery beat   --loglevel=info  # 3. scheduler
```

On **native Windows** add `--pool=solo` to the worker (Celery's prefork pool is Unix-only). To run tasks synchronously with no Redis or worker (handy for tests), set `CELERY_TASK_ALWAYS_EAGER=1`.

#### Email (Gmail SMTP)

```bash
export MAIL_USERNAME="you@gmail.com"
export MAIL_PASSWORD="<16-char Gmail App Password>"
```

Create an [App Password](https://myaccount.google.com/apppasswords) (needs 2-Step Verification); Gmail rejects normal passwords over SMTP. **If unset, emails are logged to the console instead of sent** — jobs never crash on a missing mail config.

Default admin credentials (override via `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars):

| Field | Value |
|-------|-------|
| Email | `admin@placement.local` |
| Password | `admin123` |

### Database Models

| Model | Description |
|-------|-------------|
| `User` | Unified auth model with roles: admin, company, student |
| `Company` | Company profile linked 1:1 to a company user |
| `Student` | Student profile linked 1:1 to a student user |
| `JobPosition` | Placement drive / job posting (many per company) |
| `Application` | Student application to a job (unique per student+job) |
| `Placement` | Final placement record linked to student, company, and optionally an application |
| `ApplicationStatusHistory` | Audit trail: one row per application status change (Milestone 6) |

Relationships: Company → JobPosition (1:n), Student → Application (1:n), JobPosition → Application (1:n), Application → Placement (1:1 optional), Application → ApplicationStatusHistory (1:n).

## Milestone Progress

| Milestone | Status |
|-----------|--------|
| M0 — GitHub repository setup | Done |
| M1 — Database models & schema | Done |
| M2 — Authentication & RBAC | Done |
| M3 — Admin dashboard & management | Done |
| M4 — Company dashboard & job/application management | Done |
| M5 — Student dashboard & job application system | Done |
| M6 — Application history & status tracking | Done |
| M7 — Celery + Redis background jobs | Done |
| M8 — Redis caching | Pending |

## Development Notes

- Milestone commits use the message format specified in the course milestone document.
- Issues and resolutions are logged here or in GitHub Issues.

## Author

IIT Madras BS — MAD-II Project (Jan 2026)
