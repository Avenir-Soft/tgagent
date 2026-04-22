import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import require_super_admin
from src.auth.models import User
from src.auth.schemas import UserCreate
from src.core.audit import AuditLog, log_audit
from src.core.database import escape_like, get_db
from src.core.rate_limit import limiter
from src.core.security import create_access_token, hash_password
from src.tenants.models import Tenant
from src.tenants.schemas import BulkStatusRequest, TenantCreate, TenantListOut, TenantOut, TenantUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["tenants"])

# Allowed sort columns for tenants list
_TENANT_SORT_COLUMNS = {
    "name": Tenant.name,
    "slug": Tenant.slug,
    "created_at": Tenant.created_at,
    "status": Tenant.status,
}


@router.post("/", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_tenant(
    request: Request,
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    # Use platform defaults for language/timezone when creating new tenants
    from src.platform.settings_cache import get_platform_settings
    platform_cfg = get_platform_settings()
    # signup_enabled: placeholder for future self-service registration gate
    # When self-service signup exists, check: if not platform_cfg.get("signup_enabled"): raise 403
    # trial_days: stored in platform settings, enforcement (auto-suspend) is a TODO

    tenant = Tenant(name=body.name, slug=body.slug)
    db.add(tenant)
    await db.flush()

    # Auto-create default AI settings with platform defaults
    from src.ai.models import AiSettings
    existing_ai = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == tenant.id)
    )
    if not existing_ai.scalar_one_or_none():
        default_lang = platform_cfg.get("default_language", "ru")
        ai_settings = AiSettings(
            tenant_id=tenant.id,
            language=default_lang,
        )
        db.add(ai_settings)
        await db.flush()

    await log_audit(
        db, tenant.id, "user", str(admin.id), "tenant.create", "tenant", str(tenant.id),
        {"name": body.name, "slug": body.slug},
    )
    return TenantOut.model_validate(tenant)


@router.patch("/bulk-status", response_model=dict)
@limiter.limit("10/minute")
async def bulk_update_tenant_status(
    request: Request,
    body: BulkStatusRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """Bulk update tenant status (active/suspended)."""
    if not body.tenant_ids:
        raise HTTPException(status_code=400, detail="No tenant IDs provided")

    result = await db.execute(
        select(Tenant).where(Tenant.id.in_(body.tenant_ids))
    )
    tenants = result.scalars().all()

    updated = 0
    for tenant in tenants:
        tenant.status = body.status
        updated += 1
    await db.flush()

    return {"updated": updated}


@router.get("/", response_model=TenantListOut)
async def list_tenants(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query("", max_length=200),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    from src.catalog.models import Product
    from src.conversations.models import Conversation

    # Base query with optional search
    base = select(Tenant)
    count_q = select(func.count(Tenant.id))

    if search.strip():
        safe = escape_like(search.strip())
        search_filter = or_(
            Tenant.name.ilike(f"%{safe}%"),
            Tenant.slug.ilike(f"%{safe}%"),
        )
        base = base.where(search_filter)
        count_q = count_q.where(search_filter)

    # Sorting
    sort_col = _TENANT_SORT_COLUMNS.get(sort_by, Tenant.created_at)
    if sort_order == "asc":
        base = base.order_by(sort_col.asc())
    else:
        base = base.order_by(sort_col.desc())

    # Execute paginated query + total count (sequential — shared AsyncSession)
    total_result = await db.execute(count_q)
    page_result = await db.execute(base.limit(limit).offset(offset))
    total = total_result.scalar_one()
    tenants = page_result.scalars().all()

    if not tenants:
        return TenantListOut(items=[], total=total)

    tenant_ids = [t.id for t in tenants]

    # Batch counts only for the returned page (sequential — shared AsyncSession)
    products_q = await db.execute(
        select(Product.tenant_id, func.count(Product.id))
        .where(Product.tenant_id.in_(tenant_ids))
        .group_by(Product.tenant_id)
    )
    convos_q = await db.execute(
        select(Conversation.tenant_id, func.count(Conversation.id))
        .where(Conversation.tenant_id.in_(tenant_ids))
        .group_by(Conversation.tenant_id)
    )
    users_q = await db.execute(
        select(User.tenant_id, func.count(User.id))
        .where(User.tenant_id.in_(tenant_ids))
        .group_by(User.tenant_id)
    )

    prod_map = dict(products_q.all())
    conv_map = dict(convos_q.all())
    user_map = dict(users_q.all())

    out = []
    for t in tenants:
        data = TenantOut.model_validate(t)
        data.products_count = prod_map.get(t.id, 0)
        data.conversations_count = conv_map.get(t.id, 0)
        data.users_count = user_map.get(t.id, 0)
        out.append(data)
    return TenantListOut(items=out, total=total)


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    from src.catalog.models import Product, ProductVariant
    from src.conversations.models import Conversation
    from src.orders.models import Order

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Batch counts for this tenant (sequential — shared AsyncSession)
    products_q = await db.execute(
        select(func.count(Product.id)).where(Product.tenant_id == tenant_id)
    )
    variants_q = await db.execute(
        select(func.count(ProductVariant.id)).where(ProductVariant.tenant_id == tenant_id)
    )
    convos_q = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.tenant_id == tenant_id)
    )
    users_q = await db.execute(
        select(func.count(User.id)).where(User.tenant_id == tenant_id)
    )
    orders_q = await db.execute(
        select(func.count(Order.id)).where(Order.tenant_id == tenant_id)
    )
    revenue_q = await db.execute(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(Order.tenant_id == tenant_id)
    )

    data = TenantOut.model_validate(tenant)
    data.products_count = products_q.scalar_one()
    data.variants_count = variants_q.scalar_one()
    data.conversations_count = convos_q.scalar_one()
    data.users_count = users_q.scalar_one()
    data.orders_count = orders_q.scalar_one()
    data.revenue_total = float(revenue_q.scalar_one())

    # Telegram agent info
    from src.telegram.models import TelegramAccount
    tg_result = await db.execute(
        select(TelegramAccount).where(TelegramAccount.tenant_id == tenant_id).limit(1)
    )
    tg = tg_result.scalar_one_or_none()
    if tg:
        data.telegram_phone = tg.phone_number
        data.telegram_username = tg.username
        data.telegram_display_name = tg.display_name
        data.telegram_status = tg.status

    # AI config
    from src.ai.models import AiSettings
    ai_result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == tenant_id).limit(1)
    )
    ai = ai_result.scalar_one_or_none()
    if ai:
        data.ai_provider = getattr(ai, "ai_provider", "openai")
        data.ai_model = getattr(ai, "ai_model_override", None) or "gpt-4o-mini"
        data.ai_language = ai.language
        data.ai_tone = ai.tone

    # Activity chart — messages per day for 30 days
    from src.conversations.models import Message
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)
    activity_result = await db.execute(
        sa.text(
            "SELECT (created_at AT TIME ZONE 'UTC')::date AS day, COUNT(*) AS cnt "
            "FROM messages WHERE tenant_id = :tid AND created_at >= :since "
            "GROUP BY 1 ORDER BY 1"
        ),
        {"tid": str(tenant_id), "since": month_ago},
    )
    activity_rows = activity_result.all()
    activity_map = {str(row.day): row.cnt for row in activity_rows}
    activity_30d = []
    for i in range(30):
        d = (now - timedelta(days=29 - i)).strftime("%Y-%m-%d")
        activity_30d.append({"date": d, "count": activity_map.get(d, 0)})
    data.activity_30d = activity_30d

    # Monitoring stats (sequential — shared AsyncSession)
    msg_count_result = await db.execute(
        select(func.count(Message.id)).where(Message.tenant_id == tenant_id)
    )
    last_msg_result = await db.execute(
        select(func.max(Message.created_at)).where(Message.tenant_id == tenant_id)
    )
    data.total_messages = msg_count_result.scalar_one()
    last_msg = last_msg_result.scalar_one()
    data.last_message_at = last_msg.isoformat() if last_msg else None
    data.tenant_created_days_ago = (now - tenant.created_at.replace(tzinfo=timezone.utc)).days

    return data


@router.patch("/{tenant_id}", response_model=TenantOut)
@limiter.limit("30/minute")
async def update_tenant(
    request: Request,
    tenant_id: UUID,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    changed_fields = body.model_dump(exclude_unset=True)
    for field, value in changed_fields.items():
        setattr(tenant, field, value)
    await db.flush()
    await log_audit(
        db, tenant_id, "user", str(admin.id), "tenant.update", "tenant", str(tenant_id),
        {"changed_fields": list(changed_fields.keys())},
    )
    return TenantOut.model_validate(tenant)


@router.post("/{tenant_id}/users", response_model=dict, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_tenant_user(
    request: Request,
    tenant_id: UUID,
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    """Create a user within a tenant (managed onboarding)."""
    # Enforce max_users_per_tenant platform limit
    from src.platform.settings_cache import get_platform_settings
    platform_cfg = get_platform_settings()
    max_users = platform_cfg.get("max_users_per_tenant", 10)
    user_count_result = await db.execute(
        select(func.count(User.id)).where(User.tenant_id == tenant_id)
    )
    current_count = user_count_result.scalar_one()
    if current_count >= max_users:
        raise HTTPException(
            status_code=403,
            detail=f"Лимит пользователей для тенанта: {max_users}. Текущее количество: {current_count}.",
        )

    user = User(
        tenant_id=tenant_id,
        full_name=body.full_name,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()
    await log_audit(
        db, tenant_id, "user", str(admin.id), "tenant.user_create", "user", str(user.id),
        {"email": body.email, "role": body.role},
    )
    return {"id": str(user.id), "email": user.email}


@router.post("/{tenant_id}/impersonate", response_model=dict)
@limiter.limit("10/minute")
async def impersonate_tenant(
    request: Request,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    """Impersonate a tenant by creating a short-lived JWT as the tenant's store_owner.

    Creates a 30-minute token with impersonated_by claim for audit trail.
    Returns: {access_token, tenant_name, user_email}
    """
    # Verify tenant exists
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Find first store_owner in the target tenant
    user_result = await db.execute(
        select(User)
        .where(User.tenant_id == tenant_id, User.role == "store_owner", User.is_active.is_(True))
        .order_by(User.created_at.asc())
        .limit(1)
    )
    target_user = user_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(
            status_code=404,
            detail="No active store_owner found in this tenant",
        )

    # Create short-lived JWT (30 min) with impersonation claims
    token = create_access_token(
        data={
            "sub": str(target_user.id),
            "tenant_id": str(tenant_id),
            "impersonated_by": str(admin.id),
        },
        expires_delta=timedelta(minutes=30),
    )

    # Log impersonation in audit_logs
    audit = AuditLog(
        tenant_id=tenant_id,
        actor_type="user",
        actor_id=str(admin.id),
        action="impersonate",
        entity_type="user",
        entity_id=str(target_user.id),
        meta_json={
            "admin_email": admin.email,
            "target_user_email": target_user.email,
            "target_tenant": tenant.name,
        },
    )
    db.add(audit)
    await db.flush()

    logger.info(
        "Super admin %s impersonated tenant %s (user %s)",
        admin.email, tenant.name, target_user.email,
    )

    return {
        "access_token": token,
        "tenant_name": tenant.name,
        "user_email": target_user.email,
    }
