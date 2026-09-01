from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional
import json
import logging
import threading

from db.repository import get_kv_namespace, set_kv_namespace, get_kv, set_kv

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
AUTH_DATA_DIR = BACKEND_DIR / "data" / "auth"
USERS_FILE = AUTH_DATA_DIR / "users.json"
SETTINGS_FILE = AUTH_DATA_DIR / "settings.json"
COMPANIES_FILE = AUTH_DATA_DIR / "companies.json"
CAMERAS_FILE = BACKEND_DIR / "data" / "cameras.json"
_MIGRATION_LOCK = threading.Lock()
_MIGRATED_NAMESPACES = set()

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
    AUTH_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_legacy(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception as exc:
        logger.warning("Could not migrate legacy auth file %s: %s", path, exc)
        return None


def _migrate_namespace_once(namespace: str, path: Path) -> None:
    if namespace in _MIGRATED_NAMESPACES:
        return
    with _MIGRATION_LOCK:
        if namespace in _MIGRATED_NAMESPACES:
            return
        existing = get_kv_namespace(namespace)
        if not existing:
            legacy = _read_legacy(path)
            if legacy:
                set_kv_namespace(namespace, legacy)
                logger.info("Migrated legacy %s into database namespace %s", path.name, namespace)
        _MIGRATED_NAMESPACES.add(namespace)


def atomic_write_json(path: Path, data: Dict[str, Any]):
    """Compatibility helper; known auth documents are persisted to the database."""
    path = Path(path)
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
    temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def load_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    path = Path(path)
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
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return default or {}


def get_users() -> Dict[str, Any]:
    _migrate_namespace_once("auth_users", USERS_FILE)
    return get_kv_namespace("auth_users")


def save_users(users: Dict[str, Any]):
    set_kv_namespace("auth_users", users or {})
    _MIGRATED_NAMESPACES.add("auth_users")


def _settings_namespace(company_id: Optional[str]) -> str:
    return "settings:global" if not company_id else f"settings:{company_id}"


def get_settings(company_id: Optional[str] = None) -> Dict[str, Any]:
    namespace = _settings_namespace(company_id)
    if namespace not in _MIGRATED_NAMESPACES:
        if company_id:
            legacy_path = AUTH_DATA_DIR / f"settings_{company_id}.json"
        else:
            legacy_path = SETTINGS_FILE
        legacy = _read_legacy(legacy_path)
        if get_kv(namespace, "document", None) is None and legacy:
            set_kv(namespace, "document", legacy)
        _MIGRATED_NAMESPACES.add(namespace)

    stored = get_kv(namespace, "document", None)
    if not isinstance(stored, dict):
        return deepcopy(DEFAULT_SETTINGS)

    result = deepcopy(DEFAULT_SETTINGS)
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value
    return result


def save_settings(settings: Dict[str, Any], company_id: Optional[str] = None):
    namespace = _settings_namespace(company_id)
    set_kv(namespace, "document", settings or {})
    _MIGRATED_NAMESPACES.add(namespace)


def get_cameras() -> Dict[str, Any]:
    return get_kv_namespace("legacy_auth_cameras")


def save_cameras(cameras: Dict[str, Any]):
    set_kv_namespace("legacy_auth_cameras", cameras or {})


def get_companies() -> Dict[str, Any]:
    _migrate_namespace_once("companies", COMPANIES_FILE)
    return get_kv_namespace("companies")


def save_companies(companies: Dict[str, Any]):
    set_kv_namespace("companies", companies or {})
    _MIGRATED_NAMESPACES.add("companies")


def _tokens_file() -> Path:
    return AUTH_DATA_DIR / "tokens.json"


def get_tokens() -> Dict[str, Any]:
    _migrate_namespace_once("auth_tokens", _tokens_file())
    return get_kv_namespace("auth_tokens")


def save_tokens(tokens: Dict[str, Any]):
    set_kv_namespace("auth_tokens", tokens or {})
    _MIGRATED_NAMESPACES.add("auth_tokens")
