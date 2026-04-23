"""Super Admin Platform API — cross-tenant management endpoints."""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import require_super_admin
from src.auth.models import User
from src.conversations.models import Conversation, Message
from src.core.audit import AuditLog, log_audit
from src.core.database import escape_like, get_db
from src.core.rate_limit import limiter
from src.core.security import hash_password
from src.ai.models import AITraceLog
from src.orders.models import Order
from src.tenants.models import Tenant

from src.platform.schemas import (
    AITraceLogOut,
    AuditLogOut,
    BulkUserStatusRequest,
    DailyBillingItem,
    MessagesByDay,
    ModelDistributionItem,
    PlatformSettingsOut,
    PlatformSettingsUpdate,
    PlatformStats,
    PlatformUserCreate,
    PlatformUserListOut,
    PlatformUserOut,
    PlatformUserUpdate,
    TenantBilling,
)
from src.platform.settings_cache import (
    get_platform_settings as _get_cached_settings,
    invalidate_platform_settings_cache,
    _DEFAULTS as _DEFAULT_SETTINGS,
    _SETTINGS_FILE,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform", tags=["platform"])

# ── Platform settings (loaded from settings_cache.py) ────────────────────────


def _load_settings() -> dict:
    """Load platform settings from JSON file (or defaults)."""
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read platform settings, using defaults")
    return _DEFAULT_SETTINGS.copy()


def _save_settings(data: dict) -> None:
    """Persist platform settings to JSON file.

    Note: sync I/O is acceptable here — tiny JSON file, negligible blocking.
    """
    _SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# 1. GET /platform/stats — cross-tenant KPIs
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/stats", response_model=PlatformStats)
@limiter.limit("30/minute")
async def get_platform_stats(
    request: Request,
    period: str = Query("24h", description="Period filter: 24h, 7d, 30d"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """Cross-tenant KPIs for super admin dashboard."""
    now = datetime.now(timezone.utc)
    period_map = {"24h": 1, "7d": 7, "30d": 30}
    days = period_map.get(period, 1)
    day_ago = now - timedelta(days=days)
    week_ago = now - timedelta(days=7)

    # Run all counts sequentially (shared AsyncSession is not safe for gather)
    r0 = await db.execute(select(func.count(Tenant.id)))
    r1 = await db.execute(select(func.count(User.id)))
    r2 = await db.execute(select(func.count(Conversation.id)))
    r3 = await db.execute(select(func.count(Order.id)))
    r4 = await db.execute(select(func.count(Message.id)).where(Message.created_at >= day_ago))
    r5 = await db.execute(select(func.coalesce(func.sum(Order.total_amount), 0)))
    r6 = await db.execute(select(func.count(Order.id)).where(Order.created_at >= day_ago))
    r7 = await db.execute(select(func.coalesce(func.sum(Order.total_amount), 0)).where(Order.created_at >= day_ago))
    r8 = await db.execute(select(Tenant.status, func.count(Tenant.id)).group_by(Tenant.status))
    r9 = await db.execute(
        select(func.date_trunc("day", Message.created_at).label("day"), func.count(Message.id).label("cnt"))
        .where(Message.created_at >= week_ago).group_by(sa.text("1")).order_by(sa.text("1"))
    )
    r10 = await db.execute(
        select(func.date_trunc("day", Conversation.created_at).label("day"), func.count(Conversation.id).label("cnt"))
        .where(Conversation.created_at >= week_ago).group_by(sa.text("1")).order_by(sa.text("1"))
    )
    r11 = await db.execute(
        select(func.date_trunc("day", Order.created_at).label("day"), func.count(Order.id).label("cnt"))
        .where(Order.created_at >= week_ago).group_by(sa.text("1")).order_by(sa.text("1"))
    )

    # Parse tenants_by_status
    status_rows = r8.all()
    tenants_by_status = {row[0]: row[1] for row in status_rows}

    # Parse *_by_day — fill gaps for missing days
    def _parse_by_day(result):
        rows = result.all()
        day_map = {row.day.strftime("%Y-%m-%d"): row.cnt for row in rows}
        out = []
        for i in range(7):
            d = (now - timedelta(days=6 - i)).strftime("%Y-%m-%d")
            out.append(MessagesByDay(date=d, count=day_map.get(d, 0)))
        return out

    messages_by_day = _parse_by_day(r9)
    conversations_by_day = _parse_by_day(r10)
    orders_by_day = _parse_by_day(r11)

    return PlatformStats(
        total_tenants=r0.scalar_one(),
        total_users=r1.scalar_one(),
        total_conversations=r2.scalar_one(),
        total_orders=r3.scalar_one(),
        total_messages_24h=r4.scalar_one(),
        total_revenue=float(r5.scalar_one()),
        orders_24h=r6.scalar_one(),
        revenue_24h=float(r7.scalar_one()),
        tenants_by_status=tenants_by_status,
        conversations_by_day=conversations_by_day,
        orders_by_day=orders_by_day,
        messages_by_day=messages_by_day,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. GET /platform/users — list all users across tenants
# ══════════════════════════════════════════════════════════════════════════════


@router.patch("/users/bulk-status", response_model=dict)
@limiter.limit("10/minute")
async def bulk_update_user_status(
    request: Request,
    body: BulkUserStatusRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    """Bulk update user is_active status."""
    if not body.user_ids:
        raise HTTPException(status_code=400, detail="No user IDs provided")

    result = await db.execute(
        select(User).where(User.id.in_(body.user_ids))
    )
    users = result.scalars().all()

    updated = 0
    for user in users:
        user.is_active = body.is_active
        updated += 1
    await db.flush()
    await log_audit(
        db, admin.tenant_id, "user", str(admin.id), "platform.user_bulk_status", "user", None,
        {"user_ids": [str(uid) for uid in body.user_ids], "is_active": body.is_active, "updated": updated},
    )

    return {"updated": updated}


@router.get("/users", response_model=PlatformUserListOut)
@limiter.limit("30/minute")
async def list_platform_users(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query("", max_length=200),
    tenant_id: UUID | None = Query(None, description="Filter by tenant"),
    role: str | None = Query(None, description="Filter by role"),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """List all users across tenants with pagination, search, and filters."""
    from sqlalchemy import or_

    base = (
        select(User, Tenant.name.label("tenant_name"))
        .join(Tenant, User.tenant_id == Tenant.id)
    )
    count_q = (
        select(func.count(User.id))
        .join(Tenant, User.tenant_id == Tenant.id)
    )

    # Filters
    if tenant_id:
        base = base.where(User.tenant_id == tenant_id)
        count_q = count_q.where(User.tenant_id == tenant_id)
    if role:
        base = base.where(User.role == role)
        count_q = count_q.where(User.role == role)
    if search.strip():
        safe = escape_like(search.strip())
        search_filter = or_(
            User.email.ilike(f"%{safe}%"),
            User.full_name.ilike(f"%{safe}%"),
        )
        base = base.where(search_filter)
        count_q = count_q.where(search_filter)

    # Sorting
    sort_columns = {
        "email": User.email,
        "full_name": User.full_name,
        "role": User.role,
        "created_at": User.created_at,
    }
    sort_col = sort_columns.get(sort_by, User.created_at)
    if sort_order == "asc":
        base = base.order_by(sort_col.asc())
    else:
        base = base.order_by(sort_col.desc())

    # Execute paginated query + count (sequential — shared AsyncSession)
    total_result = await db.execute(count_q)
    page_result = await db.execute(base.limit(limit).offset(offset))
    total = total_result.scalar_one()
    rows = page_result.all()

    users = []
    for user, tenant_name in rows:
        out = PlatformUserOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            tenant_id=user.tenant_id,
            tenant_name=tenant_name,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=getattr(user, "last_login_at", None),
        )
        users.append(out)
    return PlatformUserListOut(items=users, total=total)


# ══════════════════════════════════════════════════════════════════════════════
# 3. POST /platform/users — create user for any tenant
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/users", response_model=PlatformUserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_platform_user(
    request: Request,
    body: PlatformUserCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    """Create a user for any tenant (super admin only)."""
    # Verify tenant exists
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == body.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Enforce max_users_per_tenant platform limit
    platform_cfg = _get_cached_settings()
    max_users = platform_cfg.get("max_users_per_tenant", 10)
    user_count_result = await db.execute(
        select(func.count(User.id)).where(User.tenant_id == body.tenant_id)
    )
    current_count = user_count_result.scalar_one()
    if current_count >= max_users:
        raise HTTPException(
            status_code=403,
            detail=f"Лимит пользователей для тенанта: {max_users}. Текущее количество: {current_count}.",
        )

    # Check email uniqueness within tenant
    existing = await db.execute(
        select(User.id).where(User.tenant_id == body.tenant_id, User.email == body.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User with this email already exists in this tenant")

    user = User(
        tenant_id=body.tenant_id,
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()
    await log_audit(
        db, body.tenant_id, "user", str(admin.id), "platform.user_create", "user", str(user.id),
        {"email": body.email, "role": body.role, "tenant_name": tenant.name},
    )

    return PlatformUserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        tenant_id=user.tenant_id,
        tenant_name=tenant.name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3b. PATCH /platform/users/{user_id} — edit user
# ══════════════════════════════════════════════════════════════════════════════


@router.patch("/users/{user_id}", response_model=PlatformUserOut)
@limiter.limit("30/minute")
async def update_platform_user(
    request: Request,
    user_id: UUID,
    body: PlatformUserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    """Edit user: email, name, role, password, active status."""
    from src.platform.schemas import PlatformUserUpdate as _PUU  # noqa: deferred

    result = await db.execute(
        select(User, Tenant.name.label("tenant_name"))
        .join(Tenant, User.tenant_id == Tenant.id)
        .where(User.id == user_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    user, tenant_name = row

    updates = body.model_dump(exclude_unset=True)
    if "new_password" in updates and updates["new_password"]:
        user.password_hash = hash_password(updates.pop("new_password"))
    else:
        updates.pop("new_password", None)

    for field, value in updates.items():
        setattr(user, field, value)
    await db.flush()
    await log_audit(
        db, user.tenant_id, "user", str(admin.id), "platform.user_update", "user", str(user_id),
        {"changed_fields": list(updates.keys()), "email": user.email},
    )

    return PlatformUserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        tenant_id=user.tenant_id,
        tenant_name=tenant_name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. GET /platform/ai-logs — AI trace logs across tenants
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/ai-logs", response_model=list[AITraceLogOut])
@limiter.limit("30/minute")
async def get_ai_logs(
    request: Request,
    tenant_id: UUID | None = Query(None, description="Filter by tenant"),
    period: str = Query("1h", description="Period: 1h, 6h, 24h, 7d, 30d"),
    date_from: str | None = Query(None, description="Start date YYYY-MM-DD"),
    date_to: str | None = Query(None, description="End date YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """AI trace logs across all tenants (recent first)."""
    stmt = (
        select(AITraceLog, Tenant.name.label("tenant_name"))
        .join(Tenant, AITraceLog.tenant_id == Tenant.id)
        .order_by(AITraceLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if tenant_id:
        stmt = stmt.where(AITraceLog.tenant_id == tenant_id)

    # Date filtering
    if date_from and date_to:
        dt_from = datetime.fromisoformat(date_from)
        dt_to = datetime.fromisoformat(date_to + "T23:59:59")
        stmt = stmt.where(AITraceLog.created_at >= dt_from, AITraceLog.created_at <= dt_to)
    else:
        period_hours = {"1h": 1, "6h": 6, "24h": 24, "7d": 168, "30d": 720}
        hours = period_hours.get(period, 1)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = stmt.where(AITraceLog.created_at >= cutoff)

    result = await db.execute(stmt)
    rows = result.all()

    logs = []
    for trace, tenant_name in rows:
        out = AITraceLogOut(
            id=trace.id,
            tenant_id=trace.tenant_id,
            tenant_name=tenant_name,
            conversation_id=trace.conversation_id,
            trace_id=trace.trace_id,
            user_message=trace.user_message,
            detected_language=trace.detected_language,
            model=trace.model,
            state_before=trace.state_before,
            state_after=trace.state_after,
            tools_called=trace.tools_called,
            total_duration_ms=trace.total_duration_ms,
            prompt_tokens=trace.prompt_tokens,
            completion_tokens=trace.completion_tokens,
            created_at=trace.created_at,
        )
        logs.append(out)
    return logs


# ══════════════════════════════════════════════════════════════════════════════
# 5. GET /platform/billing — usage metrics per tenant
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/billing", response_model=list[TenantBilling])
@limiter.limit("30/minute")
async def get_billing(
    request: Request,
    start_date: date | None = Query(None, description="Filter from date (inclusive)"),
    end_date: date | None = Query(None, description="Filter to date (inclusive)"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """Usage metrics per tenant for billing purposes."""
    # Get all tenants
    tenants_result = await db.execute(select(Tenant.id, Tenant.name).order_by(Tenant.name))
    tenants = tenants_result.all()

    if not tenants:
        return []

    # Build date filters
    date_filter_msg = []
    date_filter_ai = []
    date_filter_order = []
    date_filter_conv = []

    if start_date:
        start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        date_filter_msg.append(Message.created_at >= start_dt)
        date_filter_ai.append(AITraceLog.created_at >= start_dt)
        date_filter_order.append(Order.created_at >= start_dt)
        date_filter_conv.append(Conversation.created_at >= start_dt)
    if end_date:
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
        date_filter_msg.append(Message.created_at <= end_dt)
        date_filter_ai.append(AITraceLog.created_at <= end_dt)
        date_filter_order.append(Order.created_at <= end_dt)
        date_filter_conv.append(Conversation.created_at <= end_dt)

    # Build queries for all metrics
    msg_stmt = (
        select(Message.tenant_id, func.count(Message.id).label("cnt"))
        .where(*date_filter_msg)
        .group_by(Message.tenant_id)
    )
    ai_stmt = (
        select(AITraceLog.tenant_id, func.count(AITraceLog.id).label("cnt"))
        .where(*date_filter_ai)
        .group_by(AITraceLog.tenant_id)
    )
    order_stmt = (
        select(Order.tenant_id, func.count(Order.id).label("cnt"))
        .where(*date_filter_order)
        .group_by(Order.tenant_id)
    )
    conv_stmt = (
        select(Conversation.tenant_id, func.count(Conversation.id).label("cnt"))
        .where(*date_filter_conv)
        .group_by(Conversation.tenant_id)
    )
    # Token totals per tenant
    token_stmt = (
        select(
            AITraceLog.tenant_id,
            func.coalesce(func.sum(AITraceLog.prompt_tokens + AITraceLog.completion_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(AITraceLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AITraceLog.completion_tokens), 0).label("completion_tokens"),
        )
        .where(*date_filter_ai)
        .group_by(AITraceLog.tenant_id)
    )

    # Execute sequentially (shared AsyncSession is not safe for gather)
    msg_r = await db.execute(msg_stmt)
    ai_r = await db.execute(ai_stmt)
    order_r = await db.execute(order_stmt)
    conv_r = await db.execute(conv_stmt)
    token_r = await db.execute(token_stmt)

    # Build lookup dicts
    msg_map = {row.tenant_id: row.cnt for row in msg_r.all()}
    ai_map = {row.tenant_id: row.cnt for row in ai_r.all()}
    order_map = {row.tenant_id: row.cnt for row in order_r.all()}
    conv_map = {row.tenant_id: row.cnt for row in conv_r.all()}
    token_map: dict = {}
    for row in token_r.all():
        # Cost: $0.15/1M input + $0.60/1M output (gpt-4o-mini rates)
        prompt_cost = row.prompt_tokens * 0.00015 / 1000
        completion_cost = row.completion_tokens * 0.0006 / 1000
        token_map[row.tenant_id] = {
            "total": row.total_tokens,
            "cost": prompt_cost + completion_cost,
        }

    billing = []
    for tid, tname in tenants:
        t_info = token_map.get(tid, {"total": 0, "cost": 0.0})
        billing.append(TenantBilling(
            tenant_id=tid,
            tenant_name=tname,
            messages_count=msg_map.get(tid, 0),
            ai_calls_count=ai_map.get(tid, 0),
            orders_count=order_map.get(tid, 0),
            conversations_count=conv_map.get(tid, 0),
            tokens_total=t_info["total"],
            estimated_cost_usd=round(t_info["cost"], 6),
        ))
    return billing


# ══════════════════════════════════════════════════════════════════════════════
# 5b. GET /platform/billing/models — model distribution for period
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/billing/models", response_model=list[ModelDistributionItem])
@limiter.limit("30/minute")
async def get_billing_models(
    request: Request,
    start_date: date | None = Query(None, description="Filter from date (inclusive)"),
    end_date: date | None = Query(None, description="Filter to date (inclusive)"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """Model distribution: calls, tokens, cost per model."""
    date_filters = []
    if start_date:
        date_filters.append(AITraceLog.created_at >= datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc))
    if end_date:
        date_filters.append(AITraceLog.created_at <= datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc))

    stmt = (
        select(
            AITraceLog.model,
            func.count(AITraceLog.id).label("calls"),
            func.coalesce(func.sum(AITraceLog.prompt_tokens + AITraceLog.completion_tokens), 0).label("tokens"),
            func.coalesce(func.sum(AITraceLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AITraceLog.completion_tokens), 0).label("completion_tokens"),
        )
        .where(*date_filters)
        .where(AITraceLog.model != "")
        .group_by(AITraceLog.model)
        .order_by(func.count(AITraceLog.id).desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Cost rates (per 1M tokens): gpt-4o-mini: $0.15 in / $0.60 out; gpt-4o: $2.50 in / $10.00 out
    model_rates = {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
    }
    default_rate = (0.15, 0.60)

    items = []
    for row in rows:
        in_rate, out_rate = model_rates.get(row.model, default_rate)
        cost = (row.prompt_tokens * in_rate + row.completion_tokens * out_rate) / 1_000_000
        items.append(ModelDistributionItem(
            model=row.model,
            calls=row.calls,
            tokens=row.tokens,
            cost_usd=round(cost, 6),
        ))
    return items


# ══════════════════════════════════════════════════════════════════════════════
# 5c. GET /platform/billing/daily — daily aggregates for charts
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/billing/daily", response_model=list[DailyBillingItem])
@limiter.limit("30/minute")
async def get_billing_daily(
    request: Request,
    start_date: date | None = Query(None, description="Filter from date (inclusive)"),
    end_date: date | None = Query(None, description="Filter to date (inclusive)"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """Daily aggregates: AI calls, messages, tokens per day."""
    # Default to last 30 days if no dates given
    if not start_date:
        start_date = (datetime.now(timezone.utc) - timedelta(days=30)).date()
    if not end_date:
        end_date = datetime.now(timezone.utc).date()

    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)

    # AI calls + tokens by day
    ai_stmt = (
        select(
            func.date_trunc("day", AITraceLog.created_at).label("day"),
            func.count(AITraceLog.id).label("ai_calls"),
            func.coalesce(func.sum(AITraceLog.prompt_tokens + AITraceLog.completion_tokens), 0).label("tokens"),
        )
        .where(AITraceLog.created_at >= start_dt, AITraceLog.created_at <= end_dt)
        .group_by(sa.text("1"))
    )

    # Messages by day
    msg_stmt = (
        select(
            func.date_trunc("day", Message.created_at).label("day"),
            func.count(Message.id).label("messages"),
        )
        .where(Message.created_at >= start_dt, Message.created_at <= end_dt)
        .group_by(sa.text("1"))
    )

    ai_r = await db.execute(ai_stmt)
    msg_r = await db.execute(msg_stmt)

    ai_map: dict = {}
    for row in ai_r.all():
        d = row.day.strftime("%Y-%m-%d")
        ai_map[d] = {"ai_calls": row.ai_calls, "tokens": row.tokens}

    msg_map: dict = {}
    for row in msg_r.all():
        d = row.day.strftime("%Y-%m-%d")
        msg_map[d] = row.messages

    # Fill all days in range
    items = []
    current = start_date
    while current <= end_date:
        d_str = current.isoformat()
        ai_info = ai_map.get(d_str, {"ai_calls": 0, "tokens": 0})
        items.append(DailyBillingItem(
            date=d_str,
            ai_calls=ai_info["ai_calls"],
            messages=msg_map.get(d_str, 0),
            tokens=ai_info["tokens"],
        ))
        current += timedelta(days=1)

    return items


# ══════════════════════════════════════════════════════════════════════════════
# 6. GET /platform/audit-logs — from audit_logs table
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/audit-logs", response_model=list[AuditLogOut])
@limiter.limit("30/minute")
async def get_audit_logs(
    request: Request,
    tenant_id: UUID | None = Query(None, description="Filter by tenant"),
    actor_type: str | None = Query(None, description="Filter by actor_type (user/ai/system)"),
    action: str | None = Query(None, description="Filter by action"),
    period: str = Query("24h", description="Period: 1h, 24h, 7d, 30d"),
    date_from: str | None = Query(None, description="Start date YYYY-MM-DD"),
    date_to: str | None = Query(None, description="End date YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """Audit logs across all tenants (recent first)."""
    stmt = (
        select(AuditLog, Tenant.name.label("tenant_name"))
        .join(Tenant, AuditLog.tenant_id == Tenant.id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if tenant_id:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)

    # Date filtering
    if date_from and date_to:
        dt_from = datetime.fromisoformat(date_from)
        dt_to = datetime.fromisoformat(date_to + "T23:59:59")
        stmt = stmt.where(
            AuditLog.created_at >= dt_from,
            AuditLog.created_at <= dt_to,
        )
    else:
        period_hours = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}
        hours = period_hours.get(period, 24)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = stmt.where(AuditLog.created_at >= cutoff)

    result = await db.execute(stmt)
    rows = result.all()

    logs = []
    for log, tenant_name in rows:
        out = AuditLogOut(
            id=log.id,
            tenant_id=log.tenant_id,
            tenant_name=tenant_name,
            actor_type=log.actor_type,
            actor_id=log.actor_id,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            meta_json=log.meta_json,
            created_at=log.created_at,
        )
        logs.append(out)
    return logs


# ══════════════════════════════════════════════════════════════════════════════
# 7. GET/PUT /platform/settings — global platform settings
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/settings", response_model=PlatformSettingsOut)
@limiter.limit("30/minute")
async def get_platform_settings(
    request: Request,
    _: User = Depends(require_super_admin),
):
    """Get global platform settings."""
    data = _load_settings()
    return PlatformSettingsOut(**data)


@router.put("/settings", response_model=PlatformSettingsOut)
@limiter.limit("10/minute")
async def update_platform_settings(
    request: Request,
    body: PlatformSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    """Update global platform settings (partial update)."""
    current = _load_settings()
    updates = body.model_dump(exclude_unset=True)

    if not updates:
        return PlatformSettingsOut(**current)

    current.update(updates)
    _save_settings(current)
    invalidate_platform_settings_cache()

    await log_audit(
        db, admin.tenant_id, "user", str(admin.id), "platform.settings_update", "platform_settings", None,
        {"changes": updates},
    )

    return PlatformSettingsOut(**current)


# ══════════════════════════════════════════════════════════════════════════════
# 8. POST /tenants/{id}/impersonate — lives in src/tenants/router.py (single source)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# 9. GET /platform/health — system health for super admin dashboard
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/health")
@limiter.limit("30/minute")
async def platform_health(
    request: Request,
    _: User = Depends(require_super_admin),
):
    """System health check: DB, Redis, Telegram clients."""
    from src.core.database import engine
    from src.core.security import _redis
    from src.telegram.service import telegram_manager

    checks: dict[str, str] = {}

    # Database
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis
    try:
        await _redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Telegram clients
    try:
        clients = telegram_manager._clients
        connected = sum(1 for c in clients.values() if c.is_connected())
        total = len(clients)
        checks["telegram"] = f"ok: {connected}/{total}" if total > 0 else "no_clients"
    except Exception as e:
        checks["telegram"] = f"error: {e}"

    # Backend is always ok if we got here
    checks["backend"] = "ok"

    return {"checks": checks}
