from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any
from urllib.parse import parse_qs

from .security import verify_token
from .users import get_user
from .storage import get_tokens
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


def get_current_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    token_data = verify_token(token)
    if not token_data:
        return None
    username = token_data.get("username")
    user = get_user(username) if username else None
    if not user or not user.get("is_active", True):
        return None
    return user


def is_admin_license_valid(user: Dict[str, Any]) -> bool:
    if user.get("role") != "Admin":
        return True
    end_str = user.get("license_end_date")
    if not end_str:
        return True
    end_dt = parse_license_datetime(end_str)
    if not end_dt:
        return False
    return end_dt >= datetime.now(timezone.utc)


def check_permission(current_user: Dict[str, Any], required_role: str) -> bool:
    user_role = current_user.get("role")
    if not user_role:
        return False
    if user_role == required_role:
        return True
    return required_role in ROLE_HIERARCHY.get(user_role, [])


def check_path_permission(current_user: Dict[str, Any], path: str, method: str) -> bool:
    role = current_user.get("role")
    if not role:
        return False
    if method == "OPTIONS":
        return True
    if role == "SuperAdmin":
        return True

    # Deleting biometric evidence is SuperAdmin-only.
    if path == "/api/events/delete" and method == "DELETE":
        return False

    if role == "Admin":
        if path.startswith("/api/users/") and ("superadmin" in path.lower() or path.endswith("/logs")):
            return False
        return True

    if role == "Supervisor":
        allowed = (
            "/api/dashboard",
            "/api/cameras",
            "/api/auth/me",
            "/api/analytics",
            "/api/registration",
            "/api/collections",
            "/api/events",
            "/api/webrtc",
            "/api/get_stream_for_camera",
            "/api/start_stream",
            "/api/stop_stream",
            "/api/start_collection_streams",
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
    # Existing installations use an explicit revocation list/active-token store.
    # A token must both validate cryptographically and remain registered here.
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
        if current_user.get("role") == "Admin" and not is_admin_license_valid(current_user):
            await self.send_forbidden(send, b'{"detail":"License expired. Contact SuperAdmin."}')
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

        # /ws/recognitions/{company_id}: a normal tenant may only subscribe to itself.
        path = scope.get("path", "")
        if path.startswith("/ws/recognitions/") and current_user.get("role") != "SuperAdmin":
            requested_company = path.rsplit("/", 1)[-1]
            if str(requested_company) != str(current_user.get("company_id") or "default"):
                await send({"type": "websocket.close", "code": 4003})
                return

        if current_user.get("role") == "Admin" and not is_admin_license_valid(current_user):
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
