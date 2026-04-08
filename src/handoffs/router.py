from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_operator
from src.auth.models import User
from src.core.database import get_db
from src.handoffs.models import Handoff
from src.handoffs.schemas import HandoffCreate, HandoffOut, HandoffUpdate

router = APIRouter(prefix="/handoffs", tags=["handoffs"])


async def _build_handoffs_out(handoffs: list[Handoff], db: AsyncSession) -> list[HandoffOut]:
    """Build HandoffOut list with order numbers and conversation names — batched."""
    from src.orders.models import Order
    from src.conversations.models import Conversation

    # Collect IDs
    order_ids = {h.linked_order_id for h in handoffs if h.linked_order_id}
    conv_ids = {h.conversation_id for h in handoffs}
    user_ids = {h.assigned_to_user_id for h in handoffs if h.assigned_to_user_id}

    # Batch load (3 queries instead of 3*N)
    order_numbers: dict = {}
    conv_names: dict = {}
    user_names: dict = {}
    if order_ids:
        result = await db.execute(select(Order.id, Order.order_number).where(Order.id.in_(order_ids)))
        order_numbers = {row[0]: row[1] for row in result.fetchall()}
    if conv_ids:
        result = await db.execute(
            select(Conversation.id, Conversation.telegram_first_name, Conversation.telegram_username)
            .where(Conversation.id.in_(conv_ids))
        )
        for cid, first_name, username in result.fetchall():
            conv_names[cid] = first_name or username
    if user_ids:
        result = await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
        user_names = {row[0]: row[1] for row in result.fetchall()}

    out = []
    for h in handoffs:
        data = HandoffOut.model_validate(h)
        if h.linked_order_id and h.linked_order_id in order_numbers:
            data.linked_order_number = order_numbers[h.linked_order_id]
        if h.conversation_id in conv_names:
            data.conversation_name = conv_names[h.conversation_id]
        if h.assigned_to_user_id and h.assigned_to_user_id in user_names:
            data.assigned_to_user_name = user_names[h.assigned_to_user_id]
        out.append(data)
    return out


@router.get("", response_model=list[HandoffOut])
async def list_handoffs(
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Handoff).where(Handoff.tenant_id == user.tenant_id)
    if status:
        q = q.where(Handoff.status == status)
    q = q.order_by(Handoff.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    handoffs = result.scalars().all()
    return await _build_handoffs_out(handoffs, db)


@router.patch("/{handoff_id}", response_model=HandoffOut)
async def update_handoff(
    handoff_id: UUID,
    body: HandoffUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
):
    result = await db.execute(
        select(Handoff).where(Handoff.id == handoff_id, Handoff.tenant_id == user.tenant_id)
    )
    handoff = result.scalar_one_or_none()
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    if body.status:
        handoff.status = body.status
        if body.status == "resolved":
            handoff.resolved_at = datetime.now(timezone.utc)
            # Restore conversation from handoff status
            from src.conversations.models import Conversation
            conv_result = await db.execute(
                select(Conversation).where(Conversation.id == handoff.conversation_id)
            )
            conv = conv_result.scalar_one_or_none()
            if conv and conv.status == "handoff":
                conv.status = "active"
                conv.ai_enabled = True
    if body.assigned_to_user_id:
        handoff.assigned_to_user_id = body.assigned_to_user_id
    if body.resolution_notes is not None:
        handoff.resolution_notes = body.resolution_notes
    await db.flush()
    return (await _build_handoffs_out([handoff], db))[0]
