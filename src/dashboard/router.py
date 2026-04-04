from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.catalog.models import Inventory, ProductVariant
from src.conversations.models import Conversation, Message
from src.conversations.schemas import BroadcastRequest
from src.core.database import async_session_factory, get_db
from src.core.rate_limit import limiter
from src.handoffs.models import Handoff
from src.leads.models import Lead
from src.orders.models import Order

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ── Draft order TTL cleanup ──────────────────────────────────────────────────

async def cleanup_expired_drafts(max_age_hours: int = 2) -> int:
    """Auto-cancel draft orders older than max_age_hours and unreserve inventory.
    Called on startup and can be called via POST /dashboard/cleanup-drafts.
    Returns count of cancelled orders.
    """
    import logging
    _logger = logging.getLogger(__name__)
    cancelled = 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    async with async_session_factory() as db:
        from src.orders.models import OrderItem
        from sqlalchemy.orm import selectinload
        result = await db.execute(
            select(Order)
            .where(Order.status == "draft", Order.created_at <= cutoff)
            .options(selectinload(Order.items))
        )
        stale_drafts = result.scalars().all()

        for order in stale_drafts:
            # Unreserve inventory
            for item in order.items:
                if not item.product_variant_id:
                    continue
                inv_result = await db.execute(
                    select(Inventory).where(
                        Inventory.tenant_id == order.tenant_id,
                        Inventory.variant_id == item.product_variant_id,
                    ).with_for_update()
                )
                inv = inv_result.scalar_one_or_none()
                if inv:
                    inv.reserved_quantity = max(0, inv.reserved_quantity - item.qty)

            order.status = "cancelled"
            cancelled += 1

        if cancelled:
            await db.commit()
            _logger.info("Cleaned up %d expired draft order(s)", cancelled)

    return cancelled


@router.get("/stats")
async def get_stats(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tid = user.tenant_id
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    conversations_count = (
        await db.execute(
            select(func.count()).select_from(Conversation).where(Conversation.tenant_id == tid)
        )
    ).scalar() or 0

    dm_count = (
        await db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.tenant_id == tid, Conversation.source_type == "dm")
        )
    ).scalar() or 0

    leads_count = (
        await db.execute(select(func.count()).select_from(Lead).where(Lead.tenant_id == tid))
    ).scalar() or 0

    orders_count = (
        await db.execute(select(func.count()).select_from(Order).where(Order.tenant_id == tid))
    ).scalar() or 0

    handoffs_count = (
        await db.execute(
            select(func.count())
            .select_from(Handoff)
            .where(Handoff.tenant_id == tid, Handoff.status == "pending")
        )
    ).scalar() or 0

    # Active conversations (last 30 min activity)
    active_cutoff = now - timedelta(minutes=30)
    active_conversations = (
        await db.execute(
            select(func.count()).select_from(Conversation)
            .where(
                Conversation.tenant_id == tid,
                Conversation.source_type == "dm",
                Conversation.status == "active",
                Conversation.last_message_at >= active_cutoff,
            )
        )
    ).scalar() or 0

    # Anomaly count (conversations with _anomalies in state_context, last 7 days)
    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import JSONB
    week_ago = now - timedelta(days=7)
    anomaly_count = (
        await db.execute(
            select(func.count()).select_from(Conversation)
            .where(
                Conversation.tenant_id == tid,
                Conversation.last_message_at >= week_ago,
                Conversation.state_context["_anomalies"].as_string() != "null",
            )
        )
    ).scalar() or 0

    # Abandoned carts (state=cart/checkout, no message in 2+ hours)
    two_hours_ago = now - timedelta(hours=2)
    abandoned_count = (
        await db.execute(
            select(func.count()).select_from(Conversation)
            .where(
                Conversation.tenant_id == tid,
                Conversation.state.in_(["cart", "checkout"]),
                Conversation.last_message_at <= two_hours_ago,
                Conversation.ai_enabled == True,  # noqa: E712
            )
        )
    ).scalar() or 0

    # Conversion: conversations → orders
    conv_with_orders = (
        await db.execute(
            select(func.count(func.distinct(Order.lead_id)))
            .select_from(Order)
            .join(Lead, Order.lead_id == Lead.id)
            .where(Order.tenant_id == tid)
        )
    ).scalar() or 0

    conversion_rate = round(min(100.0, conv_with_orders / dm_count * 100), 1) if dm_count else 0

    # Orders by status breakdown
    status_rows = (
        await db.execute(
            select(Order.status, func.count(), func.coalesce(func.sum(Order.total_amount), 0))
            .where(Order.tenant_id == tid)
            .group_by(Order.status)
        )
    ).all()
    orders_by_status = {row[0]: {"count": row[1], "revenue": float(row[2])} for row in status_rows}
    total_revenue = sum(v["revenue"] for v in orders_by_status.values())

    # Today stats
    today_orders_row = await db.execute(
        select(func.count(), func.coalesce(func.sum(Order.total_amount), 0))
        .where(Order.tenant_id == tid, Order.created_at >= today_start)
    )
    today_row = today_orders_row.one()
    today_orders = today_row[0]
    today_revenue = float(today_row[1])

    # Yesterday stats (for trend comparison)
    yesterday_orders_row = await db.execute(
        select(func.count(), func.coalesce(func.sum(Order.total_amount), 0))
        .where(Order.tenant_id == tid, Order.created_at >= yesterday_start, Order.created_at < today_start)
    )
    yesterday_row = yesterday_orders_row.one()
    yesterday_orders = yesterday_row[0]
    yesterday_revenue = float(yesterday_row[1])

    # Today messages
    today_messages = (
        await db.execute(
            select(func.count()).select_from(Message)
            .where(Message.tenant_id == tid, Message.created_at >= today_start)
        )
    ).scalar() or 0

    yesterday_messages = (
        await db.execute(
            select(func.count()).select_from(Message)
            .where(Message.tenant_id == tid, Message.created_at >= yesterday_start, Message.created_at < today_start)
        )
    ).scalar() or 0

    # Recent orders (last 5)
    recent_result = await db.execute(
        select(Order.order_number, Order.customer_name, Order.total_amount, Order.status, Order.created_at)
        .where(Order.tenant_id == tid)
        .order_by(Order.created_at.desc())
        .limit(5)
    )
    recent_orders = [
        {"order_number": r[0], "customer": r[1], "amount": float(r[2]), "status": r[3], "created_at": r[4].isoformat() if r[4] else None}
        for r in recent_result.all()
    ]

    # Orders daily (configurable period)
    from sqlalchemy import cast, Date
    period_days = min(max(days, 7), 90)
    period_start = now - timedelta(days=period_days)
    daily_result = await db.execute(
        select(cast(Order.created_at, Date).label("day"), func.count())
        .where(Order.tenant_id == tid, Order.created_at >= period_start)
        .group_by("day")
        .order_by("day")
    )
    orders_daily = [{"date": str(r[0]), "count": r[1]} for r in daily_result.all()]

    # Leads daily (same period as orders)
    leads_daily_result = await db.execute(
        select(cast(Lead.created_at, Date).label("day"), func.count())
        .where(Lead.tenant_id == tid, Lead.created_at >= period_start)
        .group_by("day")
        .order_by("day")
    )
    leads_daily = [{"date": str(r[0]), "count": r[1]} for r in leads_daily_result.all()]

    # Leads by status
    leads_rows = (
        await db.execute(
            select(Lead.status, func.count())
            .where(Lead.tenant_id == tid)
            .group_by(Lead.status)
        )
    ).all()
    leads_by_status = {row[0]: row[1] for row in leads_rows}

    return {
        "total_conversations": conversations_count,
        "dm_conversations": dm_count,
        "active_conversations": active_conversations,
        "total_leads": leads_count,
        "total_orders": orders_count,
        "pending_handoffs": handoffs_count,
        "anomaly_conversations_7d": anomaly_count,
        "abandoned_carts": abandoned_count,
        "conversion_rate_pct": conversion_rate,
        "total_revenue": total_revenue,
        "today_orders": today_orders,
        "today_revenue": today_revenue,
        "today_messages": today_messages,
        "yesterday_orders": yesterday_orders,
        "yesterday_revenue": yesterday_revenue,
        "yesterday_messages": yesterday_messages,
        "orders_by_status": orders_by_status,
        "leads_by_status": leads_by_status,
        "recent_orders": recent_orders,
        "orders_daily": orders_daily,
        "leads_daily": leads_daily,
    }


@router.get("/abandoned-carts")
async def get_abandoned_carts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Conversations stuck in cart/checkout state for 2+ hours."""
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.tenant_id == user.tenant_id,
            Conversation.state.in_(["cart", "checkout"]),
            Conversation.last_message_at < two_hours_ago,
        )
        .order_by(Conversation.last_message_at.desc())
        .limit(50)
    )
    convs = result.scalars().all()
    out = []
    for c in convs:
        ctx = c.state_context or {}
        cart = ctx.get("cart", [])
        hours_ago = round((datetime.now(timezone.utc) - c.last_message_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600, 1) if c.last_message_at else None
        out.append({
            "id": str(c.id),
            "customer": c.telegram_first_name or f"#{c.telegram_user_id}",
            "username": c.telegram_username,
            "state": c.state,
            "cart_items": [{"title": i.get("title", "?"), "qty": i.get("qty", 1)} for i in cart],
            "cart_total": sum(float(i.get("price", 0)) * i.get("qty", 1) for i in cart),
            "hours_idle": hours_ago,
            "telegram_chat_id": c.telegram_chat_id,
        })
    return out


@router.post("/abandoned-carts/{conversation_id}/recover")
async def send_cart_recovery(
    conversation_id,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Send a cart recovery reminder to the customer via Telegram."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        from fastapi import HTTPException
        raise HTTPException(404, "Conversation not found")

    ctx = conv.state_context or {}
    cart = ctx.get("cart", [])
    cart_str = ", ".join(f"{i.get('title','?')}" + (f" ×{i.get('qty')}" if i.get("qty",1) > 1 else "") for i in cart)
    total = sum(float(i.get("price", 0)) * i.get("qty", 1) for i in cart)

    from src.ai.truth_tools import ORDER_STATUS_LABELS
    lang = ctx.get("language", "ru")
    if lang in ("uz_latin",):
        text = f"Salom! Savatchangizda: {cart_str}. Jami: {int(total):,} so'm. Buyurtma berishni xohlaysizmi? 😊"
    elif lang in ("uz_cyrillic",):
        text = f"Салом! Саватчангизда: {cart_str}. Жами: {int(total):,} сўм. Буюртма беришни хоҳлайсизми? 😊"
    else:
        text = f"Привет! В вашей корзине: {cart_str}. Итого: {int(total):,} сум. Хотите оформить заказ? 😊"

    try:
        from src.telegram.service import telegram_manager
        client = telegram_manager.get_client(user.tenant_id)
        if client:
            # Resolve entity — after restart Telethon may not have the peer cached
            try:
                entity = await client.get_input_entity(conv.telegram_chat_id)
            except ValueError:
                if conv.telegram_username:
                    entity = await client.get_input_entity(conv.telegram_username)
                else:
                    raise
            sent = await client.send_message(entity, text)
            from datetime import datetime as _dt2, timezone as _tz2
            msg = Message(
                tenant_id=user.tenant_id,
                conversation_id=conv.id,
                telegram_message_id=sent.id if sent else None,
                direction="outbound",
                sender_type="human_admin",
                raw_text=text,
                ai_generated=False,
            )
            db.add(msg)
            conv.last_message_at = _dt2.now(_tz2.utc)
            await db.flush()
            return {"sent": True, "text": text}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Cart recovery send failed: %s", e)

    return {"sent": False}


@router.get("/low-stock")
async def get_low_stock(
    threshold: int = 5,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Variants with available stock below threshold."""
    result = await db.execute(
        select(Inventory, ProductVariant)
        .join(ProductVariant, Inventory.variant_id == ProductVariant.id)
        .where(
            Inventory.tenant_id == user.tenant_id,
            ProductVariant.is_active == True,  # noqa: E712
            (Inventory.quantity - Inventory.reserved_quantity) < threshold,
        )
        .order_by((Inventory.quantity - Inventory.reserved_quantity).asc())
        .limit(30)
    )
    rows = result.all()
    out = []
    for inv, variant in rows:
        out.append({
            "variant_id": str(variant.id),
            "product_id": str(variant.product_id),
            "title": variant.title,
            "available": inv.quantity - inv.reserved_quantity,
            "reserved": inv.reserved_quantity,
            "total": inv.quantity,
        })
    return out


def _build_broadcast_query(tenant_id, filter_type: str):
    """Build query for broadcast target conversations."""
    q = select(Conversation).where(
        Conversation.tenant_id == tenant_id,
        Conversation.source_type == "dm",
        Conversation.status != "closed",
    )
    if filter_type == "ordered":
        from sqlalchemy import exists
        q = q.where(
            exists(
                select(Lead.id).where(
                    Lead.conversation_id == Conversation.id,
                    Lead.tenant_id == tenant_id,
                ).join(Order, Order.lead_id == Lead.id)
            )
        )
    return q


@router.get("/broadcast-estimate")
async def broadcast_estimate(
    filter: str = "all",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Estimate audience size before sending a broadcast."""
    q = _build_broadcast_query(user.tenant_id, filter)
    count = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    return {"count": count, "filter": filter}


@router.get("/broadcast-recipients")
async def broadcast_recipients(
    filter: str = "all",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all potential broadcast recipients with details."""
    q = _build_broadcast_query(user.tenant_id, filter).order_by(Conversation.last_message_at.desc().nullslast()).limit(5000)
    convs = (await db.execute(q)).scalars().all()

    # Gather lead info (names, phones) for enrichment
    conv_ids = [c.id for c in convs]
    lead_map: dict = {}
    if conv_ids:
        leads_result = await db.execute(
            select(Lead).where(Lead.conversation_id.in_(conv_ids), Lead.tenant_id == user.tenant_id)
        )
        for ld in leads_result.scalars().all():
            lead_map[ld.conversation_id] = ld

    # Count orders per lead
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
        username = c.telegram_username
        orders = order_counts.get(lead.id, 0) if lead else 0
        out.append({
            "id": str(c.id),
            "name": name,
            "username": username,
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
    """Get past broadcasts with results."""
    from src.dashboard.models import BroadcastHistory
    result = await db.execute(
        select(BroadcastHistory)
        .where(BroadcastHistory.tenant_id == user.tenant_id)
        .order_by(BroadcastHistory.created_at.desc())
        .limit(50)
    )
    rows = result.scalars().all()
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
        for r in rows
    ]


@router.post("/broadcast")
@limiter.limit("30/hour")
async def send_broadcast(
    request: Request,
    body: BroadcastRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Send or schedule a broadcast message to customers."""
    from fastapi import HTTPException
    from src.dashboard.models import BroadcastHistory

    if not body.text.strip():
        raise HTTPException(400, "text is required")

    # Build base query, optionally filtered by conversation_ids
    def _get_query():
        q = _build_broadcast_query(user.tenant_id, body.filter)
        if body.conversation_ids:
            from uuid import UUID as _UUID
            try:
                cids = [_UUID(cid) for cid in body.conversation_ids]
            except (ValueError, TypeError):
                raise HTTPException(400, "Invalid conversation_ids")
            q = q.where(Conversation.id.in_(cids))
        return q

    # Handle scheduled broadcast
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
        return {"status": "scheduled", "scheduled_at": body.scheduled_at, "total_targets": count, "id": str(entry.id)}

    # Immediate broadcast
    q = _get_query()
    result = await db.execute(q.limit(min(body.max_recipients, 5000)))
    convs = result.scalars().all()

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
    await db.flush()

    sent_count = 0
    failed_count = 0
    recipients_log: list[dict] = []
    try:
        from src.telegram.service import telegram_manager
        client = telegram_manager.get_client(user.tenant_id)
        if not client:
            raise HTTPException(503, "Telegram client not connected")

        for conv in convs:
            r_info = {
                "name": conv.telegram_first_name or "—",
                "username": conv.telegram_username,
                "conversation_id": str(conv.id),
            }
            try:
                # Resolve entity first — after restart Telethon may not have the peer cached
                try:
                    entity = await client.get_input_entity(conv.telegram_chat_id)
                except ValueError:
                    # Fallback: try resolving by username
                    if conv.telegram_username:
                        entity = await client.get_input_entity(conv.telegram_username)
                    else:
                        raise

                if body.image_url:
                    await client.send_file(
                        entity,
                        file=body.image_url,
                        caption=body.text,
                        force_document=False,
                    )
                else:
                    await client.send_message(entity, body.text)
                msg = Message(
                    tenant_id=user.tenant_id,
                    conversation_id=conv.id,
                    direction="outbound",
                    sender_type="human_admin",
                    raw_text=body.text,
                    ai_generated=False,
                )
                db.add(msg)
                conv.last_message_at = datetime.now(timezone.utc)
                sent_count += 1
                r_info["sent"] = True
                import asyncio
                await asyncio.sleep(0.3)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Broadcast failed for chat %s: %s", conv.telegram_chat_id, e)
                failed_count += 1
                r_info["sent"] = False
            recipients_log.append(r_info)

        entry.sent_count = sent_count
        entry.failed_count = failed_count
        entry.status = "sent"
        entry.sent_at = datetime.now(timezone.utc)
        entry.recipients_json = recipients_log
        await db.flush()
    except HTTPException:
        raise
    except Exception as e:
        entry.status = "failed"
        await db.flush()
        raise HTTPException(500, f"Broadcast error: {e}")

    return {"sent": sent_count, "failed": failed_count, "total_targets": len(convs)}


@router.delete("/broadcast-history/{broadcast_id}")
async def cancel_scheduled_broadcast(
    broadcast_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Cancel a scheduled broadcast."""
    from fastapi import HTTPException
    from src.dashboard.models import BroadcastHistory
    from uuid import UUID as _UUID
    result = await db.execute(
        select(BroadcastHistory).where(
            BroadcastHistory.id == _UUID(broadcast_id),
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
    return {"status": "cancelled"}


@router.post("/cleanup-drafts")
async def cleanup_drafts_endpoint(
    user: User = Depends(require_store_owner),
):
    """Manually trigger cleanup of expired draft orders (>2h old)."""
    cancelled = await cleanup_expired_drafts(max_age_hours=2)
    return {"cancelled": cancelled}
