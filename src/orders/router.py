"""Orders API — thin HTTP handlers delegating to service layer."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.orders.models import Order, OrderItem
from src.orders.schemas import OrderCreate, OrderOut, OrderUpdate
from src.orders.service import build_orders_out, create_order as svc_create_order, update_order as svc_update_order
from src.core.audit import log_audit
from src.platform.deps import check_not_read_only

router = APIRouter(prefix="/orders", tags=["orders"])


def _order_query(tenant_id: UUID):
    return select(Order).where(Order.tenant_id == tenant_id).options(selectinload(Order.items))


@router.post("", response_model=OrderOut, status_code=201, dependencies=[Depends(check_not_read_only)])
@limiter.limit("30/minute")
async def create_order(
    request: Request,
    body: OrderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        order = await svc_create_order(user.tenant_id, body, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "order.create", "order", str(order.id),
        {"order_number": order.order_number, "customer_name": body.customer_name, "items_count": len(body.items)},
    )
    return (await build_orders_out([order], db))[0]


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: str | None = None,
    lead_id: UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = _order_query(user.tenant_id)
    if status:
        q = q.where(Order.status == status.strip().lower())
    if lead_id:
        q = q.where(Order.lead_id == lead_id)
    q = q.order_by(Order.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    orders = result.scalars().unique().all()
    return await build_orders_out(orders, db)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(_order_query(user.tenant_id).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return (await build_orders_out([order], db))[0]


@router.patch("/{order_id}", response_model=OrderOut, dependencies=[Depends(check_not_read_only)])
@limiter.limit("30/minute")
async def update_order(
    request: Request,
    order_id: UUID,
    body: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(_order_query(user.tenant_id).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    old_status = order.status
    try:
        order = await svc_update_order(user.tenant_id, order, body, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    meta = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if body.status and body.status != old_status:
        meta["old_status"] = old_status
        meta["new_status"] = body.status
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "order.update", "order", str(order_id), meta,
    )
    return (await build_orders_out([order], db))[0]


@router.delete("/{order_id}", status_code=204, dependencies=[Depends(check_not_read_only)])
@limiter.limit("20/minute")
async def delete_order(
    request: Request,
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == user.tenant_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in ("cancelled", "returned"):
        raise HTTPException(status_code=400, detail="Можно удалить только отменённые/возвращённые заказы")
    order_number = order.order_number
    await db.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
    await db.delete(order)
    await db.flush()
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "order.delete", "order", str(order_id),
        {"order_number": order_number, "status": order.status},
    )


@router.delete("", status_code=200, dependencies=[Depends(check_not_read_only)])
@limiter.limit("10/minute")
async def delete_cancelled_orders(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Order).where(Order.tenant_id == user.tenant_id, Order.status.in_(["cancelled", "returned"]))
    )
    orders = result.scalars().all()
    count = len(orders)
    for order in orders:
        await db.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
        await db.delete(order)
    await db.flush()
    return {"deleted": count}
