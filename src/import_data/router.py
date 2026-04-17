from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.import_data.csv_import import import_products_csv, import_delivery_rules_csv

router = APIRouter(prefix="/import", tags=["import"])

_MAX_CSV_SIZE = 5 * 1024 * 1024  # 5 MB


async def _read_csv(file: UploadFile) -> str:
    """Read and validate CSV upload — enforces size limit and UTF-8."""
    data = await file.read()
    if len(data) > _MAX_CSV_SIZE:
        raise HTTPException(status_code=413, detail="Файл слишком большой (макс. 5 МБ)")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Файл должен быть в кодировке UTF-8")


@router.post("/products/csv")
@limiter.limit("10/minute")
async def upload_products_csv(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    content = await _read_csv(file)
    result = await import_products_csv(db, user.tenant_id, content)
    return result


@router.post("/delivery-rules/csv")
@limiter.limit("10/minute")
async def upload_delivery_rules_csv(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    content = await _read_csv(file)
    result = await import_delivery_rules_csv(db, user.tenant_id, content)
    return result
