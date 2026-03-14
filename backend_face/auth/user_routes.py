from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator, model_validator
from datetime import datetime
from .users import (
    create_user, get_user, update_user, delete_user, list_users,
    assign_cameras_to_user, remove_cameras_from_user, get_user_cameras
)
from .storage import get_settings, save_settings

router = APIRouter(prefix="/users", tags=["users"])


# ─── Pydantic models ──────────────────────────────────────────────────────────

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
    company_name: Optional[str] = None


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


# ─── Attendance sub-model (Pydantic V2) ──────────────────────────────────────

class AttendanceSettings(BaseModel):
    """
    Typed attendance configuration with full cross-field validation.

    Fields
    ------
    punch_in          : HH:MM  – latest time considered on-time (default 09:30)
    punch_out         : HH:MM  – expected end-of-day time        (default 18:00)
    working_hours     : float  – expected hours per day          (1–24)
    grace_minutes     : int    – minutes of grace after punch_in before marking Late (0–120)
    min_hours_present : float  – minimum worked hours to count as Present
    overtime_after    : float  – hours threshold for overtime flag
    """

    punch_in: Optional[str] = None
    punch_out: Optional[str] = None
    working_hours: Optional[float] = None
    grace_minutes: Optional[int] = None
    min_hours_present: Optional[float] = None
    overtime_after: Optional[float] = None

    # ── individual field validators ───────────────────────────────────────────

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def validate_time_format(cls, v):
        if v is None:
            return v
        try:
            datetime.strptime(str(v), "%H:%M")
        except ValueError:
            raise ValueError("Time fields must be in HH:MM format (e.g. '09:30')")
        return v

    @field_validator("working_hours", mode="before")
    @classmethod
    def validate_working_hours(cls, v):
        if v is None:
            return v
        v = float(v)
        if not (1 <= v <= 24):
            raise ValueError("working_hours must be between 1 and 24")
        return v

    @field_validator("grace_minutes", mode="before")
    @classmethod
    def validate_grace_minutes(cls, v):
        if v is None:
            return v
        v = int(v)
        if not (0 <= v <= 120):
            raise ValueError("grace_minutes must be between 0 and 120")
        return v

    @field_validator("min_hours_present", "overtime_after", mode="before")
    @classmethod
    def validate_hour_thresholds(cls, v):
        if v is None:
            return v
        v = float(v)
        if not (0 <= v <= 24):
            raise ValueError("Hour threshold must be between 0 and 24")
        return v

    # ── cross-field validators ────────────────────────────────────────────────

    @model_validator(mode="after")
    def cross_validate(self):
        if self.punch_in and self.punch_out:
            t_in = datetime.strptime(self.punch_in, "%H:%M")
            t_out = datetime.strptime(self.punch_out, "%H:%M")
            if t_out <= t_in:
                raise ValueError(
                    f"punch_out ({self.punch_out}) must be later than "
                    f"punch_in ({self.punch_in})"
                )
            if self.working_hours is not None:
                window_hours = (t_out - t_in).seconds / 3600
                if self.working_hours > window_hours:
                    raise ValueError(
                        f"working_hours ({self.working_hours}h) cannot exceed the "
                        f"punch_in→punch_out window ({window_hours:.1f}h)"
                    )
        return self


# ─── Top-level settings model (Pydantic V2) ───────────────────────────────────

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

    attendance: Optional[AttendanceSettings] = None
    
    # Face Recognition Toggle Settings
    face_recognition_enabled: Optional[bool] = None
    show_bounding_boxes: Optional[bool] = None
    unknown_detection_enabled: Optional[bool] = None
    long_distance_detection_enabled: Optional[bool] = None
    min_face_size: Optional[int] = None

    @field_validator("max_cameras_per_admin", "max_cameras_per_supervisor", mode="before")
    @classmethod
    def validate_camera_limits(cls, v):
        if v is not None and int(v) < 0:
            raise ValueError("Camera limits cannot be negative")
        return v

    @field_validator("smtp_port", mode="before")
    @classmethod
    def validate_smtp_port(cls, v):
        if v is not None and not (1 <= int(v) <= 65535):
            raise ValueError("smtp_port must be between 1 and 65535")
        return v


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/")
async def create_user_endpoint(request: CreateUserRequest, request_obj: Request):
    current_user = request_obj.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if current_user["role"] not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if current_user["role"] == "Admin" and request.role not in ["Supervisor"]:
        raise HTTPException(status_code=403, detail="Admins can only create Supervisors")

    # Handle integrated company creation for Admins
    actual_company_id = request.company_id or current_user.get("company_id")
    
    if current_user["role"] == "SuperAdmin" and request.role == "Admin" and request.company_name:
        try:
            from .companies import create_company
            # Create company first
            company = create_company(name=request.company_name, company_id=request.company_id)
            actual_company_id = company["id"]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Company creation failed: {str(e)}")

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
            company_id=actual_company_id,
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

    company_id = current_user.get("company_id")
    users = list_users(company_id=company_id)

    if current_user["role"] == "Admin":
        users = [u for u in users if u["role"] in ["Supervisor"]]

    return {"users": users}


@router.get("/{username}")
async def get_user_endpoint(username: str, request: Request):
    current_user = request.scope.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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

    if current_user["role"] == "Admin" and user["role"] not in ["Supervisor"]:
        raise HTTPException(status_code=403, detail="Cannot update users outside your hierarchy")

    updates = request.model_dump(exclude_unset=True)
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

    if current_user["role"] == "Admin" and user["role"] not in ["Supervisor"]:
        raise HTTPException(status_code=403, detail="Cannot delete users outside your hierarchy")

    if delete_user(username):
        return {"message": "User deleted successfully"}
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

    if current_user["username"] != username and current_user["role"] not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Cannot view other users' cameras")
    cameras = get_user_cameras(username)
    return {"cameras": cameras}


@router.get("/settings/system")
async def get_system_settings_endpoint(request: Request, cid: Optional[str] = None):
    current_user = request.scope.get("user")
    if not current_user or current_user["role"] not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Use provided cid if SuperAdmin, otherwise use user's company_id
    effective_company_id = cid if current_user["role"] == "SuperAdmin" else current_user.get("company_id")
    return {"settings": get_settings(effective_company_id)}


@router.put("/settings/system")
async def update_system_settings_endpoint(request: SettingsRequest, request_obj: Request, cid: Optional[str] = None):
    current_user = request_obj.scope.get("user")
    if not current_user or current_user["role"] not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    effective_company_id = cid if current_user["role"] == "SuperAdmin" else current_user.get("company_id")
    settings = get_settings(effective_company_id)
    updates = request.model_dump(exclude_unset=True)
    
    # Non-SuperAdmins can only update attendance and face recognition settings
    if current_user["role"] != "SuperAdmin":
        allowed_keys = ["attendance", "face_recognition_enabled", "show_bounding_boxes", "unknown_detection_enabled", "long_distance_detection_enabled", "min_face_size"]
        updates = {k: v for k, v in updates.items() if k in allowed_keys}

    # Deep merge attendance if present
    if "attendance" in updates and updates["attendance"]:
        current_attendance = settings.get("attendance", {})
        for k, v in updates["attendance"].items():
            if v is not None:
                current_attendance[k] = v
        settings["attendance"] = current_attendance
        del updates["attendance"]

    settings.update(updates)
    save_settings(settings, effective_company_id)
    return {"message": "Settings updated successfully", "settings": settings}
