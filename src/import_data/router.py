from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.import_data.csv_import import import_products_csv, import_delivery_rules_csv

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/products/csv")
async def upload_products_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    content = (await file.read()).decode("utf-8")
    result = await import_products_csv(db, user.tenant_id, content)
    return result


@router.post("/delivery-rules/csv")
async def upload_delivery_rules_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    content = (await file.read()).decode("utf-8")
    result = await import_delivery_rules_csv(db, user.tenant_id, content)
    return result
