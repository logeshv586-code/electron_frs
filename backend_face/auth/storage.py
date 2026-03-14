import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import threading

AUTH_DATA_DIR = Path("data/auth")
USERS_FILE = AUTH_DATA_DIR / "users.json"
SETTINGS_FILE = AUTH_DATA_DIR / "settings.json"
COMPANIES_FILE = AUTH_DATA_DIR / "companies.json"
CAMERAS_FILE = Path("data/cameras.json")

_lock = threading.Lock()

def ensure_auth_data_dir():
    AUTH_DATA_DIR.mkdir(parents=True, exist_ok=True)

def atomic_write_json(path: Path, data: Dict[str, Any]):
    with _lock:
        temp_path = path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(path)

def load_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not path.exists():
        return default or {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default or {}

def get_users() -> Dict[str, Any]:
    return load_json(USERS_FILE, {})

def save_users(users: Dict[str, Any]):
    atomic_write_json(USERS_FILE, users)

def get_settings() -> Dict[str, Any]:
    return load_json(SETTINGS_FILE, {
        "max_cameras_per_admin": 10,
        "max_cameras_per_supervisor": 5,
        "require_approval_for_new_users": False,
        "attendance": {
            "punch_in": "09:30",
            "punch_out": "18:00",
            "working_hours": 8,
            "grace_minutes": 15,
            "min_hours_present": 4.0,
            "overtime_after": 9.0
        }
    })

def save_settings(settings: Dict[str, Any]):
    atomic_write_json(SETTINGS_FILE, settings)

def get_cameras() -> Dict[str, Any]:
    return load_json(CAMERAS_FILE, {})

def save_cameras(cameras: Dict[str, Any]):
    atomic_write_json(CAMERAS_FILE, cameras)

def get_companies() -> Dict[str, Any]:
    return load_json(COMPANIES_FILE, {})

def save_companies(companies: Dict[str, Any]):
    atomic_write_json(COMPANIES_FILE, companies)

def _tokens_file() -> Path:
    return AUTH_DATA_DIR / "tokens.json"

def get_tokens() -> Dict[str, Any]:
    return load_json(_tokens_file(), {})

def save_tokens(tokens: Dict[str, Any]):
    ensure_auth_data_dir()
    atomic_write_json(_tokens_file(), tokens)
