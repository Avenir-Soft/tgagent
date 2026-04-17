import json
import logging
import os
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from starlette.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.config import settings
from src.core.database import get_db
from src.telegram.models import TelegramAccount, TelegramChannel, TelegramDiscussionGroup
from src.telegram.schemas import (
    DiscussionGroupCreate,
    DiscussionGroupOut,
    TelegramAccountCreate,
    TelegramAccountOut,
    TelegramChannelCreate,
    TelegramChannelOut,
)

from src.core.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])

# ── Media disk cache ──────────────────────────────────────────────────────────
_MEDIA_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "media_cache")
_MEDIA_CACHE_TTL = 86400  # 24 hours
_MEDIA_EXT = {"photo": "jpg", "sticker": "webp", "gif": "mp4", "voice": "ogg", "video_note": "mp4", "video": "mp4"}


def _media_cache_path(tenant_id: str, message_id: str, media_type: str) -> str:
    ext = _MEDIA_EXT.get(media_type, "bin")
    tenant_dir = os.path.join(_MEDIA_CACHE_DIR, tenant_id)
    os.makedirs(tenant_dir, exist_ok=True)
    return os.path.join(tenant_dir, f"{message_id}.{ext}")

# In-memory client cache — Telethon clients can't be serialized to Redis,
# but auth metadata (hash, tenant, session path) is stored in Redis with TTL
_pending_clients: dict[str, object] = {}

_PENDING_AUTH_TTL = 900  # 15 minutes


async def _get_redis():
    """Get Redis client for pending auth storage."""
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _store_pending_auth(phone: str, data: dict, client: object):
    """Store pending auth metadata in Redis + client in memory."""
    r = await _get_redis()
    key = f"pending_auth:{phone}"
    await r.setex(key, _PENDING_AUTH_TTL, json.dumps(data))
    await r.aclose()
    _pending_clients[phone] = client


async def _get_pending_auth(phone: str) -> tuple[dict | None, object | None]:
    """Retrieve pending auth from Redis + client from memory.

    If the client is not in memory (e.g. different gunicorn worker),
    reconstruct it from the session file stored on disk.
    """
    r = await _get_redis()
    key = f"pending_auth:{phone}"
    raw = await r.get(key)
    await r.aclose()
    if not raw:
        _pending_clients.pop(phone, None)
        return None, None
    data = json.loads(raw)
    client = _pending_clients.get(phone)
    if not client:
        # Client lost (different worker or process restart) — reconstruct from session file
        session_path = data.get("session_path")
        if not session_path:
            r2 = await _get_redis()
            await r2.delete(key)
            await r2.aclose()
            return None, None
        try:
            from telethon import TelegramClient
            client = TelegramClient(
                session_path,
                settings.telegram_api_id,
                settings.telegram_api_hash,
                device_model="AI Closer Server",
                system_version="Linux 5.15",
                app_version="1.0.0",
                lang_code="ru",
                system_lang_code="ru",
            )
            await client.connect()
            _pending_clients[phone] = client
        except Exception:
            logger.warning("Failed to reconstruct Telethon client for %s", phone)
            r2 = await _get_redis()
            await r2.delete(key)
            await r2.aclose()
            return None, None
    return data, client


async def _clear_pending_auth(phone: str):
    """Remove pending auth from both Redis and memory."""
    r = await _get_redis()
    await r.delete(f"pending_auth:{phone}")
    await r.aclose()
    _pending_clients.pop(phone, None)


class ResolveLinkRequest(BaseModel):
    link: str  # t.me/..., @username, or username


class ResolveLinkResponse(BaseModel):
    entity_type: str  # "channel", "group", "user"
    telegram_id: int
    title: str
    username: str | None = None
    linked_chat_id: int | None = None  # discussion group for channels
    linked_chat_title: str | None = None


@router.post("/resolve-link")
@limiter.limit("60/minute")
async def resolve_link(
    request: Request,
    body: ResolveLinkRequest,
    user: User = Depends(require_store_owner),
):
    """Resolve a Telegram link/username to entity info using the connected client."""
    from src.telegram.service import telegram_manager

    client = telegram_manager.get_client(user.tenant_id)
    if not client:
        raise HTTPException(status_code=400, detail="Нет подключенного Telegram аккаунта")

    link = body.link.strip()

    try:
        entity = await client.get_entity(link)
    except Exception as e:
        logger.warning("Failed to resolve Telegram link %s: %s", link, e)
        raise HTTPException(status_code=404, detail="Не удалось найти канал или группу по этой ссылке")

    from telethon.tl.types import Channel, Chat, User as TgUser

    if isinstance(entity, Channel):
        if entity.megagroup or entity.gigagroup:
            entity_type = "group"
        else:
            entity_type = "channel"
        result = {
            "entity_type": entity_type,
            "telegram_id": entity.id,
            "title": entity.title,
            "username": entity.username,
            "linked_chat_id": None,
            "linked_chat_title": None,
        }
        # Try to get linked discussion group for channels
        if entity_type == "channel":
            try:
                from telethon.tl.functions.channels import GetFullChannelRequest
                full = await client(GetFullChannelRequest(entity))
                if full.full_chat.linked_chat_id:
                    result["linked_chat_id"] = full.full_chat.linked_chat_id
                    # Resolve linked chat title
                    try:
                        linked = await client.get_entity(full.full_chat.linked_chat_id)
                        result["linked_chat_title"] = getattr(linked, 'title', None)
                    except Exception as e:
                        logger.warning("Failed to resolve linked chat title for chat_id %s: %s", full.full_chat.linked_chat_id, e)
            except Exception as e:
                logger.warning("Failed to fetch full channel info for entity %s: %s", entity.id, e)
        return result
    elif isinstance(entity, Chat):
        return {
            "entity_type": "group",
            "telegram_id": entity.id,
            "title": entity.title,
            "username": None,
            "linked_chat_id": None,
            "linked_chat_title": None,
        }
    elif isinstance(entity, TgUser):
        name = " ".join(filter(None, [entity.first_name, entity.last_name]))
        return {
            "entity_type": "user",
            "telegram_id": entity.id,
            "title": name or "User",
            "username": entity.username,
            "linked_chat_id": None,
            "linked_chat_title": None,
        }
    else:
        raise HTTPException(status_code=400, detail="Неизвестный тип сущности")


class SendCodeRequest(BaseModel):
    phone_number: str
    display_name: str | None = None


class VerifyCodeRequest(BaseModel):
    phone_number: str
    code: str
    password: str | None = None  # 2FA password if needed


@router.post("/auth/send-code")
@limiter.limit("5/minute")
async def send_code(
    request: Request,
    body: SendCodeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Step 1: Send authorization code to the phone number."""
    from telethon import TelegramClient

    # Sanitize phone number to prevent path traversal
    import re
    safe_phone = re.sub(r"[^0-9+]", "", body.phone_number)
    if not safe_phone or len(safe_phone) < 5:
        raise HTTPException(status_code=400, detail="Invalid phone number")
    session_path = f"{settings.telegram_sessions_dir}/{user.tenant_id}_{safe_phone}"
    client = TelegramClient(
        session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
        device_model="AI Closer Server",
        system_version="Linux 5.15",
        app_version="1.0.0",
        lang_code="ru",
        system_lang_code="ru",
    )
    await client.connect()

    result = await client.send_code_request(body.phone_number)
    await _store_pending_auth(
        body.phone_number,
        {
            "phone_code_hash": result.phone_code_hash,
            "tenant_id": str(user.tenant_id),
            "display_name": body.display_name,
            "session_path": session_path,
            "created_at": time.time(),
        },
        client,
    )

    return {"status": "code_sent", "phone": body.phone_number}


@router.post("/auth/verify-code")
@limiter.limit("5/minute")
async def verify_code(
    request: Request,
    body: VerifyCodeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Step 2: Verify the code and complete authentication."""
    import re
    safe_phone = re.sub(r"[^0-9+]", "", body.phone_number)
    if not safe_phone or len(safe_phone) < 5:
        raise HTTPException(status_code=400, detail="Invalid phone number")
    pending, client = await _get_pending_auth(body.phone_number)
    if not pending or not client:
        raise HTTPException(status_code=400, detail="No pending auth for this phone. Send code first.")

    # Verify the auth flow belongs to this tenant (prevent cross-tenant hijack)
    if pending.get("tenant_id") != str(user.tenant_id):
        raise HTTPException(status_code=403, detail="This auth flow belongs to a different account.")

    try:
        await client.sign_in(
            body.phone_number,
            body.code,
            phone_code_hash=pending["phone_code_hash"],
        )
    except Exception as e:
        err_msg = str(e)
        if "Two-steps verification" in err_msg or "SessionPasswordNeeded" in err_msg:
            if not body.password:
                return {"status": "2fa_required", "message": "Нужен пароль двухфакторной аутентификации"}
            from telethon.errors import SessionPasswordNeededError
            try:
                await client.sign_in(password=body.password)
            except Exception as e2:
                raise HTTPException(status_code=400, detail=f"2FA error: {e2}")
        else:
            raise HTTPException(status_code=400, detail=f"Auth error: {err_msg}")

    # Get account info
    me = await client.get_me()

    # Save account to DB
    account = TelegramAccount(
        tenant_id=user.tenant_id,
        phone_number=safe_phone,
        display_name=pending.get("display_name") or me.first_name,
        username=me.username,
        session_ref=f"{user.tenant_id}_{safe_phone}",
        status="connected",
    )
    db.add(account)
    await db.flush()

    # Start listening
    from src.telegram.service import telegram_manager
    telegram_manager._clients[user.tenant_id] = client
    telegram_manager._register_handlers(client, user.tenant_id)

    await _clear_pending_auth(body.phone_number)

    # Notify frontend via SSE
    try:
        from src.sse.event_bus import publish_event
        await publish_event(
            f"sse:{user.tenant_id}:tenant",
            {"event": "telegram_status_changed", "status": "connected", "phone": safe_phone},
        )
    except Exception:
        pass

    return {
        "status": "connected",
        "account": TelegramAccountOut.model_validate(account).model_dump(mode="json"),
    }


# --- Disconnect Account ---
@router.delete("/accounts/{account_id}")
@limiter.limit("20/minute")
async def disconnect_account(
    request: Request,
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Disconnect and remove a Telegram account."""
    result = await db.execute(
        select(TelegramAccount).where(
            TelegramAccount.id == account_id,
            TelegramAccount.tenant_id == user.tenant_id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Stop Telegram client if running
    from src.telegram.service import telegram_manager
    client = telegram_manager._clients.pop(user.tenant_id, None)
    if client and client.is_connected():
        await client.disconnect()

    # Delete session file
    import os
    session_path = f"{settings.telegram_sessions_dir}/{account.session_ref}.session"
    if os.path.exists(session_path):
        os.remove(session_path)

    await db.delete(account)

    # Notify frontend via SSE
    try:
        from src.sse.event_bus import publish_event
        await publish_event(
            f"sse:{user.tenant_id}:tenant",
            {"event": "telegram_status_changed", "status": "disconnected", "phone": account.phone_number},
        )
    except Exception:
        pass

    return {"status": "disconnected", "phone": account.phone_number}


# --- Accounts ---
@router.post("/accounts", response_model=TelegramAccountOut, status_code=201)
@limiter.limit("30/minute")
async def create_account(
    request: Request,
    body: TelegramAccountCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    account = TelegramAccount(
        tenant_id=user.tenant_id,
        phone_number=body.phone_number,
        display_name=body.display_name,
        username=body.username,
    )
    db.add(account)
    await db.flush()
    return TelegramAccountOut.model_validate(account)


@router.get("/accounts", response_model=list[TelegramAccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TelegramAccount).where(TelegramAccount.tenant_id == user.tenant_id)
    )
    return [TelegramAccountOut.model_validate(a) for a in result.scalars().all()]


# --- Channels ---
@router.post("/channels", response_model=TelegramChannelOut, status_code=201)
@limiter.limit("30/minute")
async def create_channel(
    request: Request,
    body: TelegramChannelCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    channel = TelegramChannel(
        tenant_id=user.tenant_id,
        telegram_channel_id=body.telegram_channel_id,
        title=body.title,
        username=body.username,
        linked_discussion_group_id=body.linked_discussion_group_id,
    )
    db.add(channel)
    await db.flush()
    return TelegramChannelOut.model_validate(channel)


@router.get("/channels", response_model=list[TelegramChannelOut])
async def list_channels(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TelegramChannel).where(TelegramChannel.tenant_id == user.tenant_id)
    )
    return [TelegramChannelOut.model_validate(c) for c in result.scalars().all()]


# --- Discussion Groups ---
@router.post("/discussion-groups", response_model=DiscussionGroupOut, status_code=201)
@limiter.limit("30/minute")
async def create_discussion_group(
    request: Request,
    body: DiscussionGroupCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    group = TelegramDiscussionGroup(
        tenant_id=user.tenant_id,
        telegram_group_id=body.telegram_group_id,
        title=body.title,
    )
    db.add(group)
    await db.flush()
    return DiscussionGroupOut.model_validate(group)


@router.get("/discussion-groups", response_model=list[DiscussionGroupOut])
async def list_discussion_groups(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TelegramDiscussionGroup).where(
            TelegramDiscussionGroup.tenant_id == user.tenant_id
        )
    )
    return [DiscussionGroupOut.model_validate(g) for g in result.scalars().all()]


# --- Status & Reconnect ---
@router.get("/status")
async def telegram_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Real-time connection status for all accounts."""
    from src.telegram.service import telegram_manager

    result = await db.execute(
        select(TelegramAccount).where(TelegramAccount.tenant_id == user.tenant_id)
    )
    accounts = result.scalars().all()
    statuses = []
    for a in accounts:
        client = telegram_manager.get_client(user.tenant_id)
        is_alive = False
        if client:
            try:
                is_alive = client.is_connected()
            except Exception as e:
                logger.warning("Failed to check Telegram client connection for tenant %s: %s", user.tenant_id, e)
        statuses.append({
            "account_id": str(a.id),
            "phone_number": a.phone_number,
            "display_name": a.display_name,
            "db_status": a.status,
            "live_connected": is_alive,
        })
    return statuses


@router.post("/accounts/{account_id}/reconnect")
@limiter.limit("30/minute")
async def reconnect_account(
    request: Request,
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Reconnect a Telegram account."""
    from src.telegram.service import telegram_manager

    result = await db.execute(
        select(TelegramAccount).where(
            TelegramAccount.id == account_id,
            TelegramAccount.tenant_id == user.tenant_id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Disconnect old client if exists
    old_client = telegram_manager._clients.pop(user.tenant_id, None)
    if old_client:
        try:
            await old_client.disconnect()
        except Exception as e:
            logger.warning("Failed to disconnect old Telegram client for account %s: %s", account_id, e)

    # Start new client
    try:
        await telegram_manager.start_client(account)
        account.status = "connected"
        # SSE emitted by start_client
        return {"status": "reconnected", "phone": account.phone_number}
    except Exception as e:
        account.status = "error"
        logger.error("Telegram reconnect failed for account %s: %s", account_id, e)
        # SSE emitted by start_client failure path
        raise HTTPException(status_code=500, detail="Не удалось переподключить Telegram аккаунт")


@router.get("/activity-logs")
async def activity_logs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recent activity logs: last messages, conversations count, etc."""
    from sqlalchemy import func
    from src.conversations.models import Conversation, Message

    # Last 30 outbound AI/admin messages as activity log
    result = await db.execute(
        select(
            Message.id,
            Message.conversation_id,
            Message.sender_type,
            Message.raw_text,
            Message.created_at,
            Conversation.telegram_first_name,
            Conversation.telegram_username,
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.tenant_id == user.tenant_id,
            Message.direction == "outbound",
        )
        .order_by(Message.created_at.desc())
        .limit(30)
    )
    rows = result.all()
    logs = []
    for r in rows:
        logs.append({
            "id": str(r.id),
            "conversation_id": str(r.conversation_id),
            "sender_type": r.sender_type,
            "text_preview": (r.raw_text or "")[:150],
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "customer_name": r.telegram_first_name,
            "customer_username": r.telegram_username,
        })
    return logs


@router.get("/media/{message_id}")
async def get_media(
    message_id: UUID,
    request: Request,
    token: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Download media from Telegram for a message. Returns the file bytes.

    Supports auth via:
    1. Bearer header (standard)
    2. ?token= query param with signed short-lived HMAC token (for <img>/<video> tags)
    3. ?token= with JWT (legacy, includes blacklist check)
    """
    from src.core.security import decode_access_token, is_token_blacklisted

    user = None

    # Try Bearer header first
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        jwt_token = auth_header[7:]
        payload = decode_access_token(jwt_token)
        if not payload or not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid token")
        # Blacklist check — fail-closed (consistent with auth/deps.py)
        try:
            if await is_token_blacklisted(jwt_token):
                raise HTTPException(status_code=401, detail="Token revoked")
        except HTTPException:
            raise
        except Exception:
            logger.error("Redis unavailable for media blacklist check — fail-closed")
            raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")
        user_result = await db.execute(
            select(User).where(User.id == UUID(payload["sub"]), User.is_active.is_(True))
        )
        user = user_result.scalar_one_or_none()
    elif token:
        # Try signed media token first (HMAC, short-lived)
        import hmac, hashlib, time as _time
        parts = token.split(".", 2)
        if len(parts) == 3:
            # Format: user_id.expires.signature
            try:
                uid_str, expires_str, sig = parts
                expected = hmac.new(
                    settings.secret_key.encode(), f"{uid_str}.{expires_str}".encode(), hashlib.sha256
                ).hexdigest()[:32]
                if hmac.compare_digest(sig, expected) and int(expires_str) > int(_time.time()):
                    user_result = await db.execute(
                        select(User).where(User.id == UUID(uid_str), User.is_active.is_(True))
                    )
                    user = user_result.scalar_one_or_none()
            except (ValueError, TypeError):
                pass  # Fall through to JWT
        # Fallback: treat as JWT (legacy)
        if not user:
            payload = decode_access_token(token)
            if payload and payload.get("sub"):
                try:
                    if await is_token_blacklisted(token):
                        raise HTTPException(status_code=401, detail="Token revoked")
                except HTTPException:
                    raise
                except Exception:
                    logger.error("Redis unavailable for media JWT blacklist check — fail-closed")
                    raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")
                user_result = await db.execute(
                    select(User).where(User.id == UUID(payload["sub"]), User.is_active.is_(True))
                )
                user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from src.conversations.models import Message
    from src.telegram.service import telegram_manager

    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.tenant_id == user.tenant_id,
            Message.media_type.isnot(None),
        )
    )
    msg = result.scalar_one_or_none()
    if not msg or not msg.media_file_id:
        raise HTTPException(status_code=404, detail="Media not found")

    client = telegram_manager.get_client(user.tenant_id)
    if not client:
        raise HTTPException(status_code=400, detail="Telegram not connected")

    # Find the original Telegram message to download media
    try:
        from src.conversations.models import Conversation
        conv_r = await db.execute(
            select(Conversation).where(Conversation.id == msg.conversation_id)
        )
        conv = conv_r.scalar_one_or_none()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Determine content type
        content_types = {
            "photo": "image/jpeg",
            "sticker": "image/webp",
            "gif": "video/mp4",
            "voice": "audio/ogg",
            "video_note": "video/mp4",
            "video": "video/mp4",
            "document": "application/octet-stream",
        }
        content_type = content_types.get(msg.media_type, "application/octet-stream")
        cache_headers = {"Cache-Control": "public, max-age=86400"}

        # Check disk cache first — avoids Telegram API call
        cache_path = _media_cache_path(str(user.tenant_id), str(message_id), msg.media_type or "")
        if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < _MEDIA_CACHE_TTL:
            return FileResponse(cache_path, media_type=content_type, headers=cache_headers)

        # Download from Telegram
        tg_msg = await client.get_messages(conv.telegram_chat_id, ids=msg.telegram_message_id)
        if not tg_msg or not tg_msg.media:
            raise HTTPException(status_code=404, detail="Telegram message not found")

        file_bytes = await client.download_media(tg_msg, bytes)
        if not file_bytes:
            raise HTTPException(status_code=404, detail="Failed to download media")

        # Save to disk cache (fire-and-forget — serve even if cache write fails)
        try:
            with open(cache_path, "wb") as f:
                f.write(file_bytes)
        except OSError:
            logger.warning("Failed to cache media to %s", cache_path)

        return Response(content=file_bytes, media_type=content_type, headers=cache_headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to download media for message %s: %s", message_id, e)
        raise HTTPException(status_code=500, detail="Failed to download media")


@router.get("/media-token")
async def get_media_token(user: User = Depends(get_current_user)):
    """Get a short-lived signed token for media access (avoids JWT in URL logs)."""
    from src.core.security import create_media_token
    return {"token": create_media_token(str(user.id))}
