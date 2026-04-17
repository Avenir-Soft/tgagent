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

import redis.asyncio as aioredis

from src.core.config import settings

_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    access = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
    refresh = await create_refresh_token(str(user.id), str(user.tenant_id))
    return TokenResponse(access_token=access, refresh_token=refresh, user=UserOut.model_validate(user))


@router.post("/logout")
async def logout(
    credentials=Depends(bearer_scheme),
    user: User = Depends(get_current_user),
):
    """Blacklist the current JWT token."""
    await blacklist_token(credentials.credentials)
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
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Пароль минимум 8 символов")
    if body.new_password.isdigit() or body.new_password.isalpha():
        raise HTTPException(status_code=400, detail="Пароль должен содержать буквы и цифры")
    user.password_hash = hash_password(body.new_password)
    await db.flush()
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
    result = await db.execute(select(User).where(User.email == body.email))
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
