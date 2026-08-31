from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any
import os
import secrets
import uuid

import bcrypt
import jwt

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = max(5, int(os.getenv("FRS_ACCESS_TOKEN_MINUTES", "60")))
TOKEN_ISSUER = os.getenv("FRS_TOKEN_ISSUER", "electron-frs")


def _load_or_create_secret() -> str:
    configured = os.getenv("FRS_JWT_SECRET") or os.getenv("JWT_SECRET_KEY")
    if configured and len(configured) >= 32:
        return configured

    runtime_dir = Path(__file__).resolve().parents[1] / "data" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    secret_file = runtime_dir / "jwt_secret.txt"
    if secret_file.exists():
        value = secret_file.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value

    value = secrets.token_urlsafe(48)
    secret_file.write_text(value, encoding="utf-8")
    try:
        os.chmod(secret_file, 0o600)
    except Exception:
        pass
    return value


SECRET_KEY = _load_or_create_secret()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        plain = plain_password.encode("utf-8") if isinstance(plain_password, str) else plain_password
        hashed = hashed_password.encode("utf-8") if isinstance(hashed_password, str) else hashed_password
        return bcrypt.checkpw(plain, hashed)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    raw = password.encode("utf-8") if isinstance(password, str) else password
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = data.copy()
    payload.update({
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "iss": TOKEN_ISSUER,
        "jti": str(uuid.uuid4()),
    })
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=TOKEN_ISSUER,
            options={"require": ["exp", "iat", "sub", "role"]},
        )
        username = payload.get("sub")
        role = payload.get("role")
        if not username or not role:
            return None
        return {
            "username": username,
            "role": role,
            "company_id": payload.get("company_id"),
            "jti": payload.get("jti"),
            "exp": payload.get("exp"),
        }
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, jwt.PyJWTError):
        return None


def authenticate_user(username: str, password: str, role: Optional[str] = None) -> Optional[Dict[str, Any]]:
    from .storage import get_users

    users = get_users()
    user = users.get(username)
    if not user:
        return None
    if not verify_password(password, user.get("hashed_password", "")):
        return None
    if role and user.get("role") != role:
        return None
    if not user.get("is_active", True):
        return None
    return user
