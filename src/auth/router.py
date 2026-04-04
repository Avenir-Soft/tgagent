from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.auth.schemas import LoginRequest, PasswordChangeRequest, TokenResponse, UserCreate, UserOut
from src.core.database import get_db
from src.core.security import blacklist_token, create_access_token, hash_password, verify_password
from src.auth.deps import bearer_scheme, get_current_user, require_super_admin
from src.core.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    token = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout")
async def logout(
    credentials=Depends(bearer_scheme),
    user: User = Depends(get_current_user),
):
    """Blacklist the current JWT token."""
    blacklist_token(credentials.credentials)
    return {"status": "logged_out"}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/change-password")
async def change_password(
    body: PasswordChangeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="Пароль минимум 4 символа")
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
