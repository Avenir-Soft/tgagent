"""Order service layer — business logic for order management.

Handles: creation with retry, status transitions, inventory reservation,
lead status sync, Telegram notifications.
"""

import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.catalog.models import Inventory, Product, ProductVariant
from src.leads.models import Lead
from src.orders.models import Order, OrderItem
from src.orders.schemas import OrderCreate, OrderItemOut, OrderOut, OrderUpdate

logger = logging.getLogger(__name__)

# ── Status transition rules ──────────────────────────────────────────────────

VALID_TRANSITIONS = {
    "draft": {"confirmed", "processing", "cancelled"},
    "confirmed": {"processing", "shipped", "cancelled"},
    "processing": {"shipped", "delivered", "cancelled"},
    "shipped": {"delivered"},
    "delivered": {"returned"},
    "cancelled": set(),
    "returned": set(),
}

# ── Notification templates ───────────────────────────────────────────────────

STATUS_LABELS = {
    "ru": {
        "draft": "Ожидает подтверждения", "confirmed": "Подтверждён",
        "processing": "В обработке", "shipped": "Отправлен",
        "delivered": "Доставлен", "cancelled": "Отменён",
    },
    "en": {
        "draft": "Pending confirmation", "confirmed": "Confirmed",
        "processing": "Processing", "shipped": "Shipped",
        "delivered": "Delivered", "cancelled": "Cancelled",
    },
    "uz_latin": {
        "draft": "Tasdiqlash kutilmoqda", "confirmed": "Tasdiqlangan",
        "processing": "Ishlov berilmoqda", "shipped": "Jo'natildi",
        "delivered": "Yetkazildi", "cancelled": "Bekor qilindi",
    },
    "uz_cyrillic": {
        "draft": "Тасдиқлаш кутилмоқда", "confirmed": "Тасдиқланган",
        "processing": "Ишлов берилмоқда", "shipped": "Жўнатилди",
        "delivered": "Етказилди", "cancelled": "Бекор қилинди",
    },
}

_NOTIFICATION_TEMPLATES = {
    "shipped": {
        "ru": "\n\nВаш заказ отправлен! Ожидайте доставку.",
        "en": "\n\nYour order has been shipped! Expect delivery soon.",
        "uz_latin": "\n\nBuyurtmangiz jo'natildi! Yetkazilishini kuting.",
        "uz_cyrillic": "\n\nБуюртмангиз жўнатилди! Етказилишини кутинг.",
    },
    "delivered": {
        "ru": "\n\nВаш заказ доставлен! Спасибо за покупку!",
        "en": "\n\nYour order has been delivered! Thank you for your purchase!",
        "uz_latin": "\n\nBuyurtmangiz yetkazildi! Xaridingiz uchun rahmat!",
        "uz_cyrillic": "\n\nБуюртмангиз етказилди! Харидингиз учун раҳмат!",
    },
    "cancelled": {
        "ru": "\n\nЕсли у вас есть вопросы, напишите нам.",
        "en": "\n\nIf you have any questions, feel free to message us.",
        "uz_latin": "\n\nSavollaringiz bo'lsa, bizga yozing.",
        "uz_cyrillic": "\n\nСаволларингиз бўлса, бизга ёзинг.",
    },
}

_NOTIFICATION_HEADER = {
    "ru": "Обновление по заказу {num}:\nСтатус: {label}",
    "en": "Order {num} update:\nStatus: {label}",
    "uz_latin": "Buyurtma {num} yangilandi:\nHolat: {label}",
    "uz_cyrillic": "Буюртма {num} янгиланди:\nҲолат: {label}",
}


# ── Service functions ────────────────────────────────────────────────────────


def generate_order_number() -> str:
    return f"ORD-{uuid_mod.uuid4().hex[:12].upper()}"


async def build_orders_out(orders: list[Order], db: AsyncSession) -> list[OrderOut]:
    """Build OrderOut list with product/variant names — batched to avoid N+1."""
    product_ids: set[UUID] = set()
    variant_ids: set[UUID] = set()
    lead_ids: set[UUID] = set()

    for order in orders:
        for item in order.items:
            if item.product_id:
                product_ids.add(item.product_id)
            if item.product_variant_id:
                variant_ids.add(item.product_variant_id)
        if order.lead_id:
            lead_ids.add(order.lead_id)

    product_names: dict = {}
    variant_titles: dict = {}
    lead_conversations: dict = {}

    if product_ids:
        result = await db.execute(select(Product.id, Product.name).where(Product.id.in_(product_ids)))
        product_names = {row[0]: row[1] for row in result.fetchall()}
    if variant_ids:
        result = await db.execute(select(ProductVariant.id, ProductVariant.title).where(ProductVariant.id.in_(variant_ids)))
        variant_titles = {row[0]: row[1] for row in result.fetchall()}
    if lead_ids:
        result = await db.execute(select(Lead.id, Lead.conversation_id).where(Lead.id.in_(lead_ids)))
        lead_conversations = {row[0]: row[1] for row in result.fetchall()}

    out = []
    for order in orders:
        items_out = []
        for item in order.items:
            items_out.append(OrderItemOut(
                id=item.id,
                product_id=item.product_id,
                product_variant_id=item.product_variant_id,
                product_name=product_names.get(item.product_id),
                variant_title=variant_titles.get(item.product_variant_id),
                qty=item.qty,
                unit_price=item.unit_price,
                total_price=item.total_price,
            ))
        data = OrderOut.model_validate(order)
        data.items = items_out
        data.conversation_id = lead_conversations.get(order.lead_id) if order.lead_id else None
        out.append(data)
    return out


async def create_order(tenant_id: UUID, body: OrderCreate, db: AsyncSession) -> Order:
    """Create an order with validation and retry on order number collision.

    Raises ValueError on validation failure.
    """
    # Validate products exist
    product_ids = {item.product_id for item in body.items}
    variant_ids = {item.product_variant_id for item in body.items if item.product_variant_id}

    if product_ids:
        result = await db.execute(
            select(Product.id).where(Product.id.in_(product_ids), Product.tenant_id == tenant_id)
        )
        found = {row[0] for row in result.fetchall()}
        missing = product_ids - found
        if missing:
            raise ValueError(f"Products not found: {[str(p) for p in missing]}")

    if variant_ids:
        result = await db.execute(
            select(ProductVariant.id, ProductVariant.product_id)
            .where(ProductVariant.id.in_(variant_ids), ProductVariant.tenant_id == tenant_id)
        )
        variant_rows = result.fetchall()
        found = {row[0] for row in variant_rows}
        missing = variant_ids - found
        if missing:
            raise ValueError(f"Variants not found: {[str(v) for v in missing]}")
        # Validate each variant belongs to its specified product
        variant_product_map = {row[0]: row[1] for row in variant_rows}
        for item in body.items:
            if item.product_variant_id and item.product_id:
                expected_product = variant_product_map.get(item.product_variant_id)
                if expected_product and expected_product != item.product_id:
                    raise ValueError(
                        f"Variant {item.product_variant_id} belongs to product {expected_product}, "
                        f"not {item.product_id}"
                    )

    # Validate total_price = qty * unit_price
    for item in body.items:
        expected = item.qty * item.unit_price
        if abs(item.total_price - expected) > 1:
            raise ValueError(f"Item total_price mismatch: {item.total_price} != {item.qty} x {item.unit_price}")

    total = sum(item.total_price for item in body.items)

    # Create with retry on collision
    order = None
    for _attempt in range(5):
        order = Order(
            tenant_id=tenant_id,
            lead_id=body.lead_id,
            order_number=generate_order_number(),
            customer_name=body.customer_name,
            phone=body.phone,
            city=body.city,
            address=body.address,
            delivery_type=body.delivery_type,
            payment_type=body.payment_type,
            total_amount=total,
            currency=body.currency,
        )
        db.add(order)
        try:
            async with db.begin_nested():
                await db.flush()
            break
        except IntegrityError:
            order = None
    else:
        raise RuntimeError("Failed to generate unique order number")

    for item_data in body.items:
        item = OrderItem(order_id=order.id, **item_data.model_dump())
        db.add(item)
    await db.flush()
    # Re-fetch with eager-loaded items to avoid MissingGreenlet in async context
    result = await db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    )
    return result.scalar_one()


async def update_order(
    tenant_id: UUID, order: Order, body: OrderUpdate, db: AsyncSession,
) -> Order:
    """Update order fields + handle status transition side-effects.

    Raises ValueError on invalid transition.
    """
    old_status = order.status

    # Validate status transition
    if body.status and body.status != old_status:
        allowed = VALID_TRANSITIONS.get(old_status, set())
        if body.status not in allowed:
            raise ValueError(
                f"Нельзя сменить статус с '{old_status}' на '{body.status}'. "
                f"Допустимо: {', '.join(allowed) or 'нет переходов'}"
            )

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(order, field, value)
    await db.flush()

    # Auto-update lead status
    if body.status in ("confirmed", "processing", "shipped", "delivered") and old_status == "draft" and order.lead_id:
        lead = await db.get(Lead, order.lead_id)
        if lead and lead.status in ("new", "contacted", "qualified"):
            lead.status = "converted"
            await db.flush()

    # Unreserve inventory on cancellation
    if body.status == "cancelled" and old_status != "cancelled":
        await _unreserve_order_inventory(tenant_id, order, db)

    # Telegram notification
    if body.status and body.status != old_status and order.lead_id:
        await _notify_status_change(tenant_id, order, body.status, db)

    return order


async def _unreserve_order_inventory(tenant_id: UUID, order: Order, db: AsyncSession):
    """Release reserved inventory for all items in an order."""
    for item in order.items:
        if not item.product_variant_id:
            continue
        inv_result = await db.execute(
            select(Inventory).where(
                Inventory.tenant_id == tenant_id,
                Inventory.variant_id == item.product_variant_id,
            ).with_for_update()
        )
        inv = inv_result.scalar_one_or_none()
        if inv:
            inv.reserved_quantity = max(0, inv.reserved_quantity - item.qty)
    await db.flush()


async def _notify_status_change(tenant_id: UUID, order: Order, new_status: str, db: AsyncSession):
    """Send Telegram notification about order status change."""
    try:
        from src.conversations.models import Conversation, Message
        from src.telegram.service import telegram_manager

        lead = await db.get(Lead, order.lead_id)
        if not lead or not lead.conversation_id:
            return

        conv_result = await db.execute(select(Conversation).where(Conversation.id == lead.conversation_id))
        conv = conv_result.scalar_one_or_none()
        if not conv:
            return

        client = telegram_manager.get_client(tenant_id)
        if not client:
            return

        # Detect language
        lang = "ru"
        if conv.state_context and isinstance(conv.state_context, dict):
            lang = conv.state_context.get("language", "ru")

        labels = STATUS_LABELS.get(lang, STATUS_LABELS["ru"])
        label = labels.get(new_status, new_status)
        header = _NOTIFICATION_HEADER.get(lang, _NOTIFICATION_HEADER["ru"])
        msg_text = header.format(num=order.order_number, label=label)

        extra = _NOTIFICATION_TEMPLATES.get(new_status, {})
        if extra:
            msg_text += extra.get(lang, extra.get("ru", ""))

        # Entity resolution (Telethon pattern)
        try:
            entity = await client.get_input_entity(conv.telegram_chat_id)
        except ValueError:
            if conv.telegram_username:
                entity = await client.get_input_entity(conv.telegram_username)
            else:
                raise

        await client.send_message(entity, msg_text)

        # Save notification as message
        notif_msg = Message(
            tenant_id=tenant_id,
            conversation_id=conv.id,
            direction="outbound",
            sender_type="system",
            raw_text=msg_text,
            ai_generated=False,
        )
        db.add(notif_msg)
        conv.last_message_at = datetime.now(timezone.utc)
        await db.flush()

        # SSE: notify about order status change + new message
        try:
            from src.sse.event_bus import publish_event
            await publish_event(
                f"sse:{tenant_id}:conversation:{conv.id}",
                {"event": "new_message", "conversation_id": str(conv.id), "direction": "outbound"},
            )
            await publish_event(
                f"sse:{tenant_id}:tenant",
                {"event": "order_status_changed", "order_id": str(order.id)},
            )
        except Exception as e:
            logger.debug("SSE publish failed for order status change, order %s: %s", order.id, e)

    except Exception:
        logger.exception("Failed to notify user about status change")
