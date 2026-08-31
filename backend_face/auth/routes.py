from __future__ import annotations

import logging
import os
from datetime import timedelta, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .security import authenticate_user, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from .users import create_user, get_user, list_users, update_user
from .storage import ensure_auth_data_dir, get_tokens, save_tokens
from .middleware import is_tenant_license_valid
from db.repository import create_password_reset_token, consume_password_reset_token, write_audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    username: str
    email: Optional[str] = None
    assigned_menus: list
    assigned_cameras: list
    max_users_limit: int = 0
    max_cameras_limit: int = 0
    license_start_date: Optional[str] = None
    license_end_date: Optional[str] = None
    company_id: Optional[str] = None
    expires_in: int


class BootstrapSuperAdminRequest(BaseModel):
    username: str
    password: str = Field(min_length=12)


class ForgotPasswordRequest(BaseModel):
    username: str


class ResetPasswordRequest(BaseModel):
    username: str
    token: str
    new_password: str = Field(min_length=12)


class UserResponse(BaseModel):
    username: str
    role: str
    email: Optional[str] = None
    is_active: bool
    assigned_cameras: list
    assigned_menus: list
    max_users_limit: Optional[int] = 0
    max_cameras_limit: Optional[int] = 0
    company_id: Optional[str] = None
    license_start_date: Optional[str] = None
    license_end_date: Optional[str] = None


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    ensure_auth_data_dir()
    user = get_user(request.username)
    effective_role = request.role or (user.get("role") if user else None)
    if not effective_role:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    auth_user = authenticate_user(request.username, request.password, effective_role)
    if not auth_user:
        write_audit("LOGIN_FAILED", username=request.username)
        raise HTTPException(status_code=401, detail="Invalid credentials or role")

    # The platform SuperAdmin is internal. Every customer Admin/Supervisor is governed
    # by the tenant Admin's license window; an expired tenant cannot continue through a
    # Supervisor session after the Admin license has expired.
    if not is_tenant_license_valid(auth_user):
        write_audit(
            "LOGIN_BLOCKED_LICENSE",
            username=auth_user.get("username"),
            company_id=auth_user.get("company_id"),
        )
        raise HTTPException(status_code=403, detail="Company license is inactive or expired. Contact your provider.")

    expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    now = datetime.now(timezone.utc)
    access_token = create_access_token(
        data={
            "sub": auth_user["username"],
            "role": auth_user["role"],
            "company_id": auth_user.get("company_id"),
        },
        expires_delta=expires,
    )
    tokens = get_tokens()
    tokens[access_token] = {
        "username": auth_user["username"],
        "role": auth_user["role"],
        "company_id": auth_user.get("company_id"),
        "issued_at": int(now.timestamp()),
        "expires_at": int((now + expires).timestamp()),
    }
    save_tokens(tokens)
    write_audit(
        "LOGIN_SUCCESS",
        username=auth_user["username"],
        company_id=auth_user.get("company_id"),
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        role=auth_user["role"],
        username=auth_user["username"],
        email=auth_user.get("email"),
        assigned_menus=auth_user.get("assigned_menus", auth_user.get("menus", [])),
        assigned_cameras=auth_user.get("assigned_cameras", []),
        max_users_limit=int(auth_user.get("max_users_limit") or 0),
        max_cameras_limit=int(auth_user.get("max_cameras_limit") or 0),
        license_start_date=auth_user.get("license_start_date"),
        license_end_date=auth_user.get("license_end_date"),
        company_id=auth_user.get("company_id"),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user(request: Request):
    user = request.scope.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserResponse(
        username=user["username"],
        role=user["role"],
        email=user.get("email"),
        is_active=user.get("is_active", True),
        assigned_cameras=user.get("assigned_cameras", []),
        assigned_menus=user.get("assigned_menus", user.get("menus", [])),
        max_users_limit=user.get("max_users_limit", 0),
        max_cameras_limit=user.get("max_cameras_limit", 0),
        company_id=user.get("company_id"),
        license_start_date=user.get("license_start_date"),
        license_end_date=user.get("license_end_date"),
    )


@router.post("/bootstrap/superadmin")
async def bootstrap_superadmin(request: BootstrapSuperAdminRequest):
    ensure_auth_data_dir()
    if any(user.get("role") == "SuperAdmin" for user in list_users()):
        raise HTTPException(status_code=400, detail="SuperAdmin already exists")
    superadmin = create_user(
        username=request.username,
        password=request.password,
        role="SuperAdmin",
        created_by="system",
    )
    write_audit("SUPERADMIN_BOOTSTRAPPED", username=superadmin["username"])
    return {"message": "SuperAdmin created successfully", "username": superadmin["username"]}


@router.post("/logout")
async def logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        tokens = get_tokens()
        token_info = tokens.pop(token, None)
        save_tokens(tokens)
        if token_info:
            write_audit(
                "LOGOUT",
                username=token_info.get("username"),
                company_id=token_info.get("company_id"),
            )
    return {"message": "Logout successful"}


@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    # Deliberately do not reveal whether the account exists.
    user = get_user(request.username)
    generic = "If the account exists and has an email, a one-time reset token has been sent."
    if not user or not user.get("email"):
        return {"message": generic}

    token = create_password_reset_token(request.username, ttl_minutes=15)
    from .email_utils import send_email

    body = (
        f"Hello {request.username},\n\n"
        f"Your Face Recognition System one-time password reset token is:\n\n{token}\n\n"
        "This token expires in 15 minutes and can be used only once. "
        "If you did not request this reset, you can ignore this message."
    )
    sent = send_email(user["email"], "FRS password reset token", body)
    write_audit(
        "PASSWORD_RESET_REQUESTED",
        username=request.username,
        company_id=user.get("company_id"),
        details={"email_sent": bool(sent)},
    )

    response = {"message": generic}
    if os.getenv("FRS_DEV_SHOW_RESET_TOKEN", "0").lower() in {"1", "true", "yes"}:
        response["dev_token"] = token
    return response


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    user = get_user(request.username)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    if not consume_password_reset_token(request.username, request.token):
        write_audit(
            "PASSWORD_RESET_FAILED",
            username=request.username,
            company_id=user.get("company_id"),
        )
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    update_user(request.username, {"password": request.new_password})

    # Password reset revokes every current session for this user.
    tokens = get_tokens()
    tokens = {
        token: info for token, info in tokens.items()
        if info.get("username") != request.username
    }
    save_tokens(tokens)
    write_audit(
        "PASSWORD_RESET_SUCCESS",
        username=request.username,
        company_id=user.get("company_id"),
    )
    return {"message": "Password reset successfully. Sign in with your new password."}
