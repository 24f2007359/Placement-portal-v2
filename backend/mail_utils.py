"""Email delivery for background jobs (Milestone 7).

Uses plain smtplib against Gmail SMTP. Set these environment variables:

    MAIL_USERNAME=you@gmail.com
    MAIL_PASSWORD=<16-char Gmail App Password>

Generate an App Password at https://myaccount.google.com/apppasswords
(requires 2-Step Verification). A normal account password will be rejected.

If credentials are absent, send_email() logs the message and returns False
instead of raising, so a missing config can never crash a Celery task or lose
a scheduled run.
"""

import logging
import smtplib
from email.message import EmailMessage

from config import Config

logger = logging.getLogger(__name__)


def mail_is_configured():
    """Both username AND password present? if not, we fall back to console logging."""
    return bool(Config.MAIL_USERNAME and Config.MAIL_PASSWORD)


def send_email(to, subject, html_body, text_body=None, attachments=None):
    """Send one email. Returns True if it was actually handed to the SMTP server.

    attachments: list of (filename, bytes, maintype, subtype) tuples.

    called by ALL of tasks.py:
      send_interview_reminders    -> plain html, no attachment
      _build_company_report       -> html + the PDF attached
      export_*_csv                -> html + the CSV attached

    RETURNS A BOOL, NEVER RAISES. that's the whole design. a task that emails
    200 students must not die on student #47's bounced address, and a missing
    MAIL_PASSWORD must not take down the nightly beat job. so:
      - no recipient      -> log a warning, return False
      - not configured    -> log the whole message to console, return False
      - SMTP blew up      -> log the error, return False
    callers just count the Trues. see the {sent, skipped} return of the reminder job.

    the console fallback is genuinely useful: the app works end-to-end with zero
    credentials, and you can read the emails in the worker terminal during a demo.

    MULTIPART/ALTERNATIVE: set_content() lays down the plain-text part first,
    then add_alternative(subtype="html") adds the pretty one. that ORDER is
    required by the MIME spec -- clients render the LAST part they understand.
    swap them and everyone sees raw HTML tags.
    """
    if not to:
        logger.warning("send_email skipped: no recipient for %r", subject)
        return False

    if not mail_is_configured():
        # the fallback. this is why nothing crashes without a Gmail app password.
        logger.info(
            "[MAIL NOT CONFIGURED] To: %s | Subject: %s\n%s",
            to,
            subject,
            text_body or _strip_tags(html_body),
        )
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = Config.MAIL_DEFAULT_SENDER
    message["To"] = to
    message.set_content(text_body or _strip_tags(html_body))  # plain part FIRST
    message.add_alternative(html_body, subtype="html")  # html part SECOND

    # maintype/subtype e.g. ("text","csv") or ("application","pdf")
    for filename, data, maintype, subtype in attachments or []:
        message.add_attachment(
            data, maintype=maintype, subtype=subtype, filename=filename
        )

    try:
        # `with` closes the connection even if login/send throws.
        with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT, timeout=30) as server:
            # port 587 -> connect plaintext, THEN upgrade to TLS. (port 465 would
            # be SMTP_SSL instead, encrypted from the first byte.)
            if Config.MAIL_USE_TLS:
                server.starttls()
            # gmail rejects the real account password here. must be a 16-char
            # App Password from myaccount.google.com/apppasswords (needs 2FA on).
            server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
            server.send_message(message)
        logger.info("Email sent to %s (%s)", to, subject)
        return True
    except Exception as exc:  # noqa: BLE001 - a mail failure must not kill the job
        # yes, a bare `except Exception`. deliberate: smtplib throws about eight
        # different classes (auth, connect, recipient refused, timeout, DNS...)
        # and the correct response to every one of them is "log it, move on".
        logger.error("Failed to send email to %s: %s", to, exc)
        return False


def _strip_tags(html):
    """Crude HTML -> text fallback for the plain-text alternative part.

    three regexes: <br> -> newline, </p> -> newline, then nuke every remaining
    tag. finally squash 3+ blank lines down to 2.

    this is NOT a real HTML parser and would be wrong on anything complex --
    but we only ever feed it our own small templates from tasks.py, so it's fine.
    (regex-parsing arbitrary HTML is the classic sin; here the input is ours.)

    `import re` is inside the function because this is a rarely-hit fallback and
    there's no reason to pay for it at module import.
    """
    import re

    text = re.sub(r"<br\s*/?>", "\n", html or "")
    text = re.sub(r"</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
