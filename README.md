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
  app.py          # Flask application entry point
  models.py       # SQLAlchemy models
  config.py
  seed_admin.py   # Creates DB tables + pre-defined admin user
frontend/         # Vue.js SPA
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
| M2 — Authentication & RBAC | Pending |
| M3–M8 — Core features | Pending |

## Development Notes

- Milestone commits use the message format specified in the course milestone document.
- Issues and resolutions are logged here or in GitHub Issues.

## Author

IIT Madras BS — MAD-II Project (Jan 2026)
