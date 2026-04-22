"""Conversations API — thin HTTP handlers delegating to service layer."""

import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.conversations.models import CommentTemplate, Conversation, Message
from src.conversations.schemas import (
    BulkDeleteRequest, CommentTemplateCreate, CommentTemplateOut, CommentTemplateUpdate,
    ConversationOut, MessageEdit, MessageOut, MessageSend,
)
from src.conversations.service import (
    bulk_delete_conversations as svc_bulk_delete,
    delete_conversation_cascade,
    edit_message_telegram,
    get_customer_history as svc_customer_history,
    list_conversations_enriched,
    reset_conversation as svc_reset,
    send_operator_message as svc_send_operator,
)
from src.core.audit import log_audit
from src.platform.deps import check_not_read_only

router = APIRouter(tags=["conversations"])


# --- Templates (simple CRUD — kept inline) ---


@router.post("/templates", response_model=CommentTemplateOut, status_code=201, dependencies=[Depends(check_not_read_only)])
@limiter.limit("30/minute")
async def create_template(
    request: Request,
    body: CommentTemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    tpl = CommentTemplate(
        tenant_id=user.tenant_id,
        trigger_type=body.trigger_type,
        trigger_patterns=body.trigger_patterns,
        language=body.language,
        template_text=body.template_text,
    )
    db.add(tpl)
    await db.flush()
    return CommentTemplateOut.model_validate(tpl)


@router.get("/templates", response_model=list[CommentTemplateOut])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CommentTemplate).where(CommentTemplate.tenant_id == user.tenant_id)
    )
    return [CommentTemplateOut.model_validate(t) for t in result.scalars().all()]


@router.patch("/templates/{template_id}", response_model=CommentTemplateOut, dependencies=[Depends(check_not_read_only)])
@limiter.limit("30/minute")
async def update_template(
    request: Request,
    template_id: UUID,
    body: CommentTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(CommentTemplate).where(
            CommentTemplate.id == template_id,
            CommentTemplate.tenant_id == user.tenant_id,
        )
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(tpl, key, value)
    await db.flush()
    return CommentTemplateOut.model_validate(tpl)


@router.delete("/templates/{template_id}", dependencies=[Depends(check_not_read_only)])
@limiter.limit("20/minute")
async def delete_template(
    request: Request,
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(CommentTemplate).where(
            CommentTemplate.id == template_id,
            CommentTemplate.tenant_id == user.tenant_id,
        )
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(tpl)
    return {"status": "deleted"}


@router.post("/templates/test-trigger")
@limiter.limit("60/minute")
async def test_trigger(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Test which templates would match a given text."""
    test_text = (body.get("text") or "").strip().lower()
    if not test_text:
        return {"matches": []}

    result = await db.execute(
        select(CommentTemplate).where(
            CommentTemplate.tenant_id == user.tenant_id,
            CommentTemplate.is_active.is_(True),
        )
    )
    matches = []
    for tpl in result.scalars().all():
        patterns = tpl.trigger_patterns if isinstance(tpl.trigger_patterns, list) else []
        matched = False
        if tpl.trigger_type == "regex":
            for p in patterns:
                try:
                    if re.search(p, test_text, re.IGNORECASE):
                        matched = True
                        break
                except re.error:
                    pass
        else:
            for p in patterns:
                pl = p.lower()
                if len(pl) <= 2:
                    if re.search(r'(?:^|\s|^)' + re.escape(pl) + r'(?:\s|$|$)', test_text):
                        matched = True
                        break
                else:
                    if pl in test_text:
                        matched = True
                        break
        if matched:
            matches.append({
                "id": str(tpl.id),
                "trigger_type": tpl.trigger_type,
                "trigger_patterns": patterns,
                "template_text": tpl.template_text,
                "language": tpl.language,
            })
    return {"matches": matches}


# --- Comment interactions (from audit logs) ---


@router.get("/conversations/comments")
async def list_comment_interactions(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List AI comment replies from audit logs."""
    from src.core.audit import AuditLog

    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.tenant_id == user.tenant_id,
            AuditLog.entity_type == "comment",
            AuditLog.action.in_(["comment_smart_reply", "comment_template_reply"]),
        )
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(log.id),
            "action": log.action,
            "trigger_text": (log.meta_json or {}).get("trigger_text", ""),
            "reply_text": (log.meta_json or {}).get("reply_text", ""),
            "sender_name": (log.meta_json or {}).get("sender_name"),
            "sender_username": (log.meta_json or {}).get("sender_username"),
            "chat_title": (log.meta_json or {}).get("chat_title"),
            "product_name": (log.meta_json or {}).get("product_name"),
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# --- Conversations ---


@router.get("/conversations")
async def list_conversations(
    status: str | None = None,
    source_type: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await list_conversations_enriched(user.tenant_id, status, source_type, limit, offset, db)


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == user.tenant_id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationOut.model_validate(conv)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: UUID,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.tenant_id == user.tenant_id)
        .order_by(desc(Message.created_at))
        .limit(limit)
    )
    msgs = list(reversed(result.scalars().all()))
    return [MessageOut.model_validate(m) for m in msgs]


@router.get("/conversations/{conversation_id}/customer-history")
async def get_customer_history(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = await svc_customer_history(user.tenant_id, conversation_id, db)
    if data is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return data


@router.patch("/conversations/{conversation_id}/toggle-ai", dependencies=[Depends(check_not_read_only)])
@limiter.limit("60/minute")
async def toggle_ai(
    request: Request,
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == user.tenant_id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.ai_enabled = not conv.ai_enabled
    if conv.ai_enabled and conv.status == "handoff":
        conv.status = "active"
        conv.state = "idle"
    await db.flush()
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "conversation.toggle_ai", "conversation", str(conversation_id),
        {"ai_enabled": conv.ai_enabled},
    )
    return {"ai_enabled": conv.ai_enabled, "status": conv.status}


@router.post("/conversations/{conversation_id}/reset", dependencies=[Depends(check_not_read_only)])
@limiter.limit("30/minute")
async def reset_conversation(
    request: Request,
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == user.tenant_id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await svc_reset(user.tenant_id, conv, db)
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "conversation.reset", "conversation", str(conversation_id),
    )
    return result


@router.patch("/conversations/{conversation_id}/messages/{message_id}", response_model=MessageOut, dependencies=[Depends(check_not_read_only)])
@limiter.limit("30/minute")
async def edit_message(
    request: Request,
    conversation_id: UUID,
    message_id: UUID,
    body: MessageEdit,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.tenant_id == user.tenant_id,
            Message.direction == "outbound",
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    old_text = msg.raw_text
    msg.raw_text = body.raw_text
    await db.flush()
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "message.edit", "message", str(message_id),
        {"conversation_id": str(conversation_id), "sync_telegram": body.sync_telegram},
    )

    if body.sync_telegram and msg.telegram_message_id:
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == user.tenant_id,
            )
        )
        conv = conv_result.scalar_one_or_none()
        if conv:
            await edit_message_telegram(user.tenant_id, conv, msg.telegram_message_id, body.raw_text)

    return MessageOut.model_validate(msg)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=201, dependencies=[Depends(check_not_read_only)])
@limiter.limit("30/minute")
async def send_operator_message(
    request: Request,
    conversation_id: UUID,
    body: MessageSend,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if body.sync_telegram:
        msg, _ = await svc_send_operator(user.tenant_id, conv, body.raw_text, db)
    else:
        from datetime import datetime, timezone
        msg = Message(
            tenant_id=user.tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            sender_type="human_admin",
            raw_text=body.raw_text,
            ai_generated=False,
        )
        db.add(msg)
        conv.last_message_at = datetime.now(timezone.utc)
        await db.flush()

    await log_audit(
        db, user.tenant_id, "user", str(user.id), "message.send", "message", str(msg.id),
        {"conversation_id": str(conversation_id), "sync_telegram": body.sync_telegram},
    )

    # SSE: notify about operator message
    try:
        from src.sse.event_bus import publish_event
        msg_data = MessageOut.model_validate(msg).model_dump(mode="json")
        await publish_event(
            f"sse:{user.tenant_id}:conversation:{conversation_id}",
            {"event": "new_message", "conversation_id": str(conversation_id), "data": msg_data},
        )
        await publish_event(
            f"sse:{user.tenant_id}:tenant",
            {"event": "conversation_updated", "conversation_id": str(conversation_id)},
        )
    except Exception as e:
        logger.debug("SSE publish failed for operator message in conversation %s: %s", conversation_id, e)

    return MessageOut.model_validate(msg)


@router.delete("/conversations/{conversation_id}", dependencies=[Depends(check_not_read_only)])
@limiter.limit("20/minute")
async def delete_conversation(
    request: Request,
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    customer = conv.telegram_first_name or conv.telegram_username
    await delete_conversation_cascade(user.tenant_id, conversation_id, db)
    await log_audit(
        db, user.tenant_id, "user", str(user.id), "conversation.delete", "conversation", str(conversation_id),
        {"customer": customer},
    )
    return {"deleted": True}


@router.post("/conversations/bulk-delete", dependencies=[Depends(check_not_read_only)])
@limiter.limit("10/minute")
async def bulk_delete_conversations(
    request: Request,
    body: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    if not body.conversation_ids:
        raise HTTPException(status_code=400, detail="conversation_ids required")
    result = await svc_bulk_delete(user.tenant_id, body.conversation_ids, db)
    if result["deleted"] == 0:
        raise HTTPException(status_code=404, detail="No conversations found")
    return result
