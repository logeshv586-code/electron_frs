from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any, Iterable
from urllib.parse import parse_qs

from .security import verify_token
from .users import get_user
from .storage import get_tokens, get_users
from .license_dates import parse_license_datetime

PUBLIC_PATHS = {
    "/api/auth/login",
    "/api/auth/bootstrap/superadmin",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/status",
    "/favicon.ico",
    "/",
}

ROLE_HIERARCHY = {
    "SuperAdmin": ["Admin", "Supervisor"],
    "Admin": ["Supervisor"],
    "Supervisor": [],
}

MEDIA_QUERY_TOKEN_PREFIXES = (
    "/api/gallery/image",
    "/api/captured/image",
    "/api/collections/cameras/",
    "/api/webrtc/",
)

# Old compatibility endpoints pre-date tenant-aware camera management and must never
# be reachable by customer Admin/Supervisor accounts. Enhanced /api/collections routes
# are the supported camera/stream path.
LEGACY_SUPERADMIN_ONLY_PREFIXES = (
    "/capture_face_upload",
    "/capture_face_b64",
    "/api/start_stream",
    "/api/stop_stream",
    "/api/get_stream_for_camera",
    "/api/video_feed/",
)

ROLE_DEFAULT_MENUS = {
    "Admin": {
        "dashboard", "analytics", "registration", "matching", "gallery", "events",
        "attendance", "attendance-report", "day-report", "week-report", "month-report",
        "camera", "cameras", "stream-viewer", "video", "users", "settings", "backup",
    },
    "Supervisor": {"dashboard", "events", "attendance", "attendance-report", "camera", "cameras", "stream-viewer"},
}


def get_current_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    token_data = verify_token(token)
    if not token_data:
        return None
    username = token_data.get("username")
    user = get_user(username) if username else None
    if not user or not user.get("is_active", True):
        return None
    return user


def _license_window_valid(start_value: Optional[str], end_value: Optional[str]) -> bool:
    now = datetime.now(timezone.utc)
    if start_value:
        start_dt = parse_license_datetime(start_value)
        if not start_dt or start_dt > now:
            return False
    if end_value:
        end_dt = parse_license_datetime(end_value)
        if not end_dt or end_dt < now:
            return False
    return True


def is_tenant_license_valid(user: Dict[str, Any]) -> bool:
    """Validate the customer tenant license for both Admin and Supervisor users.

    SuperAdmin is the private platform operator and is not constrained by customer
    license dates. A Supervisor inherits the active license window of its company Admin.
    """
    role = user.get("role")
    if role == "SuperAdmin":
        return True
    company_id = str(user.get("company_id") or "")
    if not company_id:
        return False

    if role == "Admin":
        return _license_window_valid(user.get("license_start_date"), user.get("license_end_date"))

    admins = [
        account for account in get_users().values()
        if account.get("role") == "Admin"
        and account.get("is_active", True)
        and str(account.get("company_id") or "") == company_id
    ]
    if not admins:
        return False
    return any(_license_window_valid(admin.get("license_start_date"), admin.get("license_end_date")) for admin in admins)


# Backward compatible name used by existing modules/tests.
def is_admin_license_valid(user: Dict[str, Any]) -> bool:
    return is_tenant_license_valid(user)


def check_permission(current_user: Dict[str, Any], required_role: str) -> bool:
    user_role = current_user.get("role")
    if not user_role:
        return False
    if user_role == required_role:
        return True
    return required_role in ROLE_HIERARCHY.get(user_role, [])


def _normalized_menus(user: Dict[str, Any]) -> set[str]:
    aliases = {
        "cameras": "camera",
        "admin": "users",
        "backupmgmt": "backup",
        "attendance-report": "attendance",
        "day-report": "attendance",
        "week-report": "attendance",
        "month-report": "attendance",
    }
    configured = user.get("assigned_menus") or user.get("menus") or []
    if not configured:
        configured = ROLE_DEFAULT_MENUS.get(user.get("role"), set())
    result = set()
    for value in configured:
        key = str(value).strip().lower()
        result.add(key)
        result.add(aliases.get(key, key))
    return result


def _has_any_menu(user: Dict[str, Any], names: Iterable[str]) -> bool:
    if user.get("role") == "SuperAdmin":
        return True
    menus = _normalized_menus(user)
    return any(name in menus for name in names)


def _menu_allowed(current_user: Dict[str, Any], path: str) -> bool:
    # Authentication and protected media are supporting capabilities, not standalone menus.
    if path.startswith(("/api/auth/", "/api/gallery/image", "/api/captured/image")):
        return True
    if path.startswith("/api/registration"):
        return _has_any_menu(current_user, {"registration"})
    if path.startswith("/api/matching") or path.startswith("/api/events/match-face"):
        return _has_any_menu(current_user, {"matching", "gallery"})
    if path.startswith(("/api/events/attendance", "/api/events/export", "/api/events/employees/export", "/api/events/dashboard")):
        return _has_any_menu(current_user, {"attendance", "dashboard"})
    if path.startswith("/api/events"):
        return _has_any_menu(current_user, {"events", "attendance"})
    if path.startswith("/api/analytics"):
        return _has_any_menu(current_user, {"analytics", "dashboard"})
    if path.startswith(("/api/collections", "/api/cameras")):
        return _has_any_menu(current_user, {"camera", "stream-viewer"})
    if path.startswith(("/api/video", "/api/webrtc")):
        return _has_any_menu(current_user, {"video", "stream-viewer", "camera"})
    if path.startswith("/api/users/settings"):
        return _has_any_menu(current_user, {"settings"})
    if path.startswith("/api/users"):
        return _has_any_menu(current_user, {"users"})
    if path.startswith("/api/backup"):
        return _has_any_menu(current_user, {"backup"})
    return True


def check_path_permission(current_user: Dict[str, Any], path: str, method: str) -> bool:
    role = current_user.get("role")
    if not role:
        return False
    if method == "OPTIONS":
        return True
    if role == "SuperAdmin":
        return True

    # Customer accounts are intentionally non-destructive. Admins can create/update/
    # deactivate within their tenant; hard deletion remains an internal SuperAdmin action.
    if method == "DELETE":
        return False
    if any(path.startswith(prefix) for prefix in LEGACY_SUPERADMIN_ONLY_PREFIXES):
        return False
    if path.startswith("/api/companies"):
        return False
    if not _menu_allowed(current_user, path):
        return False

    if role == "Admin":
        return True

    if role == "Supervisor":
        allowed = (
            "/api/dashboard",
            "/api/cameras",
            "/api/auth/me",
            "/api/auth/logout",
            "/api/analytics",
            "/api/registration",
            "/api/collections",
            "/api/events",
            "/api/webrtc",
            "/api/gallery/image",
            "/api/captured/image",
        )
        return any(path.startswith(prefix) for prefix in allowed)

    return False


def _query_token(scope) -> Optional[str]:
    query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
    if not query_string:
        return None
    params = parse_qs(query_string)
    values = params.get("token")
    return values[0] if values else None


def _header_token(scope) -> Optional[str]:
    headers = dict(scope.get("headers", []))
    auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
    return auth_header[7:] if auth_header.startswith("Bearer ") else None


def _token_is_active(token: str) -> bool:
    return token in get_tokens()


class RBACMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope_type = scope.get("type")
        if scope_type == "websocket":
            await self._handle_websocket(scope, receive, send)
            return
        if scope_type != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if path in PUBLIC_PATHS or method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        token = _header_token(scope)
        if not token and method in {"GET", "HEAD"} and path.startswith(MEDIA_QUERY_TOKEN_PREFIXES):
            token = _query_token(scope)
        if not token:
            await self.send_unauthorized(send)
            return

        current_user = get_current_user_from_token(token)
        if not current_user or not _token_is_active(token):
            await self.send_unauthorized(send)
            return
        if not is_tenant_license_valid(current_user):
            await self.send_forbidden(send, b'{"detail":"Company license is inactive or expired. Contact your provider."}')
            return
        if not check_path_permission(current_user, path, method):
            await self.send_forbidden(send)
            return

        scope["user"] = current_user
        scope["auth_token"] = token
        await self.app(scope, receive, send)

    async def _handle_websocket(self, scope, receive, send):
        token = _query_token(scope) or _header_token(scope)
        current_user = get_current_user_from_token(token) if token else None
        if not token or not current_user or not _token_is_active(token):
            await send({"type": "websocket.close", "code": 4001})
            return
        if not is_tenant_license_valid(current_user):
            await send({"type": "websocket.close", "code": 4003})
            return

        path = scope.get("path", "")
        if path.startswith("/ws/recognitions/") and current_user.get("role") != "SuperAdmin":
            requested_company = path.rsplit("/", 1)[-1]
            if str(requested_company) != str(current_user.get("company_id") or "default"):
                await send({"type": "websocket.close", "code": 4003})
                return

        scope["user"] = current_user
        scope["auth_token"] = token
        await self.app(scope, receive, send)

    async def send_unauthorized(self, send):
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [[b"content-type", b"application/json"]],
        })
        await send({"type": "http.response.body", "body": b'{"detail":"Not authenticated"}'})

    async def send_forbidden(self, send, message: bytes = b'{"detail":"Not enough permissions"}'):
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [[b"content-type", b"application/json"]],
        })
        await send({"type": "http.response.body", "body": message})
