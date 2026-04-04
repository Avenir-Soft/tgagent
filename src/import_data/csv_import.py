"""CSV import service for products, variants, inventory, delivery rules."""

import csv
import io
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.catalog.models import DeliveryRule, Inventory, Product, ProductVariant


async def import_products_csv(
    db: AsyncSession, tenant_id: UUID, csv_content: str
) -> dict:
    """Import products from CSV.

    Expected columns: name, slug, description, brand, model
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    created = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        try:
            product = Product(
                tenant_id=tenant_id,
                name=row["name"].strip(),
                slug=row["slug"].strip(),
                description=row.get("description", "").strip() or None,
                brand=row.get("brand", "").strip() or None,
                model=row.get("model", "").strip() or None,
            )
            db.add(product)
            created += 1
        except Exception as e:
            errors.append({"row": i, "error": str(e)})

    await db.flush()
    return {"created": created, "errors": errors}


async def import_delivery_rules_csv(
    db: AsyncSession, tenant_id: UUID, csv_content: str
) -> dict:
    """Import delivery rules from CSV.

    Expected columns: city, zone, delivery_type, price, eta_min_days, eta_max_days, cod_available
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    created = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        try:
            rule = DeliveryRule(
                tenant_id=tenant_id,
                city=row.get("city", "").strip() or None,
                zone=row.get("zone", "").strip() or None,
                delivery_type=row["delivery_type"].strip(),
                price=Decimal(row["price"].strip()),
                eta_min_days=int(row.get("eta_min_days", 1)),
                eta_max_days=int(row.get("eta_max_days", 3)),
                cod_available=row.get("cod_available", "false").strip().lower() == "true",
            )
            db.add(rule)
            created += 1
        except Exception as e:
            errors.append({"row": i, "error": str(e)})

    await db.flush()
    return {"created": created, "errors": errors}
