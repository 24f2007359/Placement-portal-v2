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
  cache_utils.py    # Redis @cached decorator + namespace invalidation (Milestone 8)
  auth_utils.py     # JWT helpers and RBAC decorators
  config.py
  .env              # Mail credentials (gitignored)
  seed_admin.py     # Creates DB tables + pre-defined admin user
  instance/
    placement.db    # SQLite database
    exports/        # Generated CSV exports (gitignored)
    reports/        # Generated HTML/PDF reports (gitignored)
frontend/           # Vue.js SPA (Vite)
  src/views/        # Login, register, role dashboards
  src/services/     # API clients (auth, admin, company, student, exports)
```

## Running the Project

The full app has **five processes**: Redis, the Flask API, a Celery worker, Celery Beat (scheduler), and the Vue dev server. The core auth/dashboard flows need only the API + frontend; the background jobs (Milestone 7) and caching (Milestone 8) need Redis and Celery too.

> **Environment note:** this project is developed on **WSL Ubuntu** (Linux). The commands below use Linux paths and the `venv/bin/` layout. On native Windows, use `venv\Scripts\activate` instead of `source venv/bin/activate`, and add `--pool=solo` to the Celery worker command (Celery's default pool is Unix-only).

### Prerequisites

- Python 3.11+ (developed on 3.14)
- Node.js 18+ and npm
- Redis server

### 1. One-time setup

```bash
# --- Backend ---
cd backend
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip3 install -r requirements.txt
python seed_admin.py                # creates SQLite tables + the pre-seeded admin
deactivate

# --- Redis (WSL Ubuntu / Debian) ---
sudo apt update && sudo apt install -y redis-server

# --- Frontend ---
cd ../frontend
npm install
```

**Mail (optional):** create `backend/.env` to enable real email; without it, jobs log the message to the console instead of sending (nothing breaks).

```ini
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=1
MAIL_USERNAME=you@gmail.com
MAIL_PASSWORD=your-16-char-gmail-app-password
```

Use a Gmail **App Password** (needs 2-Step Verification), not your account password. `backend/.env` is gitignored.

### 2. Start the services

Open a terminal per service. Start Redis first, then the rest in any order.

```bash
# 1. Redis
sudo service redis-server start
redis-cli ping                      # -> PONG

# 2. Flask API                     (http://127.0.0.1:5000)
cd backend && source venv/bin/activate
python app.py

# 3. Celery worker  (runs the background jobs — needs Redis)
cd backend && source venv/bin/activate
celery -A celery_app.celery worker --loglevel=info
#   native Windows: append  --pool=solo

# 4. Celery Beat    (fires the scheduled jobs — needs Redis)
cd backend && source venv/bin/activate
celery -A celery_app.celery beat --loglevel=info

# 5. Frontend dev server            (http://127.0.0.1:5173)
cd frontend && npm run dev
```

Open **http://127.0.0.1:5173** and log in. Vite proxies `/api` calls to Flask, so both must be running for anything beyond the login page.

> `celery` not found? Your virtualenv isn't activated. Either `source venv/bin/activate` first, or call the binary directly: `./venv/bin/celery -A celery_app.celery worker --loglevel=info`.

### Which processes do I actually need?

| I want to… | Redis | API | Worker | Beat | Frontend |
|------------|:-----:|:---:|:------:|:----:|:--------:|
| Log in, use dashboards, apply, approve | – | ✓ | – | – | ✓ |
| Run CSV exports / trigger reports manually | ✓ | ✓ | ✓ | – | ✓ |
| See the daily/monthly jobs fire on schedule | ✓ | ✓ | ✓ | ✓ | ✓ |
| Benefit from response caching | ✓ | ✓ | – | – | ✓ |

The API runs fine without Redis — caching simply falls back to the database, and job triggers will time out until a worker is up.

### Default admin login

| Field | Value |
|-------|-------|
| Email | `admin@placement.local` |
| Password | `admin123` |

Override via `ADMIN_EMAIL` / `ADMIN_PASSWORD` before running `seed_admin.py`. Companies and students self-register from the login page.

### Production build

```bash
cd frontend && npm run build        # outputs an optimised bundle to frontend/dist/
```

Serve `frontend/dist/` behind a web server and run the Flask API under a WSGI server (e.g. Gunicorn). See `docs/MILESTONE-7-*` and `docs/MILESTONE-8-*` for the Celery/Redis production notes.

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

Credentials live in `backend/.env` (gitignored), loaded by `python-dotenv`.

### Redis Caching (Milestone 8)

Frequently-read endpoints are cached in Redis. Measured on a 60-job listing: **18.31 ms → 1.47 ms, a 12.5× speedup.**

| Endpoint | Namespace | TTL | Keyed per user? |
|----------|-----------|-----|-----------------|
| `GET /api/student/jobs` | `jobs` | 60s | **Yes** — carries `already_applied` for the caller |
| `GET /api/company/jobs` | `jobs` | 60s | **Yes** — only that company's postings |
| `GET /api/admin/jobs` | `jobs` | 60s | No |
| `GET /api/admin/companies` | `companies` | 120s | No |
| `GET /api/admin/students` | `students` | 120s | No |

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/cache/stats` | Per-namespace version, live key count, TTL, Redis hit rate |
| POST | `/api/admin/cache/flush` | Invalidate every namespace (3 × `INCR`, never `FLUSHDB`) |

**Expiry policy** — every entry is written with `SETEX`, so a missed invalidation goes stale for at most the TTL rather than forever.

**Refresh policy** — every write path explicitly invalidates, so in practice you never wait out the TTL. Approving a job, or blacklisting a company, removes its drives from every student's cached listing *immediately*.

**How invalidation scales:** each cache key embeds a namespace version (`…:jobs:v7:…`). Invalidating the whole namespace is a single atomic `INCR` — O(1) regardless of how many entries it affects, no `KEYS` scan, no blocking. Old-version keys are orphaned and expire on their own TTL.

Every cached response carries an `X-Cache: HIT|MISS` header:

```bash
curl -sI localhost:5000/api/student/jobs -H "Authorization: Bearer $TOKEN" | grep X-Cache
```

**Redis is optional.** If it's down, every read degrades to a cache miss and serves correct data straight from the database; writes still succeed. Set `CACHE_ENABLED=0` to bypass the cache entirely.

Redis DB layout: `db 0` Celery broker · `db 1` Celery results · `db 2` this cache — so flushing the cache can never eat a queued job.

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
| M8 — API optimization & Redis caching | Done |
| **All 8 core milestones complete** | **100%** |

## Development Notes

- Milestone commits use the message format specified in the course milestone document.
- Issues and resolutions are logged here or in GitHub Issues.

## Author

IIT Madras BS — MAD-II Project (Jan 2026)
