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
    "draft": {"pending_payment", "confirmed", "cancelled"},
    "pending_payment": {"confirmed", "cancelled"},
    "confirmed": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

# ── Notification templates ───────────────────────────────────────────────────

STATUS_LABELS = {
    "ru": {
        "draft": "Черновик", "pending_payment": "Ожидает оплаты",
        "confirmed": "Подтверждён", "completed": "Завершён",
        "cancelled": "Отменён",
    },
    "en": {
        "draft": "Draft", "pending_payment": "Pending payment",
        "confirmed": "Confirmed", "completed": "Completed",
        "cancelled": "Cancelled",
    },
    "uz_latin": {
        "draft": "Qoralama", "pending_payment": "To'lov kutilmoqda",
        "confirmed": "Tasdiqlangan", "completed": "Yakunlangan",
        "cancelled": "Bekor qilindi",
    },
    "uz_cyrillic": {
        "draft": "Қоралама", "pending_payment": "Тўлов кутилмоқда",
        "confirmed": "Тасдиқланган", "completed": "Якунланган",
        "cancelled": "Бекор қилинди",
    },
}

_NOTIFICATION_TEMPLATES = {
    "pending_payment": {
        "ru": "\n\nОтправьте фото чека для подтверждения оплаты.",
        "en": "\n\nPlease send a payment receipt photo for confirmation.",
        "uz_latin": "\n\nTo'lovni tasdiqlash uchun chek rasmini yuboring.",
        "uz_cyrillic": "\n\nТўловни тасдиқлаш учун чек расмини юборинг.",
    },
    "confirmed": {
        "ru": "\n\nОплата подтверждена! Ждём вас на туре! 🎉",
        "en": "\n\nPayment confirmed! We look forward to seeing you on the tour! 🎉",
        "uz_latin": "\n\nTo'lov tasdiqlandi! Sizni turda kutamiz! 🎉",
        "uz_cyrillic": "\n\nТўлов тасдиқланди! Сизни турда кутамиз! 🎉",
    },
    "completed": {
        "ru": "\n\nТур завершён! Спасибо за участие! ⭐",
        "en": "\n\nTour completed! Thank you for joining us! ⭐",
        "uz_latin": "\n\nTur yakunlandi! Qatnashganingiz uchun rahmat! ⭐",
        "uz_cyrillic": "\n\nТур якунланди! Қатнашганингиз учун раҳмат! ⭐",
    },
    "cancelled": {
        "ru": "\n\nЕсли у вас есть вопросы, напишите нам.",
        "en": "\n\nIf you have any questions, feel free to message us.",
        "uz_latin": "\n\nSavollaringiz bo'lsa, bizga yozing.",
        "uz_cyrillic": "\n\nСаволларингиз бўлса, бизга ёзинг.",
    },
}

_NOTIFICATION_HEADER = {
    "ru": "Обновление по бронированию {num}:\nСтатус: {label}",
    "en": "Booking {num} update:\nStatus: {label}",
    "uz_latin": "Buyurtma {num} yangilandi:\nHolat: {label}",
    "uz_cyrillic": "Буюртма {num} янгиланди:\nҲолат: {label}",
}


# ── Service functions ────────────────────────────────────────────────────────


def generate_order_number() -> str:
    return f"BK-{uuid_mod.uuid4().hex[:12].upper()}"


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
    if body.status in ("confirmed", "completed") and old_status in ("draft", "pending_payment") and order.lead_id:
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

        # Auto-create tour group and send invite link on confirmation
        if new_status == "confirmed":
            invite_link = await _create_tour_group_and_invite(
                tenant_id, order, conv, client, lang, db,
            )
            if invite_link:
                group_msgs = {
                    "uz_latin": f"🏔 Tur guruhiga qo'shiling:\n{invite_link}\n\nGuruhda muhim ma'lumotlar va boshqa qatnashchilar bilan bog'lanish mumkin.",
                    "uz_cyrillic": f"🏔 Тур гуруҳига қўшилинг:\n{invite_link}\n\nГуруҳда муҳим маълумотлар ва бошқа қатнашчилар билан боғланиш мумкин.",
                    "ru": f"🏔 Присоединяйтесь к группе тура:\n{invite_link}\n\nВ группе будет важная информация и связь с другими участниками.",
                    "en": f"🏔 Join the tour group:\n{invite_link}\n\nYou'll find important info and connect with other participants.",
                }
                group_text = group_msgs.get(lang, group_msgs["uz_latin"])
                await client.send_message(entity, group_text)

                # Save group invite as message
                group_msg = Message(
                    tenant_id=tenant_id,
                    conversation_id=conv.id,
                    direction="outbound",
                    sender_type="system",
                    raw_text=group_text,
                    ai_generated=False,
                )
                db.add(group_msg)

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

        # Re-enable AI for the conversation after confirmation
        if new_status == "confirmed" and not conv.ai_enabled:
            conv.ai_enabled = True

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


async def _create_tour_group_and_invite(
    tenant_id: UUID, order: Order, conv, client, lang: str, db: AsyncSession,
) -> str | None:
    """Create a Telegram group for the tour booking and return the invite link.

    Group name format: "Tour Name — DD.MM YYYY"
    Adds the customer to the group automatically.
    """
    try:
        from telethon.tl.functions.messages import CreateChatRequest, ExportChatInviteRequest
        from telethon.tl.functions.channels import CreateChannelRequest, EditPhotoRequest

        # Get tour name and dates from order items
        if not order.items:
            return None

        item = order.items[0]
        product_name = "Tur"
        departure_date = ""

        if item.product_id:
            prod = await db.get(Product, item.product_id)
            if prod:
                product_name = prod.name

        if item.product_variant_id:
            variant = await db.get(ProductVariant, item.product_variant_id)
            if variant:
                departure_date = variant.color or variant.title or ""

        # Build group title: "Paltau sharshara — 19-aprel 2026"
        group_title = product_name
        if departure_date:
            group_title += f" — {departure_date}"

        # Truncate to Telegram limit (128 chars)
        if len(group_title) > 128:
            group_title = group_title[:125] + "..."

        # Create a regular group chat (small group, not supergroup)
        # We need to add the customer as a participant
        customer_entity = None
        try:
            customer_entity = await client.get_input_entity(conv.telegram_chat_id)
        except ValueError:
            if conv.telegram_username:
                customer_entity = await client.get_input_entity(conv.telegram_username)

        if not customer_entity:
            logger.warning("Cannot resolve customer entity for group creation")
            return None

        result = await client(CreateChatRequest(
            users=[customer_entity],
            title=group_title,
        ))

        # Extract chat from result
        chat = result.chats[0] if result.chats else None
        if not chat:
            logger.warning("Group created but no chat in result")
            return None

        chat_id = chat.id
        logger.info("Tour group created: '%s' (chat_id=%s)", group_title, chat_id)

        # Export invite link
        try:
            invite_result = await client(ExportChatInviteRequest(peer=chat_id))
            invite_link = invite_result.link
            logger.info("Group invite link: %s", invite_link)
        except Exception:
            logger.warning("Failed to export invite link, trying alternate method", exc_info=True)
            # Try getting existing invite link
            try:
                from telethon.tl.functions.messages import GetFullChatRequest
                full = await client(GetFullChatRequest(chat_id=chat_id))
                invite_link = getattr(full.full_chat.exported_invite, 'link', None)
            except Exception:
                logger.warning("Could not get invite link at all", exc_info=True)
                invite_link = None

        # Save group to DB
        from src.telegram.models import TelegramDiscussionGroup
        group_record = TelegramDiscussionGroup(
            tenant_id=tenant_id,
            telegram_group_id=chat_id,
            title=group_title,
            is_active=True,
        )
        db.add(group_record)
        await db.flush()

        return invite_link

    except Exception:
        logger.exception("Failed to create tour group for order %s", order.order_number)
        return None
