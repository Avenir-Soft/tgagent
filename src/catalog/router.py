from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
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
            "size": v.size, "price": v.price, "currency": v.currency,
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
@router.post("/products", response_model=ProductDetailOut, status_code=201)
async def create_product(
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    product = Product(tenant_id=user.tenant_id, **body.model_dump())
    db.add(product)
    await db.flush()
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
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = _product_query_with_relations().where(Product.tenant_id == user.tenant_id)
    if active_only:
        q = q.where(Product.is_active.is_(True))
    if category_id:
        q = q.where(Product.category_id == category_id)
    result = await db.execute(q.order_by(Product.created_at.desc()))
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
async def update_product(
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
    return ProductOut.model_validate(product)


# --- Variants ---
@router.post("/products/{product_id}/variants", response_model=VariantOut, status_code=201)
async def create_variant(
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
async def update_variant(
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
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(variant, field, value)
    await db.flush()
    return VariantOut.model_validate(variant)


@router.delete("/variants/{variant_id}", status_code=204)
async def delete_variant(
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
    await db.delete(variant)
    await db.flush()


# --- Inventory ---
@router.put("/inventory/{variant_id}", response_model=InventoryOut)
async def update_inventory(
    variant_id: UUID,
    body: InventoryUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
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
    return InventoryOut.model_validate(inv)


# --- Delivery Rules ---
@router.post("/delivery-rules", response_model=DeliveryRuleOut, status_code=201)
async def create_delivery_rule(
    body: DeliveryRuleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    rule = DeliveryRule(tenant_id=user.tenant_id, **body.model_dump())
    db.add(rule)
    await db.flush()
    return DeliveryRuleOut.model_validate(rule)


@router.get("/delivery-rules", response_model=list[DeliveryRuleOut])
async def list_delivery_rules(
    city: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(DeliveryRule).where(
        DeliveryRule.tenant_id == user.tenant_id,
    )
    if city:
        q = q.where(DeliveryRule.city == city)
    result = await db.execute(q)
    return [DeliveryRuleOut.model_validate(r) for r in result.scalars().all()]


@router.post("/delivery-rules/import-csv")
async def import_delivery_rules_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Import delivery rules from CSV. Expected columns: city,zone,delivery_type,price,eta_min_days,eta_max_days,cod_available"""
    import csv
    import io

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="No file uploaded")
        raw = await file.read()
        text = raw.decode("utf-8-sig")
    else:
        body_bytes = await request.body()
        text = body_bytes.decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(text), delimiter=",")
    created = 0
    errors = []
    for i, row in enumerate(reader, start=2):
        try:
            rule = DeliveryRule(
                tenant_id=user.tenant_id,
                city=row.get("city") or None,
                zone=row.get("zone") or None,
                delivery_type=row.get("delivery_type", "courier"),
                price=float(row.get("price", 0)),
                eta_min_days=int(row.get("eta_min_days", 1)),
                eta_max_days=int(row.get("eta_max_days", 3)),
                cod_available=row.get("cod_available", "").lower() in ("true", "1", "yes", "да"),
            )
            db.add(rule)
            created += 1
        except Exception as e:
            errors.append(f"Row {i}: {e}")
    await db.flush()
    return {"created": created, "errors": errors}


@router.patch("/delivery-rules/{rule_id}", response_model=DeliveryRuleOut)
async def update_delivery_rule(
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
    await db.flush()
    await db.refresh(rule)
    return DeliveryRuleOut.model_validate(rule)


@router.delete("/delivery-rules/{rule_id}", status_code=204)
async def delete_delivery_rule(
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
async def create_category(
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
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Category).where(
            Category.tenant_id == user.tenant_id,
            Category.is_active.is_(True),
        ).order_by(Category.name)
    )
    return [CategoryOut.model_validate(c) for c in result.scalars().all()]


# --- Product Aliases ---
@router.post("/products/{product_id}/aliases", response_model=ProductAliasOut, status_code=201)
async def create_product_alias(
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
async def delete_product_alias(
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
async def create_product_media(
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
async def delete_product_media(
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
