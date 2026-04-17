from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import require_super_admin
from src.auth.models import User
from src.auth.schemas import UserCreate
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.core.security import hash_password
from src.tenants.models import Tenant
from src.tenants.schemas import TenantCreate, TenantOut, TenantUpdate

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("/", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_tenant(
    request: Request,
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    tenant = Tenant(name=body.name, slug=body.slug)
    db.add(tenant)
    await db.flush()
    return TenantOut.model_validate(tenant)


@router.get("/", response_model=list[TenantOut])
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    return [TenantOut.model_validate(t) for t in result.scalars().all()]


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantOut.model_validate(tenant)


@router.patch("/{tenant_id}", response_model=TenantOut)
@limiter.limit("30/minute")
async def update_tenant(
    request: Request,
    tenant_id: UUID,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    await db.flush()
    return TenantOut.model_validate(tenant)


@router.post("/{tenant_id}/users", response_model=dict, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_tenant_user(
    request: Request,
    tenant_id: UUID,
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """Create a user within a tenant (managed onboarding)."""
    user = User(
        tenant_id=tenant_id,
        full_name=body.full_name,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()
    return {"id": str(user.id), "email": user.email}
