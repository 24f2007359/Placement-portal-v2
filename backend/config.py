import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'placement.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Default admin credentials (override via env in production)
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@placement.local")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

    JWT_ALGORITHM = "HS256"
    JWT_EXPIRATION_HOURS = int(os.environ.get("JWT_EXPIRATION_HOURS", 24))
