from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from .users import get_user_cameras, get_user
from .storage import get_cameras

router = APIRouter(prefix="/cameras", tags=["cameras"])

class CameraAssignmentResponse(BaseModel):
    cameras: List[Dict[str, Any]]
    total_count: int

@router.get("/my-cameras", response_model=CameraAssignmentResponse)
async def get_my_cameras(request: Request):
    current_user = request.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    assigned_camera_ids = get_user_cameras(current_user["username"])
    all_cameras = get_cameras()
    
    # Filter cameras that are assigned to this user
    user_cameras = []
    for camera_id in assigned_camera_ids:
        if camera_id in all_cameras:
            camera_data = all_cameras[camera_id].copy()
            camera_data["id"] = camera_id
            user_cameras.append(camera_data)
        else:
            user_cameras.append({"id": camera_id})
    
    return CameraAssignmentResponse(
        cameras=user_cameras,
        total_count=len(user_cameras)
    )

@router.get("/available")
async def get_available_cameras(request: Request):
    current_user = request.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    all_cameras = get_cameras()
    users = {}  # This would come from get_users() in a real implementation
    
    # Get all assigned cameras
    assigned_cameras = set()
    for camera_id, camera_data in all_cameras.items():
        if camera_data.get("assigned_to"):
            assigned_cameras.add(camera_id)
    
    # Return unassigned cameras
    available_cameras = []
    for camera_id, camera_data in all_cameras.items():
        if camera_id not in assigned_cameras:
            camera_data["id"] = camera_id
            available_cameras.append(camera_data)
    
    return {"cameras": available_cameras}

@router.get("/{camera_id}/access")
async def check_camera_access(camera_id: str, request: Request):
    current_user = request.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    assigned_cameras = get_user_cameras(current_user["username"])
    has_access = camera_id in assigned_cameras
    
    return {"camera_id": camera_id, "has_access": has_access}
