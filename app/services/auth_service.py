import os
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super_secret_safetysignal_key_2026_xyz")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day

class AuthService:
    @staticmethod
    def get_password_hash(password: str) -> str:
        """Hashes password using SHA-256 with a unique salt."""
        salt = secrets.token_hex(16)
        hash_val = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return f"{salt}${hash_val}"

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verifies plain password against stored salt$hash."""
        try:
            salt, stored_hash = hashed_password.split("$")
            computed_hash = hashlib.sha256((salt + plain_password).encode("utf-8")).hexdigest()
            return computed_hash == stored_hash
        except Exception:
            return False

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    @staticmethod
    def decode_token(token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None

auth_service = AuthService()