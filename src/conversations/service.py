"""Conversation service layer — business logic for conversations.

Handles: enriched listing, customer history, state reset with inventory cleanup,
cascade deletion, operator messaging via Telegram.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.conversations.models import Conversation, Message
from src.conversations.schemas import ConversationOut

logger = logging.getLogger(__name__)


async def list_conversations_enriched(
    tenant_id: UUID,
    status: str | None,
    source_type: str | None,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> list[dict]:
    """List conversations with last message, unread count, and avatar — 4 queries total."""
    q = select(Conversation).where(Conversation.tenant_id == tenant_id)
    if status:
        q = q.where(Conversation.status == status)
    if source_type:
        q = q.where(Conversation.source_type == source_type)
    q = q.order_by(Conversation.last_message_at.desc().nullslast()).offset(offset).limit(limit)
    result = await db.execute(q)
    conversations = result.scalars().all()

    if not conversations:
        return []

    conv_ids = [c.id for c in conversations]

    # Last message per conversation (DISTINCT ON — PostgreSQL)
    last_msg_q = (
        select(Message.conversation_id, Message.raw_text, Message.sender_type)
        .where(Message.conversation_id.in_(conv_ids))
        .distinct(Message.conversation_id)
        .order_by(Message.conversation_id, Message.created_at.desc())
    )
    last_msgs_r = await db.execute(last_msg_q)
    last_msg_map = {row[0]: (row[1], row[2]) for row in last_msgs_r.fetchall()}

    # Unread count: inbound messages after last outbound
    last_out_sq = (
        select(
            Message.conversation_id,
            func.max(Message.created_at).label("last_out_at"),
        )
        .where(Message.conversation_id.in_(conv_ids), Message.direction == "outbound")
        .group_by(Message.conversation_id)
        .subquery()
    )
    unread_q = (
        select(Message.conversation_id, func.count().label("cnt"))
        .outerjoin(last_out_sq, Message.conversation_id == last_out_sq.c.conversation_id)
        .where(
            Message.conversation_id.in_(conv_ids),
            Message.direction == "inbound",
            or_(last_out_sq.c.last_out_at.is_(None), Message.created_at > last_out_sq.c.last_out_at),
        )
        .group_by(Message.conversation_id)
    )
    unread_r = await db.execute(unread_q)
    unread_map = {row[0]: row[1] for row in unread_r.fetchall()}

    # Batch-load lead avatar_url
    from src.leads.models import Lead
    tg_user_ids = [c.telegram_user_id for c in conversations if c.telegram_user_id]
    avatar_map: dict = {}
    if tg_user_ids:
        avatar_r = await db.execute(
            select(Lead.telegram_user_id, Lead.avatar_url).where(
                Lead.tenant_id == tenant_id,
                Lead.telegram_user_id.in_(tg_user_ids),
                Lead.avatar_url.isnot(None),
            )
        )
        avatar_map = {row[0]: row[1] for row in avatar_r.fetchall()}

    out = []
    for c in conversations:
        data = ConversationOut.model_validate(c).model_dump(mode="json")
        lm = last_msg_map.get(c.id, (None, None))
        data["last_message_text"] = lm[0]
        data["last_message_sender_type"] = lm[1]
        data["unread_count"] = unread_map.get(c.id, 0)
        data["avatar_url"] = avatar_map.get(c.telegram_user_id)
        out.append(data)
    return out


async def get_customer_history(tenant_id: UUID, conversation_id: UUID, db: AsyncSession) -> dict:
    """Get customer info + order history for the conversation's customer."""
    from src.orders.models import Order, OrderItem
    from src.leads.models import Lead
    from src.catalog.models import Product, ProductVariant

    conv_r = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
    )
    conv = conv_r.scalar_one_or_none()
    if not conv:
        return None

    # Find lead
    lead = None
    if conv.telegram_user_id:
        lead_r = await db.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.telegram_user_id == conv.telegram_user_id,
            ).order_by(Lead.created_at.desc()).limit(1)
        )
        lead = lead_r.scalar_one_or_none()

    # Get orders from ALL leads for this telegram user
    orders = []
    all_lead_ids = []
    if conv.telegram_user_id:
        leads_r = await db.execute(
            select(Lead.id).where(Lead.tenant_id == tenant_id, Lead.telegram_user_id == conv.telegram_user_id)
        )
        all_lead_ids = [row[0] for row in leads_r.fetchall()]

    if all_lead_ids:
        orders_r = await db.execute(
            select(Order)
            .where(Order.lead_id.in_(all_lead_ids))
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .limit(20)
        )
        all_orders = orders_r.scalars().all()

        # Batch-load product/variant names (fixes N+1)
        all_product_ids: set = set()
        all_variant_ids: set = set()
        for o in all_orders:
            for item in (o.items or []):
                if item.product_id:
                    all_product_ids.add(item.product_id)
                if item.product_variant_id:
                    all_variant_ids.add(item.product_variant_id)

        product_names = {}
        if all_product_ids:
            pr = await db.execute(select(Product.id, Product.name).where(Product.id.in_(all_product_ids)))
            product_names = {pid: name for pid, name in pr.all()}
        variant_titles = {}
        if all_variant_ids:
            vr = await db.execute(select(ProductVariant.id, ProductVariant.title).where(ProductVariant.id.in_(all_variant_ids)))
            variant_titles = {vid: title for vid, title in vr.all()}

        for o in all_orders:
            items_out = []
            for item in (o.items or []):
                items_out.append({
                    "product_name": product_names.get(item.product_id, "") if item.product_id else "",
                    "variant_title": variant_titles.get(item.product_variant_id, "") if item.product_variant_id else "",
                    "quantity": item.qty,
                    "price": float(item.unit_price),
                })
            orders.append({
                "order_number": o.order_number,
                "status": o.status,
                "total_amount": float(o.total_amount) if o.total_amount else 0,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "items": items_out,
            })

    msg_count_r = await db.execute(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
    )
    total_messages = msg_count_r.scalar() or 0

    return {
        "customer_name": lead.customer_name if lead else conv.telegram_first_name,
        "telegram_username": conv.telegram_username,
        "phone": lead.phone if lead else None,
        "city": lead.city if lead else None,
        "lead_status": lead.status if lead else None,
        "avatar_url": lead.avatar_url if lead else None,
        "total_messages": total_messages,
        "total_orders": len(orders),
        "orders": orders,
    }


async def reset_conversation(tenant_id: UUID, conv: Conversation, db: AsyncSession) -> dict:
    """Reset conversation state — clears cart, unreserves draft inventory, preserves language."""
    from src.leads.models import Lead
    from src.orders.models import Order
    from src.catalog.models import Inventory

    lead_ids = []
    if conv.telegram_user_id:
        leads_r = await db.execute(
            select(Lead.id).where(Lead.tenant_id == tenant_id, Lead.telegram_user_id == conv.telegram_user_id)
        )
        lead_ids = [row[0] for row in leads_r.fetchall()]

    # Unreserve inventory for draft orders
    if lead_ids:
        draft_r = await db.execute(
            select(Order)
            .where(Order.lead_id.in_(lead_ids), Order.status == "draft")
            .options(selectinload(Order.items))
        )
        draft_orders = draft_r.scalars().all()

        # Batch-load all inventories in one query instead of N+1
        all_variant_ids = {
            item.product_variant_id
            for order in draft_orders
            for item in order.items
            if item.product_variant_id
        }
        inv_map: dict = {}
        if all_variant_ids:
            inv_r2 = await db.execute(
                select(Inventory).where(
                    Inventory.tenant_id == tenant_id,
                    Inventory.variant_id.in_(all_variant_ids),
                ).with_for_update()
            )
            inv_map = {inv.variant_id: inv for inv in inv_r2.scalars().all()}

        for order in draft_orders:
            for item in order.items:
                if not item.product_variant_id:
                    continue
                inv = inv_map.get(item.product_variant_id)
                if inv:
                    inv.reserved_quantity = max(0, inv.reserved_quantity - item.qty)
            order.status = "cancelled"

    # Preserve active order references
    active_orders = []
    if lead_ids:
        active_r = await db.execute(
            select(Order).where(
                Order.lead_id.in_(lead_ids),
                Order.status.notin_(["draft", "cancelled"]),
            )
        )
        for o in active_r.scalars().all():
            active_orders.append({
                "order_id": str(o.id),
                "order_number": o.order_number,
                "status": o.status,
                "total_amount": float(o.total_amount) if o.total_amount else 0,
            })

    # Reset state, preserve language
    old_lang = (conv.state_context or {}).get("language", "ru")
    conv.state_context = {"language": old_lang}
    if active_orders:
        conv.state_context["orders"] = active_orders
    conv.state = "idle"
    if conv.status == "handoff":
        conv.status = "active"
    conv.ai_enabled = True
    await db.flush()
    return {"status": "reset", "state": "idle", "ai_enabled": True}


async def delete_conversation_cascade(tenant_id: UUID, conversation_id: UUID, db: AsyncSession):
    """Delete conversation and ALL related data: messages, handoffs, leads, orders, order items."""
    from src.handoffs.models import Handoff
    from src.leads.models import Lead
    from src.orders.models import Order, OrderItem

    # Find leads → orders → order items
    leads_r = await db.execute(
        select(Lead.id).where(Lead.conversation_id == conversation_id, Lead.tenant_id == tenant_id)
    )
    lead_ids = [row[0] for row in leads_r.fetchall()]

    order_ids = []
    if lead_ids:
        orders_r = await db.execute(
            select(Order.id).where(Order.lead_id.in_(lead_ids), Order.tenant_id == tenant_id)
        )
        order_ids = [row[0] for row in orders_r.fetchall()]

    # Delete in cascade order
    if order_ids:
        await db.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
        await db.execute(delete(Order).where(Order.id.in_(order_ids), Order.tenant_id == tenant_id))
    if lead_ids:
        await db.execute(delete(Lead).where(Lead.id.in_(lead_ids), Lead.tenant_id == tenant_id))
    await db.execute(delete(Handoff).where(Handoff.conversation_id == conversation_id, Handoff.tenant_id == tenant_id))
    await db.execute(delete(Message).where(Message.conversation_id == conversation_id, Message.tenant_id == tenant_id))
    await db.execute(delete(Conversation).where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id))
    await db.flush()


async def bulk_delete_conversations(tenant_id: UUID, conv_ids: list[UUID], db: AsyncSession) -> dict:
    """Bulk delete conversations with full cascade."""
    from src.handoffs.models import Handoff
    from src.leads.models import Lead
    from src.orders.models import Order, OrderItem

    # Verify all belong to tenant
    result = await db.execute(
        select(Conversation.id).where(Conversation.id.in_(conv_ids), Conversation.tenant_id == tenant_id)
    )
    valid_ids = [row[0] for row in result.fetchall()]
    if not valid_ids:
        return {"deleted": 0, "skipped": len(conv_ids)}

    leads_r = await db.execute(
        select(Lead.id).where(Lead.conversation_id.in_(valid_ids), Lead.tenant_id == tenant_id)
    )
    lead_ids = [row[0] for row in leads_r.fetchall()]

    order_ids = []
    if lead_ids:
        orders_r = await db.execute(
            select(Order.id).where(Order.lead_id.in_(lead_ids), Order.tenant_id == tenant_id)
        )
        order_ids = [row[0] for row in orders_r.fetchall()]

    if order_ids:
        await db.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
        await db.execute(delete(Order).where(Order.id.in_(order_ids), Order.tenant_id == tenant_id))
    if lead_ids:
        await db.execute(delete(Lead).where(Lead.id.in_(lead_ids), Lead.tenant_id == tenant_id))
    await db.execute(delete(Handoff).where(Handoff.conversation_id.in_(valid_ids), Handoff.tenant_id == tenant_id))
    await db.execute(delete(Message).where(Message.conversation_id.in_(valid_ids), Message.tenant_id == tenant_id))
    await db.execute(delete(Conversation).where(Conversation.id.in_(valid_ids), Conversation.tenant_id == tenant_id))
    await db.flush()

    return {"deleted": len(valid_ids), "skipped": len(conv_ids) - len(valid_ids)}


async def send_operator_message(
    tenant_id: UUID, conv: Conversation, text: str, db: AsyncSession,
) -> tuple[Message, int | None]:
    """Send operator message, optionally via Telegram. Returns (Message, tg_msg_id)."""
    telegram_message_id = None

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
            telegram_message_id = sent.id
    except Exception as e:
        logger.warning("Failed to send Telegram message: %s", e)

    msg = Message(
        tenant_id=tenant_id,
        conversation_id=conv.id,
        telegram_message_id=telegram_message_id,
        direction="outbound",
        sender_type="human_admin",
        raw_text=text,
        ai_generated=False,
    )
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc)
    await db.flush()
    return msg, telegram_message_id


async def edit_message_telegram(
    tenant_id: UUID, conv: Conversation, telegram_message_id: int, new_text: str,
):
    """Edit a message in Telegram (fire-and-forget)."""
    try:
        from src.telegram.service import telegram_manager
        client = telegram_manager.get_client(tenant_id)
        if client:
            await client.edit_message(conv.telegram_chat_id, telegram_message_id, new_text)
    except Exception as e:
        logger.warning("Failed to edit Telegram message: %s", e)
