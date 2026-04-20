import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.catalog.models import (
    Category,
    DeliveryRule,
    Inventory,
    Product,
    ProductAlias,
    ProductMedia,
    ProductVariant,
)
from src.catalog.schemas import (
    CategoryCreate,
    CategoryOut,
    DeliveryRuleCreate,
    DeliveryRuleOut,
    DeliveryRuleUpdate,
    InventoryOut,
    InventoryUpdate,
    ProductAliasCreate,
    ProductAliasOut,
    ProductCreate,
    ProductDetailOut,
    ProductMediaCreate,
    ProductMediaOut,
    ProductOut,
    ProductUpdate,
    VariantCreate,
    VariantOut,
    VariantUpdate,
)

from src.ai.truth_tools import invalidate_catalog_cache

router = APIRouter(tags=["catalog"])


def _build_product_detail(product: Product) -> ProductDetailOut:
    """Build a rich product response with variants, stock, and price range."""
    variants = product.variants or []
    aliases = product.aliases or []
    active_variants = [v for v in variants if v.is_active]

    prices = [v.price for v in active_variants]
    total_stock = 0
    variant_list = []
    for v in active_variants:
        stock = 0
        reserved = 0
        for inv in (v.inventory or []):
            stock += inv.quantity - inv.reserved_quantity
            reserved += inv.reserved_quantity
        total_stock += stock
        vd = {
            "id": v.id, "title": v.title, "sku": v.sku,
            "color": v.color, "storage": v.storage, "ram": v.ram,
            "size": v.size, "attributes_json": v.attributes_json,
            "price": v.price, "currency": v.currency,
            "is_active": v.is_active, "stock": stock, "reserved": reserved,
        }
        variant_list.append(vd)

    category_name = product.category.name if product.category else None

    data = ProductOut.model_validate(product).model_dump()
    data["variants"] = variant_list
    data["aliases"] = aliases
    data["total_stock"] = total_stock
    data["min_price"] = min(prices) if prices else None
    data["max_price"] = max(prices) if prices else None
    data["category_name"] = category_name
    # First image URL from product media
    media_list = sorted((product.media or []), key=lambda m: m.sort_order)
    data["image_url"] = media_list[0].url if media_list else None
    return ProductDetailOut(**data)


# --- Products ---
def _slugify(text: str) -> str:
    """Generate URL-safe slug from text (supports cyrillic)."""
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")[:500]


@router.post("/products", response_model=ProductDetailOut, status_code=201)
@limiter.limit("30/minute")
async def create_product(
    request: Request,
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    # Auto-generate slug from name if not provided
    data = body.model_dump(exclude={"variants"})
    if not data.get("slug"):
        data["slug"] = _slugify(body.name)
    product = Product(tenant_id=user.tenant_id, **data)
    db.add(product)
    await db.flush()

    # Create inline variants if provided
    if body.variants:
        for v in body.variants:
            variant = ProductVariant(
                tenant_id=user.tenant_id,
                product_id=product.id,
                **v.model_dump(),
            )
            db.add(variant)
        await db.flush()

    # Invalidate AI search cache so new product is immediately visible
    await invalidate_catalog_cache(user.tenant_id)

    # Re-fetch with eager-loaded relationships to avoid MissingGreenlet
    result = await db.execute(
        _product_query_with_relations().where(Product.id == product.id)
    )
    product = result.scalar_one()
    return _build_product_detail(product)


def _product_query_with_relations():
    """Base query with all relationships eagerly loaded."""
    return select(Product).options(
        selectinload(Product.variants).selectinload(ProductVariant.inventory),
        selectinload(Product.aliases),
        selectinload(Product.category),
        selectinload(Product.media),
    )


@router.get("/products", response_model=list[ProductDetailOut])
async def list_products(
    category_id: UUID | None = None,
    active_only: bool = False,
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = _product_query_with_relations().where(Product.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(Product.is_active.is_(True))
    if category_id:
        q = q.where(Product.category_id == category_id)
    result = await db.execute(q.order_by(Product.created_at.desc()).offset(offset).limit(limit))
    return [_build_product_detail(p) for p in result.scalars().unique().all()]


@router.get("/products/{product_id}", response_model=ProductDetailOut)
async def get_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        _product_query_with_relations().where(
            Product.id == product_id, Product.tenant_id == user.tenant_id
        )
    )
    product = result.scalars().unique().one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _build_product_detail(product)


@router.patch("/products/{product_id}", response_model=ProductOut)
@limiter.limit("30/minute")
async def update_product(
    request: Request,
    product_id: UUID,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == user.tenant_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await db.flush()
    await invalidate_catalog_cache(user.tenant_id)
    return ProductOut.model_validate(product)


# --- Variants ---
@router.post("/products/{product_id}/variants", response_model=VariantOut, status_code=201)
@limiter.limit("30/minute")
async def create_variant(
    request: Request,
    product_id: UUID,
    body: VariantCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    # verify product belongs to tenant
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == user.tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")
    variant = ProductVariant(tenant_id=user.tenant_id, product_id=product_id, **body.model_dump())
    db.add(variant)
    await db.flush()
    await invalidate_catalog_cache(user.tenant_id)
    return VariantOut.model_validate(variant)


@router.get("/products/{product_id}/variants", response_model=list[VariantOut])
async def list_variants(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.product_id == product_id,
            ProductVariant.tenant_id == user.tenant_id,
        )
    )
    return [VariantOut.model_validate(v) for v in result.scalars().all()]


@router.patch("/variants/{variant_id}", response_model=VariantOut)
@limiter.limit("30/minute")
async def update_variant(
    request: Request,
    variant_id: UUID,
    body: VariantUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id,
            ProductVariant.tenant_id == user.tenant_id,
        )
    )
    variant = result.scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")

    # Save old attributes for change detection
    old_attrs = dict(variant.attributes_json or {})

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(variant, field, value)
    await db.flush()
    await invalidate_catalog_cache(user.tenant_id)

    # Detect attributes_json changes → notify affected customers
    new_attrs = dict(variant.attributes_json or {})
    if old_attrs != new_attrs:
        import asyncio
        asyncio.create_task(_notify_variant_change(
            tenant_id=user.tenant_id,
            variant_id=variant_id,
            variant_title=variant.title,
            product_id=variant.product_id,
            old_attrs=old_attrs,
            new_attrs=new_attrs,
        ))

    return VariantOut.model_validate(variant)


async def _notify_variant_change(
    tenant_id: UUID,
    variant_id: UUID,
    variant_title: str,
    product_id: UUID,
    old_attrs: dict,
    new_attrs: dict,
):
    """Background task: notify affected customers when variant attributes change.

    Sends Telegram DM to customers with confirmed/pending_payment orders for this variant,
    and posts to the tour group if it exists.
    """
    import asyncio
    import logging
    logger = logging.getLogger("catalog.notify")

    try:
        from src.telegram.service import telegram_manager
        client = telegram_manager.get_client(tenant_id)
        if not client:
            logger.warning("No Telegram client — skipping variant change notifications")
            return

        from src.core.database import async_session_factory
        async with async_session_factory() as db:
            # Get product (tour) name
            prod_result = await db.execute(
                select(Product.name).where(Product.id == product_id)
            )
            product_name = prod_result.scalar_one_or_none() or "Tur"

            # Build notification text from changed fields
            changes = []
            old_mp = old_attrs.get("meeting_point", "")
            new_mp = new_attrs.get("meeting_point", "")
            if old_mp != new_mp and new_mp:
                changes.append(f"📍 Yangi yig'ilish joyi: {new_mp}")

            old_time = old_attrs.get("departure_time") or old_attrs.get("time", "")
            new_time = new_attrs.get("departure_time") or new_attrs.get("time", "")
            if old_time != new_time and new_time:
                changes.append(f"⏰ Yangi vaqt: {new_time}")

            _ATTR_LABELS = {
                "included": "🎒 Kiradi",
                "what_to_bring": "📋 Olib kelish kerak",
            }
            for key in sorted(set(list(old_attrs.keys()) + list(new_attrs.keys()))):
                if key in ("meeting_point", "departure_time", "time"):
                    continue
                if old_attrs.get(key) != new_attrs.get(key) and new_attrs.get(key):
                    label = _ATTR_LABELS.get(key, key)
                    changes.append(f"{label}: {new_attrs[key]}")

            if not changes:
                return

            dm_msg = (
                f"⚠️ Muhim o'zgarish!\n\n"
                f"{product_name} — {variant_title}\n\n"
                + "\n".join(changes)
                + "\n\nNoqulaylik uchun uzr so'raymiz!"
            )

            # Find customers who booked this variant (confirmed or pending_payment)
            from src.orders.models import Order, OrderItem
            from src.leads.models import Lead

            order_result = await db.execute(
                select(Order.lead_id).distinct()
                .join(OrderItem, Order.id == OrderItem.order_id)
                .where(
                    Order.tenant_id == tenant_id,
                    Order.status.in_(["confirmed", "pending_payment"]),
                    OrderItem.product_variant_id == variant_id,
                )
            )
            lead_ids = [r[0] for r in order_result.fetchall() if r[0]]

            if not lead_ids:
                logger.info("No affected customers for variant %s change", variant_id)
                return

            lead_result = await db.execute(
                select(Lead.telegram_user_id).where(
                    Lead.id.in_(lead_ids),
                    Lead.telegram_user_id.isnot(None),
                )
            )
            user_ids = [r[0] for r in lead_result.fetchall()]

            # Send DM to each affected customer
            sent = 0
            for tg_user_id in user_ids:
                try:
                    entity = await client.get_input_entity(tg_user_id)
                    await client.send_message(entity, dm_msg)
                    sent += 1
                    await asyncio.sleep(0.5)  # avoid flood
                except Exception as e:
                    logger.warning("Failed to notify user %s: %s", tg_user_id, e)

            logger.info("Notified %d/%d customers about variant %s change", sent, len(user_ids), variant_id)

            # Send to tour group (search by title pattern)
            group_prefix = f"Easy Tour | {product_name}"
            try:
                dialogs = await client.get_dialogs(limit=100)
                for d in dialogs:
                    if d.is_group and d.title and d.title.startswith(group_prefix):
                        group_msg = (
                            f"📢 O'zgarish!\n\n"
                            f"{variant_title} sanasi uchun:\n\n"
                            + "\n".join(changes)
                        )
                        await client.send_message(d.entity, group_msg)
                        logger.info("Sent group notification to: %s", d.title)
            except Exception:
                logger.warning("Failed to send group notification", exc_info=True)

    except Exception:
        logger.exception("Variant change notification failed (non-fatal)")


@router.delete("/variants/{variant_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_variant(
    request: Request,
    variant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id,
            ProductVariant.tenant_id == user.tenant_id,
        )
    )
    variant = result.scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")
    # Prevent deletion if variant is referenced by existing orders
    from src.orders.models import OrderItem
    order_ref = await db.execute(
        select(OrderItem.id).where(OrderItem.product_variant_id == variant_id).limit(1)
    )
    if order_ref.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Cannot delete variant: referenced by existing orders")
    await db.delete(variant)
    await db.flush()
    await invalidate_catalog_cache(user.tenant_id)


# --- Inventory ---
@router.put("/inventory/{variant_id}", response_model=InventoryOut)
@limiter.limit("30/minute")
async def update_inventory(
    request: Request,
    variant_id: UUID,
    body: InventoryUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    if body.reserved_quantity > body.quantity:
        raise HTTPException(status_code=400, detail="reserved_quantity cannot exceed quantity")
    result = await db.execute(
        select(Inventory).where(
            Inventory.variant_id == variant_id,
            Inventory.tenant_id == user.tenant_id,
        )
    )
    inv = result.scalar_one_or_none()
    if inv:
        inv.quantity = body.quantity
        inv.reserved_quantity = body.reserved_quantity
    else:
        inv = Inventory(
            tenant_id=user.tenant_id,
            variant_id=variant_id,
            quantity=body.quantity,
            reserved_quantity=body.reserved_quantity,
        )
        db.add(inv)
    await db.flush()
    await invalidate_catalog_cache(user.tenant_id)
    return InventoryOut.model_validate(inv)


# --- Delivery Rules ---
@router.post("/delivery-rules", response_model=DeliveryRuleOut, status_code=201)
@limiter.limit("30/minute")
async def create_delivery_rule(
    request: Request,
    body: DeliveryRuleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    if body.eta_min_days > body.eta_max_days:
        raise HTTPException(status_code=400, detail="eta_min_days cannot exceed eta_max_days")
    rule = DeliveryRule(tenant_id=user.tenant_id, **body.model_dump())
    db.add(rule)
    await db.flush()
    return DeliveryRuleOut.model_validate(rule)


@router.get("/delivery-rules", response_model=list[DeliveryRuleOut])
async def list_delivery_rules(
    city: str | None = None,
    limit: int = Query(500, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(DeliveryRule).where(
        DeliveryRule.tenant_id == user.tenant_id,
    )
    if city:
        q = q.where(DeliveryRule.city == city)
    result = await db.execute(q.offset(offset).limit(limit))
    return [DeliveryRuleOut.model_validate(r) for r in result.scalars().all()]


@router.post("/delivery-rules/import-csv")
@limiter.limit("10/minute")
async def import_delivery_rules_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Import delivery rules from CSV. Expected columns: city,zone,delivery_type,price,eta_min_days,eta_max_days,cod_available"""
    import csv
    import io

    MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 MB

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="No file uploaded")
        raw = await file.read()
        if len(raw) > MAX_CSV_SIZE:
            raise HTTPException(status_code=400, detail=f"Файл слишком большой (макс. {MAX_CSV_SIZE // 1024 // 1024} МБ)")
        text = raw.decode("utf-8-sig")
    else:
        body_bytes = await request.body()
        if len(body_bytes) > MAX_CSV_SIZE:
            raise HTTPException(status_code=400, detail=f"Файл слишком большой (макс. {MAX_CSV_SIZE // 1024 // 1024} МБ)")
        text = body_bytes.decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(text), delimiter=",")
    created = 0
    errors = []
    for i, row in enumerate(reader, start=2):
        try:
            eta_min = int(row.get("eta_min_days", 1))
            eta_max = int(row.get("eta_max_days", 3))
            if eta_min > eta_max:
                errors.append(f"Row {i}: eta_min_days ({eta_min}) > eta_max_days ({eta_max})")
                continue
            rule = DeliveryRule(
                tenant_id=user.tenant_id,
                city=row.get("city") or None,
                zone=row.get("zone") or None,
                delivery_type=row.get("delivery_type", "courier"),
                price=float(row.get("price", 0)),
                eta_min_days=eta_min,
                eta_max_days=eta_max,
                cod_available=row.get("cod_available", "").lower() in ("true", "1", "yes", "да"),
            )
            db.add(rule)
            created += 1
        except Exception as e:
            errors.append(f"Row {i}: {e}")
    await db.flush()
    return {"created": created, "errors": errors}


@router.patch("/delivery-rules/{rule_id}", response_model=DeliveryRuleOut)
@limiter.limit("30/minute")
async def update_delivery_rule(
    request: Request,
    rule_id: UUID,
    body: DeliveryRuleUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(DeliveryRule).where(
            DeliveryRule.id == rule_id,
            DeliveryRule.tenant_id == user.tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Delivery rule not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    if rule.eta_min_days > rule.eta_max_days:
        raise HTTPException(status_code=400, detail="eta_min_days cannot exceed eta_max_days")
    await db.flush()
    await db.refresh(rule)
    return DeliveryRuleOut.model_validate(rule)


@router.delete("/delivery-rules/{rule_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_delivery_rule(
    request: Request,
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(DeliveryRule).where(
            DeliveryRule.id == rule_id,
            DeliveryRule.tenant_id == user.tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Delivery rule not found")
    await db.delete(rule)
    return None


# --- Categories ---
@router.post("/categories", response_model=CategoryOut, status_code=201)
@limiter.limit("30/minute")
async def create_category(
    request: Request,
    body: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    category = Category(tenant_id=user.tenant_id, **body.model_dump())
    db.add(category)
    await db.flush()
    return CategoryOut.model_validate(category)


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    limit: int = Query(200, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Category).where(
            Category.tenant_id == user.tenant_id,
            Category.is_active.is_(True),
        ).order_by(Category.name).offset(offset).limit(limit)
    )
    return [CategoryOut.model_validate(c) for c in result.scalars().all()]


# --- Product Aliases ---
@router.post("/products/{product_id}/aliases", response_model=ProductAliasOut, status_code=201)
@limiter.limit("30/minute")
async def create_product_alias(
    request: Request,
    product_id: UUID,
    body: ProductAliasCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    # verify product belongs to tenant
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == user.tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")
    alias = ProductAlias(
        tenant_id=user.tenant_id, product_id=product_id, **body.model_dump()
    )
    db.add(alias)
    await db.flush()
    return ProductAliasOut.model_validate(alias)


@router.get("/products/{product_id}/aliases", response_model=list[ProductAliasOut])
async def list_product_aliases(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ProductAlias).where(
            ProductAlias.product_id == product_id,
            ProductAlias.tenant_id == user.tenant_id,
        ).order_by(ProductAlias.priority.desc())
    )
    return [ProductAliasOut.model_validate(a) for a in result.scalars().all()]


@router.delete("/aliases/{alias_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_product_alias(
    request: Request,
    alias_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(ProductAlias).where(
            ProductAlias.id == alias_id,
            ProductAlias.tenant_id == user.tenant_id,
        )
    )
    alias = result.scalar_one_or_none()
    if not alias:
        raise HTTPException(status_code=404, detail="Alias not found")
    await db.delete(alias)
    await db.flush()


# --- Product Media ---
@router.post("/products/{product_id}/media", response_model=ProductMediaOut, status_code=201)
@limiter.limit("30/minute")
async def create_product_media(
    request: Request,
    product_id: UUID,
    body: ProductMediaCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    # verify product belongs to tenant
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == user.tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")
    media = ProductMedia(
        tenant_id=user.tenant_id, product_id=product_id, **body.model_dump()
    )
    db.add(media)
    await db.flush()
    return ProductMediaOut.model_validate(media)


@router.get("/products/{product_id}/media", response_model=list[ProductMediaOut])
async def list_product_media(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ProductMedia).where(
            ProductMedia.product_id == product_id,
            ProductMedia.tenant_id == user.tenant_id,
        ).order_by(ProductMedia.sort_order)
    )
    return [ProductMediaOut.model_validate(m) for m in result.scalars().all()]


@router.delete("/media/{media_id}", status_code=204)
@limiter.limit("20/minute")
async def delete_product_media(
    request: Request,
    media_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(ProductMedia).where(
            ProductMedia.id == media_id,
            ProductMedia.tenant_id == user.tenant_id,
        )
    )
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    await db.delete(media)
    await db.flush()


@router.get("/products/{product_id}/sales")
async def get_product_sales(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sales history for a specific product."""
    from sqlalchemy import func
    from src.orders.models import Order, OrderItem

    result = await db.execute(
        select(
            Order.order_number,
            Order.customer_name,
            Order.status,
            Order.created_at,
            OrderItem.qty,
            OrderItem.unit_price,
            OrderItem.total_price,
            ProductVariant.title.label("variant_title"),
        )
        .join(OrderItem, Order.id == OrderItem.order_id)
        .outerjoin(ProductVariant, OrderItem.product_variant_id == ProductVariant.id)
        .where(
            Order.tenant_id == user.tenant_id,
            OrderItem.product_id == product_id,
        )
        .order_by(Order.created_at.desc())
        .limit(50)
    )
    rows = result.all()

    # Summary stats
    total_qty = sum(r.qty for r in rows if r.status != "cancelled")
    total_revenue = sum(float(r.total_price) for r in rows if r.status != "cancelled")

    return {
        "total_sold": total_qty,
        "total_revenue": total_revenue,
        "orders": [
            {
                "order_number": r.order_number,
                "customer": r.customer_name,
                "status": r.status,
                "variant": r.variant_title,
                "qty": r.qty,
                "price": float(r.unit_price),
                "total": float(r.total_price),
                "date": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ────────────────────────────────────────────────────────
# Smart Product Creation — AI-powered endpoints
# ────────────────────────────────────────────────────────

import json as _json
import os as _os
import uuid as _uuid
from fastapi import File, Form, UploadFile


@router.post("/upload/image")
@limiter.limit("60/minute")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_store_owner),
):
    """Upload an image file → returns URL. Max 10MB, images only."""
    max_size = 10 * 1024 * 1024
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}

    if file.content_type not in allowed:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    data = await file.read()
    if len(data) > max_size:
        raise HTTPException(400, "File too large (max 10MB)")

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp", "gif", "avif"):
        ext = "jpg"

    filename = f"{_uuid.uuid4().hex}.{ext}"
    tenant_dir = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
        "uploads", str(user.tenant_id),
    )
    _os.makedirs(tenant_dir, exist_ok=True)
    filepath = _os.path.join(tenant_dir, filename)

    with open(filepath, "wb") as f:
        f.write(data)

    url = f"/uploads/{user.tenant_id}/{filename}"
    return {"url": url, "filename": filename}


@router.post("/products/ai-generate")
@limiter.limit("20/minute")
async def ai_generate_product(
    request: Request,
    body: dict,
    user: User = Depends(require_store_owner),
    db: AsyncSession = Depends(get_db),
):
    """AI generates product specs, variants, aliases from a name.

    Input: {"name": "iPhone 15 Pro"}
    Returns: category, brand, model, spec_axes, aliases, description
    """
    import openai
    from src.core.config import settings

    name = (body.get("name") or "").strip()
    if not name or len(name) < 2:
        raise HTTPException(400, "Product name is required (min 2 chars)")

    # Get existing categories for context
    cat_result = await db.execute(
        select(Category.name).where(
            Category.tenant_id == user.tenant_id, Category.is_active.is_(True)
        )
    )
    existing_categories = [r[0] for r in cat_result.fetchall()]

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    system_prompt = """You are a product catalog assistant for an electronics/household store in Uzbekistan.
Given a product name, generate structured data for the catalog.

Return ONLY valid JSON (no markdown, no code blocks):
{
  "category": "category name in Russian (e.g. Смартфоны, Наушники, Телевизоры, Ноутбуки, Аксессуары, Бытовая техника)",
  "brand": "brand name",
  "model": "model name without brand",
  "description": "short description in Russian, 1-2 sentences",
  "spec_axes": {
    "color": ["color1", "color2", ...],
    "storage": ["128GB", "256GB", ...] or null if not applicable,
    "ram": ["8GB", ...] or null if not applicable,
    "size": ["size1", ...] or null if not applicable
  },
  "aliases": ["alias1", "alias2", ...],
  "base_title_template": "{color} {storage} {ram}"
}

RULES:
- spec_axes: only include axes that apply to this product type. Phones have color+storage+ram. Headphones have color only. TVs have size. Washing machines might have capacity.
- aliases: generate 8-15 search aliases in Russian, Uzbek (cyrillic), Uzbek (latin), English, and common typos. Include: brand+model, model only, brand in cyrillic, common abbreviations, category words.
- colors: use ORIGINAL English color names as the manufacturer uses them (e.g. "Titanium Black", "Silver", "Natural Titanium", "Desert Titanium"). Do NOT translate to Russian.
- base_title_template: template for generating variant title from specs. Use {color}, {storage}, {ram}, {size} placeholders.
- If product is simple (no variants like a single-SKU item), set spec_axes with only color: ["Standard"] or similar."""

    user_msg = f"Product name: {name}"
    if existing_categories:
        user_msg += f"\n\nExisting categories in store: {', '.join(existing_categories)}"

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model_main,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=800,
            temperature=0.3,
        )
        content = (response.choices[0].message.content or "").strip()
        # Strip markdown code blocks if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        result = _json.loads(content)
    except _json.JSONDecodeError:
        raise HTTPException(500, "AI returned invalid JSON — try again")
    except Exception as e:
        raise HTTPException(500, f"AI generation failed: {str(e)}")

    # Check for existing product with same name
    existing = await db.execute(
        select(Product.id, Product.name).where(
            Product.tenant_id == user.tenant_id,
            Product.name.ilike(f"%{name}%"),
            Product.is_active.is_(True),
        ).limit(3)
    )
    duplicates = [{"id": str(r[0]), "name": r[1]} for r in existing.fetchall()]
    if duplicates:
        result["possible_duplicates"] = duplicates

    return result


@router.post("/products/smart-create", response_model=ProductDetailOut, status_code=201)
@limiter.limit("20/minute")
async def smart_create_product(
    request: Request,
    payload: str = Form(...),
    photos: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Create a product with variants, inventory, aliases, and photos in one request.

    payload (form field, JSON string):
    {
      "name": "iPhone 15 Pro",
      "brand": "Apple",
      "model": "iPhone 15 Pro",
      "description": "...",
      "category_name": "Смартфоны",
      "variants": [
        {"color": "Blue", "storage": "128GB", "ram": "8GB", "price": 15200000, "quantity": 3},
        ...
      ],
      "aliases": ["айфон 15 про", ...],
      "photo_mapping": {
        "main": "photo_0",
        "colors": {"Blue": "photo_1", "Black": "photo_2"}
      }
    }

    photos: uploaded files with names matching photo_mapping values
    """
    try:
        data = _json.loads(payload)
    except _json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON in payload")

    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Product name is required")

    variants_data = data.get("variants", [])
    if not variants_data:
        raise HTTPException(400, "At least one variant is required")

    aliases_data = data.get("aliases", [])
    photo_mapping = data.get("photo_mapping", {})

    # --- 1. Resolve or create category ---
    category_id = None
    category_name = (data.get("category_name") or "").strip()
    if category_name:
        cat_result = await db.execute(
            select(Category).where(
                Category.tenant_id == user.tenant_id,
                Category.name.ilike(category_name),
            )
        )
        category = cat_result.scalar_one_or_none()
        if not category:
            category = Category(
                tenant_id=user.tenant_id,
                name=category_name,
                slug=_slugify(category_name),
            )
            db.add(category)
            await db.flush()
        category_id = category.id

    # --- 2. Create product ---
    product = Product(
        tenant_id=user.tenant_id,
        name=name,
        slug=_slugify(name),
        brand=(data.get("brand") or "").strip() or None,
        model=(data.get("model") or "").strip() or None,
        description=(data.get("description") or "").strip() or None,
        category_id=category_id,
    )
    db.add(product)
    await db.flush()

    # --- 3. Create variants + inventory ---
    # Map color → list of variant IDs (for photo assignment)
    color_variant_ids: dict[str, list] = {}

    for v in variants_data:
        color = (v.get("color") or "").strip() or None
        storage = (v.get("storage") or "").strip() or None
        ram = (v.get("ram") or "").strip() or None
        size = (v.get("size") or "").strip() or None
        price = v.get("price", 0)
        quantity = v.get("quantity", 0)

        # Build title from specs
        title_parts = [p for p in [color, storage, ram, size] if p]
        title = v.get("title") or " ".join(title_parts) or name

        variant = ProductVariant(
            tenant_id=user.tenant_id,
            product_id=product.id,
            title=title,
            color=color,
            storage=storage,
            ram=ram,
            size=size,
            price=price,
            currency=v.get("currency", "UZS"),
        )
        db.add(variant)
        await db.flush()

        # Create inventory
        if quantity > 0:
            inv = Inventory(
                tenant_id=user.tenant_id,
                variant_id=variant.id,
                quantity=quantity,
                reserved_quantity=0,
            )
            db.add(inv)

        # Track color → variants for photo mapping
        if color:
            color_variant_ids.setdefault(color, []).append(variant.id)

    await db.flush()

    # --- 4. Create aliases ---
    seen_aliases = set()
    for alias_text in aliases_data:
        alias_clean = alias_text.strip().lower()
        if alias_clean and alias_clean not in seen_aliases and len(alias_clean) <= 300:
            seen_aliases.add(alias_clean)
            db.add(ProductAlias(
                tenant_id=user.tenant_id,
                product_id=product.id,
                alias_text=alias_clean,
            ))
    await db.flush()

    # --- 5. Upload photos and create media ---
    # Index uploaded files by field name
    photo_files: dict[str, UploadFile] = {}
    for i, f in enumerate(photos):
        # Files come as photo_0, photo_1, etc. or by filename
        photo_files[f"photo_{i}"] = f

    upload_base = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
        "uploads", str(user.tenant_id),
    )
    _os.makedirs(upload_base, exist_ok=True)

    async def _save_photo(upload_file: UploadFile) -> str:
        """Save uploaded file and return URL."""
        file_data = await upload_file.read()
        ext = upload_file.filename.rsplit(".", 1)[-1].lower() if upload_file.filename and "." in upload_file.filename else "jpg"
        if ext not in ("jpg", "jpeg", "png", "webp", "gif", "avif"):
            ext = "jpg"
        fname = f"{_uuid.uuid4().hex}.{ext}"
        path = _os.path.join(upload_base, fname)
        with open(path, "wb") as fp:
            fp.write(file_data)
        return f"/uploads/{user.tenant_id}/{fname}"

    # Main photo
    main_photo_key = photo_mapping.get("main")
    if main_photo_key and main_photo_key in photo_files:
        url = await _save_photo(photo_files[main_photo_key])
        db.add(ProductMedia(
            tenant_id=user.tenant_id,
            product_id=product.id,
            variant_id=None,
            url=url,
            sort_order=0,
        ))

    # Color photos → assign to all variants of that color
    color_photo_map = photo_mapping.get("colors", {})
    for color_name, photo_key in color_photo_map.items():
        if photo_key in photo_files:
            url = await _save_photo(photo_files[photo_key])
            variant_ids = color_variant_ids.get(color_name, [])
            if variant_ids:
                for vid in variant_ids:
                    db.add(ProductMedia(
                        tenant_id=user.tenant_id,
                        product_id=product.id,
                        variant_id=vid,
                        url=url,
                        sort_order=1,
                    ))
            else:
                # No variants with this color — add as product-level
                db.add(ProductMedia(
                    tenant_id=user.tenant_id,
                    product_id=product.id,
                    variant_id=None,
                    url=url,
                    sort_order=1,
                ))

    await db.flush()

    # Invalidate cache
    await invalidate_catalog_cache(user.tenant_id)

    # Re-fetch with relations
    result = await db.execute(
        _product_query_with_relations().where(Product.id == product.id)
    )
    product = result.scalar_one()
    return _build_product_detail(product)
