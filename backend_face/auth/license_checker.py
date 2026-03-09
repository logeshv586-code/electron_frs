import asyncio
import logging
from datetime import datetime, timezone, timedelta
from .storage import get_users
from .email_utils import send_email
from .license_dates import parse_license_datetime

logger = logging.getLogger(__name__)

async def check_licenses_and_notify():
    """
    Check all Admin licenses and send notification emails if they are close to expiry.
    Run this periodically.
    """
    while True:
        try:
            logger.info("Checking Admin licenses for expiry...")
            users = get_users()
            now = datetime.now(timezone.utc)
            
            for username, user in users.items():
                if user.get("role") != "Admin":
                    continue
                
                email = user.get("email")
                if not email:
                    continue
                
                end_str = user.get("license_end_date")
                if not end_str:
                    continue
                
                end_dt = parse_license_datetime(end_str)
                if not end_dt:
                    continue
                
                days_left = (end_dt - now).days
                
                # Notify at 30, 7, 3, 1, and 0 days
                if days_left in [30, 7, 3, 1, 0]:
                    subject = f"License Expiry Notification - {username}"
                    if days_left > 0:
                        body = f"Hello {username},\n\nYour license for the Face Recognition System is expiring in {days_left} days (on {end_dt.date()}).\nPlease contact the SuperAdmin to renew your license."
                    else:
                        body = f"Hello {username},\n\nYour license for the Face Recognition System has expired today.\nPlease contact the SuperAdmin immediately to restore access."
                    
                    send_email(email, subject, body)
                    logger.info(f"Sent expiry notification to {email} for user {username} ({days_left} days left)")

            # Run once every 24 hours
            await asyncio.sleep(24 * 3600)
            
        except Exception as e:
            logger.error(f"Error in license checker background task: {e}")
            await asyncio.sleep(3600)  # Retry after 1 hour if error

def start_license_checker():
    """Start the license checker in a background task"""
    loop = asyncio.get_event_loop()
    loop.create_task(check_licenses_and_notify())
