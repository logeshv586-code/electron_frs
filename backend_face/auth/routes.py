import logging
from datetime import timedelta, datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from .security import authenticate_user, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from .users import create_user, get_user, list_users
from .storage import ensure_auth_data_dir, get_tokens, save_tokens
from .license_dates import parse_license_datetime

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
    license_start_date: Optional[str] = None
    license_end_date: Optional[str] = None
    company_id: Optional[str] = None

class BootstrapSuperAdminRequest(BaseModel):
    username: str
    password: str

class ForgotPasswordRequest(BaseModel):
    username: str

class ResetPasswordRequest(BaseModel):
    username: str
    token: str # Simple token check for now
    new_password: str

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
    
    # Special handling for SuperAdmin - allow login without role matching
    user = get_user(request.username)
    
    # Auto-discover role if not provided
    effective_role = request.role
    if not effective_role and user:
        effective_role = user.get("role")
        logger.info(f"Auto-discovered role '{effective_role}' for user '{request.username}'")

    if user and user["role"] == "SuperAdmin":
        # For SuperAdmin, authenticate without role check
        auth_user = authenticate_user(request.username, request.password, user["role"])
    else:
        # For other roles, require exact role match
        if not effective_role:
             raise HTTPException(status_code=400, detail="Role selection required for this user")
        auth_user = authenticate_user(request.username, request.password, effective_role)
    
    if not auth_user:
        raise HTTPException(status_code=401, detail="Invalid credentials or role")
    
    # Enforce Admin license expiry at login
    if auth_user["role"] == "Admin":
        end_str = auth_user.get("license_end_date")
        if end_str:
            end_dt = parse_license_datetime(end_str)
            now = datetime.now(timezone.utc)
            if end_dt and end_dt < now:
                raise HTTPException(status_code=403, detail="License expired. Contact SuperAdmin.")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token_data = {
        "sub": auth_user["username"], 
        "role": auth_user["role"],
        "company_id": auth_user.get("company_id")
    }
    access_token = create_access_token(
        data=token_data,
        expires_delta=access_token_expires
    )
    
    # Register active token
    tokens = get_tokens()
    tokens[access_token] = {
        "username": auth_user["username"],
        "role": auth_user["role"],
        "company_id": auth_user.get("company_id"),
        "issued_at": int(datetime.now(timezone.utc).timestamp())
    }
    save_tokens(tokens)
    
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        role=auth_user["role"],
        username=auth_user["username"],
        email=auth_user.get("email"),
        assigned_menus=auth_user.get("assigned_menus", auth_user.get("menus", [])),
        license_start_date=auth_user.get("license_start_date"),
        license_end_date=auth_user.get("license_end_date"),
        company_id=auth_user.get("company_id")
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
        license_end_date=user.get("license_end_date")
    )

@router.post("/bootstrap/superadmin")
async def bootstrap_superadmin(request: BootstrapSuperAdminRequest):
    """Create initial SuperAdmin user if none exists"""
    ensure_auth_data_dir()
    
    # Check if any SuperAdmin already exists
    users = list_users()
    superadmin_exists = any(user["role"] == "SuperAdmin" for user in users)
    
    if superadmin_exists:
        raise HTTPException(status_code=400, detail="SuperAdmin already exists")
    
    # Create SuperAdmin user
    superadmin = create_user(
        username=request.username,
        password=request.password,
        role="SuperAdmin",
        created_by="system"
    )
    
    return {"message": "SuperAdmin created successfully", "username": superadmin["username"]}

@router.post("/logout")
async def logout(request: Request):
    # Revoke current token server-side
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        tokens = get_tokens()
        if token in tokens:
            del tokens[token]
            save_tokens(tokens)
            return {"message": "Logout successful"}
    return {"message": "Logout successful"}

@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    user = get_user(request.username)
    if not user:
        # Don't reveal user existence for security, but logs will help
        logger.info(f"Forgot password requested for non-existent user: {request.username}")
        return {"message": "If an email is associated with this account, instructions have been sent."}
    
    email = user.get("email")
    if not email:
        logger.warn(f"User {request.username} requested password reset but has no email configured.")
        return {"message": "No email associated with this account. Please contact your Admin."}
    
    # Simple token for demonstration: username_timestamp_reset
    token = f"{request.username}_{int(datetime.now(timezone.utc).timestamp())}_reset"
    
    # In a real app, you'd store this token with an expiry
    # For now, we'll just log it and send a simulated email
    from .email_utils import send_email
    subject = "Password Reset Request"
    body = f"Hello {request.username},\n\nYou requested a password reset. Use the following token to reset your password: {token}\n\nIf you did not request this, please ignore this email."
    
    if send_email(email, subject, body):
        return {"message": "Reset instructions sent to your email."}
    else:
        # Fallback for dev/unconfigured SMTP
        return {"message": "Reset token generated (simulated): " + token}

@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    user = get_user(request.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Basic token validation (in production, use a secure signed token or DB lookup)
    if not request.token.startswith(request.username) or "_reset" not in request.token:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    
    from .users import update_user
    update_user(request.username, {"password": request.new_password})
    logger.info(f"Password reset successful for user: {request.username}")
    
    return {"message": "Password has been reset successfully."}
