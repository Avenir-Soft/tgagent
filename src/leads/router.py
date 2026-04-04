from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.leads.models import Lead
from src.leads.schemas import LeadCreate, LeadOut, LeadUpdate

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
    return [LeadOut.model_validate(l) for l in result.scalars().all()]


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
    return LeadOut.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
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
