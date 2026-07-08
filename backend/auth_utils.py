from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import g, jsonify, request

from config import Config
from models import User


def create_token(user):
    payload = {
        "user_id": user.id,
        "role": user.role.value,
        "exp": datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm=Config.JWT_ALGORITHM)


def decode_token(token):
    return jwt.decode(token, Config.SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])


def get_current_user():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    try:
        payload = decode_token(token)
        user = User.query.get(payload["user_id"])
        if not user or not user.is_active:
            return None
        return user
    except jwt.PyJWTError:
        return None


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        g.current_user = user
        return f(*args, **kwargs)

    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        @token_required
        def decorated(*args, **kwargs):
            if g.current_user.role.value not in roles:
                return jsonify({"error": "Access denied for this role"}), 403
            return f(*args, **kwargs)

        return decorated

    return decorator


def user_response(user):
    data = {
        "id": user.id,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
    }

    if user.role.value == "company" and user.company:
        data["profile"] = {
            "id": user.company.id,
            "name": user.company.name,
            "industry": user.company.industry,
            "location": user.company.location,
            "approval_status": user.company.approval_status.value,
            "is_blacklisted": user.company.is_blacklisted,
        }
    elif user.role.value == "student" and user.student:
        data["profile"] = {
            "id": user.student.id,
            "full_name": user.student.full_name,
            "institute_id": user.student.institute_id,
            "contact": user.student.contact,
            "branch": user.student.branch,
            "cgpa": user.student.cgpa,
            "graduation_year": user.student.graduation_year,
            "skills": user.student.skills,
            "education": user.student.education,
            "experience": user.student.experience,
            "resume_path": user.student.resume_path,
            "is_blacklisted": user.student.is_blacklisted,
        }

    return data
