"""
===============================================================================
FILE : backend/auth_utils.py
WHAT : JWT mint/verify + the @token_required / @role_required decorators.
WHY  : this is the REAL security boundary of the app. the vue-router guard in
       frontend/src/router/index.js is just UX -- anyone can bypass that with
       devtools. nothing gets past THESE decorators.

USED BY:
  routes.py         -> create_token() on login/register, @token_required on /me
  admin_routes.py   -> @role_required("admin") on every route
  company_routes.py -> @role_required("company")
  student_routes.py -> @role_required("student")
  export_routes.py  -> @role_required("student","company") etc + @token_required

HOW A REQUEST FLOWS:
  1. frontend api.js interceptor sticks `Authorization: Bearer <jwt>` on it
  2. @role_required -> @token_required -> get_current_user()
  3. decode the jwt, look the user up, check they're still active
  4. stash the User on flask's `g` (per-request scratchpad)
  5. the route body just reads g.current_user. no db lookup needed.

WHY JWT AND NOT SESSIONS? stateless. the server keeps nothing. the flip side is
you CANNOT revoke a token -- logging out just throws the client's copy away. a
stolen token stays valid until it expires (JWT_EXPIRATION_HOURS, default 24).
that's why is_active is re-checked from the DB on EVERY request: it's our only
kill switch for a blacklisted user who still holds a valid token.
===============================================================================
"""

from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import g, jsonify, request

from config import Config
from models import User


def create_token(user):
    """Mint a signed JWT for this user.

    called by: routes.py -> login(), register_student(), register_company()

    the payload is PUBLIC -- base64, not encrypted. anyone can read it. so never
    put anything secret in here. what stops tampering is the SIGNATURE: change
    one byte of the payload and decode_token() throws.

    `exp` is special: PyJWT enforces it automatically on decode and raises
    ExpiredSignatureError. we don't have to check it ourselves.
    """
    payload = {
        "user_id": user.id,
        "role": user.role.value,  # .value -> the enum's string, e.g. "student"
        "exp": datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm=Config.JWT_ALGORITHM)


def decode_token(token):
    """Verify signature + expiry, return the payload dict.

    raises jwt.PyJWTError (or a subclass) on ANY problem -- bad signature,
    expired, malformed. callers catch that.

    passing algorithms=[...] explicitly is a real security fix, not boilerplate:
    without it an attacker could hand us a token with alg:"none" and we'd
    happily accept an unsigned one.
    """
    return jwt.decode(token, Config.SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])


def get_current_user():
    """Pull the User out of the Authorization header. Returns None on any failure.

    returns None (not an exception) for: no header, wrong scheme, bad/expired
    token, deleted user, DEACTIVATED user. the caller turns None into a 401.

    `not user.is_active` is the important line. an admin blacklists a student ->
    is_active=False -> their still-valid JWT stops working on the very next
    request. this is the only way to revoke a stateless token.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]  # maxsplit=1: don't choke on a token with spaces
    try:
        payload = decode_token(token)
        user = User.query.get(payload["user_id"])
        if not user or not user.is_active:
            return None
        return user
    except jwt.PyJWTError:
        return None


def token_required(f):
    """Decorator: "you must be logged in as SOMEBODY."

    on success, parks the User object on `g.current_user`. `g` is flask's
    per-request global -- torn down when the response is sent, so there's no
    leakage between requests or threads.

    @wraps(f) copies over __name__/__doc__. NOT optional: flask registers routes
    by function name, so without it every decorated view would be called
    "decorated" and the second blueprint registration would explode.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        g.current_user = user
        return f(*args, **kwargs)

    return decorated


def role_required(*roles):
    """Decorator FACTORY: "you must be logged in AND be one of these roles."

    usage:
        @role_required("admin")                       -> admin only
        @role_required("student", "company")          -> either one

    three levels deep because it takes arguments:
        role_required("admin")  -> returns `decorator`
        decorator(view_fn)      -> returns `decorated`
        decorated(*a, **kw)     -> actually runs per request

    note it stacks @token_required underneath, so auth runs first (401) and only
    then the role check (403). different status codes on purpose:
        401 = "who are you?"      -> frontend should send you to /login
        403 = "I know you, no."   -> frontend shows an error
    """

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
    """Serialize a User for the API. NEVER includes password_hash.

    used by: routes.py -> login / register / me. the result gets stashed in the
    frontend's localStorage by services/auth.js -> setSession().

    the `profile` key is SHAPE-SHIFTY, which trips people up:
      role=company -> profile has .name
      role=student -> profile has .full_name
      role=admin   -> NO profile key at all (admins have no profile row)
    that's why CompanyDashboard.vue reads auth.user?.profile?.name while
    StudentDashboard.vue reads auth.user?.profile?.full_name.

    the `and user.company` guard matters: role could say company while the
    Company row is missing (mid-transaction, or hand-edited db). don't crash.
    """
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
            # the frontend uses this to decide whether to show the
            # "awaiting approval" banner
            "approval_status": user.company.approval_status.value,
            "is_blacklisted": user.company.is_blacklisted,
        }
    elif user.role.value == "student" and user.student:
        data["profile"] = {
            "id": user.student.id,
            "full_name": user.student.full_name,
            "institute_id": user.student.institute_id,
            "contact": user.student.contact,
            # branch / cgpa / graduation_year are the eligibility trio --
            # student_routes._check_eligibility() tests against these
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
