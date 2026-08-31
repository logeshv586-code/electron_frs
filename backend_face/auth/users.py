from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from .storage import get_users, save_users, get_settings
from .security import get_password_hash

VALID_ROLES = {"SuperAdmin", "Admin", "Supervisor"}


def get_default_menus_for_role(role: str) -> List[str]:
    role_menus = {
        "SuperAdmin": [
            "dashboard", "companies", "registration", "matching", "gallery", "events",
            "attendance", "camera", "stream-viewer", "video", "users", "settings", "backup", "analytics",
        ],
        "Admin": [
            "dashboard", "registration", "matching", "gallery", "events", "attendance",
            "camera", "stream-viewer", "video", "users", "settings", "backup", "analytics",
        ],
        "Supervisor": ["dashboard", "events", "attendance", "camera", "stream-viewer"],
    }
    return list(role_menus.get(role, ["dashboard"]))


def _menu_set(user: Dict[str, Any]) -> set[str]:
    configured = user.get("assigned_menus") or get_default_menus_for_role(user.get("role", "Supervisor"))
    aliases = {
        "cameras": "camera",
        "attendance-report": "attendance",
        "day-report": "attendance",
        "week-report": "attendance",
        "month-report": "attendance",
        "backupmgmt": "backup",
        "admin": "users",
    }
    result = set()
    for value in configured:
        key = str(value).strip().lower()
        result.add(key)
        result.add(aliases.get(key, key))
    return result


def create_user(
    username: str,
    password: str,
    role: str,
    created_by: str,
    is_active: bool = True,
    max_users_limit: int = 0,
    max_cameras_limit: int = 0,
    assigned_menus: List[str] = None,
    license_start_date: Optional[str] = None,
    license_end_date: Optional[str] = None,
    email: Optional[str] = None,
    company_id: Optional[str] = None,
) -> Dict[str, Any]:
    users = get_users()
    username = str(username or "").strip()
    if not username:
        raise ValueError("Username is required")
    if username in users:
        raise ValueError("User already exists")
    if role not in VALID_ROLES:
        raise ValueError("Invalid role")
    if len(password or "") < 12:
        raise ValueError("Password must contain at least 12 characters")

    creator = users.get(created_by) if created_by else None
    if role in {"Admin", "Supervisor"} and not company_id:
        raise ValueError("Customer Admin and Supervisor accounts must belong to a company")

    if creator and creator.get("role") == "Admin":
        if role != "Supervisor":
            raise ValueError("Admins can only create Supervisor accounts")
        creator_company = str(creator.get("company_id") or "")
        if str(company_id or "") != creator_company:
            raise ValueError("Supervisor must belong to the Admin's company")
        current_users = sum(
            1 for account in users.values()
            if account.get("role") == "Supervisor"
            and str(account.get("company_id") or "") == creator_company
        )
        limit = int(creator.get("max_users_limit") or 0)
        if limit > 0 and current_users >= limit:
            raise ValueError(f"User creation limit reached. Maximum Supervisors: {limit}.")

        if assigned_menus is not None:
            creator_menus = _menu_set(creator)
            requested = {str(item).strip().lower() for item in assigned_menus}
            if not requested.issubset(creator_menus):
                raise ValueError("Cannot grant a Supervisor menus that are not enabled for this Admin")

    user_data = {
        "username": username,
        "hashed_password": get_password_hash(password),
        "role": role,
        "email": email,
        "is_active": bool(is_active),
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "assigned_cameras": [],
        "assigned_menus": list(assigned_menus) if assigned_menus is not None else get_default_menus_for_role(role),
        "max_users_limit": max(0, int(max_users_limit or 0)),
        "max_cameras_limit": max(0, int(max_cameras_limit or 0)),
        "company_id": str(company_id) if company_id else None,
    }
    if role == "Admin":
        user_data["license_start_date"] = license_start_date
        user_data["license_end_date"] = license_end_date

    users[username] = user_data
    save_users(users)
    return user_data


def get_user(username: str) -> Optional[Dict[str, Any]]:
    return get_users().get(username)


def update_user(username: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    users = get_users()
    if username not in users:
        return None

    user = users[username]
    allowed_updates = {
        "is_active", "assigned_cameras", "assigned_menus", "max_users_limit", "max_cameras_limit",
        "license_start_date", "license_end_date", "email", "company_id", "password",
    }
    for key, value in updates.items():
        if key not in allowed_updates:
            continue
        if key == "password":
            if len(value or "") < 12:
                raise ValueError("Password must contain at least 12 characters")
            user["hashed_password"] = get_password_hash(value)
        elif key in {"max_users_limit", "max_cameras_limit"}:
            user[key] = max(0, int(value or 0))
        elif key in {"assigned_cameras", "assigned_menus"}:
            user[key] = list(value or [])
        else:
            user[key] = value

    save_users(users)
    return user


def delete_user(username: str) -> bool:
    users = get_users()
    if username not in users:
        return False

    user_to_delete = users[username]
    company_id = user_to_delete.get("company_id")
    role = user_to_delete.get("role")

    from .cleanup_utils import cleanup_user_tokens
    cleanup_user_tokens(username)
    del users[username]
    save_users(users)

    if role == "Admin" and company_id:
        remaining_admins = [
            account for account in users.values()
            if account.get("company_id") == company_id and account.get("role") == "Admin"
        ]
        if not remaining_admins:
            try:
                from .companies import delete_company
                delete_company(company_id)
            except Exception:
                pass
    return True


def list_users(company_id: Optional[str] = None) -> List[Dict[str, Any]]:
    users = get_users()
    if company_id:
        return [account for account in users.values() if str(account.get("company_id") or "") == str(company_id)]
    return list(users.values())


def _same_tenant(actor: Dict[str, Any], target: Dict[str, Any]) -> bool:
    if actor.get("role") == "SuperAdmin":
        return True
    return bool(actor.get("company_id")) and str(actor.get("company_id")) == str(target.get("company_id"))


def _validate_camera_tenant(actor: Dict[str, Any], camera_ids: List[str]) -> tuple[bool, str]:
    if actor.get("role") == "SuperAdmin":
        return True, ""
    from db.repository import get_camera

    company_id = str(actor.get("company_id") or "")
    if not company_id:
        return False, "User is not assigned to a company"
    for value in camera_ids:
        try:
            camera = get_camera(int(value))
        except Exception:
            camera = None
        if not camera:
            return False, f"Camera {value} does not exist"
        if str(camera.get("company_id") or "") != company_id:
            return False, f"Camera {value} belongs to another company"
    return True, ""


def can_assign_cameras(admin_username: str, target_username: str, camera_count: int) -> tuple[bool, str]:
    users = get_users()
    actor = users.get(admin_username)
    target = users.get(target_username)
    if not actor or not target:
        return False, "User not found"
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        return False, "Insufficient permissions"
    if not _same_tenant(actor, target):
        return False, "Cannot manage users from another company"
    if actor.get("role") == "Admin" and target.get("role") != "Supervisor":
        return False, "Admins can only assign cameras to Supervisors"

    current_cameras = len(target.get("assigned_cameras") or [])
    if target.get("role") == "Admin":
        limit = int(target.get("max_cameras_limit") or 0)
    else:
        settings = get_settings(target.get("company_id"))
        limit = int(settings.get("max_cameras_per_supervisor", 5) or 0)
    if limit > 0 and current_cameras + camera_count > limit:
        return False, f"Would exceed maximum cameras ({limit}) for {target.get('role')} {target_username}"
    return True, ""


def assign_cameras_to_user(admin_username: str, target_username: str, camera_ids: List[str]) -> tuple[bool, str]:
    users = get_users()
    actor = users.get(admin_username)
    target = users.get(target_username)
    if not actor or not target:
        return False, "User not found"
    if not _same_tenant(actor, target):
        return False, "Cannot manage users from another company"

    normalized = sorted({str(value) for value in (camera_ids or [])})
    valid, reason = _validate_camera_tenant(actor, normalized)
    if not valid:
        return False, reason

    can_assign, reason = can_assign_cameras(admin_username, target_username, len(normalized))
    if not can_assign:
        return False, reason

    current = {str(value) for value in target.get("assigned_cameras", [])}
    target["assigned_cameras"] = sorted(current.union(normalized))
    save_users(users)
    return True, f"Successfully assigned {len(normalized)} cameras to {target_username}"


def remove_cameras_from_user(admin_username: str, target_username: str, camera_ids: List[str]) -> tuple[bool, str]:
    users = get_users()
    actor = users.get(admin_username)
    target = users.get(target_username)
    if not actor or not target:
        return False, "User not found"
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        return False, "Insufficient permissions"
    if not _same_tenant(actor, target):
        return False, "Cannot manage users from another company"

    current = {str(value) for value in target.get("assigned_cameras", [])}
    target["assigned_cameras"] = sorted(current - {str(value) for value in (camera_ids or [])})
    save_users(users)
    return True, f"Successfully removed {len(camera_ids or [])} cameras from {target_username}"


def get_user_cameras(username: str) -> List[str]:
    user = get_user(username)
    if not user:
        return []
    return [str(value) for value in user.get("assigned_cameras", [])]
