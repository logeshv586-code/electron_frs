import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from .storage import get_settings
import logging

logger = logging.getLogger(__name__)

def send_email(to_email: str, subject: str, body: str):
    settings = get_settings()
    smtp_host = settings.get("smtp_host")
    smtp_port = settings.get("smtp_port", 587)
    smtp_user = settings.get("smtp_user")
    smtp_password = settings.get("smtp_password")
    smtp_use_tls = settings.get("smtp_use_tls", True)
    email_from = settings.get("email_from", smtp_user)

    if not all([smtp_host, smtp_port, smtp_user, smtp_password]):
        logger.warning("Email settings not configured. Cannot send email.")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = email_from
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(smtp_host, smtp_port)
        if smtp_use_tls:
            server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False
