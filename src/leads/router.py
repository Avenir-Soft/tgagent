import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.leads.models import Lead
from src.leads.schemas import LeadOut, LeadUpdate
from src.orders.models import Order

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=list[LeadOut])
async def list_leads(
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Lead).where(Lead.tenant_id == user.tenant_id)
    if status:
        q = q.where(Lead.status == status)
    q = q.order_by(Lead.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    leads = result.scalars().all()

    # Batch-load order counts
    lead_ids = [l.id for l in leads]
    order_counts: dict = {}
    if lead_ids:
        oc_result = await db.execute(
            select(Order.lead_id, func.count(Order.id))
            .where(Order.lead_id.in_(lead_ids))
            .group_by(Order.lead_id)
        )
        order_counts = dict(oc_result.all())

    out = []
    for l in leads:
        lead_out = LeadOut.model_validate(l)
        lead_out.order_count = order_counts.get(l.id, 0)
        out.append(lead_out)
    return out


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.tenant_id == user.tenant_id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead_out = LeadOut.model_validate(lead)
    oc_result = await db.execute(
        select(func.count(Order.id)).where(Order.lead_id == lead.id)
    )
    lead_out.order_count = oc_result.scalar() or 0
    return lead_out


@router.patch("/{lead_id}", response_model=LeadOut)
@limiter.limit("30/minute")
async def update_lead(
    request: Request,
    lead_id: UUID,
    body: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.tenant_id == user.tenant_id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)
    await db.flush()
    return LeadOut.model_validate(lead)


@router.post("/refresh-avatars", status_code=200)
@limiter.limit("10/minute")
async def refresh_avatars(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Download Telegram avatars for all leads that don't have one yet."""
    import os
    from src.telegram.service import telegram_manager

    client = telegram_manager.get_client(user.tenant_id)
    if not client:
        raise HTTPException(status_code=400, detail="Telegram not connected")

    result = await db.execute(
        select(Lead).where(
            Lead.tenant_id == user.tenant_id,
            Lead.avatar_url.is_(None),
            Lead.telegram_user_id.isnot(None),
        )
    )
    leads = result.scalars().all()
    updated = 0
    avatars_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "avatars")
    os.makedirs(avatars_dir, exist_ok=True)

    for lead in leads:
        try:
            # Resolve entity — after restart Telethon may not have the peer cached
            try:
                entity = await client.get_input_entity(lead.telegram_user_id)
            except ValueError:
                if lead.telegram_username:
                    entity = await client.get_input_entity(lead.telegram_username)
                else:
                    continue
            avatar_path = os.path.join(avatars_dir, f"{lead.id}.jpg")
            downloaded = await client.download_profile_photo(
                entity, file=avatar_path, download_big=False
            )
            if downloaded:
                lead.avatar_url = f"/static/avatars/{lead.id}.jpg"
                updated += 1
            elif os.path.exists(avatar_path):
                os.remove(avatar_path)
        except Exception as e:
            logger.debug("Failed to download avatar for lead %s: %s", lead.id, e)
            continue
    await db.flush()
    return {"total": len(leads), "updated": updated}
