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
from src.ai.schemas import AiSettingsCreate, AiSettingsOut, ApiKeyInput, ApiKeyStatusOut
from src.ai.tracer import get_traces, clear_traces
from src.core.audit import log_audit
from src.core.security import encrypt_api_key, decrypt_api_key

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
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "settings.update", "ai_settings", None,
        {"changed_fields": list(body.model_dump().keys())},
    )
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


# ── Per-Tenant API Key Management ────────────────────────────────────────────

import logging as _logging

_api_key_logger = _logging.getLogger(__name__)

_VALID_PROVIDERS = {"openai", "anthropic"}
_PROVIDER_KEY_PREFIXES = {"openai": "sk-", "anthropic": "sk-ant-"}


@router.put("/ai-settings/api-key")
@limiter.limit("10/minute")
async def save_api_key(
    request: Request,
    body: ApiKeyInput,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Save an encrypted API key for this tenant. Validates the key first."""
    if body.provider not in _VALID_PROVIDERS:
        raise HTTPException(400, f"Неизвестный провайдер: {body.provider}. Допустимые: {', '.join(_VALID_PROVIDERS)}")

    api_key = body.api_key.strip()
    if not api_key or len(api_key) < 10:
        raise HTTPException(400, "API ключ слишком короткий")

    # Validate key by making a lightweight test call
    try:
        await _validate_api_key(body.provider, api_key, body.model)
    except Exception as e:
        raise HTTPException(400, f"Ключ невалиден: {e}")

    # Load or create settings
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    ai_settings = result.scalar_one_or_none()
    if not ai_settings:
        ai_settings = AiSettings(tenant_id=user.tenant_id)
        db.add(ai_settings)
        await db.flush()

    # Encrypt and save
    ai_settings.ai_provider = body.provider
    ai_settings.ai_api_key_encrypted = encrypt_api_key(api_key)
    if body.model:
        ai_settings.ai_model_override = body.model
    await db.flush()
    invalidate_ai_settings_cache(user.tenant_id)

    _api_key_logger.info("Tenant %s saved %s API key", user.tenant_id, body.provider)
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "api_key.set", "ai_settings", None,
        {"provider": body.provider, "model": body.model},
    )
    return {"status": "saved", "provider": body.provider, "model": body.model}


@router.get("/ai-settings/api-key-status", response_model=ApiKeyStatusOut)
async def get_api_key_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check if tenant has a custom API key configured. Never returns the actual key."""
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    ai_settings = result.scalar_one_or_none()
    if not ai_settings:
        return ApiKeyStatusOut(has_key=False, provider="openai", model=None)
    return ApiKeyStatusOut(
        has_key=bool(ai_settings.ai_api_key_encrypted),
        provider=ai_settings.ai_provider or "openai",
        model=ai_settings.ai_model_override,
    )


@router.delete("/ai-settings/api-key")
@limiter.limit("10/minute")
async def delete_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Remove tenant's custom API key — revert to platform default."""
    result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == user.tenant_id)
    )
    ai_settings = result.scalar_one_or_none()
    if not ai_settings:
        raise HTTPException(404, "Настройки не найдены")

    ai_settings.ai_api_key_encrypted = None
    ai_settings.ai_model_override = None
    ai_settings.ai_provider = "openai"
    await db.flush()
    invalidate_ai_settings_cache(user.tenant_id)

    _api_key_logger.info("Tenant %s deleted custom API key", user.tenant_id)
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "api_key.delete", "ai_settings", None,
    )
    return {"status": "deleted"}


@router.post("/ai-settings/test-api-key")
@limiter.limit("5/minute")
async def test_api_key(
    request: Request,
    body: ApiKeyInput,
    user: User = Depends(require_store_owner),
):
    """Test an API key without saving it."""
    if body.provider not in _VALID_PROVIDERS:
        raise HTTPException(400, f"Неизвестный провайдер: {body.provider}")
    try:
        await _validate_api_key(body.provider, body.api_key.strip(), body.model)
    except Exception as e:
        raise HTTPException(400, f"Ключ невалиден: {e}")
    return {"status": "valid", "provider": body.provider}


async def _validate_api_key(provider: str, api_key: str, model: str | None = None):
    """Validate an API key by making a lightweight test API call.

    Raises Exception with descriptive message on failure.
    """
    if provider == "openai":
        import openai
        client = openai.AsyncOpenAI(api_key=api_key)
        test_model = model or "gpt-4o-mini"
        try:
            await client.chat.completions.create(
                model=test_model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
            )
        except openai.AuthenticationError:
            raise ValueError("Неверный API ключ OpenAI")
        except openai.PermissionDeniedError:
            raise ValueError("API ключ не имеет доступа к этой модели")
        except openai.NotFoundError:
            raise ValueError(f"Модель '{test_model}' не найдена")
        except Exception as e:
            raise ValueError(f"Ошибка OpenAI: {type(e).__name__}: {e}")

    elif provider == "anthropic":
        try:
            import anthropic
        except ImportError:
            raise ValueError("Anthropic SDK не установлен на сервере (pip install anthropic)")
        client = anthropic.AsyncAnthropic(api_key=api_key)
        test_model = model or "claude-haiku-4-5"
        try:
            await client.messages.create(
                model=test_model,
                max_tokens=1,
                messages=[{"role": "user", "content": "test"}],
            )
        except anthropic.AuthenticationError:
            raise ValueError("Неверный API ключ Anthropic")
        except anthropic.PermissionDeniedError:
            raise ValueError("API ключ не имеет доступа к этой модели")
        except anthropic.NotFoundError:
            raise ValueError(f"Модель '{test_model}' не найдена")
        except Exception as e:
            raise ValueError(f"Ошибка Anthropic: {type(e).__name__}: {e}")

    else:
        raise ValueError(f"Неизвестный провайдер: {provider}")


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
    return (ai_settings.prompt_rules or []) if ai_settings else []


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
