from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from math import ceil
from typing import Optional

import cv2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .models import (
    CameraCollection, CameraCreateRequest, CameraListResponse, CameraOperationResponse,
    CameraUpdateRequest, CameraValidationRequest, CameraValidationResponse,
    CollectionCreateRequest, CollectionUpdateRequest,
)
from .recording import CameraRecordingManager, get_recording_manager
from .service import EnhancedCameraService
from .streaming import CameraStreamManager, get_stream_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/collections", tags=["Camera Management"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "camera_management")
camera_service = EnhancedCameraService(DATA_DIR)


def get_camera_service() -> EnhancedCameraService:
    return camera_service


def get_stream_service() -> CameraStreamManager:
    return get_stream_manager()


def get_recording_service() -> CameraRecordingManager:
    return get_recording_manager()


def _user(request: Request) -> dict:
    return request.scope.get("user", {}) or {}


def _company_scope(request: Request) -> Optional[str]:
    user = _user(request)
    return None if user.get("role") == "SuperAdmin" else str(user.get("company_id") or "default")


def _assigned_ids(request: Request) -> set[str]:
    user = _user(request)
    return {str(value) for value in user.get("assigned_cameras") or []}


def _can_view_camera(request: Request, camera) -> bool:
    user = _user(request)
    if user.get("role") == "SuperAdmin":
        return True
    if str(camera.company_id or "default") != str(user.get("company_id") or "default"):
        return False
    if user.get("role") == "Supervisor":
        assigned = _assigned_ids(request)
        return bool(assigned) and str(camera.id) in assigned
    return user.get("role") == "Admin"


def _owned_camera(request: Request, service: EnhancedCameraService, camera_id: int):
    camera = next((item for item in service._load_cameras() if int(item.id) == int(camera_id)), None)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not _can_view_camera(request, camera):
        raise HTTPException(status_code=403, detail="Not authorized to access this camera")
    return camera


def _owned_collection(request: Request, service: EnhancedCameraService, collection_id: str):
    collection = next((item for item in service._load_collections() if str(item.id) == str(collection_id)), None)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    company_id = _company_scope(request)
    if company_id is not None and str(collection.company_id or "default") != company_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this collection")
    return collection


def _require_admin(request: Request) -> dict:
    user = _user(request)
    if user.get("role") not in {"SuperAdmin", "Admin"}:
        raise HTTPException(status_code=403, detail="Only an Admin can manage camera configuration")
    return user


def _require_superadmin(request: Request) -> dict:
    user = _user(request)
    if user.get("role") != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can permanently delete camera configuration")
    return user


def _start_stream_for_camera(camera, stream_service: CameraStreamManager) -> str:
    existing = stream_service.get_camera_stream(camera.id)
    if existing:
        return existing
    return stream_service.start_stream(
        camera_id=camera.id,
        rtsp_url=camera.rtsp_url,
        camera_name=camera.name,
        company_id=camera.company_id,
        location=camera.location,
        camera_role=camera.camera_role,
        direction=camera.direction,
        site_id=camera.site_id,
        zone_id=camera.zone_id,
    )


def _visible_cameras(request: Request, service: EnhancedCameraService):
    return [camera for camera in service._load_cameras() if _can_view_camera(request, camera)]


@router.post("/validate-camera", response_model=CameraValidationResponse)
async def validate_camera(payload: CameraValidationRequest, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    _require_admin(request)
    if _user(request).get("role") != "SuperAdmin":
        payload.company_id = _company_scope(request)
    return service.validate_camera(payload)


@router.get("/cameras", response_model=CameraListResponse)
async def get_cameras(request: Request, page: int = 1, per_page: int = 12, service: EnhancedCameraService = Depends(get_camera_service)):
    page = max(1, page)
    per_page = max(1, min(per_page, 50))
    cameras = _visible_cameras(request, service)
    total = len(cameras)
    start = (page - 1) * per_page
    paged = cameras[start:start + per_page]
    company_id = _company_scope(request)
    collections = service._load_collections()
    if company_id is not None:
        collections = [item for item in collections if str(item.company_id or "default") == company_id]
    if _user(request).get("role") == "Supervisor":
        visible_collection_ids = {camera.collection_id for camera in cameras if camera.collection_id}
        collections = [item for item in collections if item.id in visible_collection_ids]
    return CameraListResponse(
        cameras=paged,
        collections=collections,
        total_cameras=total,
        active_cameras=sum(1 for camera in cameras if camera.is_active),
        current_page=page,
        total_pages=max(1, ceil(total / per_page)) if total else 1,
        cameras_per_page=per_page,
    )


@router.post("/cameras", response_model=CameraOperationResponse)
async def create_camera(payload: CameraCreateRequest, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    _require_admin(request)
    if _user(request).get("role") != "SuperAdmin":
        payload.company_id = _company_scope(request)
    elif not payload.company_id:
        raise HTTPException(status_code=400, detail="SuperAdmin must select a company for the camera")
    return service.create_camera(payload)


@router.get("/cameras/{camera_id}")
async def get_camera(camera_id: int, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    return _owned_camera(request, service, camera_id)


@router.put("/cameras/{camera_id}", response_model=CameraOperationResponse)
async def update_camera(camera_id: int, payload: CameraUpdateRequest, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    _require_admin(request)
    _owned_camera(request, service, camera_id)
    return service.update_camera(camera_id, payload)


@router.delete("/cameras/{camera_id}", response_model=CameraOperationResponse)
async def delete_camera(camera_id: int, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    _require_superadmin(request)
    _owned_camera(request, service, camera_id)
    return service.delete_camera(camera_id)


@router.post("/cameras/{camera_id}/activate")
async def activate_camera(camera_id: int, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    _require_admin(request)
    _owned_camera(request, service, camera_id)
    return service.activate_camera(camera_id)


@router.post("/cameras/{camera_id}/deactivate")
async def deactivate_camera(camera_id: int, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    _require_admin(request)
    _owned_camera(request, service, camera_id)
    return service.deactivate_camera(camera_id)


@router.post("/cameras/{camera_id}/start-stream")
async def start_camera_stream(camera_id: int, request: Request, service: EnhancedCameraService = Depends(get_camera_service), stream_service: CameraStreamManager = Depends(get_stream_service)):
    camera = _owned_camera(request, service, camera_id)
    stream_id = _start_stream_for_camera(camera, stream_service)
    return {"success": True, "stream_id": stream_id, "message": "Stream started successfully"}


@router.delete("/cameras/{camera_id}/stop-stream")
async def stop_camera_stream(camera_id: int, request: Request, service: EnhancedCameraService = Depends(get_camera_service), stream_service: CameraStreamManager = Depends(get_stream_service)):
    _owned_camera(request, service, camera_id)
    stream_id = stream_service.get_camera_stream(camera_id)
    if not stream_id:
        return {"success": True, "message": "Stream already stopped"}
    return {"success": stream_service.stop_stream(stream_id), "message": "Stream stopped successfully"}


@router.get("/cameras/{camera_id}/stream")
async def get_camera_stream(camera_id: int, request: Request, service: EnhancedCameraService = Depends(get_camera_service), stream_service: CameraStreamManager = Depends(get_stream_service)):
    camera = _owned_camera(request, service, camera_id)
    stream_id = _start_stream_for_camera(camera, stream_service)
    return StreamingResponse(
        stream_service.generate_mjpeg_stream(stream_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/cameras/{camera_id}/frame")
async def get_camera_frame(camera_id: int, request: Request, service: EnhancedCameraService = Depends(get_camera_service), stream_service: CameraStreamManager = Depends(get_stream_service)):
    camera = _owned_camera(request, service, camera_id)
    frame = None
    stream_id = stream_service.get_camera_stream(camera_id)
    if stream_id:
        current = stream_service.current_frames.get(stream_id)
        if current:
            frame = current[0]
    if frame is None:
        cap = stream_service._open_capture(camera.rtsp_url)
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            raise HTTPException(status_code=503, detail="Camera is offline")
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None or frame.size == 0:
            raise HTTPException(status_code=503, detail="Camera is online but no frame is available")
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 86])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode camera frame")
    return Response(content=buffer.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Camera-ID": str(camera_id)})


@router.post("/cameras/{camera_id}/start-recording")
async def start_camera_recording(camera_id: int, request: Request, duration_minutes: Optional[int] = None, service: EnhancedCameraService = Depends(get_camera_service), recording_service: CameraRecordingManager = Depends(get_recording_service)):
    _require_admin(request)
    camera = _owned_camera(request, service, camera_id)
    recording_id = recording_service.start_recording(camera_id, camera.rtsp_url, duration_minutes)
    return {"success": True, "recording_id": recording_id, "message": "Recording started successfully"}


@router.post("/cameras/{camera_id}/stop-recording/{recording_id}")
async def stop_camera_recording(camera_id: int, recording_id: str, request: Request, service: EnhancedCameraService = Depends(get_camera_service), recording_service: CameraRecordingManager = Depends(get_recording_service)):
    _require_admin(request)
    _owned_camera(request, service, camera_id)
    if not recording_service.stop_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    return {"success": True, "message": "Recording stopped successfully"}


@router.get("/cameras/{camera_id}/recordings")
async def get_camera_recordings(camera_id: int, request: Request, service: EnhancedCameraService = Depends(get_camera_service), recording_service: CameraRecordingManager = Depends(get_recording_service)):
    _require_admin(request)
    _owned_camera(request, service, camera_id)
    return recording_service.get_camera_recordings(camera_id)


@router.get("/recordings/active")
async def get_active_recordings(request: Request, service: EnhancedCameraService = Depends(get_camera_service), recording_service: CameraRecordingManager = Depends(get_recording_service)):
    _require_admin(request)
    allowed_camera_ids = {camera.id for camera in _visible_cameras(request, service)}
    active = recording_service.get_active_recordings()
    if isinstance(active, dict):
        return {key: value for key, value in active.items() if int(value.get("camera_id", -1)) in allowed_camera_ids}
    if isinstance(active, list):
        return [row for row in active if int(row.get("camera_id", -1)) in allowed_camera_ids]
    return active


@router.get("/")
async def get_collections(request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    company_id = _company_scope(request)
    collections = service._load_collections()
    if company_id is not None:
        collections = [item for item in collections if str(item.company_id or "default") == company_id]
    if _user(request).get("role") == "Supervisor":
        visible_ids = {camera.collection_id for camera in _visible_cameras(request, service) if camera.collection_id}
        collections = [item for item in collections if item.id in visible_ids]
    return {"collections": collections}


@router.post("/")
async def create_collection(payload: CollectionCreateRequest, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    _require_admin(request)
    company_id = _company_scope(request)
    if company_id is None:
        company_id = str(payload.company_id or "")
        if not company_id:
            raise HTTPException(status_code=400, detail="SuperAdmin must select a company")
    existing = service._load_collections()
    if any(item.name.lower() == payload.name.lower() and str(item.company_id or "default") == company_id for item in existing):
        raise HTTPException(status_code=409, detail="Collection name already exists for this company")
    collection = CameraCollection(
        id=str(uuid.uuid4()), name=payload.name, description=payload.description,
        created_at=datetime.now(timezone.utc), camera_count=0, company_id=company_id,
    )
    existing.append(collection)
    service._save_collections(existing)
    return {"success": True, "collection": collection}


@router.put("/{collection_id}")
async def update_collection(collection_id: str, payload: CollectionUpdateRequest, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    _require_admin(request)
    collection = _owned_collection(request, service, collection_id)
    collections = service._load_collections()
    if payload.name:
        if any(
            item.id != collection_id and item.name.lower() == payload.name.lower()
            and str(item.company_id or "default") == str(collection.company_id or "default")
            for item in collections
        ):
            raise HTTPException(status_code=409, detail="Collection name already exists")
        collection.name = payload.name
    if payload.description is not None:
        collection.description = payload.description
    service._save_collections(collections)
    if payload.name:
        cameras = service._load_cameras()
        for camera in cameras:
            if camera.collection_id == collection_id:
                camera.collection_name = collection.name
        service._save_cameras(cameras)
    return {"success": True, "collection": collection}


@router.delete("/{collection_id}")
async def delete_collection(collection_id: str, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    _require_superadmin(request)
    collection = _owned_collection(request, service, collection_id)
    cameras = service._load_cameras()
    for camera in cameras:
        if camera.collection_id == collection_id:
            camera.collection_id = None
            camera.collection_name = None
    service._save_cameras(cameras)
    service._save_collections([item for item in service._load_collections() if item.id != collection_id])
    return {"success": True, "message": f"Collection '{collection.name}' deleted successfully"}


@router.get("/{collection_id}/streams")
async def get_collection_streams(collection_id: str, request: Request, service: EnhancedCameraService = Depends(get_camera_service)):
    if collection_id != "all":
        _owned_collection(request, service, collection_id)
    cameras = [
        camera for camera in _visible_cameras(request, service)
        if collection_id == "all" or camera.collection_id == collection_id
    ]
    token = request.scope.get("auth_token")
    suffix = f"?token={token}" if token else ""
    include_rtsp = _user(request).get("role") in {"SuperAdmin", "Admin"}
    streams = []
    for camera in cameras:
        item = {
            "camera_id": camera.id,
            "camera_name": camera.name,
            "stream_url": f"/api/collections/cameras/{camera.id}/stream{suffix}",
            "frame_url": f"/api/collections/cameras/{camera.id}/frame{suffix}",
            "camera_ip": camera.ip_address,
            "location": camera.location,
            "site_id": camera.site_id,
            "zone_id": camera.zone_id,
            "camera_role": camera.camera_role,
            "direction": camera.direction,
            "collection_name": camera.collection_name or "Unassigned",
            "stream_id": f"stream_{camera.id}",
        }
        if include_rtsp:
            item["rtsp_url"] = camera.rtsp_url
        streams.append(item)
    return {"success": True, "streams": streams}


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "camera_management", "time": time.time()}
