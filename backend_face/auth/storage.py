from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional
import json
import logging

from db.repository import get_kv_namespace, set_kv_namespace, get_kv, set_kv

logger = logging.getLogger(__name__)

# Kept for import compatibility only. Runtime state is now database-backed.
AUTH_DATA_DIR = Path("data/auth")
USERS_FILE = AUTH_DATA_DIR / "users.json"
SETTINGS_FILE = AUTH_DATA_DIR / "settings.json"
COMPANIES_FILE = AUTH_DATA_DIR / "companies.json"
CAMERAS_FILE = Path("data/cameras.json")

DEFAULT_SETTINGS = {
    "max_cameras_per_admin": 10,
    "max_cameras_per_supervisor": 5,
    "require_approval_for_new_users": False,
    "face_recognition_enabled": True,
    "show_bounding_boxes": True,
    "unknown_detection_enabled": True,
    "long_distance_detection_enabled": True,
    "min_face_size": 20,
    "recognition": {
        "min_recognition_face_px": 56,
        "min_attendance_face_px": 72,
        "confirmation_frames": 3,
        "confirmation_window": 5,
        "known_distance_threshold": 0.46,
        "distant_distance_threshold": 0.42,
        "match_margin": 0.04,
        "min_quality": 0.18,
        "min_attendance_quality": 0.24,
        "unknown_cluster_similarity": 0.88,
    },
    "attendance": {
        "punch_in": "09:30",
        "punch_out": "18:00",
        "working_hours": 8,
        "grace_minutes": 15,
        "min_hours_present": 4.0,
        "overtime_after": 9.0,
        "shift_start": "06:00",
        "shift_end": "23:59",
    },
}


def ensure_auth_data_dir():
    """Compatibility no-op; the DB layer initializes its own runtime directory."""
    return None


def atomic_write_json(path: Path, data: Dict[str, Any]):
    """Legacy compatibility helper.

    Known auth runtime documents are written to the database rather than disk.
    Unknown paths are still written atomically so older optional modules keep working.
    """
    name = path.name.lower()
    if name == "users.json":
        save_users(data)
        return
    if name == "companies.json":
        save_companies(data)
        return
    if name == "tokens.json":
        save_tokens(data)
        return
    if name.startswith("settings") and name.endswith(".json"):
        company_id = None
        if name not in {"settings.json", "settings_default.json"}:
            company_id = path.stem.replace("settings_", "", 1)
        save_settings(data, company_id=company_id)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    temp_path.replace(path)


def load_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    name = path.name.lower()
    if name == "users.json":
        return get_users()
    if name == "companies.json":
        return get_companies()
    if name == "tokens.json":
        return get_tokens()
    if name.startswith("settings") and name.endswith(".json"):
        company_id = None
        if name not in {"settings.json", "settings_default.json"}:
            company_id = path.stem.replace("settings_", "", 1)
        return get_settings(company_id)

    if not path.exists():
        return default or {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, IOError):
        return default or {}


def get_users() -> Dict[str, Any]:
    return get_kv_namespace("auth_users")


def save_users(users: Dict[str, Any]):
    set_kv_namespace("auth_users", users or {})


def get_settings(company_id: Optional[str] = None) -> Dict[str, Any]:
    namespace = "settings:global" if not company_id else f"settings:{company_id}"
    stored = get_kv(namespace, "document", None)
    if not isinstance(stored, dict):
        return deepcopy(DEFAULT_SETTINGS)

    # Deep merge so new production-safe options appear after an upgrade.
    result = deepcopy(DEFAULT_SETTINGS)
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value
    return result


def save_settings(settings: Dict[str, Any], company_id: Optional[str] = None):
    namespace = "settings:global" if not company_id else f"settings:{company_id}"
    set_kv(namespace, "document", settings or {})


def get_cameras() -> Dict[str, Any]:
    # Compatibility store used by old auth modules only. Main camera management now has a DB table.
    return get_kv_namespace("legacy_auth_cameras")


def save_cameras(cameras: Dict[str, Any]):
    set_kv_namespace("legacy_auth_cameras", cameras or {})


def get_companies() -> Dict[str, Any]:
    return get_kv_namespace("companies")


def save_companies(companies: Dict[str, Any]):
    set_kv_namespace("companies", companies or {})


def _tokens_file() -> Path:
    return AUTH_DATA_DIR / "tokens.json"


def get_tokens() -> Dict[str, Any]:
    return get_kv_namespace("auth_tokens")


def save_tokens(tokens: Dict[str, Any]):
    set_kv_namespace("auth_tokens", tokens or {})
