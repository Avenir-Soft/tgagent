from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.ai.models import AiSettings
from src.ai.orchestrator import invalidate_ai_settings_cache
from src.ai.schemas import AiSettingsCreate, AiSettingsOut
from src.ai.tracer import get_traces, clear_traces

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
@limiter.limit("30/minute")
async def update_ai_settings(
    request: Request,
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
        # JSONB fields need explicit flag_modified for SQLAlchemy change detection
        if body.prompt_rules is not None:
            flag_modified(settings, "prompt_rules")
    else:
        settings = AiSettings(tenant_id=user.tenant_id, **body.model_dump())
        db.add(settings)
    await db.flush()
    invalidate_ai_settings_cache(user.tenant_id)
    return AiSettingsOut.model_validate(settings)


@router.post("/ai-settings/test-notification")
@limiter.limit("60/minute")
async def test_notification(
    request: Request,
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
@limiter.limit("30/minute")
async def reset_ai_settings(
    request: Request,
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
    invalidate_ai_settings_cache(user.tenant_id)
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
@limiter.limit("30/minute")
async def add_prompt_rule(
    request: Request,
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
    invalidate_ai_settings_cache(user.tenant_id)
    return new_rule


@router.patch("/ai-settings/prompt-rules/{rule_id}")
@limiter.limit("30/minute")
async def toggle_prompt_rule(
    request: Request,
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
            invalidate_ai_settings_cache(user.tenant_id)
            return r
    raise HTTPException(404, "Rule not found")


@router.delete("/ai-settings/prompt-rules/{rule_id}")
@limiter.limit("20/minute")
async def delete_prompt_rule(
    request: Request,
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
    invalidate_ai_settings_cache(user.tenant_id)
    return {"deleted": True, "remaining": len(rules)}


# ── AI Trace Monitor ─────────────────────────────────────────────────────────

@router.get("/ai-traces")
async def get_ai_traces(
    limit: int = 30,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get AI traces from DB with pagination."""
    traces, total = await get_traces(user.tenant_id, db, limit=min(limit, 100), offset=offset)
    return {"traces": traces, "total": total, "count": len(traces)}


@router.get("/ai-traces/daily-stats")
async def get_ai_traces_daily_stats(
    days: int = 14,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get daily aggregated AI trace stats for charts."""
    from sqlalchemy import func, cast, Date
    from src.ai.models import AITraceLog
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            cast(AITraceLog.created_at, Date).label("day"),
            func.count().label("count"),
            func.sum(AITraceLog.prompt_tokens).label("prompt_tokens"),
            func.sum(AITraceLog.completion_tokens).label("completion_tokens"),
            func.avg(AITraceLog.total_duration_ms).label("avg_duration_ms"),
        )
        .where(AITraceLog.tenant_id == user.tenant_id, AITraceLog.created_at >= since)
        .group_by("day")
        .order_by("day")
    )
    rows = result.fetchall()
    return [
        {
            "date": str(row.day),
            "count": row.count,
            "prompt_tokens": row.prompt_tokens or 0,
            "completion_tokens": row.completion_tokens or 0,
            "avg_duration_ms": round(row.avg_duration_ms or 0),
        }
        for row in rows
    ]


@router.delete("/ai-traces")
async def clear_ai_traces(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Clear all AI traces for this tenant."""
    await clear_traces(user.tenant_id, db)
    return {"cleared": True}
