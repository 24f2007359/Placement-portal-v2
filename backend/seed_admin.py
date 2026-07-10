"""
===============================================================================
FILE : backend/seed_admin.py
WHAT : creates all DB tables + the one pre-defined admin user.
WHY  : Milestone 1 requires the admin to exist "programmatically", and there is
       deliberately NO admin registration route -- otherwise anyone could sign
       up as admin and approve themselves.

RUN  : python seed_admin.py
       (from backend/, with the venv active)

WHEN TO RE-RUN:
  - first time you set the project up
  - after ANY milestone that adds a new table. db.create_all() only creates
    tables that don't exist yet -- it never drops, never alters, never touches
    your rows. so it's safe to run over and over.
    e.g. M6 added `application_status_history` -> re-run this once and it appears.

WHAT IT WON'T DO:
  it does NOT add new COLUMNS to existing tables. create_all() is create-only.
  if you ever add a column to a model you'll need alembic, or just delete
  instance/placement.db and start fresh (fine for a course project).

CREDS: admin@placement.local / admin123  (override via ADMIN_EMAIL / ADMIN_PASSWORD)
===============================================================================
"""

import sys

from app import app  # importing this builds the whole Flask app + blueprints
from config import Config
from models import User, UserRole, db


def seed_admin():
    """Create the admin User row -- but only if one doesn't already exist.

    idempotent on purpose: running this twice must not blow up with a unique
    constraint error on the email column, and must not reset the password of a
    live admin. so we look first, bail early if found.
    called by init_database() below, inside an app context.
    """
    existing = User.query.filter_by(role=UserRole.ADMIN).first()
    if existing:
        print(f"Admin already exists: {existing.email}")
        return existing

    admin = User(email=Config.ADMIN_EMAIL, role=UserRole.ADMIN)
    # set_password() hashes it (models.py). we NEVER store the plaintext.
    admin.set_password(Config.ADMIN_PASSWORD)
    db.session.add(admin)
    db.session.commit()
    print(f"Admin user created: {Config.ADMIN_EMAIL}")
    return admin


def init_database():
    """Build the schema, then seed the admin.

    `with app.app_context():` is mandatory -- outside a request, SQLAlchemy has
    no idea which app (and therefore which DB) it's talking to. without it you
    get "Working outside of application context".

    NOTE: there's no Admin/Company/Student *profile* row for the admin. an admin
    is just a User with role=ADMIN and no attached profile. that's why
    auth_utils.user_response() only builds a `profile` key for company/student.
    """
    with app.app_context():
        db.create_all()  # CREATE TABLE IF NOT EXISTS, for every model in models.py
        print("Database tables created.")
        seed_admin()


if __name__ == "__main__":
    init_database()
    sys.exit(0)  # explicit 0 so shell scripts / CI can chain on success
