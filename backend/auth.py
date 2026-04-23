import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
import models

load_dotenv()

# Tokens that have historically appeared in placeholder keys — if we spot any
# of these in SECRET_KEY, the value almost certainly came from a template the
# operator forgot to override.
_PLACEHOLDER_MARKERS = (
    "fallback", "change-in-production", "change-this", "your-secret",
    "please-change", "example", "placeholder",
)
_MIN_SECRET_LENGTH = 32


def _validate_secret_key(raw: Optional[str]) -> str:
    """Refuse to start with a missing, default, or obviously-templated key.

    Bypass for local hacking only via ALLOW_WEAK_SECRET=1 — logged as a
    warning so it's impossible to miss."""
    if not raw:
        raise RuntimeError(
            "SECRET_KEY is not set.\n"
            "Generate one with:\n"
            '    python -c "import secrets; print(secrets.token_urlsafe(64))"\n'
            "and put it in backend/.env as SECRET_KEY=..."
        )
    lower = raw.lower()
    weak_reason: Optional[str] = None
    if len(raw) < _MIN_SECRET_LENGTH:
        weak_reason = f"too short ({len(raw)} chars, need ≥{_MIN_SECRET_LENGTH})"
    else:
        for marker in _PLACEHOLDER_MARKERS:
            if marker in lower:
                weak_reason = f"contains placeholder marker '{marker}'"
                break

    if weak_reason:
        if os.getenv("ALLOW_WEAK_SECRET") == "1":
            import logging
            logging.getLogger("compass.app").warning(
                "SECRET_KEY is weak (%s) — allowed because ALLOW_WEAK_SECRET=1. "
                "Never run production with this flag.", weak_reason,
            )
            return raw
        raise RuntimeError(
            f"SECRET_KEY is unsafe: {weak_reason}.\n"
            "Generate a strong key with:\n"
            '    python -c "import secrets; print(secrets.token_urlsafe(64))"\n'
            "Set ALLOW_WEAK_SECRET=1 to override for local-only testing."
        )
    return raw


SECRET_KEY = _validate_secret_key(os.getenv("SECRET_KEY"))
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_hex(64)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    user_id: int = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user
