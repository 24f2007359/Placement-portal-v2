import enum
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def _utcnow():
    return datetime.now(timezone.utc)


class UserRole(enum.Enum):
    ADMIN = "admin"
    COMPANY = "company"
    STUDENT = "student"


class ApprovalStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class JobStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    ACTIVE = "active"
    CLOSED = "closed"


class ApplicationStatus(enum.Enum):
    APPLIED = "applied"
    SHORTLISTED = "shortlisted"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    PLACED = "placed"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    company = db.relationship("Company", back_populates="user", uselist=False)
    student = db.relationship("Student", back_populates="user", uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email} ({self.role.value})>"


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False, index=True)
    industry = db.Column(db.String(100))
    location = db.Column(db.String(150))
    website = db.Column(db.String(200))
    hr_contact = db.Column(db.String(120))
    description = db.Column(db.Text)
    approval_status = db.Column(
        db.Enum(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False
    )
    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    user = db.relationship("User", back_populates="company")
    job_positions = db.relationship(
        "JobPosition", back_populates="company", cascade="all, delete-orphan"
    )
    placements = db.relationship("Placement", back_populates="company")

    def __repr__(self):
        return f"<Company {self.name}>"


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False, index=True)
    institute_id = db.Column(db.String(50), unique=True, index=True)
    contact = db.Column(db.String(20))
    branch = db.Column(db.String(100))
    cgpa = db.Column(db.Float)
    graduation_year = db.Column(db.Integer)
    skills = db.Column(db.Text)
    education = db.Column(db.Text)
    experience = db.Column(db.Text)
    resume_path = db.Column(db.String(300))
    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    user = db.relationship("User", back_populates="student")
    applications = db.relationship(
        "Application", back_populates="student", cascade="all, delete-orphan"
    )
    placements = db.relationship("Placement", back_populates="student")

    def __repr__(self):
        return f"<Student {self.full_name}>"


class JobPosition(db.Model):
    __tablename__ = "job_positions"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text)
    salary_min = db.Column(db.Integer)
    salary_max = db.Column(db.Integer)
    skills_required = db.Column(db.Text)
    experience_required = db.Column(db.String(100))
    eligibility_branch = db.Column(db.String(200))
    eligibility_cgpa = db.Column(db.Float)
    eligibility_year = db.Column(db.Integer)
    benefits = db.Column(db.Text)
    application_deadline = db.Column(db.DateTime)
    status = db.Column(db.Enum(JobStatus), default=JobStatus.PENDING, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    company = db.relationship("Company", back_populates="job_positions")
    applications = db.relationship(
        "Application", back_populates="job_position", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<JobPosition {self.title}>"


class Application(db.Model):
    __tablename__ = "applications"
    __table_args__ = (
        db.UniqueConstraint("student_id", "job_id", name="uq_student_job_application"),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    job_id = db.Column(db.Integer, db.ForeignKey("job_positions.id"), nullable=False, index=True)
    status = db.Column(
        db.Enum(ApplicationStatus), default=ApplicationStatus.APPLIED, nullable=False
    )
    applied_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    feedback = db.Column(db.Text)
    interview_date = db.Column(db.DateTime)

    student = db.relationship("Student", back_populates="applications")
    job_position = db.relationship("JobPosition", back_populates="applications")
    placement = db.relationship("Placement", back_populates="application", uselist=False)
    status_history = db.relationship(
        "ApplicationStatusHistory",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationStatusHistory.created_at",
    )

    def __repr__(self):
        return f"<Application student={self.student_id} job={self.job_id}>"


class ApplicationStatusHistory(db.Model):
    """Audit trail: one row per application status change (Milestone 6)."""

    __tablename__ = "application_status_history"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer, db.ForeignKey("applications.id"), nullable=False, index=True
    )
    from_status = db.Column(db.Enum(ApplicationStatus))  # null for the first "applied" entry
    to_status = db.Column(db.Enum(ApplicationStatus), nullable=False)
    changed_by_role = db.Column(db.String(20))  # admin / company / student
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    application = db.relationship("Application", back_populates="status_history")

    def __repr__(self):
        return f"<StatusHistory app={self.application_id} -> {self.to_status.value}>"


class Placement(db.Model):
    __tablename__ = "placements"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), unique=True)
    position = db.Column(db.String(200), nullable=False)
    salary = db.Column(db.Integer)
    joining_date = db.Column(db.Date)
    offer_letter_path = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    student = db.relationship("Student", back_populates="placements")
    company = db.relationship("Company", back_populates="placements")
    application = db.relationship("Application", back_populates="placement")

    def __repr__(self):
        return f"<Placement student={self.student_id} company={self.company_id}>"


# --- Milestone 6 helpers: status tracking + history -------------------------


def log_application_status(
    application,
    to_status,
    from_status=None,
    changed_by_role=None,
    changed_by_user_id=None,
    note=None,
):
    """Append a status-history row for an application.

    Only stages the row on the session (no commit) so callers can commit it
    together with the status change in one transaction.
    """
    entry = ApplicationStatusHistory(
        application=application,
        from_status=from_status,
        to_status=to_status,
        changed_by_role=changed_by_role,
        changed_by_user_id=changed_by_user_id,
        note=note,
    )
    db.session.add(entry)
    return entry


def change_application_status(
    application, new_status, changed_by_role=None, changed_by_user_id=None, note=None
):
    """Update an application's status and record the transition in history."""
    old_status = application.status
    application.status = new_status
    return log_application_status(
        application,
        to_status=new_status,
        from_status=old_status,
        changed_by_role=changed_by_role,
        changed_by_user_id=changed_by_user_id,
        note=note,
    )


def serialize_status_history(application):
    """Return the status timeline for an application.

    Falls back to a synthetic "applied" entry for legacy applications created
    before history tracking existed (so old data still renders a timeline).
    """
    if application.status_history:
        return [
            {
                "id": entry.id,
                "from_status": entry.from_status.value if entry.from_status else None,
                "to_status": entry.to_status.value,
                "changed_by_role": entry.changed_by_role,
                "note": entry.note,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry in application.status_history
        ]

    return [
        {
            "id": None,
            "from_status": None,
            "to_status": ApplicationStatus.APPLIED.value,
            "changed_by_role": "student",
            "note": "Application submitted",
            "created_at": application.applied_at.isoformat()
            if application.applied_at
            else None,
        }
    ]


def serialize_placement(placement):
    """Serialize a placement record for API responses (Milestone 6)."""
    student = placement.student
    company = placement.company
    return {
        "id": placement.id,
        "student_id": placement.student_id,
        "student_name": student.full_name if student else None,
        "company_id": placement.company_id,
        "company_name": company.name if company else None,
        "application_id": placement.application_id,
        "position": placement.position,
        "salary": placement.salary,
        "joining_date": placement.joining_date.isoformat() if placement.joining_date else None,
        "created_at": placement.created_at.isoformat() if placement.created_at else None,
    }
