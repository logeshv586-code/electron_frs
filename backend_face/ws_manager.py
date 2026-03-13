from typing import Dict, List
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Maps company_id -> list of active WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, company_id: str):
        await websocket.accept()
        if company_id not in self.active_connections:
            self.active_connections[company_id] = []
        self.active_connections[company_id].append(websocket)
        logger.info(f"New WebSocket connection for company: {company_id}")

    def disconnect(self, websocket: WebSocket, company_id: str):
        if company_id in self.active_connections:
            if websocket in self.active_connections[company_id]:
                self.active_connections[company_id].remove(websocket)
            if not self.active_connections[company_id]:
                del self.active_connections[company_id]
        logger.info(f"WebSocket disconnected for company: {company_id}")

    async def broadcast(self, message: dict, company_id: str):
        if company_id in self.active_connections:
            # Create a copy of the list to avoid issues with disconnection during iteration
            for connection in list(self.active_connections[company_id]):
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to WebSocket for company {company_id}: {e}")
                    # Auto-disconnect on failure
                    self.disconnect(connection, company_id)

ws_manager = ConnectionManager()
