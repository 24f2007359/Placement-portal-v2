"""Celery background jobs (Milestone 7).

Three families of jobs:

  1. send_interview_reminders          — scheduled (Beat, daily 09:00 IST)
  2. generate_monthly_placement_reports — scheduled (Beat, 1st of month 06:00)
  3. export_*_csv                       — user-triggered, asynchronous

All datetimes coming out of SQLite are treated as naive UTC; helpers below
normalise before comparing so a tz-aware value stored earlier can't break the
comparison.
"""

import csv
import io
import logging
import os
from datetime import datetime, timedelta, timezone

from jinja2 import Template
from xhtml2pdf import pisa

from celery_app import celery
from config import Config
from mail_utils import send_email
from models import (
    Application,
    ApplicationStatus,
    ApprovalStatus,
    Company,
    JobPosition,
    JobStatus,
    Placement,
    Student,
    User,
)

logger = logging.getLogger(__name__)


# --- helpers ---------------------------------------------------------------


def _naive_utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive(value):
    """Normalise a possibly tz-aware datetime to naive UTC for comparison."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _fmt(value, default="—"):
    if value is None or value == "":
        return default
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M")
    return str(value)


def _previous_month_window(today=None):
    """Return (start, end, label) for the calendar month before `today`."""
    today = today or _naive_utcnow()
    this_month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_end = this_month_start
    prev_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
    return prev_month_start, prev_month_end, prev_month_start.strftime("%B %Y")


def _write_csv(filename, header, rows):
    """Write rows to EXPORT_DIR/filename; return (path, csv_bytes)."""
    _ensure_dir(Config.EXPORT_DIR)
    path = os.path.join(Config.EXPORT_DIR, filename)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    content = buffer.getvalue()

    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)

    return path, content.encode("utf-8")


def _render_pdf(html):
    """Render HTML to PDF bytes. Returns None if conversion fails."""
    out = io.BytesIO()
    result = pisa.CreatePDF(html, dest=out)
    if result.err:
        logger.error("PDF generation failed (%s errors)", result.err)
        return None
    return out.getvalue()


# --- 1. Interview reminder job ---------------------------------------------

_REMINDER_HTML = Template(
    """
    <p>Hello {{ student_name }},</p>
    <p>This is a reminder that you have an interview scheduled:</p>
    <ul>
      <li><strong>Position:</strong> {{ job_title }}</li>
      <li><strong>Company:</strong> {{ company_name }}</li>
      <li><strong>Interview:</strong> {{ interview_date }}</li>
    </ul>
    {% if feedback %}<p><strong>Note from the company:</strong> {{ feedback }}</p>{% endif %}
    <p>All the best!<br/>— Placement Portal</p>
    """
)


@celery.task(name="tasks.send_interview_reminders")
def send_interview_reminders(lookahead_hours=None):
    """Email every student whose interview falls within the next N hours."""
    hours = lookahead_hours or Config.INTERVIEW_REMINDER_LOOKAHEAD_HOURS
    now = _naive_utcnow()
    horizon = now + timedelta(hours=hours)

    candidates = Application.query.filter(
        Application.status == ApplicationStatus.INTERVIEW,
        Application.interview_date.isnot(None),
    ).all()

    sent, skipped = 0, 0
    for application in candidates:
        interview_at = _as_naive(application.interview_date)
        if not (now <= interview_at <= horizon):
            continue

        student = application.student
        email = student.user.email if student and student.user else None
        if not email:
            skipped += 1
            continue

        job = application.job_position
        company = job.company if job else None

        html = _REMINDER_HTML.render(
            student_name=student.full_name,
            job_title=job.title if job else "—",
            company_name=company.name if company else "—",
            interview_date=_fmt(interview_at),
            feedback=application.feedback,
        )
        if send_email(email, f"Interview reminder: {job.title if job else 'Interview'}", html):
            sent += 1
        else:
            skipped += 1

    logger.info("Interview reminders: %s sent, %s skipped", sent, skipped)
    return {"checked": len(candidates), "sent": sent, "skipped": skipped, "lookahead_hours": hours}


# --- 2. Monthly placement report job ---------------------------------------

_REPORT_HTML = Template(
    """
<html><head><meta charset="utf-8"/><style>
  body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; color: #212529; }
  h1 { font-size: 18pt; margin-bottom: 2px; }
  h2 { font-size: 13pt; margin-top: 18px; border-bottom: 1px solid #dee2e6; }
  .muted { color: #6c757d; font-size: 9pt; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { border: 1px solid #dee2e6; padding: 5px 7px; text-align: left; font-size: 9.5pt; }
  th { background-color: #f1f3f5; }
  .stat { display: inline-block; width: 30%; padding: 6px 0; }
  .stat b { font-size: 15pt; color: #0d6efd; }
</style></head><body>
  <h1>Placement Report — {{ company.name }}</h1>
  <div class="muted">Reporting period: {{ period }} &nbsp;|&nbsp; Generated {{ generated_at }}</div>

  <h2>Summary</h2>
  <div>
    <span class="stat"><b>{{ stats.applications_received }}</b><br/>Applications received</span>
    <span class="stat"><b>{{ stats.shortlisted }}</b><br/>Shortlisted</span>
    <span class="stat"><b>{{ stats.interviews }}</b><br/>Interviews</span>
    <span class="stat"><b>{{ stats.offers }}</b><br/>Offers made</span>
    <span class="stat"><b>{{ stats.placed }}</b><br/>Placed</span>
    <span class="stat"><b>{{ stats.rejected }}</b><br/>Rejected</span>
  </div>
  <p class="muted">
    Job postings (all time): {{ stats.jobs_posted }} &nbsp;|&nbsp; Active: {{ stats.active_jobs }}
    &nbsp;|&nbsp; Conversion (placed / applications): {{ stats.conversion_rate }}%
  </p>

  <h2>Placements this period ({{ placements|length }})</h2>
  {% if placements %}
  <table>
    <tr><th>Student</th><th>Position</th><th>Salary</th><th>Joining date</th></tr>
    {% for p in placements %}
    <tr><td>{{ p.student }}</td><td>{{ p.position }}</td><td>{{ p.salary }}</td><td>{{ p.joining }}</td></tr>
    {% endfor %}
  </table>
  {% else %}<p class="muted">No placements recorded in this period.</p>{% endif %}

  <h2>Applications this period ({{ applications|length }})</h2>
  {% if applications %}
  <table>
    <tr><th>Student</th><th>Job</th><th>Status</th><th>Applied on</th></tr>
    {% for a in applications %}
    <tr><td>{{ a.student }}</td><td>{{ a.job }}</td><td>{{ a.status }}</td><td>{{ a.applied }}</td></tr>
    {% endfor %}
  </table>
  {% else %}<p class="muted">No applications received in this period.</p>{% endif %}

  <p class="muted" style="margin-top:24px;">Placement Portal V2 — automated monthly report.</p>
</body></html>
"""
)


def _build_company_report(company, start, end, period_label):
    """Render one company's report to HTML + PDF on disk. Returns a summary dict."""
    company_apps = (
        Application.query.join(JobPosition)
        .filter(JobPosition.company_id == company.id)
        .all()
    )
    period_apps = [
        a for a in company_apps if start <= (_as_naive(a.applied_at) or start) < end
    ]
    period_placements = [
        p
        for p in Placement.query.filter_by(company_id=company.id).all()
        if start <= (_as_naive(p.created_at) or start) < end
    ]

    def count(status):
        return sum(1 for a in period_apps if a.status == status)

    received = len(period_apps)
    placed = count(ApplicationStatus.PLACED)
    stats = {
        "jobs_posted": JobPosition.query.filter_by(company_id=company.id).count(),
        "active_jobs": JobPosition.query.filter_by(
            company_id=company.id, status=JobStatus.ACTIVE
        ).count(),
        "applications_received": received,
        "shortlisted": count(ApplicationStatus.SHORTLISTED),
        "interviews": count(ApplicationStatus.INTERVIEW),
        "offers": count(ApplicationStatus.OFFER),
        "placed": placed,
        "rejected": count(ApplicationStatus.REJECTED),
        "conversion_rate": round((placed / received) * 100, 1) if received else 0.0,
    }

    html = _REPORT_HTML.render(
        company=company,
        period=period_label,
        generated_at=_fmt(_naive_utcnow()),
        stats=stats,
        placements=[
            {
                "student": p.student.full_name if p.student else "—",
                "position": p.position,
                "salary": _fmt(p.salary),
                "joining": _fmt(p.joining_date),
            }
            for p in period_placements
        ],
        applications=[
            {
                "student": a.student.full_name if a.student else "—",
                "job": a.job_position.title if a.job_position else "—",
                "status": a.status.value,
                "applied": _fmt(_as_naive(a.applied_at)),
            }
            for a in period_apps
        ],
    )

    _ensure_dir(Config.REPORT_DIR)
    slug = f"company{company.id}_{start.strftime('%Y-%m')}"
    html_path = os.path.join(Config.REPORT_DIR, f"report_{slug}.html")
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(html)

    pdf_bytes = _render_pdf(html)
    pdf_path = None
    if pdf_bytes:
        pdf_path = os.path.join(Config.REPORT_DIR, f"report_{slug}.pdf")
        with open(pdf_path, "wb") as handle:
            handle.write(pdf_bytes)

    # Email the report to the company (HR contact preferred, else login email).
    recipient = company.hr_contact if _looks_like_email(company.hr_contact) else None
    if not recipient and company.user:
        recipient = company.user.email
    attachments = (
        [(f"report_{slug}.pdf", pdf_bytes, "application", "pdf")] if pdf_bytes else []
    )
    emailed = send_email(
        recipient,
        f"Monthly placement report — {period_label}",
        f"<p>Hello {company.name},</p><p>Your placement report for "
        f"<strong>{period_label}</strong> is attached.</p>"
        f"<p>Applications: {stats['applications_received']} · "
        f"Placed: {stats['placed']}</p><p>— Placement Portal</p>",
        attachments=attachments,
    )

    return {
        "company_id": company.id,
        "company": company.name,
        "period": period_label,
        "html_path": html_path,
        "pdf_path": pdf_path,
        "emailed": emailed,
        "stats": stats,
    }


def _looks_like_email(value):
    return bool(value) and "@" in value and "." in value.split("@")[-1]


@celery.task(name="tasks.generate_monthly_placement_reports")
def generate_monthly_placement_reports():
    """Generate + email last month's placement report for every approved company."""
    start, end, label = _previous_month_window()
    companies = Company.query.filter(
        Company.approval_status == ApprovalStatus.APPROVED,
        Company.is_blacklisted.is_(False),
    ).all()

    reports = [_build_company_report(c, start, end, label) for c in companies]
    logger.info("Generated %s monthly reports for %s", len(reports), label)
    return {"period": label, "companies": len(reports), "reports": reports}


@celery.task(name="tasks.generate_company_report")
def generate_company_report(company_id):
    """On-demand report for one company (admin-triggered)."""
    company = Company.query.get(company_id)
    if not company:
        return {"error": f"Company {company_id} not found"}
    start, end, label = _previous_month_window()
    return _build_company_report(company, start, end, label)


# --- 3. User-triggered CSV exports -----------------------------------------


@celery.task(name="tasks.export_applications_csv", bind=True)
def export_applications_csv(self, user_id):
    """Export the caller's application history to CSV, then email an alert.

    Students export their own applications; companies export applications
    received against their own job postings.
    """
    user = User.query.get(user_id)
    if not user:
        return {"error": f"User {user_id} not found"}

    timestamp = _naive_utcnow().strftime("%Y%m%d%H%M%S")
    role = user.role.value

    if role == "student":
        student = user.student
        if not student:
            return {"error": "Student profile not found"}
        header = ["Job Title", "Company", "Status", "Applied On", "Interview Date", "Feedback"]
        rows = [
            [
                a.job_position.title if a.job_position else "",
                a.job_position.company.name if a.job_position and a.job_position.company else "",
                a.status.value,
                _fmt(_as_naive(a.applied_at), ""),
                _fmt(_as_naive(a.interview_date), ""),
                a.feedback or "",
            ]
            for a in Application.query.filter_by(student_id=student.id)
            .order_by(Application.applied_at.desc())
            .all()
        ]
    elif role == "company":
        company = user.company
        if not company:
            return {"error": "Company profile not found"}
        header = ["Student", "Institute ID", "Email", "Job Title", "Status", "Applied On", "Interview Date", "Feedback"]
        rows = [
            [
                a.student.full_name if a.student else "",
                a.student.institute_id if a.student else "",
                a.student.user.email if a.student and a.student.user else "",
                a.job_position.title if a.job_position else "",
                a.status.value,
                _fmt(_as_naive(a.applied_at), ""),
                _fmt(_as_naive(a.interview_date), ""),
                a.feedback or "",
            ]
            for a in Application.query.join(JobPosition)
            .filter(JobPosition.company_id == company.id)
            .order_by(Application.applied_at.desc())
            .all()
        ]
    else:
        return {"error": "Only students and companies can export applications"}

    filename = f"applications_user{user_id}_{timestamp}.csv"
    path, data = _write_csv(filename, header, rows)

    send_email(
        user.email,
        "Your applications export is ready",
        f"<p>Your CSV export of <strong>{len(rows)}</strong> application(s) is ready.</p>"
        "<p>It is attached, and also downloadable from your dashboard.</p>"
        "<p>— Placement Portal</p>",
        attachments=[(filename, data, "text", "csv")],
    )

    return {"filename": filename, "rows": len(rows), "path": path}


@celery.task(name="tasks.export_placements_csv", bind=True)
def export_placements_csv(self, user_id):
    """Export placement history for the caller (student, company, or admin)."""
    user = User.query.get(user_id)
    if not user:
        return {"error": f"User {user_id} not found"}

    timestamp = _naive_utcnow().strftime("%Y%m%d%H%M%S")
    role = user.role.value

    if role == "student":
        if not user.student:
            return {"error": "Student profile not found"}
        query = Placement.query.filter_by(student_id=user.student.id)
    elif role == "company":
        if not user.company:
            return {"error": "Company profile not found"}
        query = Placement.query.filter_by(company_id=user.company.id)
    elif role == "admin":
        query = Placement.query
    else:
        return {"error": "Unsupported role"}

    header = ["Student", "Company", "Position", "Salary", "Joining Date", "Recorded On"]
    rows = [
        [
            p.student.full_name if p.student else "",
            p.company.name if p.company else "",
            p.position,
            p.salary if p.salary is not None else "",
            _fmt(p.joining_date, ""),
            _fmt(_as_naive(p.created_at), ""),
        ]
        for p in query.order_by(Placement.created_at.desc()).all()
    ]

    filename = f"placements_user{user_id}_{timestamp}.csv"
    path, data = _write_csv(filename, header, rows)

    send_email(
        user.email,
        "Your placements export is ready",
        f"<p>Your CSV export of <strong>{len(rows)}</strong> placement record(s) is ready.</p>"
        "<p>It is attached, and also downloadable from your dashboard.</p>"
        "<p>— Placement Portal</p>",
        attachments=[(filename, data, "text", "csv")],
    )

    return {"filename": filename, "rows": len(rows), "path": path}
