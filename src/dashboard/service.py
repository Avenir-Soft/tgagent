"""Dashboard service layer — stats, broadcast, cart recovery, draft cleanup.

Heavy aggregation queries and background tasks extracted from router.
"""

import asyncio
import json
import logging
import uuid as _uuid_mod
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Date, cast, func, select, text as _sql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.catalog.models import Inventory, ProductVariant
from src.conversations.models import Conversation, Message
from src.core.database import async_session_factory
from src.dashboard.models import BroadcastHistory
from src.handoffs.models import Handoff
from src.leads.models import Lead
from src.orders.models import Order

logger = logging.getLogger(__name__)


# ── Draft cleanup ────────────────────────────────────────────────────────────


async def cleanup_expired_drafts(max_age_hours: int = 2, tenant_id: UUID | None = None) -> int:
    """Auto-cancel draft orders older than max_age_hours and unreserve inventory.

    If tenant_id is provided, only clean up drafts for that tenant.
    If None (startup/scheduled), clean up across all tenants.
    """
    cancelled = 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    async with async_session_factory() as db:
        from src.orders.models import OrderItem
        q = select(Order).where(Order.status == "draft", Order.created_at <= cutoff)
        if tenant_id:
            q = q.where(Order.tenant_id == tenant_id)
        result = await db.execute(
            q.options(selectinload(Order.items))
        )
        stale_drafts = result.scalars().all()

        for order in stale_drafts:
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
            logger.info("Cleaned up %d expired draft order(s)", cancelled)

    return cancelled


# ── Stats ────────────────────────────────────────────────────────────────────


async def get_dashboard_stats(tenant_id: UUID, days: int, db: AsyncSession) -> dict:
    """Aggregate all dashboard KPIs in a single call."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    tid = tenant_id

    # Core counts
    conversations_count = (await db.execute(
        select(func.count()).select_from(Conversation).where(Conversation.tenant_id == tid)
    )).scalar() or 0

    dm_count = (await db.execute(
        select(func.count()).select_from(Conversation)
        .where(Conversation.tenant_id == tid, Conversation.source_type == "dm")
    )).scalar() or 0

    leads_count = (await db.execute(
        select(func.count()).select_from(Lead).where(Lead.tenant_id == tid)
    )).scalar() or 0

    orders_count = (await db.execute(
        select(func.count()).select_from(Order).where(Order.tenant_id == tid)
    )).scalar() or 0

    handoffs_count = (await db.execute(
        select(func.count()).select_from(Handoff)
        .where(Handoff.tenant_id == tid, Handoff.status == "pending")
    )).scalar() or 0

    # Active conversations (last 30 min)
    active_cutoff = now - timedelta(minutes=30)
    active_conversations = (await db.execute(
        select(func.count()).select_from(Conversation)
        .where(
            Conversation.tenant_id == tid, Conversation.source_type == "dm",
            Conversation.status == "active", Conversation.last_message_at >= active_cutoff,
        )
    )).scalar() or 0

    # Anomaly count (7 days)
    week_ago = now - timedelta(days=7)
    anomaly_count = (await db.execute(
        select(func.count()).select_from(Conversation)
        .where(
            Conversation.tenant_id == tid,
            Conversation.last_message_at >= week_ago,
            Conversation.state_context["_anomalies"].as_string() != "null",
        )
    )).scalar() or 0

    # Abandoned carts
    two_hours_ago = now - timedelta(hours=2)
    abandoned_count = (await db.execute(
        select(func.count()).select_from(Conversation)
        .where(
            Conversation.tenant_id == tid,
            Conversation.state.in_(["cart", "checkout"]),
            Conversation.last_message_at <= two_hours_ago,
            Conversation.ai_enabled == True,  # noqa: E712
        )
    )).scalar() or 0

    # Conversion rate
    conv_with_orders = (await db.execute(
        select(func.count(func.distinct(Order.lead_id)))
        .select_from(Order).join(Lead, Order.lead_id == Lead.id)
        .where(Order.tenant_id == tid)
    )).scalar() or 0
    conversion_rate = round(min(100.0, conv_with_orders / dm_count * 100), 1) if dm_count else 0

    # Orders by status + revenue
    status_rows = (await db.execute(
        select(Order.status, func.count(), func.coalesce(func.sum(Order.total_amount), 0))
        .where(Order.tenant_id == tid).group_by(Order.status)
    )).all()
    orders_by_status = {row[0]: {"count": row[1], "revenue": float(row[2])} for row in status_rows}
    active_statuses = {"confirmed", "processing", "shipped", "delivered"}
    total_revenue = sum(v["revenue"] for k, v in orders_by_status.items() if k in active_statuses)

    # Today / yesterday stats
    today_row = (await db.execute(
        select(func.count(), func.coalesce(func.sum(Order.total_amount), 0))
        .where(Order.tenant_id == tid, Order.created_at >= today_start, Order.status.notin_(["cancelled", "draft"]))
    )).one()
    yesterday_row = (await db.execute(
        select(func.count(), func.coalesce(func.sum(Order.total_amount), 0))
        .where(Order.tenant_id == tid, Order.created_at >= yesterday_start, Order.created_at < today_start, Order.status.notin_(["cancelled", "draft"]))
    )).one()

    today_messages = (await db.execute(
        select(func.count()).select_from(Message).where(Message.tenant_id == tid, Message.created_at >= today_start)
    )).scalar() or 0
    yesterday_messages = (await db.execute(
        select(func.count()).select_from(Message).where(Message.tenant_id == tid, Message.created_at >= yesterday_start, Message.created_at < today_start)
    )).scalar() or 0

    # Recent orders
    recent_result = await db.execute(
        select(Order.order_number, Order.customer_name, Order.total_amount, Order.status, Order.created_at)
        .where(Order.tenant_id == tid).order_by(Order.created_at.desc()).limit(5)
    )
    recent_orders = [
        {"order_number": r[0], "customer": r[1], "amount": float(r[2]), "status": r[3], "created_at": r[4].isoformat() if r[4] else None}
        for r in recent_result.all()
    ]

    # Daily time series
    period_days = min(max(days, 7), 90)
    period_start = now - timedelta(days=period_days)

    daily_result = await db.execute(
        select(cast(Order.created_at, Date).label("day"), func.count())
        .where(Order.tenant_id == tid, Order.created_at >= period_start)
        .group_by("day").order_by("day")
    )
    orders_daily = [{"date": str(r[0]), "count": r[1]} for r in daily_result.all()]

    leads_daily_result = await db.execute(
        select(cast(Lead.created_at, Date).label("day"), func.count())
        .where(Lead.tenant_id == tid, Lead.created_at >= period_start)
        .group_by("day").order_by("day")
    )
    leads_daily = [{"date": str(r[0]), "count": r[1]} for r in leads_daily_result.all()]

    # Leads by status
    leads_rows = (await db.execute(
        select(Lead.status, func.count()).where(Lead.tenant_id == tid).group_by(Lead.status)
    )).all()
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
        "today_orders": today_row[0],
        "today_revenue": float(today_row[1]),
        "today_messages": today_messages,
        "yesterday_orders": yesterday_row[0],
        "yesterday_revenue": float(yesterday_row[1]),
        "yesterday_messages": yesterday_messages,
        "orders_by_status": orders_by_status,
        "leads_by_status": leads_by_status,
        "recent_orders": recent_orders,
        "orders_daily": orders_daily,
        "leads_daily": leads_daily,
    }


# ── Abandoned carts ──────────────────────────────────────────────────────────


async def get_abandoned_carts(tenant_id: UUID, db: AsyncSession) -> list[dict]:
    """Conversations stuck in cart/checkout for 2+ hours."""
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.state.in_(["cart", "checkout"]),
            Conversation.last_message_at < two_hours_ago,
        )
        .order_by(Conversation.last_message_at.desc()).limit(50)
    )
    convs = result.scalars().all()
    out = []
    for c in convs:
        ctx = c.state_context or {}
        cart = ctx.get("cart", [])
        if c.last_message_at:
            lma = c.last_message_at if c.last_message_at.tzinfo else c.last_message_at.replace(tzinfo=timezone.utc)
            hours_ago = round((datetime.now(timezone.utc) - lma).total_seconds() / 3600, 1)
        else:
            hours_ago = None
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


async def send_cart_recovery(tenant_id: UUID, conv: Conversation, db: AsyncSession) -> dict:
    """Send a cart recovery reminder via Telegram."""
    ctx = conv.state_context or {}
    cart = ctx.get("cart", [])
    cart_str = ", ".join(
        f"{i.get('title', '?')}" + (f" x{i.get('qty')}" if i.get("qty", 1) > 1 else "")
        for i in cart
    )
    total = sum(float(i.get("price", 0)) * i.get("qty", 1) for i in cart)
    lang = ctx.get("language", "ru")

    if lang == "uz_latin":
        text = f"Salom! Savatchangizda: {cart_str}. Jami: {int(total):,} so'm. Buyurtma berishni xohlaysizmi? 😊"
    elif lang == "uz_cyrillic":
        text = f"Салом! Саватчангизда: {cart_str}. Жами: {int(total):,} сўм. Буюртма беришни хоҳлайсизми? 😊"
    else:
        text = f"Привет! В вашей корзине: {cart_str}. Итого: {int(total):,} сум. Хотите оформить заказ? 😊"

    try:
        from src.telegram.service import telegram_manager
        client = telegram_manager.get_client(tenant_id)
        if client:
            try:
                entity = await client.get_input_entity(conv.telegram_chat_id)
            except ValueError:
                if conv.telegram_username:
                    entity = await client.get_input_entity(conv.telegram_username)
                else:
                    raise
            sent = await client.send_message(entity, text)
            msg = Message(
                tenant_id=tenant_id,
                conversation_id=conv.id,
                telegram_message_id=sent.id if sent else None,
                direction="outbound",
                sender_type="human_admin",
                raw_text=text,
                ai_generated=False,
            )
            db.add(msg)
            conv.last_message_at = datetime.now(timezone.utc)
            await db.flush()
            return {"sent": True, "text": text}
    except Exception as e:
        logger.warning("Cart recovery send failed: %s", e)

    return {"sent": False}


# ── Low stock ────────────────────────────────────────────────────────────────


async def get_low_stock(tenant_id: UUID, threshold: int, db: AsyncSession) -> list[dict]:
    """Variants with available stock below threshold."""
    result = await db.execute(
        select(Inventory, ProductVariant)
        .join(ProductVariant, Inventory.variant_id == ProductVariant.id)
        .where(
            Inventory.tenant_id == tenant_id,
            ProductVariant.is_active == True,  # noqa: E712
            (Inventory.quantity - Inventory.reserved_quantity) < threshold,
        )
        .order_by((Inventory.quantity - Inventory.reserved_quantity).asc()).limit(30)
    )
    return [
        {
            "variant_id": str(variant.id),
            "product_id": str(variant.product_id),
            "title": variant.title,
            "available": inv.quantity - inv.reserved_quantity,
            "reserved": inv.reserved_quantity,
            "total": inv.quantity,
        }
        for inv, variant in result.all()
    ]


# ── Broadcast ────────────────────────────────────────────────────────────────


def build_broadcast_query(tenant_id: UUID, filter_type: str):
    """Build query for broadcast target conversations."""
    from sqlalchemy import exists
    q = select(Conversation).where(
        Conversation.tenant_id == tenant_id,
        Conversation.source_type == "dm",
        Conversation.status != "closed",
    )
    if filter_type == "ordered":
        q = q.where(exists(
            select(Lead.id).where(
                Lead.conversation_id == Conversation.id,
                Lead.tenant_id == tenant_id,
            ).join(Order, Order.lead_id == Lead.id)
        ))
    return q


async def send_broadcast_background(
    tenant_id: UUID, broadcast_id: str, text: str, image_url: str | None,
    conv_data: list[dict],
):
    """Background task: send broadcast messages via Telegram."""
    bid = _uuid_mod.UUID(broadcast_id) if isinstance(broadcast_id, str) else broadcast_id
    logger.info("Broadcast BG started: %s, targets=%d", bid, len(conv_data))

    sent_count = 0
    failed_count = 0
    recipients_log: list[dict] = []

    async def _set_status(status: str, recipients: list | None = None):
        """Update broadcast status using ORM — handles all type coercion."""
        try:
            async with async_session_factory() as s:
                entry = await s.get(BroadcastHistory, bid)
                if entry:
                    entry.status = status
                    entry.sent_count = sent_count
                    entry.failed_count = failed_count
                    if status == "sent":
                        entry.sent_at = datetime.now(timezone.utc)
                    if recipients is not None:
                        entry.recipients_json = recipients
                    await s.commit()
                    logger.info("Broadcast %s: status → %s (%d/%d)", bid, status, sent_count, failed_count)
                else:
                    logger.error("Broadcast %s: not found in DB", bid)
        except Exception:
            logger.exception("Broadcast %s: failed to update status to %s", bid, status)

    try:
        from src.telegram.service import telegram_manager
        client = telegram_manager.get_client(tenant_id)
        if not client:
            try:
                from src.telegram.models import TelegramAccount
                async with async_session_factory() as acct_db:
                    acct = (await acct_db.execute(
                        select(TelegramAccount).where(
                            TelegramAccount.tenant_id == tenant_id,
                            TelegramAccount.status == "connected",
                        )
                    )).scalar_one_or_none()
                    if acct:
                        await telegram_manager.start_client(acct)
                        client = telegram_manager.get_client(tenant_id)
            except Exception as e:
                logger.warning("Broadcast: failed to auto-start client: %s", e)
        if not client:
            await _set_status("failed")
            return

        # Auto-reconnect if disconnected
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
                await _set_status("failed")
                return

        for conv in conv_data:
            r_info = {"name": conv["first_name"] or "—", "username": conv["username"], "conversation_id": conv["id"]}
            try:
                try:
                    entity = await client.get_input_entity(conv["chat_id"])
                except ValueError:
                    if conv["username"]:
                        entity = await client.get_input_entity(conv["username"])
                    else:
                        raise

                if image_url:
                    await client.send_file(entity, file=image_url, caption=text, force_document=False)
                else:
                    await client.send_message(entity, text)
                sent_count += 1
                r_info["sent"] = True

                # Save message record via ORM
                try:
                    async with async_session_factory() as msg_db:
                        conv_uuid = _uuid_mod.UUID(conv["id"]) if isinstance(conv["id"], str) else conv["id"]
                        msg = Message(
                            tenant_id=tenant_id,
                            conversation_id=conv_uuid,
                            direction="outbound",
                            sender_type="human_admin",
                            raw_text=text,
                            ai_generated=False,
                        )
                        msg_db.add(msg)
                        c = await msg_db.get(Conversation, conv_uuid)
                        if c:
                            c.last_message_at = datetime.now(timezone.utc)
                        await msg_db.commit()
                except Exception as e:
                    logger.warning("Broadcast: message record save failed: %s", e)

                await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning("Broadcast send failed for %s: %s", conv["chat_id"], e)
                failed_count += 1
                r_info["sent"] = False
            recipients_log.append(r_info)

        await _set_status("sent", recipients_log)

    except Exception:
        logger.exception("Broadcast %s crashed", bid)
        await _set_status("failed")
