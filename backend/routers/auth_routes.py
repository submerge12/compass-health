import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    get_current_user,
)
from database import get_db
from logging_config import user_id_var
from services.rate_limit import RateLimit

# Two-tier limits: the short window stops bursts; the long window stops a
# slow-drip dictionary attack. Register is tighter because account-creation
# abuse costs more to clean up than a handful of failed logins.
_login_burst   = RateLimit(rate=5,  per_seconds=60,   bucket="login_burst")
_login_hour    = RateLimit(rate=30, per_seconds=3600, bucket="login_hour")
_register_burst = RateLimit(rate=3,  per_seconds=60,   bucket="register_burst")
_register_day   = RateLimit(rate=10, per_seconds=86400, bucket="register_day")

log = logging.getLogger("compass.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_TOKEN_EXPIRE_DAYS = 7


# ── Schemas ──────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    email: Optional[str] = None          # optional — auto-generated if omitted
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    # Optional so the client can logout even if it has already lost its
    # refresh token. When omitted, all refresh tokens for the authenticated
    # user are revoked (logout-everywhere semantics).
    refresh_token: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    has_bmr_profile: bool
    username: str
    membership_level: str
    is_admin: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_token_response(user: models.User, db: Session) -> dict:
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token_str = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    db_refresh = models.RefreshToken(
        user_id=user.id,
        token=refresh_token_str,
        expires_at=expires_at,
    )
    db.add(db_refresh)
    db.commit()

    has_bmr = user.bmr_profile is not None
    mem_level = user.membership.level if user.membership else "free"

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "has_bmr_profile": has_bmr,
        "username": user.username,
        "membership_level": mem_level,
        "is_admin": bool(user.is_admin),
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_register_burst.check), Depends(_register_day.check)],
)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == body.username).first():
        log.info("register rejected: username taken", extra={"event": "register_conflict"})
        raise HTTPException(status_code=409, detail="Username already taken")
    if len(body.password) < 6:
        log.info("register rejected: weak password", extra={"event": "register_weak_pw"})
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")

    # Resolve email — auto-generate a placeholder if not supplied
    email = (body.email or "").strip() or f"{body.username}@local.compass"
    if db.query(models.User).filter(models.User.email == email).first():
        # Avoid collision for auto-generated placeholder
        email = f"{body.username}_{datetime.now(timezone.utc).timestamp():.0f}@local.compass"

    # First registered user automatically becomes admin
    is_first_user = db.query(models.User).count() == 0

    user = models.User(
        username=body.username,
        email=email,
        hashed_password=hash_password(body.password),
        is_admin=is_first_user,
    )
    db.add(user)
    db.flush()   # get user.id before commit

    db.add(models.Membership(user_id=user.id, level="free"))
    db.add(models.UserSettings(user_id=user.id))
    db.commit()
    db.refresh(user)

    # Populate contextvar so the access-log line for this request carries
    # the freshly minted user_id instead of "-".
    user_id_var.set(user.id)
    log.info(
        "user registered",
        extra={"event": "register_ok", "new_user_id": user.id, "is_admin": bool(user.is_admin)},
    )
    return _build_token_response(user, db)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(_login_burst.check), Depends(_login_hour.check)],
)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        # Log username attempt on failure for brute-force detection. We only
        # log the attempted username, never the password.
        log.warning(
            "login failed: bad credentials",
            extra={"event": "login_fail", "attempted_username": body.username[:64]},
        )
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active:
        log.warning(
            "login rejected: account disabled",
            extra={"event": "login_disabled", "target_user_id": user.id},
        )
        raise HTTPException(status_code=403, detail="Account is disabled")

    user_id_var.set(user.id)
    log.info(
        "login ok",
        extra={"event": "login_ok", "is_admin": bool(user.is_admin)},
    )
    return _build_token_response(user, db)


@router.post("/refresh")
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    db_token = (
        db.query(models.RefreshToken)
        .filter(models.RefreshToken.token == body.refresh_token)
        .first()
    )
    if not db_token:
        log.info("refresh failed: unknown token", extra={"event": "refresh_unknown"})
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    token_expires = db_token.expires_at
    if token_expires.tzinfo is None:
        token_expires = token_expires.replace(tzinfo=timezone.utc)
    if token_expires < now:
        db.delete(db_token)
        db.commit()
        log.info(
            "refresh failed: expired",
            extra={"event": "refresh_expired", "target_user_id": db_token.user_id},
        )
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = db.query(models.User).filter(models.User.id == db_token.user_id).first()
    if not user:
        log.warning(
            "refresh failed: user missing",
            extra={"event": "refresh_orphan", "target_user_id": db_token.user_id},
        )
        raise HTTPException(status_code=401, detail="User not found")

    user_id_var.set(user.id)
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(
    body: Optional[LogoutRequest] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == current_user.id
    )
    scope = "single"
    # If a specific refresh token is provided, revoke only that session;
    # otherwise revoke every session for this user.
    if body and body.refresh_token:
        q = q.filter(models.RefreshToken.token == body.refresh_token)
    else:
        scope = "all"
    deleted = q.delete(synchronize_session=False)
    db.commit()
    log.info(
        "logout",
        extra={"event": "logout_ok", "scope": scope, "sessions_revoked": deleted},
    )
    return {"detail": "Logged out"}
