from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
from passlib.context import CryptContext
from .storage import get_users

SECRET_KEY = "your-secret-key-here-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    # Non-expiring token: do not include exp claim; include issued-at for traceability
    to_encode.update({"iat": int(datetime.utcnow().timestamp())})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        # Ignore expiration entirely
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
        username: str = payload.get("sub")
        role: str = payload.get("role")
        company_id: Optional[str] = payload.get("company_id")
        if username is None or role is None:
            return None
        return {"username": username, "role": role, "company_id": company_id}
    except jwt.PyJWTError:
        return None

def authenticate_user(username: str, password: str, role: str) -> Optional[Dict[str, Any]]:
    users = get_users()
    user = users.get(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    if user.get("role") != role:
        return None
    if not user.get("is_active", True):
        return None
    return user
