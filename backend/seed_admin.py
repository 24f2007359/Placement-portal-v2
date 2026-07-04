"""Create database tables and seed the pre-defined admin user."""

import sys

from app import app
from config import Config
from models import User, UserRole, db


def seed_admin():
    existing = User.query.filter_by(role=UserRole.ADMIN).first()
    if existing:
        print(f"Admin already exists: {existing.email}")
        return existing

    admin = User(email=Config.ADMIN_EMAIL, role=UserRole.ADMIN)
    admin.set_password(Config.ADMIN_PASSWORD)
    db.session.add(admin)
    db.session.commit()
    print(f"Admin user created: {Config.ADMIN_EMAIL}")
    return admin


def init_database():
    with app.app_context():
        db.create_all()
        print("Database tables created.")
        seed_admin()


if __name__ == "__main__":
    init_database()
    sys.exit(0)
