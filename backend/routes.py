from flask import Blueprint, g, jsonify, request

from auth_utils import create_token, role_required, token_required, user_response
from models import ApprovalStatus, Company, Student, User, UserRole, db

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api")


def _validate_credentials(data):
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return None, None, jsonify({"error": "Email and password are required"}), 400
    if len(password) < 6:
        return None, None, jsonify({"error": "Password must be at least 6 characters"}), 400

    return email, password, None, None


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email, password, error_response, status = _validate_credentials(data)
    if error_response:
        return error_response, status

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401

    if not user.is_active:
        return jsonify({"error": "Account is deactivated"}), 403

    if user.role == UserRole.COMPANY:
        if user.company and user.company.is_blacklisted:
            return jsonify({"error": "Company account is blacklisted"}), 403
    elif user.role == UserRole.STUDENT:
        if user.student and user.student.is_blacklisted:
            return jsonify({"error": "Student account is blacklisted"}), 403

    token = create_token(user)
    user_data = user_response(user)

    return jsonify(
        {
            "message": "Login successful",
            "token": token,
            "user": user_data,
            "redirect": _dashboard_path(user.role),
        }
    )


@auth_bp.route("/register/student", methods=["POST"])
def register_student():
    data = request.get_json(silent=True) or {}
    email, password, error_response, status = _validate_credentials(data)
    if error_response:
        return error_response, status

    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"error": "Full name is required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    institute_id = (data.get("institute_id") or "").strip() or None
    if institute_id and Student.query.filter_by(institute_id=institute_id).first():
        return jsonify({"error": "Institute ID already registered"}), 409

    user = User(email=email, role=UserRole.STUDENT)
    user.set_password(password)

    student = Student(
        user=user,
        full_name=full_name,
        institute_id=institute_id,
        contact=(data.get("contact") or "").strip() or None,
        branch=(data.get("branch") or "").strip() or None,
    )

    db.session.add(user)
    db.session.add(student)
    db.session.commit()

    token = create_token(user)
    return (
        jsonify(
            {
                "message": "Student registered successfully",
                "token": token,
                "user": user_response(user),
                "redirect": _dashboard_path(UserRole.STUDENT),
            }
        ),
        201,
    )


@auth_bp.route("/register/company", methods=["POST"])
def register_company():
    data = request.get_json(silent=True) or {}
    email, password, error_response, status = _validate_credentials(data)
    if error_response:
        return error_response, status

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Company name is required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    user = User(email=email, role=UserRole.COMPANY)
    user.set_password(password)

    company = Company(
        user=user,
        name=name,
        industry=(data.get("industry") or "").strip() or None,
        location=(data.get("location") or "").strip() or None,
        website=(data.get("website") or "").strip() or None,
        hr_contact=(data.get("hr_contact") or "").strip() or None,
        description=(data.get("description") or "").strip() or None,
        approval_status=ApprovalStatus.PENDING,
    )

    db.session.add(user)
    db.session.add(company)
    db.session.commit()

    token = create_token(user)
    return (
        jsonify(
            {
                "message": "Company registered successfully. Awaiting admin approval.",
                "token": token,
                "user": user_response(user),
                "redirect": _dashboard_path(UserRole.COMPANY),
            }
        ),
        201,
    )


@auth_bp.route("/me", methods=["GET"])
@token_required
def me():
    return jsonify({"user": user_response(g.current_user)})


@dashboard_bp.route("/company/dashboard", methods=["GET"])
@role_required("company")
def company_dashboard():
    company = g.current_user.company
    if not company:
        return jsonify({"error": "Company profile not found"}), 404

    approved = company.approval_status == ApprovalStatus.APPROVED
    if not approved or company.is_blacklisted or not g.current_user.is_active:
        return jsonify(
            {
                "error": "Dashboard access requires admin approval",
                "approval_status": company.approval_status.value,
                "approved": False,
            }
        ), 403

    return jsonify(
        {
            "message": "Welcome to the Company dashboard",
            "role": "company",
            "approved": True,
            "approval_status": company.approval_status.value,
        }
    )


@dashboard_bp.route("/student/dashboard", methods=["GET"])
@role_required("student")
def student_dashboard():
    return jsonify(
        {
            "message": "Welcome to the Student dashboard",
            "role": "student",
        }
    )


def _dashboard_path(role):
    paths = {
        UserRole.ADMIN: "/admin/dashboard",
        UserRole.COMPANY: "/company/dashboard",
        UserRole.STUDENT: "/student/dashboard",
    }
    return paths[role]
