import uuid as uuid_mod
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.catalog.models import Product, ProductVariant
from src.core.database import get_db
from src.orders.models import Order, OrderItem
from src.orders.schemas import OrderCreate, OrderItemOut, OrderOut, OrderUpdate

router = APIRouter(prefix="/orders", tags=["orders"])


def _generate_order_number() -> str:
    return f"ORD-{uuid_mod.uuid4().hex[:8].upper()}"


async def _build_orders_out(orders: list[Order], db: AsyncSession) -> list[OrderOut]:
    """Build OrderOut list with product/variant names — batched to avoid N+1."""
    # Collect all unique product/variant/lead IDs across all orders
    product_ids = set()
    variant_ids = set()
    lead_ids = set()
    for order in orders:
        for item in order.items:
            if item.product_id:
                product_ids.add(item.product_id)
            if item.product_variant_id:
                variant_ids.add(item.product_variant_id)
        if order.lead_id:
            lead_ids.add(order.lead_id)

    # Batch load products, variants, and lead->conversation mapping
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
        from src.leads.models import Lead
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


def _order_query(tenant_id: UUID):
    return select(Order).where(Order.tenant_id == tenant_id).options(selectinload(Order.items))


@router.post("", response_model=OrderOut, status_code=201)
async def create_order(
    body: OrderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    total = sum(item.total_price for item in body.items)
    order = Order(
        tenant_id=user.tenant_id,
        lead_id=body.lead_id,
        order_number=_generate_order_number(),
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
    await db.flush()

    for item_data in body.items:
        item = OrderItem(order_id=order.id, **item_data.model_dump())
        db.add(item)
    await db.flush()

    return (await _build_orders_out([order], db))[0]


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = _order_query(user.tenant_id)
    if status:
        q = q.where(Order.status == status)
    q = q.order_by(Order.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    orders = result.scalars().unique().all()
    return await _build_orders_out(orders, db)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        _order_query(user.tenant_id).where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return (await _build_orders_out([order], db))[0]


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


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order(
    order_id: UUID,
    body: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        _order_query(user.tenant_id).where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    old_status = order.status

    # Validate status transitions
    VALID_TRANSITIONS = {
        "draft": {"confirmed", "cancelled"},
        "confirmed": {"processing", "cancelled"},
        "processing": {"shipped", "cancelled"},
        "shipped": {"delivered"},
        "delivered": set(),
        "cancelled": set(),
    }
    if body.status and body.status != old_status:
        allowed = VALID_TRANSITIONS.get(old_status, set())
        if body.status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Нельзя сменить статус с '{old_status}' на '{body.status}'. Допустимо: {', '.join(allowed) or 'нет переходов'}",
            )

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(order, field, value)
    await db.flush()

    # Unreserve inventory when order is cancelled from admin
    if body.status == "cancelled" and old_status != "cancelled":
        from src.catalog.models import Inventory
        for item in order.items:
            if not item.product_variant_id:
                continue
            inv_result = await db.execute(
                select(Inventory).where(
                    Inventory.tenant_id == user.tenant_id,
                    Inventory.variant_id == item.product_variant_id,
                ).with_for_update()
            )
            inv = inv_result.scalar_one_or_none()
            if inv:
                inv.reserved_quantity = max(0, inv.reserved_quantity - item.qty)
        await db.flush()

    # Notify user in Telegram if status changed
    if body.status and body.status != old_status and order.lead_id:
        try:
            from src.leads.models import Lead
            from src.conversations.models import Conversation
            from src.telegram.service import telegram_manager

            lead = await db.get(Lead, order.lead_id)
            if lead and lead.conversation_id:
                conv_result = await db.execute(
                    select(Conversation).where(Conversation.id == lead.conversation_id)
                )
                conv = conv_result.scalar_one_or_none()
                if conv:
                    client = telegram_manager.get_client(user.tenant_id)
                    if client:
                        # Detect language from conversation state_context
                        lang = "ru"
                        if conv.state_context and isinstance(conv.state_context, dict):
                            lang = conv.state_context.get("language", "ru")
                        labels = STATUS_LABELS.get(lang, STATUS_LABELS["ru"])
                        label = labels.get(body.status, body.status)
                        header = _NOTIFICATION_HEADER.get(lang, _NOTIFICATION_HEADER["ru"])
                        msg_text = header.format(num=order.order_number, label=label)
                        extra = _NOTIFICATION_TEMPLATES.get(body.status, {})
                        if extra:
                            msg_text += extra.get(lang, extra.get("ru", ""))

                        await client.send_message(conv.telegram_chat_id, msg_text)

                        # Save notification as message
                        from src.conversations.models import Message
                        from datetime import datetime, timezone
                        notif_msg = Message(
                            tenant_id=user.tenant_id,
                            conversation_id=conv.id,
                            direction="outbound",
                            sender_type="system",
                            raw_text=msg_text,
                            ai_generated=False,
                        )
                        db.add(notif_msg)
                        conv.last_message_at = datetime.now(timezone.utc)
                        await db.flush()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Failed to notify user about status change")

    return (await _build_orders_out([order], db))[0]
