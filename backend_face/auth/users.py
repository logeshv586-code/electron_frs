from typing import Dict, Any, Optional, List
from .storage import get_users, save_users, get_settings, save_settings
from .security import get_password_hash, verify_password

def create_user(username: str, password: str, role: str, created_by: str, is_active: bool = True, max_users_limit: int = 0, max_cameras_limit: int = 0, assigned_menus: List[str] = None, license_start_date: Optional[str] = None, license_end_date: Optional[str] = None, email: Optional[str] = None, company_id: Optional[str] = None) -> Dict[str, Any]:
    users = get_users()
    if username in users:
        raise ValueError("User already exists")
    
    # Check if creator has permission to create more users
    if role == "Supervisor" and created_by:
        creator = users.get(created_by)
        if creator and creator["role"] == "Admin":
            current_users = sum(1 for u in users.values() if u.get("created_by") == created_by)
            limit = creator.get("max_users_limit", 0)
            if limit > 0 and current_users >= limit:
                raise ValueError(f"User creation limit reached. You can only create {limit} users.")

    user_data = {
        "username": username,
        "hashed_password": get_password_hash(password),
        "role": role,
        "email": email,
        "is_active": is_active,
        "created_by": created_by,
        "created_at": "2024-01-01T00:00:00Z",  # Use proper timestamp in production
        "assigned_cameras": [],
        "assigned_menus": assigned_menus if assigned_menus is not None else get_default_menus_for_role(role),
        "max_users_limit": max_users_limit,
        "max_cameras_limit": max_cameras_limit,
        "company_id": company_id
    }
    # Apply license period for Admin users if provided
    if role == "Admin":
        user_data["license_start_date"] = license_start_date
        user_data["license_end_date"] = license_end_date
    users[username] = user_data
    save_users(users)
    return user_data

def get_user(username: str) -> Optional[Dict[str, Any]]:
    users = get_users()
    return users.get(username)

def update_user(username: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    users = get_users()
    if username not in users:
        return None
    
    user = users[username]
    allowed_updates = ["is_active", "assigned_cameras", "assigned_menus", "max_users_limit", "max_cameras_limit", "license_start_date", "license_end_date", "email", "company_id", "password"]
    for key, value in updates.items():
        if key in allowed_updates:
            if key == "password":
                user["hashed_password"] = get_password_hash(value)
            else:
                user[key] = value
    
    save_users(users)
    return user

def delete_user(username: str) -> bool:
    users = get_users()
    if username not in users:
        return False
    
    del users[username]
    save_users(users)
    return True

def list_users(company_id: Optional[str] = None) -> List[Dict[str, Any]]:
    users = get_users()
    if company_id:
        return [u for u in users.values() if u.get("company_id") == company_id]
    return list(users.values())

def get_default_menus_for_role(role: str) -> List[str]:
    role_menus = {
        "SuperAdmin": ["dashboard", "users", "cameras", "analytics", "settings", "logs"],
        "Admin": ["dashboard", "cameras", "analytics", "users"],
        "Supervisor": ["dashboard", "cameras"]
    }
    return role_menus.get(role, ["dashboard"])

def can_assign_cameras(admin_username: str, target_username: str, camera_count: int) -> tuple[bool, str]:
    users = get_users()
    admin = users.get(admin_username)
    target = users.get(target_username)
    
    if not admin or not target:
        return False, "User not found"
    
    if admin["role"] not in ["SuperAdmin", "Admin"]:
        return False, "Insufficient permissions"
    
    if admin["role"] == "Admin" and target["role"] != "Supervisor":
        return False, "Admins can only assign cameras to Supervisors"
    
    # Check Admin's limit if Admin is assigning to themselves (or if SuperAdmin is assigning to Admin)
    # Actually, if target is Admin, we check their limit
    if target["role"] == "Admin":
        limit = target.get("max_cameras_limit", 0)
        current_cameras = len(target.get("assigned_cameras", []))
        if limit > 0 and current_cameras + camera_count > limit:
            return False, f"Would exceed maximum cameras ({limit}) for Admin {target_username}"

    # Global/System settings check for Supervisors (optional, can be overridden by specific logic if needed)
    # But usually Supervisors don't have a limit unless specified. 
    # Let's keep the global check for Supervisors for backward compatibility or safety
    if target["role"] == "Supervisor":
        settings = get_settings()
        max_cameras = settings.get(f"max_cameras_per_{target['role'].lower()}", 5)
        current_cameras = len(target.get("assigned_cameras", []))
        if current_cameras + camera_count > max_cameras:
            return False, f"Would exceed maximum cameras ({max_cameras}) for {target['role']}"
    
    return True, ""

def assign_cameras_to_user(admin_username: str, target_username: str, camera_ids: List[str]) -> tuple[bool, str]:
    users = get_users()
    admin = users.get(admin_username)
    target = users.get(target_username)
    
    if not admin or not target:
        return False, "User not found"
    
    if admin["role"] == "Admin":
        admin_cameras = set(admin.get("assigned_cameras") or [])
        if admin_cameras:
            cameras_to_assign = set(camera_ids)
            if not cameras_to_assign.issubset(admin_cameras):
                return False, "You can only assign cameras that you have access to"

    can_assign, reason = can_assign_cameras(admin_username, target_username, len(camera_ids))
    if not can_assign:
        return False, reason
    
    current_cameras = set(target.get("assigned_cameras", []))
    new_cameras = set(camera_ids)
    
    # Check for exclusive assignment conflicts
    for username, user_data in users.items():
        if username == target_username:
            continue
            
        # Allow Admin to share cameras with their Supervisors (delegation)
        # So if the existing owner is the Admin assigning the camera, it's allowed.
        if username == admin_username:
            continue

        if user_data.get("role") in ["Admin", "Supervisor"]:
            existing_cameras = set(user_data.get("assigned_cameras", []))
            conflicts = existing_cameras.intersection(new_cameras)
            if conflicts:
                return False, f"Cameras {list(conflicts)} are already assigned to {username}"
    
    # Assign cameras
    updated_cameras = list(current_cameras.union(new_cameras))
    target["assigned_cameras"] = updated_cameras
    save_users(users)
    
    return True, f"Successfully assigned {len(camera_ids)} cameras to {target_username}"

def remove_cameras_from_user(admin_username: str, target_username: str, camera_ids: List[str]) -> tuple[bool, str]:
    users = get_users()
    admin = users.get(admin_username)
    target = users.get(target_username)
    
    if not admin or not target:
        return False, "User not found"
    
    if admin["role"] not in ["SuperAdmin", "Admin"]:
        return False, "Insufficient permissions"
    
    current_cameras = set(target.get("assigned_cameras", []))
    cameras_to_remove = set(camera_ids)
    
    updated_cameras = list(current_cameras - cameras_to_remove)
    target["assigned_cameras"] = updated_cameras
    save_users(users)
    
    return True, f"Successfully removed {len(camera_ids)} cameras from {target_username}"

def get_user_cameras(username: str) -> List[str]:
    user = get_user(username)
    if not user:
        return []
    return user.get("assigned_cameras", [])
