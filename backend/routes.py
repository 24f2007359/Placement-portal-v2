"""
===============================================================================
FILE : backend/routes.py
WHAT : authentication. login, the two registration routes, and /me.
WHY  : Milestone 2. everything else in the app assumes you already have a JWT.

BLUEPRINTS DEFINED HERE (both registered in app.py):
  auth_bp      -> /api/auth/*   login, register/student, register/company, me
  dashboard_bp -> /api          (empty now -- the placeholder dashboards moved
                                 into admin_routes / company_routes / student_routes
                                 in M3-M5. kept so app.py's import doesn't break
                                 and future shared /api routes have a home.)

FRONTEND COUNTERPART: src/services/auth.js -> login/registerStudent/registerCompany/fetchMe

THE THREE ROLES, THREE DIFFERENT DEALS:
  student  -> self-register, instantly usable
  company  -> self-register, but approval_status=PENDING, so locked out until an
              admin approves. we STILL hand them a token (they can log in, they
              just get 403 on every /api/company/* route).
  admin    -> NO REGISTRATION ROUTE. deliberately. seed_admin.py makes the one
              admin row. otherwise anybody could sign up as admin and approve
              themselves. this absence is a feature.
===============================================================================
"""

from flask import Blueprint, g, jsonify, request

from auth_utils import create_token, token_required, user_response
from cache_utils import bump_companies, bump_students
from models import ApprovalStatus, Company, Student, User, UserRole, db

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api")


def _validate_credentials(data):
    """Shared email+password checks for login and both registers.

    returns a 4-tuple: (email, password, error_response, status_code)
    on success -> (email, pw, None, None)     <- caller checks `if error_response`
    on failure -> (None, None, jsonify(...), 400)

    yes it's a clunky signature. it exists so the three callers can do:
        email, password, error_response, status = _validate_credentials(data)
        if error_response:
            return error_response, status

    email is lowercased + stripped so "  Bob@Gmail.COM " and "bob@gmail.com" are
    the same account. that matters because the db unique constraint is
    case-SENSITIVE -- without this you could register the same address twice.

    len < 6 mirrors the frontend's minlength=6. never trust the frontend; a
    curl request skips it entirely.
    """
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return None, None, jsonify({"error": "Email and password are required"}), 400
    if len(password) < 6:
        return None, None, jsonify({"error": "Password must be at least 6 characters"}), 400

    return email, password, None, None


@auth_bp.route("/login", methods=["POST"])
def login():
    """POST /api/auth/login -> { message, token, user, redirect }

    ONE route for all three roles. we look the email up, check the hash, and the
    User row tells us what they are.

    called by: services/auth.js -> login() <- views/LoginView.vue

    THE ERROR MESSAGE IS VAGUE ON PURPOSE. "Invalid email or password" for both
    a missing user AND a bad password. if we said "no such user" an attacker
    could enumerate which emails are registered.

    then three more gates, each with its own message because at that point we
    know who you are and being specific is helpful, not leaky:
      is_active False  -> 403 deactivated (admin turned you off)
      company blacklisted -> 403
      student blacklisted -> 403

    `redirect` is computed SERVER-side (_dashboard_path). the frontend just
    obeys it, so the role->route mapping lives in one place.
    """
    data = request.get_json(silent=True) or {}
    email, password, error_response, status = _validate_credentials(data)
    if error_response:
        return error_response, status

    user = User.query.filter_by(email=email).first()
    # single check for both cases -> no user enumeration
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401

    if not user.is_active:
        return jsonify({"error": "Account is deactivated"}), 403

    # blacklisted users often still have is_active=True if only the profile flag
    # was set, so check the profile too. `and user.company` guards a role/profile
    # mismatch.
    if user.role == UserRole.COMPANY:
        if user.company and user.company.is_blacklisted:
            return jsonify({"error": "Company account is blacklisted"}), 403
    elif user.role == UserRole.STUDENT:
        if user.student and user.student.is_blacklisted:
            return jsonify({"error": "Student account is blacklisted"}), 403

    # NOTE: a PENDING company gets past here and receives a token. that's
    # intentional -- they can log in and see the "awaiting approval" banner.
    # the 403 comes later, from _ensure_company_access() on the dashboard call.
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
    """POST /api/auth/register/student -> 201 { token, user, redirect }

    creates BOTH rows (User + Student) in one transaction.
    called by: services/auth.js -> registerStudent() <- RegisterStudentView.vue

    two 409s to look out for:
      email already registered      (unique on users.email)
      institute ID already taken    (unique on students.institute_id)
    we check both by hand for friendly messages; the db constraints are the
    actual backstop against a race.

    `user=user` on the Student passes the OBJECT, so sqlalchemy fills in
    student.user_id after it INSERTs the user. no need to commit twice to get
    the id first.

    the student is logged in immediately -- we mint a token right here. no
    approval step, unlike companies.
    """
    data = request.get_json(silent=True) or {}
    email, password, error_response, status = _validate_credentials(data)
    if error_response:
        return error_response, status

    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"error": "Full name is required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    # `or None` -> an empty string becomes NULL. important: '' would collide with
    # the next student who also left it blank (unique constraint), but many NULLs
    # are allowed.
    institute_id = (data.get("institute_id") or "").strip() or None
    if institute_id and Student.query.filter_by(institute_id=institute_id).first():
        return jsonify({"error": "Institute ID already registered"}), 409

    user = User(email=email, role=UserRole.STUDENT)
    user.set_password(password)  # hashes it

    # branch is captured at signup; cgpa + graduation_year come later on the
    # Profile tab. all three are the eligibility trio.
    student = Student(
        user=user,
        full_name=full_name,
        institute_id=institute_id,
        contact=(data.get("contact") or "").strip() or None,
        branch=(data.get("branch") or "").strip() or None,
    )

    db.session.add(user)
    db.session.add(student)
    db.session.commit()  # one commit -> both rows or neither
    bump_students()  # M8: a new row in the admin student search

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
        201,  # 201 Created, not 200
    )


@auth_bp.route("/register/company", methods=["POST"])
def register_company():
    """POST /api/auth/register/company -> 201 { token, user, redirect }

    same as register_student EXCEPT approval_status=PENDING.
    called by: services/auth.js -> registerCompany() <- RegisterCompanyView.vue

    !! we hand them a working token and tell them to go to /company/dashboard !!
    that looks wrong but isn't. they log in fine; it's _ensure_company_access()
    in company_routes.py that 403s every actual data call. CompanyDashboard.vue
    catches that 403 and renders the yellow "pending approval" banner.

    doing it this way means a company can sit on their dashboard and watch for
    approval, instead of being bounced to a dead-end page.
    """
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
        # if this looks like an email, the M7 monthly report gets mailed here
        hr_contact=(data.get("hr_contact") or "").strip() or None,
        description=(data.get("description") or "").strip() or None,
        approval_status=ApprovalStatus.PENDING,  # THE GATE. explicit > implicit default.
    )

    db.session.add(user)
    db.session.add(company)
    db.session.commit()
    # M8: a new PENDING company must show up in the admin approval queue at once
    # -- that queue is the whole point of the Companies tab.
    bump_companies()

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
    """GET /api/auth/me -> { user }

    "who am i, right now, according to the server?"
    called by: services/auth.js -> fetchMe()

    why it exists: the frontend caches the user blob in localStorage, and that
    goes stale. an admin approves your company, or you update your profile from
    another tab -> the cached copy is a lie. this re-syncs it.

    @token_required puts the User on g.current_user, so no db lookup here.
    """
    return jsonify({"user": user_response(g.current_user)})


def _dashboard_path(role):
    """UserRole -> the frontend route to land on after login/register.

    lives server-side so there's ONE mapping. the frontend has a mirror copy in
    services/auth.js -> dashboardPath() (used by the router guard, where no API
    call is available). keep the two in sync.

    takes the ENUM, not the string. paths[role] KeyErrors loudly on a bad role,
    which is what we want -- better than silently returning '/login'.
    """
    paths = {
        UserRole.ADMIN: "/admin/dashboard",
        UserRole.COMPANY: "/company/dashboard",
        UserRole.STUDENT: "/student/dashboard",
    }
    return paths[role]
