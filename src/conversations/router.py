from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.conversations.models import CommentTemplate, Conversation, Message
from src.conversations.schemas import (
    CommentTemplateCreate, CommentTemplateOut, CommentTemplateUpdate,
    ConversationOut, MessageEdit, MessageOut, MessageSend,
)

router = APIRouter(tags=["conversations"])


# --- Templates ---
@router.post("/templates", response_model=CommentTemplateOut, status_code=201)
async def create_template(
    body: CommentTemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    tpl = CommentTemplate(
        tenant_id=user.tenant_id,
        trigger_type=body.trigger_type,
        trigger_patterns=body.trigger_patterns,
        language=body.language,
        template_text=body.template_text,
    )
    db.add(tpl)
    await db.flush()
    return CommentTemplateOut.model_validate(tpl)


@router.get("/templates", response_model=list[CommentTemplateOut])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CommentTemplate).where(CommentTemplate.tenant_id == user.tenant_id)
    )
    return [CommentTemplateOut.model_validate(t) for t in result.scalars().all()]


@router.patch("/templates/{template_id}", response_model=CommentTemplateOut)
async def update_template(
    template_id: UUID,
    body: CommentTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(CommentTemplate).where(
            CommentTemplate.id == template_id,
            CommentTemplate.tenant_id == user.tenant_id,
        )
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(tpl, key, value)
    await db.flush()
    return CommentTemplateOut.model_validate(tpl)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(CommentTemplate).where(
            CommentTemplate.id == template_id,
            CommentTemplate.tenant_id == user.tenant_id,
        )
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(tpl)
    return {"status": "deleted"}


@router.post("/templates/test-trigger")
async def test_trigger(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Test which templates would match a given text."""
    import re
    test_text = (body.get("text") or "").strip().lower()
    if not test_text:
        return {"matches": []}

    result = await db.execute(
        select(CommentTemplate).where(
            CommentTemplate.tenant_id == user.tenant_id,
            CommentTemplate.is_active.is_(True),
        )
    )
    matches = []
    for tpl in result.scalars().all():
        patterns = tpl.trigger_patterns if isinstance(tpl.trigger_patterns, list) else []
        matched = False
        if tpl.trigger_type == "regex":
            for p in patterns:
                try:
                    if re.search(p, test_text, re.IGNORECASE):
                        matched = True
                        break
                except re.error:
                    pass
        else:
            # keyword, emoji, plus, price, stock, etc. — substring match
            # Short patterns (<=2 chars) use word-boundary regex to avoid false positives
            for p in patterns:
                pl = p.lower()
                if len(pl) <= 2:
                    if re.search(r'(?:^|\s|^)' + re.escape(pl) + r'(?:\s|$|$)', test_text):
                        matched = True
                        break
                else:
                    if pl in test_text:
                        matched = True
                        break
        if matched:
            matches.append({
                "id": str(tpl.id),
                "trigger_type": tpl.trigger_type,
                "trigger_patterns": patterns,
                "template_text": tpl.template_text,
                "language": tpl.language,
            })
    return {"matches": matches}


# --- Conversations ---
@router.get("/conversations")
async def list_conversations(
    status: str | None = None,
    source_type: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Conversation).where(Conversation.tenant_id == user.tenant_id)
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

    # Unread count: inbound messages after last outbound per conversation
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

    out = []
    for c in conversations:
        data = ConversationOut.model_validate(c).model_dump(mode="json")
        lm = last_msg_map.get(c.id, (None, None))
        data["last_message_text"] = lm[0]
        data["last_message_sender_type"] = lm[1]
        data["unread_count"] = unread_map.get(c.id, 0)
        out.append(data)

    return out


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == user.tenant_id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationOut.model_validate(conv)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: UUID,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Get the LAST N messages (most recent), then return in ASC order for display
    from sqlalchemy import desc
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.tenant_id == user.tenant_id)
        .order_by(desc(Message.created_at))
        .limit(limit)
    )
    msgs = list(reversed(result.scalars().all()))  # reverse to ASC for display
    return [MessageOut.model_validate(m) for m in msgs]


@router.get("/conversations/{conversation_id}/customer-history")
async def get_customer_history(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get customer info + order history for the conversation's customer."""
    from src.orders.models import Order, OrderItem
    from src.leads.models import Lead

    conv_r = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == user.tenant_id
        )
    )
    conv = conv_r.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Find lead (may have multiple — use most recent)
    lead = None
    if conv.telegram_user_id:
        lead_r = await db.execute(
            select(Lead).where(
                Lead.tenant_id == user.tenant_id,
                Lead.telegram_user_id == conv.telegram_user_id,
            ).order_by(Lead.created_at.desc()).limit(1)
        )
        lead = lead_r.scalar_one_or_none()

    # Get orders from ALL leads for this telegram user
    orders = []
    all_lead_ids = []
    if conv.telegram_user_id:
        leads_r = await db.execute(
            select(Lead.id).where(
                Lead.tenant_id == user.tenant_id,
                Lead.telegram_user_id == conv.telegram_user_id,
            )
        )
        all_lead_ids = [row[0] for row in leads_r.fetchall()]

    if all_lead_ids:
        from sqlalchemy.orm import selectinload
        from src.catalog.models import Product, ProductVariant
        orders_r = await db.execute(
            select(Order)
            .where(Order.lead_id.in_(all_lead_ids))
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .limit(20)
        )
        for o in orders_r.scalars().all():
            items_out = []
            for item in (o.items or []):
                # Look up product/variant names
                p_name = ""
                v_title = ""
                if item.product_id:
                    p_r = await db.execute(select(Product.name).where(Product.id == item.product_id))
                    p_name = p_r.scalar() or ""
                if item.product_variant_id:
                    v_r = await db.execute(select(ProductVariant.title).where(ProductVariant.id == item.product_variant_id))
                    v_title = v_r.scalar() or ""
                items_out.append({
                    "product_name": p_name,
                    "variant_title": v_title,
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

    # Message count
    from sqlalchemy import func
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
        "total_messages": total_messages,
        "total_orders": len(orders),
        "orders": orders,
    }


@router.patch("/conversations/{conversation_id}/toggle-ai")
async def toggle_ai(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == user.tenant_id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.ai_enabled = not conv.ai_enabled
    # If re-enabling AI and conversation was in handoff, reactivate it
    if conv.ai_enabled and conv.status == "handoff":
        conv.status = "active"
        conv.state = "idle"
    await db.flush()
    return {"ai_enabled": conv.ai_enabled, "status": conv.status}


@router.post("/conversations/{conversation_id}/reset")
async def reset_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Reset conversation state — clears cart, products, resets to idle. AI stays enabled. Preserves language."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == user.tenant_id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Unreserve inventory for any draft orders belonging to this customer
    if conv.telegram_user_id:
        from src.leads.models import Lead
        from src.orders.models import Order, OrderItem
        from src.catalog.models import Inventory
        from sqlalchemy.orm import selectinload

        leads_r = await db.execute(
            select(Lead.id).where(
                Lead.tenant_id == user.tenant_id,
                Lead.telegram_user_id == conv.telegram_user_id,
            )
        )
        lead_ids = [row[0] for row in leads_r.fetchall()]

        if lead_ids:
            draft_r = await db.execute(
                select(Order)
                .where(Order.lead_id.in_(lead_ids), Order.status == "draft")
                .options(selectinload(Order.items))
            )
            for order in draft_r.scalars().all():
                for item in order.items:
                    if not item.product_variant_id:
                        continue
                    inv_r = await db.execute(
                        select(Inventory).where(
                            Inventory.tenant_id == user.tenant_id,
                            Inventory.variant_id == item.product_variant_id,
                        ).with_for_update()
                    )
                    inv = inv_r.scalar_one_or_none()
                    if inv:
                        inv.reserved_quantity = max(0, inv.reserved_quantity - item.qty)
                order.status = "cancelled"

    # Preserve language preference across reset
    old_lang = (conv.state_context or {}).get("language", "ru")
    conv.state_context = {"language": old_lang}
    conv.state = "idle"
    if conv.status == "handoff":
        conv.status = "active"
    conv.ai_enabled = True
    await db.flush()
    return {"status": "reset", "state": "idle", "ai_enabled": True}


@router.patch("/conversations/{conversation_id}/messages/{message_id}", response_model=MessageOut)
async def edit_message(
    conversation_id: UUID,
    message_id: UUID,
    body: MessageEdit,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Edit an outbound message. Optionally sync edit to Telegram."""
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.tenant_id == user.tenant_id,
            Message.direction == "outbound",
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.raw_text = body.raw_text
    await db.flush()

    # Sync to Telegram if requested and message has telegram_message_id
    if body.sync_telegram and msg.telegram_message_id:
        conv_result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = conv_result.scalar_one_or_none()
        if conv:
            try:
                from src.telegram.service import telegram_manager
                client = telegram_manager.get_client(user.tenant_id)
                if client:
                    await client.edit_message(
                        conv.telegram_chat_id,
                        msg.telegram_message_id,
                        body.raw_text,
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Failed to edit Telegram message: %s", e)

    return MessageOut.model_validate(msg)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=201)
async def send_operator_message(
    conversation_id: UUID,
    body: MessageSend,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Send a message from the operator. Optionally send to Telegram."""
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    telegram_message_id = None

    # Send to Telegram
    if body.sync_telegram:
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
                sent = await client.send_message(entity, body.raw_text)
                telegram_message_id = sent.id
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to send Telegram message: %s", e)

    # Save message
    from datetime import datetime, timezone
    msg = Message(
        tenant_id=user.tenant_id,
        conversation_id=conversation_id,
        telegram_message_id=telegram_message_id,
        direction="outbound",
        sender_type="human_admin",
        raw_text=body.raw_text,
        ai_generated=False,
    )
    db.add(msg)

    conv.last_message_at = datetime.now(timezone.utc)
    await db.flush()

    return MessageOut.model_validate(msg)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Delete a conversation and all related data (messages, handoffs, leads, orders, order items)."""
    from src.handoffs.models import Handoff
    from src.leads.models import Lead
    from src.orders.models import Order, OrderItem

    # Verify conversation exists and belongs to tenant
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 1. Find leads linked to this conversation
    leads_r = await db.execute(
        select(Lead.id).where(
            Lead.conversation_id == conversation_id,
            Lead.tenant_id == user.tenant_id,
        )
    )
    lead_ids = [row[0] for row in leads_r.fetchall()]

    # 2. Find orders linked to those leads
    order_ids = []
    if lead_ids:
        orders_r = await db.execute(
            select(Order.id).where(
                Order.lead_id.in_(lead_ids),
                Order.tenant_id == user.tenant_id,
            )
        )
        order_ids = [row[0] for row in orders_r.fetchall()]

    # 3. Delete order items (OrderItem has no tenant_id — order_ids already tenant-scoped)
    if order_ids:
        await db.execute(
            delete(OrderItem).where(
                OrderItem.order_id.in_(order_ids),
            )
        )

    # 4. Delete orders
    if order_ids:
        await db.execute(
            delete(Order).where(
                Order.id.in_(order_ids),
                Order.tenant_id == user.tenant_id,
            )
        )

    # 5. Delete leads
    if lead_ids:
        await db.execute(
            delete(Lead).where(
                Lead.id.in_(lead_ids),
                Lead.tenant_id == user.tenant_id,
            )
        )

    # 6. Delete handoffs
    await db.execute(
        delete(Handoff).where(
            Handoff.conversation_id == conversation_id,
            Handoff.tenant_id == user.tenant_id,
        )
    )

    # 7. Delete messages
    await db.execute(
        delete(Message).where(
            Message.conversation_id == conversation_id,
            Message.tenant_id == user.tenant_id,
        )
    )

    # 8. Delete the conversation itself
    await db.delete(conv)
    await db.flush()

    return {"deleted": True}


@router.post("/conversations/bulk-delete")
async def bulk_delete_conversations(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Bulk delete conversations by list of IDs. Cascades to messages, leads, orders, handoffs."""
    from src.handoffs.models import Handoff
    from src.leads.models import Lead
    from src.orders.models import Order, OrderItem

    conv_ids = body.get("conversation_ids", [])
    if not conv_ids:
        raise HTTPException(status_code=400, detail="conversation_ids required")

    # Verify all conversations belong to tenant
    result = await db.execute(
        select(Conversation.id).where(
            Conversation.id.in_([UUID(c) for c in conv_ids]),
            Conversation.tenant_id == user.tenant_id,
        )
    )
    valid_ids = [row[0] for row in result.fetchall()]
    if not valid_ids:
        raise HTTPException(status_code=404, detail="No conversations found")

    # Find leads → orders → order items
    leads_r = await db.execute(
        select(Lead.id).where(Lead.conversation_id.in_(valid_ids), Lead.tenant_id == user.tenant_id)
    )
    lead_ids = [row[0] for row in leads_r.fetchall()]

    order_ids = []
    if lead_ids:
        orders_r = await db.execute(
            select(Order.id).where(Order.lead_id.in_(lead_ids), Order.tenant_id == user.tenant_id)
        )
        order_ids = [row[0] for row in orders_r.fetchall()]

    # Delete in order: items → orders → leads → handoffs → messages → conversations
    if order_ids:
        await db.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
        await db.execute(delete(Order).where(Order.id.in_(order_ids), Order.tenant_id == user.tenant_id))
    if lead_ids:
        await db.execute(delete(Lead).where(Lead.id.in_(lead_ids), Lead.tenant_id == user.tenant_id))
    await db.execute(delete(Handoff).where(Handoff.conversation_id.in_(valid_ids), Handoff.tenant_id == user.tenant_id))
    await db.execute(delete(Message).where(Message.conversation_id.in_(valid_ids), Message.tenant_id == user.tenant_id))
    await db.execute(delete(Conversation).where(Conversation.id.in_(valid_ids), Conversation.tenant_id == user.tenant_id))
    await db.flush()

    return {"deleted": len(valid_ids), "skipped": len(conv_ids) - len(valid_ids)}
