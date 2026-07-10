"""
===============================================================================
FILE : backend/student_routes.py
WHAT : every /api/student/* endpoint. profile, job search, apply, track, download.
WHY  : Milestone 5 (+ M6 history/placements bolted on).

BLUEPRINT: student_bp, url_prefix="/api/student"
FRONTEND COUNTERPART: src/services/student.js <- views/StudentDashboard.vue

EVERY ROUTE IS @role_required("student"). on top of that, every route calls
_ensure_student_access() first, which re-checks blacklist/active. why both?
role_required proves you're A student; _ensure_student_access proves you're a
student in good standing WITH a profile row.

THE TWO RULES THIS FILE ENFORCES (both Milestone 6 requirements):
  1. students only ever SEE approved drives from approved companies
     -> _approved_jobs_query() is the single chokepoint. every job read goes
        through it. there is no other way to list a job.
  2. a student cannot apply to the same job twice
     -> explicit check for a friendly 409, PLUS the db unique constraint as the
        real backstop under a race.
===============================================================================
"""

import os
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request, send_file
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from auth_utils import role_required
from cache_utils import NS_JOBS, bump_jobs, bump_students, cached
from models import (
    Application,
    ApplicationStatus,
    ApprovalStatus,
    Company,
    JobPosition,
    JobStatus,
    Placement,
    Student,
    db,
    log_application_status,
    serialize_placement,
    serialize_status_history,
)

student_bp = Blueprint("student", __name__, url_prefix="/api/student")

# resumes land here. NOT under static/ -- these files must never be served
# directly by the web server, only through an authed route.
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "instance", "uploads", "resumes")
# a WHITELIST, not a blacklist. blacklists always leak (.php5, .pHtml, ...).
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}


def _ensure_student_access():
    """Gate every student route. Returns (student, None) or (None, error_tuple).

    the awkward two-value return is so callers can do:
        student, error_response = _ensure_student_access()
        if error_response:
            return error_response
    ...and `error_response` is already the (jsonify, status) tuple flask wants.

    checks, in order:
      1. a Student profile row actually exists (404 if the User says student but
         the profile is missing -- shouldn't happen, but don't 500 over it)
      2. not blacklisted, and the User is still active

    note @role_required already blocked non-students. this adds the *standing*
    check, and hands the route its Student object so it doesn't re-look-it-up.
    """
    student = g.current_user.student
    if not student:
        return None, (jsonify({"error": "Student profile not found"}), 404)

    if student.is_blacklisted or not g.current_user.is_active:
        return None, (jsonify({"error": "Student account is deactivated or blacklisted"}), 403)

    return student, None


def _serialize_student(student):
    """Student row -> JSON for GET/PUT /profile. fatter than auth_utils.user_response's
    `profile` blob -- this one is what fills the Profile tab form."""
    return {
        "id": student.id,
        "full_name": student.full_name,
        "email": student.user.email if student.user else None,
        "institute_id": student.institute_id,
        "contact": student.contact,
        "branch": student.branch,
        "cgpa": student.cgpa,
        "graduation_year": student.graduation_year,
        "skills": student.skills,
        "education": student.education,
        "experience": student.experience,
        "resume_path": student.resume_path,
        "is_blacklisted": student.is_blacklisted,
    }


def _serialize_job_for_student(job, student):
    """Job row -> JSON for the Browse Jobs table.

    the interesting bit is `already_applied` / `application_status`: we look up
    THIS student's application for THIS job so the frontend can grey out the
    Apply button instead of letting them fire a doomed 409.

    !! N+1 QUERY WARNING !! this runs one SELECT per job in the list. fine for a
    course project with 20 jobs; if the list ever gets big, fetch all of this
    student's applications once into a dict and look up in memory.
    """
    applied = Application.query.filter_by(student_id=student.id, job_id=job.id).first()
    return {
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "company_id": job.company_id,
        "company_name": job.company.name if job.company else None,
        "company_location": job.company.location if job.company else None,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "skills_required": job.skills_required,
        "experience_required": job.experience_required,
        "eligibility_branch": job.eligibility_branch,
        "eligibility_cgpa": job.eligibility_cgpa,
        "eligibility_year": job.eligibility_year,
        "benefits": job.benefits,
        "application_deadline": job.application_deadline.isoformat()
        if job.application_deadline
        else None,
        "status": job.status.value,
        "already_applied": applied is not None,
        "application_status": applied.status.value if applied else None,
    }


def _serialize_application(application, include_history=False):
    """Application row -> JSON for the My Applications table.

    include_history defaults to FALSE on purpose. the LIST endpoint skips the
    timeline (no point shipping 6 history rows x 40 applications). only the
    DETAIL endpoint passes include_history=True, which is why the frontend fires
    a second request when you click "Timeline".

    has_offer_letter: true for offer|placed, OR if a Placement row exists at all.
    that `or` covers a placement recorded off-portal without the status moving.
    """
    job = application.job_position
    company = job.company if job else None
    placement = application.placement
    data = {
        "id": application.id,
        "job_id": application.job_id,
        "job_title": job.title if job else None,
        "company_name": company.name if company else None,
        "status": application.status.value,
        "applied_at": application.applied_at.isoformat() if application.applied_at else None,
        "feedback": application.feedback,
        "interview_date": application.interview_date.isoformat()
        if application.interview_date
        else None,
        "has_offer_letter": application.status in (
            ApplicationStatus.OFFER,
            ApplicationStatus.PLACED,
        )
        or (placement is not None),
        "placement_id": placement.id if placement else None,
        "placement": serialize_placement(placement) if placement else None,
    }
    if include_history:
        data["status_history"] = serialize_status_history(application)
    return data


def _approved_jobs_query():
    """THE VISIBILITY CHOKEPOINT. Returns an unexecuted Query, not a list.

    !! every single job a student can see or apply to comes through here. !!
    list_jobs() adds search filters onto it; apply_for_job() adds .filter(id==x).
    that's why a student can never see or apply to a pending/rejected drive --
    there is no code path that reads JobPosition without this filter.

    three conditions, all required:
      - the COMPANY is approved       (a pending company's jobs stay hidden)
      - the COMPANY isn't blacklisted (blacklisting instantly hides their jobs)
      - the JOB is approved or active (pending = not yet admin-approved,
                                       closed = finished or admin-rejected)

    APPROVED and ACTIVE both count as "students may apply". ACTIVE is just the
    company saying "we're actively hiring"; it grants no extra visibility.

    returning a Query (lazy) instead of .all() is the whole trick -- callers
    chain more filters, and .count() on it never loads a single row.
    """
    return (
        JobPosition.query.join(Company)
        .filter(Company.approval_status == ApprovalStatus.APPROVED)
        .filter(Company.is_blacklisted.is_(False))
        .filter(JobPosition.status.in_([JobStatus.APPROVED, JobStatus.ACTIVE]))
    )


def _check_eligibility(student, job):
    """Can this student apply to this job? -> (True, None) or (False, "why not").

    called ONLY by apply_for_job(). note the Browse Jobs list does NOT filter on
    eligibility -- students still SEE jobs they can't apply to, along with the
    requirements, so they know what to fix in their profile.

    each rule is skipped when the job doesn't set it (null = no restriction).
    within a rule, a MISSING profile value is its own error, distinct from
    "you don't meet it" -- "CGPA is required in your profile" tells the student
    to go fill it in, which is far more useful than "not eligible".

    cgpa  -> minimum (>=)
    year  -> EXACT match, not a minimum. a 2025 grad can't apply to a 2026 drive.
    branch-> comma-separated list, case-insensitive. the literal string "all"
             anywhere in that list waves everyone through.
    """
    if job.eligibility_cgpa is not None:
        # `is not None` not `if job.eligibility_cgpa` -- a required CGPA of 0.0
        # is falsy but still a real rule.
        if student.cgpa is None:
            return False, "CGPA is required in your profile to apply for this job"
        if student.cgpa < job.eligibility_cgpa:
            return False, f"Minimum CGPA required is {job.eligibility_cgpa}"

    if job.eligibility_year is not None:
        if student.graduation_year is None:
            return False, "Graduation year is required in your profile to apply for this job"
        if student.graduation_year != job.eligibility_year:
            return False, f"Only graduation year {job.eligibility_year} is eligible"

    if job.eligibility_branch:
        if not student.branch:
            return False, "Branch is required in your profile to apply for this job"
        # normalise both sides: "CSE, ECE , Mech" -> ['cse','ece','mech']
        allowed = [b.strip().lower() for b in job.eligibility_branch.split(",")]
        if student.branch.lower() not in allowed and "all" not in allowed:
            return False, "Your branch is not eligible for this job"

    return True, None


def _generate_offer_letter_text(student, application):
    """Build a plain-text offer letter on the fly.

    only used when there's no REAL uploaded offer_letter_path on the Placement.
    keeps the demo working end-to-end without anyone having to upload a PDF.
    """
    job = application.job_position
    company = job.company if job else None
    lines = [
        "OFFER LETTER",
        "============",
        "",
        f"Date: {datetime.now(timezone.utc).strftime('%d %B %Y')}",
        f"Student: {student.full_name}",
        f"Institute ID: {student.institute_id or 'N/A'}",
        "",
        f"We are pleased to offer you the position of {job.title if job else 'N/A'}",
        f"at {company.name if company else 'N/A'}.",
        "",
        f"Application Status: {application.status.value.upper()}",
        "",
        "Congratulations on your placement!",
        "",
        "— Placement Portal",
    ]
    return "\n".join(lines)


@student_bp.route("/dashboard", methods=["GET"])
@role_required("student")
def student_dashboard():
    """GET /api/student/dashboard -> the 5 stat cards.

    called by: services/student.js -> getDashboard()

    `applications` here is a QUERY, not a list. so each .count() below fires its
    own cheap SELECT COUNT(*) and we never pull a single row into python.
    _approved_jobs_query().count() likewise.
    """
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    applications = Application.query.filter_by(student_id=student.id)
    return jsonify(
        {
            "message": "Welcome to the Student dashboard",
            "role": "student",
            "stats": {
                "available_jobs": _approved_jobs_query().count(),
                "applications_submitted": applications.count(),
                "shortlisted": applications.filter_by(
                    status=ApplicationStatus.SHORTLISTED
                ).count(),
                "interviews_scheduled": applications.filter(
                    Application.status == ApplicationStatus.INTERVIEW
                ).count(),
                "placed": applications.filter(
                    Application.status == ApplicationStatus.PLACED
                ).count(),
            },
        }
    )


@student_bp.route("/profile", methods=["GET"])
@role_required("student")
def get_profile():
    """GET /api/student/profile -> the full profile row.
    called by: services/student.js -> getProfile() -> fills the Profile tab form."""
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response
    return jsonify({"profile": _serialize_student(student)})


@student_bp.route("/profile", methods=["PUT"])
@role_required("student")
def update_profile():
    """PUT /api/student/profile -> partial update. called by saveProfile().

    THE PATTERN: `if "branch" in data:` not `if data.get("branch"):`
    -> we only touch a column when the key is actually PRESENT in the body.
       so sending {"cgpa": 8.5} alone won't blank out skills/education.
       and sending {"branch": ""} DOES intentionally clear branch to NULL.
    that distinction is impossible with .get(), which can't tell "absent" from
    "explicitly empty".

    note institute_id is NOT updatable here -- it's a unique key set at signup.
    the frontend renders it disabled, and this route simply ignores it.
    """
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    data = request.get_json(silent=True) or {}

    if "full_name" in data:
        full_name = (data.get("full_name") or "").strip()
        if not full_name:
            return jsonify({"error": "Full name cannot be empty"}), 400
        student.full_name = full_name

    if "contact" in data:
        student.contact = (data.get("contact") or "").strip() or None

    if "branch" in data:
        student.branch = (data.get("branch") or "").strip() or None

    # cast explicitly: the frontend's v-model.number usually sends a real number,
    # but a raw curl/JSON client can send "8.5" as a string. `not in (None, "")`
    # lets the user clear the field back to NULL.
    if "cgpa" in data:
        cgpa = data.get("cgpa")
        student.cgpa = float(cgpa) if cgpa not in (None, "") else None

    if "graduation_year" in data:
        year = data.get("graduation_year")
        student.graduation_year = int(year) if year not in (None, "") else None

    # the boring text fields, all handled identically: strip, and turn "" -> NULL.
    # isinstance check guards against someone POSTing {"skills": 123}.
    for field in ["skills", "education", "experience", "resume_path"]:
        if field in data:
            value = data.get(field)
            student.__setattr__(
                field, value.strip() if isinstance(value, str) and value.strip() else None
            )

    db.session.commit()
    # M8: the admin student search shows name/branch/contact -> now stale.
    bump_students()
    return jsonify({"message": "Profile updated successfully", "profile": _serialize_student(student)})


@student_bp.route("/profile/resume", methods=["POST"])
@role_required("student")
def upload_resume():
    """POST /api/student/profile/resume -> multipart file upload.

    called by: services/student.js -> uploadResume() (FormData, not JSON)

    THREE SECURITY LAYERS, all needed:
      1. extension WHITELIST -- reject anything not pdf/doc/docx/txt
      2. secure_filename()   -- strips "../", slashes, null bytes, unicode
                                nasties. without it a filename of
                                "../../app.py" would let a student overwrite
                                the source code.
      3. prefix with student_<id>_ -- so two students uploading "resume.pdf"
                                don't clobber each other, and the owner is
                                obvious from the filename on disk.

    note the prefix goes INSIDE secure_filename(), so the whole thing gets
    sanitised together.

    we store an absolute filesystem path in resume_path, not a URL. the file is
    never web-servable; it'd only ever go out through an authed route.

    LIMITATION: no size cap. a student could upload a 2GB "resume". a real
    deployment would set MAX_CONTENT_LENGTH in config.
    """
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    # request.files, NOT request.form -- multipart puts files in a separate dict
    if "resume" not in request.files:
        return jsonify({"error": "No resume file uploaded"}), 400

    file = request.files["resume"]
    # a browser can send an empty file part when the user picks nothing
    if not file or not file.filename:
        return jsonify({"error": "No resume file selected"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_RESUME_EXTENSIONS:
        return jsonify({"error": "Allowed formats: pdf, doc, docx, txt"}), 400

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # first upload creates the dir
    filename = secure_filename(f"student_{student.id}_{file.filename}")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)  # overwrites silently if they re-upload. that's fine.

    student.resume_path = filepath
    db.session.commit()
    return jsonify(
        {
            "message": "Resume uploaded successfully",
            "profile": _serialize_student(student),
        }
    )


@student_bp.route("/jobs", methods=["GET"])
@role_required("student")
@cached(NS_JOBS, vary_on_user=True)  # M8. see the !! below before you touch this
def list_jobs():
    """GET /api/student/jobs?q=&company= -> the Browse Jobs table.

    called by: services/student.js -> getJobs()

    !! CACHED, AND vary_on_user=True IS LOAD-BEARING !! (Milestone 8)
    every job in this response carries `already_applied` / `application_status`
    for THE CALLING STUDENT. cache it under a shared key and student B sees
    student A's applied state -- a real data leak, not just a stale list.
    the cache key therefore embeds the user id.

    invalidated (bump_jobs()) by: job create/update, admin approve/reject/remove
    job, company approval changes, and apply_for_job() below. TTL 60s is only the
    backstop if an invalidation is ever missed.

    @cached sits BELOW @role_required on purpose -> auth runs first, and
    g.current_user exists by the time the key is built.

    starts from _approved_jobs_query() so the visibility rules are baked in
    before a single search filter is applied. you physically cannot widen it.

    ?q= searches THREE columns at once (title OR skills OR company name) via
    db.or_(). ilike = case-insensitive LIKE. the %...% makes it a substring
    match, which means no index is used -- fine at this scale.

    ?company= narrows to one company by name.

    NOTE: no eligibility filtering. students see jobs they can't apply to, plus
    the requirements, so they know what to fix. the gate is at apply time.
    """
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    query = _approved_jobs_query()  # already joined to Company

    q = (request.args.get("q") or "").strip()
    if q:
        query = query.filter(
            db.or_(
                JobPosition.title.ilike(f"%{q}%"),
                JobPosition.skills_required.ilike(f"%{q}%"),
                Company.name.ilike(f"%{q}%"),  # works because of the join above
            )
        )

    company_name = (request.args.get("company") or "").strip()
    if company_name:
        query = query.filter(Company.name.ilike(f"%{company_name}%"))

    jobs = query.order_by(JobPosition.created_at.desc()).all()  # newest first
    return jsonify({"jobs": [_serialize_job_for_student(job, student) for job in jobs]})


@student_bp.route("/jobs/<int:job_id>/apply", methods=["POST"])
@role_required("student")
def apply_for_job(job_id):
    """POST /api/student/jobs/<id>/apply -> 201, creates the Application.

    called by: services/student.js -> applyForJob()

    FOUR GATES, in this order (cheapest / most important first):
      1. is the job even visible to you? -> _approved_jobs_query(). note we
         start from that query rather than JobPosition.query.get(), so asking to
         apply to a PENDING drive returns a plain 404 -- we don't even admit it
         exists.
      2. deadline passed?          -> 400
      3. already applied?          -> 409
      4. eligible (cgpa/branch/yr)?-> 400 with the specific reason

    THE DOUBLE DUPLICATE CHECK (Milestone 6 requirement):
      the `existing` lookup gives a friendly 409. but two concurrent requests can
      BOTH pass it, then both try to INSERT. the UniqueConstraint on
      (student_id, job_id) makes one of them lose at COMMIT with an
      IntegrityError, which we catch and turn into the exact same 409.
      the app check is for UX; the db constraint is the actual guarantee.
      rollback() is mandatory there or the session stays poisoned.

    the log_application_status() call writes the FIRST row of the M6 audit trail
    (from_status=None -> to_status=applied). we add it BEFORE commit, so the
    Application and its history row land atomically -- and passing
    `application=` (the object) lets sqlalchemy fill the FK even though the
    parent has no id yet.
    """
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    # gate 1: visibility. non-approved jobs simply don't exist to a student.
    job = _approved_jobs_query().filter(JobPosition.id == job_id).first()
    if not job:
        return jsonify({"error": "Job not found or not available for application"}), 404

    # gate 2: deadline. sqlite hands back a NAIVE datetime, but a value written by
    # an older code path may carry tzinfo. normalise both sides to naive-UTC
    # before comparing, or python raises
    # "can't compare offset-naive and offset-aware datetimes".
    if job.application_deadline:
        deadline = job.application_deadline
        if deadline.tzinfo is not None:
            deadline = deadline.replace(tzinfo=None)
        if deadline < datetime.now(timezone.utc).replace(tzinfo=None):
            return jsonify({"error": "Application deadline has passed"}), 400

    # gate 3: duplicate (friendly path)
    existing = Application.query.filter_by(student_id=student.id, job_id=job.id).first()
    if existing:
        return jsonify({"error": "You have already applied for this job"}), 409

    # gate 4: eligibility. `reason` is a human sentence, straight to the user.
    eligible, reason = _check_eligibility(student, job)
    if not eligible:
        return jsonify({"error": reason}), 400

    application = Application(student_id=student.id, job_id=job.id)  # status defaults to APPLIED
    db.session.add(application)
    log_application_status(  # M6: first entry in the timeline
        application,
        to_status=ApplicationStatus.APPLIED,
        changed_by_role="student",
        changed_by_user_id=g.current_user.id,
        note="Application submitted",
    )
    try:
        db.session.commit()  # application + history row, one transaction
    except IntegrityError:
        # gate 3, the real one: lost the race on the unique constraint.
        db.session.rollback()
        return jsonify({"error": "You have already applied for this job"}), 409

    # M8: this student's job list now shows already_applied=True for this job,
    # AND the company/admin job lists show applications_count+1. bump AFTER the
    # commit -- bumping before would let a concurrent read re-cache the old data
    # in the window between bump and commit.
    bump_jobs()

    return (
        jsonify(
            {
                "message": "Application submitted successfully",
                "application": _serialize_application(application),
            }
        ),
        201,
    )


@student_bp.route("/applications", methods=["GET"])
@role_required("student")
def list_applications():
    """GET /api/student/applications?status= -> My Applications table.

    called by: services/student.js -> getApplications()

    scoped to student_id from the JWT, so you can only ever see your own.
    (Milestone 6: "Students can view their own records.")

    ApplicationStatus(status) raises ValueError on a bogus string like
    "?status=banana" -> we catch it and 400 instead of leaking a 500 traceback.
    that's why the cast is inside a try, not an `if status in [...]` check.

    NO history in this payload -- see _serialize_application's docstring.
    """
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    status = (request.args.get("status") or "").strip().lower()
    query = Application.query.filter_by(student_id=student.id)

    if status:
        try:
            query = query.filter(Application.status == ApplicationStatus(status))
        except ValueError:
            return jsonify({"error": "Invalid status filter"}), 400

    applications = query.order_by(Application.applied_at.desc()).all()
    return jsonify({"applications": [_serialize_application(app) for app in applications]})


@student_bp.route("/applications/<int:application_id>", methods=["GET"])
@role_required("student")
def get_application(application_id):
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    # filter_by(id=..., student_id=...) NOT .get(id).
    # this is the ownership check AND the lookup in one. asking for someone
    # else's application id gives a 404, not a 403 -- we don't confirm it exists.
    application = Application.query.filter_by(
        id=application_id, student_id=student.id
    ).first_or_404()
    # include_history=True -> THIS is what feeds the Timeline modal (M6)
    return jsonify({"application": _serialize_application(application, include_history=True)})


@student_bp.route("/placements", methods=["GET"])
@role_required("student")
def list_student_placements():
    """GET /api/student/placements -> the Placements tab. (Milestone 6)

    called by: services/student.js -> getPlacements()
    empty for most students -- a Placement row only exists once a company marks
    them offer/placed. serialize_placement() is shared from models.py so all
    three roles get the identical shape.
    """
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    placements = (
        Placement.query.filter_by(student_id=student.id)
        .order_by(Placement.created_at.desc())
        .all()
    )
    return jsonify({"placements": [serialize_placement(p) for p in placements]})


@student_bp.route("/applications/<int:application_id>/offer-letter", methods=["GET"])
@role_required("student")
def download_offer_letter(application_id):
    """GET /api/student/applications/<id>/offer-letter -> the file.

    called by: services/student.js -> downloadOfferLetter() (responseType blob)

    ownership again via filter_by(student_id=...) -> can't fetch someone else's.
    then a status gate: offer/placed only. 400 otherwise.

    TWO PATHS:
      1. a real file was uploaded (placement.offer_letter_path exists on disk)
         -> serve that.
      2. nothing uploaded -> generate a plain-text letter on the fly, write it to
         the uploads dir, and serve that. keeps the demo working without anyone
         having to produce a real PDF.

    the os.path.exists() check matters: the db could point at a file that got
    deleted, and send_file() on a missing path throws a 500. this way we quietly
    fall through to the generated one.

    as_attachment=True -> sends Content-Disposition: attachment, so the browser
    saves it instead of rendering it inline.
    """
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    application = Application.query.filter_by(
        id=application_id, student_id=student.id
    ).first_or_404()

    if application.status not in (ApplicationStatus.OFFER, ApplicationStatus.PLACED):
        return jsonify({"error": "Offer letter is available only for offer/placed applications"}), 400

    # path 1: a genuine uploaded letter
    placement = application.placement
    if placement and placement.offer_letter_path and os.path.exists(placement.offer_letter_path):
        return send_file(
            placement.offer_letter_path,
            as_attachment=True,
            download_name=f"offer_letter_{application_id}.txt",
        )

    # path 2: fabricate one. overwrites any previous generated copy, which is
    # fine -- it's derived data, regenerated from the db every time.
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    temp_path = os.path.join(UPLOAD_FOLDER, f"offer_{application_id}.txt")
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(_generate_offer_letter_text(student, application))

    return send_file(
        temp_path,
        as_attachment=True,
        download_name=f"offer_letter_{application_id}.txt",
    )
