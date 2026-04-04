from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.ai.models import AiSettings
from src.ai.schemas import AiSettingsCreate, AiSettingsOut

router = APIRouter(tags=["ai"])


@router.get("/ai-settings", response_model=AiSettingsOut)
async def get_ai_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        # Return defaults by creating a transient instance
        settings = AiSettings(tenant_id=user.tenant_id)
        db.add(settings)
        await db.flush()
    return AiSettingsOut.model_validate(settings)


@router.put("/ai-settings", response_model=AiSettingsOut)
async def update_ai_settings(
    body: AiSettingsCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    settings = result.scalar_one_or_none()
    if settings:
        for field, value in body.model_dump().items():
            setattr(settings, field, value)
    else:
        settings = AiSettings(tenant_id=user.tenant_id, **body.model_dump())
        db.add(settings)
    await db.flush()
    return AiSettingsOut.model_validate(settings)


@router.post("/ai-settings/test-notification")
async def test_notification(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Send a test Telegram notification to the configured operator."""
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    settings = result.scalar_one_or_none()
    if not settings or not settings.operator_telegram_username:
        raise HTTPException(400, "Telegram оператора не настроен")
    try:
        from src.telegram.service import telegram_manager
        client = telegram_manager.get_client(user.tenant_id)
        if not client:
            raise HTTPException(503, "Telegram клиент не подключён")
        await client.send_message(
            settings.operator_telegram_username,
            "✅ Тестовое уведомление из AI Closer.\nЕсли вы видите это сообщение — уведомления работают!"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Ошибка отправки: {str(e)}")
    return {"status": "sent"}


@router.post("/ai-settings/reset", response_model=AiSettingsOut)
async def reset_ai_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Reset AI settings to defaults (preserves prompt_rules)."""
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        settings = AiSettings(tenant_id=user.tenant_id)
        db.add(settings)
        await db.flush()
        return AiSettingsOut.model_validate(settings)

    defaults = AiSettingsCreate()
    for field, value in defaults.model_dump().items():
        if field == "prompt_rules":
            continue  # preserve manually curated rules
        setattr(settings, field, value)
    await db.flush()
    return AiSettingsOut.model_validate(settings)


# ── Prompt Rules CRUD ─────────────────────────────────────────────────────────

@router.get("/ai-settings/prompt-rules")
async def get_prompt_rules(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    ai_settings = result.scalar_one_or_none()
    return ai_settings.prompt_rules or [] if ai_settings else []


@router.post("/ai-settings/prompt-rules")
async def add_prompt_rule(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Add a manual prompt rule. Body: {"rule": "...", "reason": "..."}"""
    rule_text = body.get("rule", "").strip()
    if not rule_text:
        raise HTTPException(400, "rule is required")

    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    ai_settings = result.scalar_one_or_none()
    if not ai_settings:
        ai_settings = AiSettings(tenant_id=user.tenant_id)
        db.add(ai_settings)
        await db.flush()

    rules = ai_settings.prompt_rules or []
    new_rule = {
        "id": str(uuid4()),
        "rule": rule_text,
        "reason": body.get("reason", ""),
        "source": "manual",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    rules.append(new_rule)
    ai_settings.prompt_rules = rules
    flag_modified(ai_settings, "prompt_rules")
    await db.flush()
    return new_rule


@router.patch("/ai-settings/prompt-rules/{rule_id}")
async def toggle_prompt_rule(
    rule_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Toggle rule active/inactive. Body: {"active": true/false}"""
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    ai_settings = result.scalar_one_or_none()
    if not ai_settings:
        raise HTTPException(404, "Settings not found")

    rules = ai_settings.prompt_rules or []
    for r in rules:
        if r.get("id") == rule_id:
            r["active"] = body.get("active", not r.get("active", True))
            ai_settings.prompt_rules = rules
            flag_modified(ai_settings, "prompt_rules")
            await db.flush()
            return r
    raise HTTPException(404, "Rule not found")


@router.delete("/ai-settings/prompt-rules/{rule_id}")
async def delete_prompt_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    ai_settings = result.scalar_one_or_none()
    if not ai_settings:
        raise HTTPException(404, "Settings not found")

    rules = ai_settings.prompt_rules or []
    original_len = len(rules)
    rules = [r for r in rules if r.get("id") != rule_id]
    if len(rules) == original_len:
        raise HTTPException(404, "Rule not found")

    ai_settings.prompt_rules = rules
    flag_modified(ai_settings, "prompt_rules")
    await db.flush()
    return {"deleted": True, "remaining": len(rules)}
