from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from .users import (
    create_user, get_user, update_user, delete_user, list_users,
    assign_cameras_to_user, remove_cameras_from_user, get_user_cameras,
)
from .storage import get_settings, save_settings
from .license_dates import parse_license_datetime

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(BaseModel):
    username: str
    password: str = Field(min_length=12)
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
    assigned_menus: Optional[List[str]] = None
    max_users_limit: Optional[int] = None
    max_cameras_limit: Optional[int] = None
    license_start_date: Optional[str] = None
    license_end_date: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=12)


class AssignCamerasRequest(BaseModel):
    camera_ids: List[str]


class AttendanceSettings(BaseModel):
    punch_in: Optional[str] = None
    punch_out: Optional[str] = None
    working_hours: Optional[float] = None
    grace_minutes: Optional[int] = None
    min_hours_present: Optional[float] = None
    overtime_after: Optional[float] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None

    @field_validator("punch_in", "punch_out", "shift_start", "shift_end", mode="before")
    @classmethod
    def validate_time_format(cls, value):
        if value is None:
            return value
        try:
            datetime.strptime(str(value), "%H:%M")
        except ValueError:
            raise ValueError("Time fields must use HH:MM format")
        return str(value)

    @field_validator("working_hours", "min_hours_present", "overtime_after", mode="before")
    @classmethod
    def validate_hours(cls, value):
        if value is None:
            return value
        value = float(value)
        if not 0 <= value <= 24:
            raise ValueError("Hour values must be between 0 and 24")
        return value

    @field_validator("grace_minutes", mode="before")
    @classmethod
    def validate_grace(cls, value):
        if value is None:
            return value
        value = int(value)
        if not 0 <= value <= 180:
            raise ValueError("grace_minutes must be between 0 and 180")
        return value

    @model_validator(mode="after")
    def cross_validate(self):
        if self.punch_in and self.punch_out and self.working_hours is not None:
            start = datetime.strptime(self.punch_in, "%H:%M")
            end = datetime.strptime(self.punch_out, "%H:%M")
            if end <= start:
                end += timedelta(days=1)
            window = (end - start).total_seconds() / 3600
            if self.working_hours > window:
                raise ValueError("working_hours cannot exceed the configured attendance window")
        return self


class RecognitionSettings(BaseModel):
    min_recognition_face_px: Optional[int] = Field(default=None, ge=40, le=300)
    min_attendance_face_px: Optional[int] = Field(default=None, ge=56, le=400)
    confirmation_frames: Optional[int] = Field(default=None, ge=2, le=10)
    confirmation_window: Optional[int] = Field(default=None, ge=3, le=20)
    known_distance_threshold: Optional[float] = Field(default=None, ge=0.30, le=0.55)
    distant_distance_threshold: Optional[float] = Field(default=None, ge=0.28, le=0.50)
    match_margin: Optional[float] = Field(default=None, ge=0.01, le=0.20)
    min_quality: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    min_attendance_quality: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    unknown_cluster_similarity: Optional[float] = Field(default=None, ge=0.70, le=0.99)

    @model_validator(mode="after")
    def validate_relationships(self):
        if self.min_recognition_face_px and self.min_attendance_face_px:
            if self.min_attendance_face_px < self.min_recognition_face_px:
                raise ValueError("Attendance face size must be at least the recognition face size")
        if self.known_distance_threshold and self.distant_distance_threshold:
            if self.distant_distance_threshold > self.known_distance_threshold:
                raise ValueError("Distant matching must be at least as strict as normal matching")
        if self.confirmation_frames and self.confirmation_window:
            if self.confirmation_window < self.confirmation_frames:
                raise ValueError("confirmation_window must be >= confirmation_frames")
        return self


class SettingsRequest(BaseModel):
    max_cameras_per_admin: Optional[int] = Field(default=None, ge=0)
    max_cameras_per_supervisor: Optional[int] = Field(default=None, ge=0)
    require_approval_for_new_users: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    email_from: Optional[str] = None
    attendance: Optional[AttendanceSettings] = None
    recognition: Optional[RecognitionSettings] = None
    face_recognition_enabled: Optional[bool] = None
    show_bounding_boxes: Optional[bool] = None
    unknown_detection_enabled: Optional[bool] = None
    long_distance_detection_enabled: Optional[bool] = None
    min_face_size: Optional[int] = Field(default=None, ge=16, le=300)

    @field_validator("smtp_port", mode="before")
    @classmethod
    def validate_smtp_port(cls, value):
        if value is not None and not 1 <= int(value) <= 65535:
            raise ValueError("smtp_port must be between 1 and 65535")
        return value


def _current(request: Request) -> dict:
    user = request.scope.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _same_tenant(actor: dict, target: dict) -> bool:
    return actor.get("role") == "SuperAdmin" or (
        bool(actor.get("company_id"))
        and str(actor.get("company_id")) == str(target.get("company_id"))
    )


def _managed_target(actor: dict, username: str, require_supervisor_for_admin: bool = True) -> dict:
    target = get_user(username)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if not _same_tenant(actor, target):
        raise HTTPException(status_code=403, detail="Cannot access users from another company")
    if actor.get("role") == "Admin" and require_supervisor_for_admin and target.get("role") != "Supervisor":
        raise HTTPException(status_code=403, detail="Admins can only manage Supervisors in their company")
    return target


def _validate_admin_license_dates(start_value: Optional[str], end_value: Optional[str]) -> tuple[str, str]:
    start_value = start_value or datetime.now(timezone.utc).isoformat()
    if not end_value:
        raise HTTPException(status_code=400, detail="Admin license expiry date is required")
    start_dt = parse_license_datetime(start_value)
    end_dt = parse_license_datetime(end_value)
    if not start_dt or not end_dt:
        raise HTTPException(status_code=400, detail="Invalid license date")
    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="License expiry must be later than license start")
    return start_value, end_value


@router.post("/")
async def create_user_endpoint(payload: CreateUserRequest, request: Request):
    actor = _current(request)
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    role = payload.role.strip()
    if actor.get("role") == "Admin" and role != "Supervisor":
        raise HTTPException(status_code=403, detail="Admins can only create Supervisors")

    company_id = actor.get("company_id") if actor.get("role") == "Admin" else payload.company_id
    license_start = payload.license_start_date
    license_end = payload.license_end_date

    if actor.get("role") == "SuperAdmin" and role == "Admin":
        if not payload.company_name or not payload.company_id:
            raise HTTPException(status_code=400, detail="Company name and company ID are required for an Admin")
        from .companies import create_company
        try:
            company = create_company(name=payload.company_name, company_id=payload.company_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Company creation failed: {exc}")
        company_id = company["id"]
        license_start, license_end = _validate_admin_license_dates(license_start, license_end)
    elif role == "Supervisor":
        if not company_id:
            raise HTTPException(status_code=400, detail="Supervisor must belong to a company")
    elif role == "SuperAdmin" and actor.get("role") != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can create platform accounts")

    try:
        user = create_user(
            username=payload.username,
            password=payload.password,
            role=role,
            created_by=actor["username"],
            max_users_limit=payload.max_users_limit or 0,
            max_cameras_limit=payload.max_cameras_limit or 0,
            assigned_menus=payload.assigned_menus,
            license_start_date=license_start,
            license_end_date=license_end,
            email=payload.email,
            company_id=company_id,
        )
        return {"message": "User created successfully", "user": user}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/")
async def list_users_endpoint(request: Request, cid: Optional[str] = None):
    actor = _current(request)
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if actor.get("role") == "SuperAdmin":
        users = list_users(company_id=cid) if cid else list_users()
    else:
        users = [
            account for account in list_users(company_id=actor.get("company_id"))
            if account.get("role") == "Supervisor"
        ]
    return {"users": users}


@router.get("/{username}")
async def get_user_endpoint(username: str, request: Request):
    actor = _current(request)
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return {"user": _managed_target(actor, username)}


@router.put("/{username}")
async def update_user_endpoint(username: str, payload: UpdateUserRequest, request: Request):
    actor = _current(request)
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    target = _managed_target(actor, username)
    updates = payload.model_dump(exclude_unset=True)

    if actor.get("role") == "Admin":
        allowed = {"is_active", "email", "assigned_menus", "password"}
        updates = {key: value for key, value in updates.items() if key in allowed}
        if "assigned_menus" in updates:
            actor_menus = {str(item).lower() for item in actor.get("assigned_menus") or []}
            requested = {str(item).lower() for item in updates["assigned_menus"] or []}
            if actor_menus and not requested.issubset(actor_menus):
                raise HTTPException(status_code=403, detail="Cannot grant menus that are not enabled for your account")
    elif target.get("role") == "Admin" and ("license_start_date" in updates or "license_end_date" in updates):
        start_value = updates.get("license_start_date", target.get("license_start_date"))
        end_value = updates.get("license_end_date", target.get("license_end_date"))
        start_value, end_value = _validate_admin_license_dates(start_value, end_value)
        updates["license_start_date"] = start_value
        updates["license_end_date"] = end_value

    try:
        updated = update_user(username, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "User updated successfully", "user": updated}


@router.delete("/{username}")
async def delete_user_endpoint(username: str, request: Request):
    actor = _current(request)
    if actor.get("role") != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can permanently delete users")
    _managed_target(actor, username, require_supervisor_for_admin=False)
    if delete_user(username):
        return {"message": "User deleted successfully"}
    raise HTTPException(status_code=500, detail="Failed to delete user")


@router.post("/{username}/cameras/assign")
async def assign_cameras_api(username: str, payload: AssignCamerasRequest, request: Request):
    actor = _current(request)
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    _managed_target(actor, username)
    success, message = assign_cameras_to_user(actor["username"], username, payload.camera_ids)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}


@router.post("/{username}/cameras/remove")
async def remove_cameras_api(username: str, payload: AssignCamerasRequest, request: Request):
    actor = _current(request)
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    _managed_target(actor, username)
    success, message = remove_cameras_from_user(actor["username"], username, payload.camera_ids)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}


@router.get("/{username}/cameras")
async def get_user_cameras_endpoint(username: str, request: Request):
    actor = _current(request)
    if actor.get("username") != username:
        if actor.get("role") not in {"SuperAdmin", "Admin"}:
            raise HTTPException(status_code=403, detail="Cannot view another user's cameras")
        _managed_target(actor, username)
    return {"cameras": get_user_cameras(username)}


@router.get("/settings/system")
async def get_system_settings_endpoint(request: Request, cid: Optional[str] = None):
    actor = _current(request)
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    company_id = cid if actor.get("role") == "SuperAdmin" else actor.get("company_id")
    if actor.get("role") == "SuperAdmin" and company_id:
        from .companies import get_company
        if not get_company(company_id):
            raise HTTPException(status_code=404, detail="Company not found")
    return {"settings": get_settings(company_id)}


@router.put("/settings/system")
async def update_system_settings_endpoint(payload: SettingsRequest, request: Request, cid: Optional[str] = None):
    actor = _current(request)
    if actor.get("role") not in {"SuperAdmin", "Admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    company_id = cid if actor.get("role") == "SuperAdmin" else actor.get("company_id")
    if actor.get("role") == "SuperAdmin" and company_id:
        from .companies import get_company
        if not get_company(company_id):
            raise HTTPException(status_code=404, detail="Company not found")

    settings = get_settings(company_id)
    updates = payload.model_dump(exclude_unset=True)
    if actor.get("role") != "SuperAdmin":
        allowed = {
            "attendance", "face_recognition_enabled", "show_bounding_boxes",
            "unknown_detection_enabled", "long_distance_detection_enabled", "min_face_size",
        }
        updates = {key: value for key, value in updates.items() if key in allowed}

    for nested in ("attendance", "recognition"):
        if nested in updates and updates[nested]:
            merged = dict(settings.get(nested, {}))
            merged.update({key: value for key, value in updates[nested].items() if value is not None})
            settings[nested] = merged
            updates.pop(nested, None)
    settings.update(updates)
    save_settings(settings, company_id)
    return {"message": "Settings updated successfully", "settings": settings}
