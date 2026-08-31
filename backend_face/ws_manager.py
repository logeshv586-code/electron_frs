from typing import Dict, List
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, company_id: str) -> bool:
        """Authenticate before accepting a tenant recognition WebSocket."""
        token = websocket.query_params.get("token", "").strip()
        if not token:
            logger.warning("Rejected recognition WebSocket without token for company %s", company_id)
            await websocket.close(code=4401, reason="Authentication required")
            return False

        try:
            from auth.security import verify_token
            from auth.users import get_user

            claims = verify_token(token)
            if not claims:
                await websocket.close(code=4401, reason="Invalid or expired token")
                return False

            user = get_user(claims.get("username"))
            if not user or not user.get("is_active", True):
                await websocket.close(code=4401, reason="Account unavailable")
                return False

            role = str(user.get("role") or claims.get("role") or "")
            user_company = str(user.get("company_id") or claims.get("company_id") or "default")
            requested_company = str(company_id or "default")
            if role != "SuperAdmin" and user_company != requested_company:
                logger.warning(
                    "Rejected cross-tenant WebSocket subscription user=%s user_company=%s requested=%s",
                    user.get("username"), user_company, requested_company,
                )
                await websocket.close(code=4403, reason="Tenant access denied")
                return False
        except Exception as exc:
            logger.error("WebSocket authentication error: %s", exc)
            await websocket.close(code=1011, reason="Authentication service error")
            return False

        await websocket.accept()
        self.active_connections.setdefault(str(company_id), []).append(websocket)
        logger.info("Authenticated WebSocket connection for company: %s", company_id)
        return True

    def disconnect(self, websocket: WebSocket, company_id: str):
        key = str(company_id)
        if key in self.active_connections:
            if websocket in self.active_connections[key]:
                self.active_connections[key].remove(websocket)
            if not self.active_connections[key]:
                del self.active_connections[key]
        logger.info("WebSocket disconnected for company: %s", company_id)

    async def broadcast(self, message: dict, company_id: str):
        key = str(company_id)
        for connection in list(self.active_connections.get(key, [])):
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.error("Error broadcasting to WebSocket for company %s: %s", company_id, exc)
                self.disconnect(connection, key)


ws_manager = ConnectionManager()
