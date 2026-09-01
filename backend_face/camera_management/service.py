from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException

from db.repository import (
    delete_camera_record,
    delete_collection_record,
    get_camera,
    list_cameras,
    list_collections,
    next_camera_id,
    save_camera,
    save_collection,
    update_collection_counts,
)
from .models import (
    CameraCollection,
    EnhancedCamera,
    CameraCreateRequest,
    CameraUpdateRequest,
    CameraValidationRequest,
    CameraValidationResponse,
    CameraListResponse,
    CameraOperationResponse,
    extract_ip_from_url,
    validate_private_ip,
)

logger = logging.getLogger(__name__)


def _dt(value, default_now: bool = False):
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.now(timezone.utc) if default_now else None


def _camera_model(row) -> EnhancedCamera:
    data = dict(row)
    data["is_active"] = bool(data.get("is_active"))
    data["created_at"] = _dt(data.get("created_at"), True)
    data["last_seen"] = _dt(data.get("last_seen"), False)
    return EnhancedCamera(**data)


def _collection_model(row) -> CameraCollection:
    data = dict(row)
    data["created_at"] = _dt(data.get("created_at"), True)
    return CameraCollection(**data)


class EnhancedCameraService:
    """Database-backed camera configuration service.

    Existing cameras.json/collections.json are imported one time when the DB is empty.
    After that the database is authoritative.
    """

    def __init__(self, data_dir: str):
        self.data_dir = str(data_dir)
        self.cameras_file = os.path.join(self.data_dir, "cameras.json")
        self.collections_file = os.path.join(self.data_dir, "collections.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self._migrate_legacy_files()

    def _migrate_legacy_files(self) -> None:
        if not list_cameras(None) and os.path.exists(self.cameras_file):
            try:
                payload = json.loads(Path(self.cameras_file).read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    for camera in payload:
                        if isinstance(camera, dict):
                            camera.setdefault("camera_role", "BIDIRECTIONAL")
                            camera.setdefault("direction", "AUTO")
                            save_camera(camera)
                    logger.info("Migrated %s legacy cameras into database", len(payload))
            except Exception as exc:
                logger.warning("Could not migrate cameras.json: %s", exc)

        if not list_collections(None) and os.path.exists(self.collections_file):
            try:
                payload = json.loads(Path(self.collections_file).read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    for collection in payload:
                        if isinstance(collection, dict):
                            save_collection(collection)
                    logger.info("Migrated %s legacy camera collections into database", len(payload))
            except Exception as exc:
                logger.warning("Could not migrate collections.json: %s", exc)
        update_collection_counts()

    def _load_cameras(self) -> List[EnhancedCamera]:
        return [_camera_model(row) for row in list_cameras(None)]

    def _save_cameras(self, cameras: List[EnhancedCamera]):
        desired_ids = set()
        for camera in cameras:
            data = camera.model_dump() if hasattr(camera, "model_dump") else camera.dict()
            desired_ids.add(int(data["id"]))
            save_camera(data)
        for existing in list_cameras(None):
            if int(existing["id"]) not in desired_ids:
                delete_camera_record(int(existing["id"]))
        update_collection_counts()

    def _load_collections(self) -> List[CameraCollection]:
        return [_collection_model(row) for row in list_collections(None)]

    def _save_collections(self, collections: List[CameraCollection]):
        desired_ids = set()
        for collection in collections:
            data = collection.model_dump() if hasattr(collection, "model_dump") else collection.dict()
            desired_ids.add(str(data["id"]))
            save_collection(data)
        for existing in list_collections(None):
            if str(existing["id"]) not in desired_ids:
                delete_collection_record(str(existing["id"]))
        update_collection_counts()

    def _update_collection_counts(self):
        update_collection_counts()

    def validate_camera(self, request: CameraValidationRequest) -> CameraValidationResponse:
        try:
            is_index = str(request.ip).isdigit()
            if not is_index:
                validation = validate_private_ip(request.ip)
                if not validation["isValid"] and os.getenv("FRS_ALLOW_PUBLIC_CAMERA_URLS", "0").lower() not in {"1", "true", "yes"}:
                    return CameraValidationResponse(valid=False, error=validation["message"], type="ip_validation")

            for camera in self._load_cameras():
                if str(request.company_id or "") != str(camera.company_id or ""):
                    continue
                camera_ip = extract_ip_from_url(camera.rtsp_url) or camera.rtsp_url
                if camera_ip == request.ip and camera_ip != request.exclude_ip:
                    existing_collection = camera.collection_name or "Unassigned"
                    return CameraValidationResponse(
                        valid=False,
                        error=f"A camera with IP/index {request.ip} already exists",
                        type="duplicate",
                        existingCollection=existing_collection,
                    )
            return CameraValidationResponse(valid=True)
        except Exception as exc:
            logger.error("Camera validation failed: %s", exc)
            return CameraValidationResponse(valid=False, error="Validation failed. Please try again.", type="server_error")

    def create_camera(self, request: CameraCreateRequest) -> CameraOperationResponse:
        cameras = self._load_cameras()
        new_id = next_camera_id()
        ip_address = extract_ip_from_url(request.rtsp_url) or (request.rtsp_url if request.rtsp_url.isdigit() else None)
        validation = self.validate_camera(CameraValidationRequest(
            ip=ip_address or request.rtsp_url,
            streamUrl=request.rtsp_url,
            collection_name=request.collection_id,
            company_id=request.company_id,
        ))
        if not validation.valid:
            raise HTTPException(status_code=409, detail=validation.error)

        if request.company_id:
            try:
                from auth.storage import get_users
                users = get_users()
                admin_limit = max(
                    [int(u.get("max_cameras_limit") or 0) for u in users.values()
                     if u.get("company_id") == request.company_id and u.get("role") == "Admin"] or [0]
                )
                if admin_limit > 0:
                    count = sum(1 for c in cameras if c.company_id == request.company_id)
                    if count >= admin_limit:
                        raise HTTPException(status_code=403, detail=f"License limit reached. Maximum cameras: {admin_limit}.")
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning("Camera license check failed: %s", exc)

        collection_name = None
        if request.collection_id:
            collection = next((c for c in self._load_collections() if c.id == request.collection_id), None)
            if collection and request.company_id and collection.company_id not in {None, request.company_id}:
                raise HTTPException(status_code=403, detail="Collection belongs to another company")
            collection_name = collection.name if collection else None

        now = datetime.now(timezone.utc)
        camera = EnhancedCamera(
            id=new_id,
            name=request.name,
            rtsp_url=request.rtsp_url,
            collection_id=request.collection_id,
            collection_name=collection_name,
            ip_address=ip_address,
            location=request.location,
            site_id=request.site_id,
            zone_id=request.zone_id,
            camera_role=request.camera_role,
            direction=request.direction,
            line_x1=request.line_x1,
            line_y1=request.line_y1,
            line_x2=request.line_x2,
            line_y2=request.line_y2,
            in_side=request.in_side,
            status="inactive",
            created_at=now,
            error_count=0,
            company_id=request.company_id,
            is_active=False,
        )
        save_camera(camera.model_dump())
        update_collection_counts()
        return CameraOperationResponse(success=True, message=f"Camera '{camera.name}' added successfully", camera=camera)

    def get_cameras(self, page: int = 1, per_page: int = 6, company_id: Optional[str] = None) -> CameraListResponse:
        cameras = [_camera_model(r) for r in list_cameras(company_id)]
        collections = [_collection_model(r) for r in list_collections(company_id)]
        total = len(cameras)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        return CameraListResponse(
            cameras=cameras[start:start + per_page],
            collections=collections,
            total_cameras=total,
            active_cameras=sum(1 for camera in cameras if camera.is_active),
            current_page=page,
            total_pages=total_pages,
            cameras_per_page=per_page,
        )

    def update_camera(self, camera_id: int, request: CameraUpdateRequest) -> CameraOperationResponse:
        row = get_camera(camera_id)
        if not row:
            raise HTTPException(status_code=404, detail="Camera not found")
        data = dict(row)
        updates = request.model_dump(exclude_none=True)
        if "rtsp_url" in updates:
            new_ip = extract_ip_from_url(updates["rtsp_url"]) or (updates["rtsp_url"] if updates["rtsp_url"].isdigit() else None)
            validation = self.validate_camera(CameraValidationRequest(
                ip=new_ip or updates["rtsp_url"],
                streamUrl=updates["rtsp_url"],
                exclude_ip=data.get("ip_address"),
                company_id=data.get("company_id"),
            ))
            if not validation.valid:
                raise HTTPException(status_code=409, detail=validation.error)
            updates["ip_address"] = new_ip
        if "collection_id" in updates:
            collection = next((c for c in self._load_collections() if c.id == updates["collection_id"]), None)
            updates["collection_name"] = collection.name if collection else None
        data.update(updates)
        saved = _camera_model(save_camera(data))
        update_collection_counts()
        return CameraOperationResponse(success=True, message=f"Camera '{saved.name}' updated successfully", camera=saved)

    def activate_camera(self, camera_id: int) -> CameraOperationResponse:
        row = get_camera(camera_id)
        if not row:
            raise HTTPException(status_code=404, detail="Camera not found")
        row.update({"is_active": True, "status": "active", "last_seen": datetime.now(timezone.utc).isoformat()})
        camera = _camera_model(save_camera(row))
        try:
            from .streaming import get_stream_manager
            manager = get_stream_manager()
            if not manager.get_camera_stream(camera_id):
                manager.start_stream(
                    camera.id,
                    camera.rtsp_url,
                    camera.name,
                    company_id=camera.company_id,
                    location=camera.location,
                    camera_role=camera.camera_role,
                    direction=camera.direction,
                    site_id=camera.site_id,
                    zone_id=camera.zone_id,
                    line_x1=camera.line_x1,
                    line_y1=camera.line_y1,
                    line_x2=camera.line_x2,
                    line_y2=camera.line_y2,
                    in_side=camera.in_side,
                )
        except Exception as exc:
            logger.warning("Camera activated but stream did not start: %s", exc)
        return CameraOperationResponse(success=True, message=f"Camera '{camera.name}' activated successfully", camera=camera)

    def deactivate_camera(self, camera_id: int) -> CameraOperationResponse:
        row = get_camera(camera_id)
        if not row:
            raise HTTPException(status_code=404, detail="Camera not found")
        try:
            from .streaming import get_stream_manager
            manager = get_stream_manager()
            stream_id = manager.get_camera_stream(camera_id)
            if stream_id:
                manager.stop_stream(stream_id)
        except Exception as exc:
            logger.warning("Could not stop camera stream %s: %s", camera_id, exc)
        row.update({"is_active": False, "status": "inactive"})
        camera = _camera_model(save_camera(row))
        return CameraOperationResponse(success=True, message=f"Camera '{camera.name}' deactivated successfully", camera=camera)

    def delete_camera(self, camera_id: int) -> CameraOperationResponse:
        row = get_camera(camera_id)
        if not row:
            raise HTTPException(status_code=404, detail="Camera not found")
        name = row.get("name") or f"Camera {camera_id}"
        try:
            from .streaming import get_stream_manager
            manager = get_stream_manager()
            stream_id = manager.get_camera_stream(camera_id)
            if stream_id:
                manager.stop_stream(stream_id)
        except Exception:
            pass
        delete_camera_record(camera_id)
        update_collection_counts()
        return CameraOperationResponse(success=True, message=f"Camera '{name}' deleted successfully")
