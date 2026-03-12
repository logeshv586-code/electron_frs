from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from .users import (
    create_user, get_user, update_user, delete_user, list_users,
    assign_cameras_to_user, remove_cameras_from_user, get_user_cameras
)
from .storage import get_settings, save_settings

router = APIRouter(prefix="/users", tags=["users"])

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str
    email: Optional[str] = None
    max_users_limit: Optional[int] = 0
    max_cameras_limit: Optional[int] = 0
    assigned_menus: Optional[List[str]] = None
    license_start_date: Optional[str] = None
    license_end_date: Optional[str] = None
    company_id: Optional[str] = None

class UpdateUserRequest(BaseModel):
    is_active: Optional[bool] = None
    email: Optional[str] = None
    assigned_cameras: Optional[List[str]] = None
    assigned_menus: Optional[List[str]] = None
    max_users_limit: Optional[int] = None
    max_cameras_limit: Optional[int] = None
    license_start_date: Optional[str] = None
    license_end_date: Optional[str] = None
    password: Optional[str] = None

class AssignCamerasRequest(BaseModel):
    camera_ids: List[str]

class SettingsRequest(BaseModel):
    max_cameras_per_admin: Optional[int] = None
    max_cameras_per_supervisor: Optional[int] = None
    require_approval_for_new_users: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    email_from: Optional[str] = None

@router.post("/")
async def create_user_endpoint(request: CreateUserRequest, request_obj: Request):
    current_user = request_obj.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user["role"] not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    if current_user["role"] == "Admin" and request.role not in ["Supervisor"]:
        raise HTTPException(status_code=403, detail="Admins can only create Supervisors")
    
    try:
        user = create_user(
            username=request.username,
            password=request.password,
            role=request.role,
            created_by=current_user["username"],
            max_users_limit=request.max_users_limit or 0,
            max_cameras_limit=request.max_cameras_limit or 0,
            assigned_menus=request.assigned_menus,
            license_start_date=request.license_start_date,
            license_end_date=request.license_end_date,
            email=request.email,
            company_id=request.company_id or current_user.get("company_id")
        )
        return {"message": "User created successfully", "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/")
async def list_users_endpoint(request: Request):
    current_user = request.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user["role"] not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Filter users based on company and role hierarchy
    company_id = current_user.get("company_id")
    users = list_users(company_id=company_id)
    
    if current_user["role"] == "Admin":
        users = [user for user in users if user["role"] in ["Supervisor"]]
    
    return {"users": users}

@router.get("/{username}")
async def get_user_endpoint(username: str, request: Request):
    current_user = request.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if current user can view this user
    if current_user["role"] == "Admin" and user["role"] not in ["Supervisor"]:
        raise HTTPException(status_code=403, detail="Cannot view users outside your hierarchy")
    
    if current_user["role"] == "Supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot view other users")
    
    return {"user": user}

@router.put("/{username}")
async def update_user_endpoint(username: str, request: UpdateUserRequest, request_obj: Request):
    current_user = request_obj.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user["role"] not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if current user can update this user
    if current_user["role"] == "Admin" and user["role"] not in ["Supervisor"]:
        raise HTTPException(status_code=403, detail="Cannot update users outside your hierarchy")
    
    updates = request.dict(exclude_unset=True)
    updated_user = update_user(username, updates)
    
    return {"message": "User updated successfully", "user": updated_user}

@router.delete("/{username}")
async def delete_user_endpoint(username: str, request: Request):
    current_user = request.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user["role"] not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if current user can delete this user
    if current_user["role"] == "Admin" and user["role"] not in ["Supervisor"]:
        raise HTTPException(status_code=403, detail="Cannot delete users outside your hierarchy")
    
    if delete_user(username):
        return {"message": "User deleted successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete user")

@router.post("/{username}/cameras/assign")
async def assign_cameras_api(username: str, request: AssignCamerasRequest, request_obj: Request):
    current_user = request_obj.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    success, message = assign_cameras_to_user(current_user["username"], username, request.camera_ids)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"message": message}

@router.post("/{username}/cameras/remove")
async def remove_cameras_api(username: str, request: AssignCamerasRequest, request_obj: Request):
    current_user = request_obj.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    success, message = remove_cameras_from_user(current_user["username"], username, request.camera_ids)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"message": message}

@router.get("/{username}/cameras")
async def get_user_cameras_endpoint(username: str, request: Request):
    current_user = request.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Users can only view their own cameras unless they're SuperAdmin/Admin
    if current_user["username"] != username and current_user["role"] not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Cannot view other users' cameras")
    
    cameras = get_user_cameras(username)
    return {"cameras": cameras}

@router.get("/settings/system")
async def get_system_settings(request: Request):
    current_user = request.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user["role"] != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can view system settings")
    
    settings = get_settings()
    return {"settings": settings}

@router.put("/settings/system")
async def update_system_settings(request: SettingsRequest, request_obj: Request):
    current_user = request_obj.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user["role"] != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can update system settings")
    
    settings = get_settings()
    updates = request.dict(exclude_unset=True)
    settings.update(updates)
    save_settings(settings)
    
    return {"message": "Settings updated successfully", "settings": settings}
