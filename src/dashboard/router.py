"""Dashboard API — thin HTTP handlers delegating to service layer."""

from uuid import UUID as _UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.conversations.models import Conversation
from src.conversations.schemas import BroadcastRequest
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.dashboard.service import (
    build_broadcast_query,
    cleanup_expired_drafts,
    get_abandoned_carts as svc_abandoned_carts,
    get_dashboard_stats,
    get_low_stock as svc_low_stock,
    send_broadcast_background,
    send_cart_recovery as svc_cart_recovery,
)
from src.core.audit import log_audit
from src.leads.models import Lead
from src.orders.models import Order

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_stats(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await get_dashboard_stats(user.tenant_id, days, db)


@router.get("/abandoned-carts")
async def get_abandoned_carts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await svc_abandoned_carts(user.tenant_id, db)


@router.post("/abandoned-carts/{conversation_id}/recover")
@limiter.limit("10/minute")
async def send_cart_recovery(
    request: Request,
    conversation_id: _UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return await svc_cart_recovery(user.tenant_id, conv, db)


@router.get("/low-stock")
async def get_low_stock(
    threshold: int = 5,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await svc_low_stock(user.tenant_id, threshold, db)


@router.get("/broadcast-estimate")
async def broadcast_estimate(
    filter: str = "all",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = build_broadcast_query(user.tenant_id, filter)
    count = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = {"count": count, "filter": filter}
    if count > 5000:
        result["max_sendable"] = 5000
        result["truncated"] = True
    return result


@router.get("/broadcast-recipients")
async def broadcast_recipients(
    filter: str = "all",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = build_broadcast_query(user.tenant_id, filter).order_by(
        Conversation.last_message_at.desc().nullslast()
    ).limit(5000)
    convs = (await db.execute(q)).scalars().all()

    conv_ids = [c.id for c in convs]
    lead_map: dict = {}
    if conv_ids:
        leads_result = await db.execute(
            select(Lead).where(Lead.conversation_id.in_(conv_ids), Lead.tenant_id == user.tenant_id)
        )
        for ld in leads_result.scalars().all():
            lead_map[ld.conversation_id] = ld

    order_counts: dict = {}
    lead_ids = [ld.id for ld in lead_map.values()]
    if lead_ids:
        oc_result = await db.execute(
            select(Order.lead_id, func.count(Order.id)).where(Order.lead_id.in_(lead_ids)).group_by(Order.lead_id)
        )
        for lid, cnt in oc_result.all():
            order_counts[lid] = cnt

    out = []
    for c in convs:
        lead = lead_map.get(c.id)
        name = c.telegram_first_name or (lead.customer_name if lead else None) or "—"
        orders = order_counts.get(lead.id, 0) if lead else 0
        out.append({
            "id": str(c.id),
            "name": name,
            "username": c.telegram_username,
            "telegram_chat_id": c.telegram_chat_id,
            "state": c.state,
            "orders": orders,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        })
    return out


@router.get("/broadcast-history")
async def get_broadcast_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from src.dashboard.models import BroadcastHistory
    result = await db.execute(
        select(BroadcastHistory)
        .where(BroadcastHistory.tenant_id == user.tenant_id)
        .order_by(BroadcastHistory.created_at.desc())
        .limit(50)
    )
    return [
        {
            "id": str(r.id),
            "message_text": r.message_text,
            "image_url": r.image_url,
            "filter_type": r.filter_type,
            "sent_count": r.sent_count,
            "failed_count": r.failed_count,
            "total_targets": r.total_targets,
            "status": r.status,
            "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "recipients": r.recipients_json or [],
        }
        for r in result.scalars().all()
    ]


@router.post("/broadcast")
@limiter.limit("30/hour")
async def send_broadcast(
    request: Request,
    body: BroadcastRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    from src.dashboard.models import BroadcastHistory

    if not body.text.strip():
        raise HTTPException(400, "text is required")
    if body.max_recipients > 5000:
        raise HTTPException(400, "max_recipients cannot exceed 5000")

    def _get_query():
        q = build_broadcast_query(user.tenant_id, body.filter)
        if body.conversation_ids:
            try:
                cids = [_UUID(cid) for cid in body.conversation_ids]
            except (ValueError, TypeError):
                raise HTTPException(400, "Invalid conversation_ids")
            q = q.where(Conversation.id.in_(cids))
        return q

    # Confirmation gate: if > 100 recipients and not confirmed, return warning
    if not body.confirmed and not body.scheduled_at:
        q_check = _get_query()
        recipient_count = (await db.execute(select(func.count()).select_from(q_check.subquery()))).scalar() or 0
        if recipient_count > 100:
            return {
                "status": "confirmation_required",
                "recipient_count": min(recipient_count, 5000),
                "message": f"Вы собираетесь отправить рассылку {min(recipient_count, 5000)} получателям. Подтвердите отправку.",
                "confirm_hint": "Повторите запрос с confirmed=true для отправки",
            }

    # Scheduled broadcast
    if body.scheduled_at:
        from dateutil.parser import isoparse
        try:
            sched_time = isoparse(body.scheduled_at)
        except (ValueError, TypeError):
            raise HTTPException(400, "Invalid scheduled_at format")

        q = _get_query()
        count = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0

        entry = BroadcastHistory(
            tenant_id=user.tenant_id,
            message_text=body.text,
            image_url=body.image_url,
            filter_type=body.filter,
            total_targets=count,
            status="scheduled",
            scheduled_at=sched_time,
            created_by_user_id=user.id,
            target_conversation_ids=body.conversation_ids,
        )
        db.add(entry)
        await db.flush()
        await log_audit(
            db, user.tenant_id, "user", str(user.id), "broadcast.create", "broadcast", str(entry.id),
            {"filter": body.filter, "total_targets": count, "scheduled_at": body.scheduled_at},
        )
        return {"status": "scheduled", "scheduled_at": body.scheduled_at, "total_targets": count, "id": str(entry.id)}

    # Immediate broadcast
    q = _get_query()
    result = await db.execute(q.limit(min(body.max_recipients, 5000)))
    convs = result.scalars().all()

    from src.telegram.service import telegram_manager
    client = telegram_manager.get_client(user.tenant_id)
    # If client not in memory (e.g. after --reload), try to start it
    if not client:
        from src.telegram.models import TelegramAccount
        acct_result = await db.execute(
            select(TelegramAccount).where(
                TelegramAccount.tenant_id == user.tenant_id,
                TelegramAccount.status == "connected",
            )
        )
        acct = acct_result.scalar_one_or_none()
        if acct:
            try:
                await telegram_manager.start_client(acct)
                client = telegram_manager.get_client(user.tenant_id)
            except Exception:
                pass
    if not client:
        raise HTTPException(503, "Telegram client not connected")
    # Auto-reconnect if disconnected or broken
    try:
        if not client.is_connected():
            raise ConnectionError("not connected")
        await client.get_me()
    except Exception:
        try:
            await client.disconnect()
        except Exception:
            pass
        try:
            await client.connect()
            await client.get_me()
        except Exception:
            raise HTTPException(503, "Telegram client disconnected — try reconnecting on Telegram page")

    entry = BroadcastHistory(
        tenant_id=user.tenant_id,
        message_text=body.text,
        image_url=body.image_url,
        filter_type=body.filter,
        total_targets=len(convs),
        status="sending",
        created_by_user_id=user.id,
    )
    db.add(entry)
    await db.commit()

    # Audit after commit since we committed
    try:
        from src.core.database import async_session_factory
        async with async_session_factory() as audit_db:
            await log_audit(
                audit_db, user.tenant_id, "user", str(user.id), "broadcast.create", "broadcast", str(entry.id),
                {"filter": body.filter, "total_targets": len(convs)},
            )
            await audit_db.commit()
    except Exception:
        pass

    conv_data = [
        {
            "id": str(conv.id),
            "chat_id": conv.telegram_chat_id,
            "first_name": conv.telegram_first_name,
            "username": conv.telegram_username,
        }
        for conv in convs
    ]

    background_tasks.add_task(
        send_broadcast_background,
        user.tenant_id, str(entry.id), body.text, body.image_url, conv_data,
    )

    resp = {"status": "sending", "total_targets": len(convs), "id": str(entry.id)}
    actual_count = (await db.execute(select(func.count()).select_from(_get_query().subquery()))).scalar() or 0
    if actual_count > len(convs):
        resp["truncated"] = True
        resp["total_audience"] = actual_count
    return resp


@router.delete("/broadcast-history/{broadcast_id}")
@limiter.limit("20/minute")
async def cancel_scheduled_broadcast(
    request: Request,
    broadcast_id: _UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    from src.dashboard.models import BroadcastHistory
    result = await db.execute(
        select(BroadcastHistory).where(
            BroadcastHistory.id == broadcast_id,
            BroadcastHistory.tenant_id == user.tenant_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Broadcast not found")
    if entry.status != "scheduled":
        raise HTTPException(400, "Can only cancel scheduled broadcasts")
    entry.status = "cancelled"
    await db.flush()
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "broadcast.cancel", "broadcast", str(broadcast_id),
    )
    return {"status": "cancelled"}


@router.post("/cleanup-drafts")
@limiter.limit("10/minute")
async def cleanup_drafts_endpoint(
    request: Request,
    user: User = Depends(require_store_owner),
):
    cancelled = await cleanup_expired_drafts(max_age_hours=2, tenant_id=user.tenant_id)
    return {"cancelled": cancelled}
