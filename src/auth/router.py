from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.auth.schemas import LoginRequest, PasswordChangeRequest, ForgotPasswordRequest, RefreshRequest, ResetPasswordRequest, TokenResponse, UserCreate, UserOut
from src.core.database import get_db
from src.core.security import blacklist_token, create_access_token, create_refresh_token, hash_password, revoke_refresh_token, validate_refresh_token, verify_password
from src.auth.deps import bearer_scheme, get_current_user, require_super_admin
from src.core.rate_limit import limiter

import logging
import secrets

from src.core.audit import log_audit
from src.core.config import settings
from src.core.redis import get_redis

_redis = get_redis()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("30/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.email == body.email, User.is_active.is_(True)).limit(1)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    # Record last login
    from datetime import datetime, timezone
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()

    access = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
    refresh = await create_refresh_token(str(user.id), str(user.tenant_id))

    await log_audit(db, user.tenant_id, "user", str(user.id), "login", "user", str(user.id), {"email": user.email})

    return TokenResponse(access_token=access, refresh_token=refresh, user=UserOut.model_validate(user))


@router.post("/logout")
async def logout(
    credentials=Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Blacklist the current JWT token."""
    await blacklist_token(credentials.credentials)
    await log_audit(db, user.tenant_id, "user", str(user.id), "logout", "user", str(user.id))
    return {"status": "logged_out"}


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh_token(request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access + refresh token pair (rotation)."""
    result_pair = await validate_refresh_token(body.refresh_token)
    if not result_pair:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user_id, tenant_id = result_pair
    user_result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or deactivated")

    new_access = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
    new_refresh = await create_refresh_token(str(user.id), str(user.tenant_id))
    return TokenResponse(access_token=new_access, refresh_token=new_refresh, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: PasswordChangeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    # Password complexity validated by PasswordChangeRequest schema (field_validator)
    user.password_hash = hash_password(body.new_password)
    await db.flush()

    # Invalidate any pending password reset tokens for this user
    try:
        cursor = 0
        while True:
            cursor, keys = await _redis.scan(cursor, match="pwd_reset:*", count=100)
            for key in keys:
                val = await _redis.get(key)
                if val == str(user.id):
                    await _redis.delete(key)
            if cursor == 0:
                break
    except Exception:
        pass  # Non-critical — don't break password change

    await log_audit(db, user.tenant_id, "user", str(user.id), "password_change", "user", str(user.id))
    return {"status": "ok"}


@router.get("/operators")
async def list_operators(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(User).where(
            User.tenant_id == user.tenant_id,
            User.is_active.is_(True),
        )
    )
    return [
        {"id": str(u.id), "full_name": u.full_name, "role": u.role, "email": u.email}
        for u in result.scalars().all()
    ]


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Generate a password reset token. In DEBUG mode the token is returned in the response."""
    result = await db.execute(
        select(User).where(User.email == body.email, User.is_active.is_(True)).limit(1)
    )
    user = result.scalar_one_or_none()

    # Always return success to prevent email enumeration
    response = {"status": "ok", "message": "Если аккаунт существует, ссылка для сброса отправлена"}

    if not user:
        return response

    token = secrets.token_urlsafe(32)
    await _redis.setex(f"pwd_reset:{token}", 3600, str(user.id))  # 1 hour TTL
    logger.info("Password reset token generated for user %s", user.email)

    if settings.debug:
        response["reset_token"] = token  # Only in dev — for testing

    return response


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using a valid reset token."""
    user_id = await _redis.get(f"pwd_reset:{body.token}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Ссылка устарела или недействительна")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Пользователь не найден")

    user.password_hash = hash_password(body.new_password)
    await db.flush()

    # Delete the used token
    await _redis.delete(f"pwd_reset:{body.token}")

    return {"status": "ok", "message": "Пароль успешно изменён"}
