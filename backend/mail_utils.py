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
    return bool(Config.MAIL_USERNAME and Config.MAIL_PASSWORD)


def send_email(to, subject, html_body, text_body=None, attachments=None):
    """Send one email. Returns True if it was actually handed to the SMTP server.

    attachments: list of (filename, bytes, maintype, subtype) tuples.
    """
    if not to:
        logger.warning("send_email skipped: no recipient for %r", subject)
        return False

    if not mail_is_configured():
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
    message.set_content(text_body or _strip_tags(html_body))
    message.add_alternative(html_body, subtype="html")

    for filename, data, maintype, subtype in attachments or []:
        message.add_attachment(
            data, maintype=maintype, subtype=subtype, filename=filename
        )

    try:
        with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT, timeout=30) as server:
            if Config.MAIL_USE_TLS:
                server.starttls()
            server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
            server.send_message(message)
        logger.info("Email sent to %s (%s)", to, subject)
        return True
    except Exception as exc:  # noqa: BLE001 - a mail failure must not kill the job
        logger.error("Failed to send email to %s: %s", to, exc)
        return False


def _strip_tags(html):
    """Crude HTML -> text fallback for the plain-text alternative part."""
    import re

    text = re.sub(r"<br\s*/?>", "\n", html or "")
    text = re.sub(r"</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
