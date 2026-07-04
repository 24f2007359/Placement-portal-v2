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
  auth_utils.py     # JWT helpers and RBAC decorators
  config.py
  seed_admin.py     # Creates DB tables + pre-defined admin user
frontend/           # Vue.js SPA (Vite)
  src/views/        # Login, register, role dashboards
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

Relationships: Company → JobPosition (1:n), Student → Application (1:n), JobPosition → Application (1:n), Application → Placement (1:1 optional).

## Milestone Progress

| Milestone | Status |
|-----------|--------|
| M0 — GitHub repository setup | Done |
| M1 — Database models & schema | Done |
| M2 — Authentication & RBAC | Done |
| M3–M8 — Core features | Pending |

## Development Notes

- Milestone commits use the message format specified in the course milestone document.
- Issues and resolutions are logged here or in GitHub Issues.

## Author

IIT Madras BS — MAD-II Project (Jan 2026)
