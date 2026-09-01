from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from .security import get_password_hash
from .storage import get_users, save_users

logger = logging.getLogger(__name__)


def bootstrap_admin_from_env() -> Optional[Dict[str, Any]]:
    """Create the first SuperAdmin only when the user store is empty.

    Required for a clean installation:
      FRS_BOOTSTRAP_ADMIN_USER
      FRS_BOOTSTRAP_ADMIN_PASSWORD

    The password is never written to source files. After the first successful startup,
    the account lives in the configured database and the bootstrap password can be
    removed from the environment.
    """
    users = get_users()
    if users:
        return None

    username = os.getenv("FRS_BOOTSTRAP_ADMIN_USER", "").strip()
    password = os.getenv("FRS_BOOTSTRAP_ADMIN_PASSWORD", "")
    email = os.getenv("FRS_BOOTSTRAP_ADMIN_EMAIL", "").strip() or None

    if not username or len(password) < 12:
        logger.warning(
            "No users exist. Set FRS_BOOTSTRAP_ADMIN_USER and a "
            "FRS_BOOTSTRAP_ADMIN_PASSWORD of at least 12 characters to create the first SuperAdmin."
        )
        return None

    now = datetime.now(timezone.utc).isoformat()
    user = {
        "username": username,
        "hashed_password": get_password_hash(password),
        "role": "SuperAdmin",
        "email": email,
        "is_active": True,
        "created_by": "system-bootstrap",
        "created_at": now,
        "assigned_cameras": [],
        "assigned_menus": [
            "dashboard", "companies", "registration", "matching", "gallery", "events",
            "attendance", "holiday-calendar", "cameras", "stream-viewer", "video", "admin",
            "settings", "backupmgmt",
        ],
        "max_users_limit": 0,
        "max_cameras_limit": 0,
        "company_id": None,
    }
    users[username] = user
    save_users(users)
    logger.warning(
        "Created initial SuperAdmin '%s' from environment. Remove "
        "FRS_BOOTSTRAP_ADMIN_PASSWORD from the environment after confirming login.",
        username,
    )
    return user
