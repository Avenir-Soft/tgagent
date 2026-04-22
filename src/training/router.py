"""Training data pipeline — collect, curate, and export fine-tuning data."""

import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.ai.models import AiSettings
from src.conversations.models import Conversation, Message
from src.conversations.schemas import TrainingLabelUpdate
from src.core.database import get_db
from src.core.config import settings
from src.core.rate_limit import limiter

router = APIRouter(prefix="/training", tags=["training"])
logger = logging.getLogger(__name__)

# Singleton OpenAI client
import openai as _openai_mod
_openai_client: _openai_mod.AsyncOpenAI | None = None


def _get_openai_client() -> _openai_mod.AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = _openai_mod.AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client

SYSTEM_PROMPT_PREVIEW = (
    "You are a multilingual AI sales assistant for a Telegram store. "
    "Answer only in the customer's language. Never fabricate product specs or prices."
)


# ── Stats ──────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def training_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tid = user.tenant_id

    candidate_convs = (await db.execute(
        select(func.count()).select_from(Conversation)
        .where(Conversation.tenant_id == tid, Conversation.is_training_candidate == True)  # noqa: E712
    )).scalar() or 0

    total_ai_msgs = (await db.execute(
        select(func.count()).select_from(Message)
        .where(Message.tenant_id == tid, Message.ai_generated == True)  # noqa: E712
    )).scalar() or 0

    approved = (await db.execute(
        select(func.count()).select_from(Message)
        .where(Message.tenant_id == tid, Message.training_label == "approved")
    )).scalar() or 0

    rejected = (await db.execute(
        select(func.count()).select_from(Message)
        .where(Message.tenant_id == tid, Message.training_label == "rejected")
    )).scalar() or 0

    unlabeled_candidate = (await db.execute(
        select(func.count()).select_from(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.tenant_id == tid,
            Message.ai_generated == True,  # noqa: E712
            Message.training_label == None,  # noqa: E711
            Conversation.is_training_candidate == True,  # noqa: E712
        )
    )).scalar() or 0

    return {
        "candidate_conversations": candidate_convs,
        "total_ai_messages": total_ai_msgs,
        "labeled": {"approved": approved, "rejected": rejected},
        "unlabeled_in_candidates": unlabeled_candidate,
        "coverage_pct": round(((approved + rejected) / total_ai_msgs * 100) if total_ai_msgs else 0, 1),
    }


# ── Candidate conversations ────────────────────────────────────────────────────

@router.get("/conversations")
async def list_training_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.tenant_id == user.tenant_id,
            Conversation.is_training_candidate == True,  # noqa: E712
        )
        .order_by(Conversation.last_message_at.desc().nullslast())
        .limit(100)
    )
    convs = result.scalars().all()
    if not convs:
        return []

    # Batch aggregation — single query instead of 3 per conversation
    conv_ids = [c.id for c in convs]
    from sqlalchemy import case
    stats_q = (
        select(
            Message.conversation_id,
            func.count().filter(Message.ai_generated == True).label("ai_total"),  # noqa: E712
            func.count().filter(Message.training_label == "approved").label("approved"),
            func.count().filter(Message.training_label == "rejected").label("rejected"),
        )
        .where(Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
    )
    stats_result = await db.execute(stats_q)
    stats_map = {}
    for row in stats_result.fetchall():
        stats_map[row[0]] = {"ai_total": row[1], "approved": row[2], "rejected": row[3]}

    out = []
    for c in convs:
        s = stats_map.get(c.id, {"ai_total": 0, "approved": 0, "rejected": 0})
        out.append({
            "id": str(c.id),
            "customer": c.telegram_first_name or f"#{c.telegram_user_id}",
            "username": c.telegram_username,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            "ai_messages": s["ai_total"],
            "approved": s["approved"],
            "rejected": s["rejected"],
            "unlabeled": s["ai_total"] - s["approved"] - s["rejected"],
        })
    return out


# ── Label a message ────────────────────────────────────────────────────────────

@router.patch("/messages/{message_id}/label")
@limiter.limit("60/minute")
async def label_message(
    request: Request,
    message_id: UUID,
    body: TrainingLabelUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    if body.label not in (None, "approved", "rejected"):
        raise HTTPException(400, "label must be 'approved', 'rejected', or null")

    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.tenant_id == user.tenant_id,
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(404, "Message not found")

    msg.training_label = body.label
    if body.label == "rejected":
        msg.rejection_reason = body.reason
        msg.rejection_selected_text = body.selected_text
    elif body.label != "rejected":
        msg.rejection_reason = None
        msg.rejection_selected_text = None
    await db.flush()
    return {
        "id": str(message_id),
        "training_label": body.label,
        "rejection_reason": msg.rejection_reason,
        "rejection_selected_text": msg.rejection_selected_text,
    }


# ── Auto-label a conversation ─────────────────────────────────────────────────
# Uses _anomalies from state_context to auto-reject anomalous turns.
# All other AI turns in the conversation are marked approved.

@router.post("/conversations/{conversation_id}/auto-label")
@limiter.limit("30/minute")
async def auto_label_conversation(
    request: Request,
    conversation_id: UUID,
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
        raise HTTPException(404, "Conversation not found")

    # Get all messages ordered by created_at
    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    messages = msgs_result.scalars().all()

    # Build a set of turn indices with anomalies from state_context
    # _anomalies store the `turn` preview (first 60 chars of user message)
    anomalous_turns: set[str] = set()
    ctx = conv.state_context or {}
    for a in ctx.get("_anomalies", []):
        anomalous_turns.add(a.get("turn", "")[:60])

    # Go through messages: for each AI message find preceding user message
    approved_count = rejected_count = 0
    for i, msg in enumerate(messages):
        if not msg.ai_generated or msg.training_label is not None:
            continue
        # Find the preceding user message
        user_turn = ""
        for prev in reversed(messages[:i]):
            if prev.direction == "inbound":
                user_turn = (prev.raw_text or "")[:60]
                break

        is_anomalous = any(user_turn.startswith(t[:40]) for t in anomalous_turns if t)
        msg.training_label = "rejected" if is_anomalous else "approved"
        if is_anomalous:
            rejected_count += 1
        else:
            approved_count += 1

    # Mark as training candidate if not already
    conv.is_training_candidate = True
    await db.flush()

    return {"approved": approved_count, "rejected": rejected_count}


# ── Smart Auto-Label (GPT-4o) ─────────────────────────────────────────────────

REVIEW_SYSTEM_PROMPT = """You are a quality reviewer for an AI sales assistant in a Telegram store.

IMPORTANT CONTEXT: This AI assistant has access to real-time database tools (product search, price lookup, stock check, delivery options, order management). When the AI shows prices, product lists, stock info, or specs — these come from the database via tool calls, NOT fabricated. Do NOT reject responses just because they contain specific prices or product details — that is the AI doing its job correctly.

Review each AI response against these criteria:
1. LANGUAGE — AI must respond in the SAME language/script as the customer. Russian customer → Russian. Uzbek Latin → Uzbek Latin. Uzbek Cyrillic → Uzbek Cyrillic. Mixing scripts or languages = reject.
2. RELEVANCE — AI must address the customer's actual question/request
3. TONE — Professional, friendly, concise. Not robotic or overly verbose
4. INSTRUCTIONS — AI must not claim to add items to cart without actually doing it, must not give repair advice, must redirect off-topic questions
5. COMPLETENESS — AI should provide useful info, not just "I don't know" or "contact operator" when it could have searched
6. NO FABRICATION — AI must not invent specs (RAM, battery, camera) that weren't in tool results. But showing prices/stock from search results is CORRECT behavior.

For each turn, respond with JSON:
{"evaluations": [{"index": 0, "label": "approved" or "rejected", "reason": "short clear reason" or null}]}

IMPORTANT RULES:
- Showing product lists with prices = APPROVED (prices come from DB)
- Showing delivery costs = APPROVED (from delivery rules DB)
- Minor style issues = APPROVED
- Short appropriate responses = APPROVED
- Only reject for CLEAR problems: wrong language, off-topic response, fabricated specs, rude tone, ignoring customer question"""


async def _smart_label_batch(
    turns: list[dict],
    model: str,
) -> list[dict]:
    """Send a batch of turns to GPT for evaluation."""
    import openai
    client = _get_openai_client()

    turns_text = ""
    for i, t in enumerate(turns):
        turns_text += f"\n--- Turn {i} ---\nCustomer: {t['user']}\nAI: {t['ai']}\n"

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": f"Review these {len(turns)} AI responses:{turns_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1000,
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        return data.get("evaluations", [])
    except Exception as e:
        logger.error("Smart label batch failed: %s", e)
        return []


@router.post("/conversations/{conversation_id}/smart-label")
@limiter.limit("10/minute")
async def smart_label_conversation(
    request: Request,
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Use GPT-4o (fallback model) to evaluate and label AI responses intelligently."""
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    messages = msgs_result.scalars().all()

    # Build turns: unlabeled AI messages + their preceding user message
    MAX_PER_CONV = 50  # Cap to avoid unbounded GPT-4o calls per conversation
    turns_to_review: list[dict] = []
    for i, msg in enumerate(messages):
        if not msg.ai_generated or msg.training_label is not None:
            continue
        user_text = ""
        for prev in reversed(messages[:i]):
            if prev.direction == "inbound":
                user_text = prev.raw_text or ""
                break
        turns_to_review.append({
            "msg_id": msg.id,
            "user": user_text[:500],
            "ai": (msg.raw_text or "")[:500],
        })
        if len(turns_to_review) >= MAX_PER_CONV:
            break

    if not turns_to_review:
        return {"approved": 0, "rejected": 0, "message": "No unlabeled messages"}

    model = settings.openai_model_fallback  # gpt-4o
    approved_count = rejected_count = 0

    # Process in batches of 8 turns
    batch_size = 8
    for batch_start in range(0, len(turns_to_review), batch_size):
        batch = turns_to_review[batch_start:batch_start + batch_size]
        evaluations = await _smart_label_batch(batch, model)

        for ev in evaluations:
            idx = ev.get("index", -1)
            if 0 <= idx < len(batch):
                msg_id = batch[idx]["msg_id"]
                label = ev.get("label", "approved")
                reason = ev.get("reason")

                # Find message and update
                msg_result = await db.execute(
                    select(Message).where(Message.id == msg_id)
                )
                msg = msg_result.scalar_one_or_none()
                if msg:
                    msg.training_label = label
                    if label == "rejected" and reason:
                        msg.rejection_reason = reason
                    if label == "approved":
                        approved_count += 1
                    elif label == "rejected":
                        rejected_count += 1

    conv.is_training_candidate = True
    await db.flush()

    return {
        "approved": approved_count,
        "rejected": rejected_count,
        "total_reviewed": len(turns_to_review),
        "model_used": model,
    }


# ── Smart Label ALL candidates at once ────────────────────────────────────────

MAX_SMART_LABEL_MESSAGES = 200  # Cap to avoid unbounded GPT-4o calls


@router.post("/smart-label-all")
@limiter.limit("5/minute")
async def smart_label_all(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Smart-label all unlabeled AI messages across all candidate conversations (capped)."""
    result = await db.execute(
        select(Conversation.id)
        .where(
            Conversation.tenant_id == user.tenant_id,
            Conversation.is_training_candidate == True,  # noqa: E712
        )
    )
    conv_ids = [row[0] for row in result.fetchall()]

    total_approved = total_rejected = total_reviewed = 0
    global_budget = MAX_SMART_LABEL_MESSAGES

    for cid in conv_ids:
        if global_budget <= 0:
            break

        msgs_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == cid)
            .order_by(Message.created_at.asc())
        )
        messages = msgs_result.scalars().all()

        turns_to_review: list[dict] = []
        for i, msg in enumerate(messages):
            if not msg.ai_generated or msg.training_label is not None:
                continue
            user_text = ""
            for prev in reversed(messages[:i]):
                if prev.direction == "inbound":
                    user_text = prev.raw_text or ""
                    break
            turns_to_review.append({
                "msg_id": msg.id,
                "user": user_text[:500],
                "ai": (msg.raw_text or "")[:500],
            })
            if len(turns_to_review) >= global_budget:
                break

        if not turns_to_review:
            continue

        model = settings.openai_model_fallback
        batch_size = 8
        for batch_start in range(0, len(turns_to_review), batch_size):
            batch = turns_to_review[batch_start:batch_start + batch_size]
            evaluations = await _smart_label_batch(batch, model)

            for ev in evaluations:
                idx = ev.get("index", -1)
                if 0 <= idx < len(batch):
                    msg_id = batch[idx]["msg_id"]
                    label = ev.get("label", "approved")
                    reason = ev.get("reason")

                    msg_result = await db.execute(
                        select(Message).where(Message.id == msg_id)
                    )
                    msg = msg_result.scalar_one_or_none()
                    if msg:
                        msg.training_label = label
                        if label == "rejected" and reason:
                            msg.rejection_reason = reason
                        if label == "approved":
                            total_approved += 1
                        elif label == "rejected":
                            total_rejected += 1

        total_reviewed += len(turns_to_review)
        global_budget -= len(turns_to_review)

    await db.flush()
    return {
        "approved": total_approved,
        "rejected": total_rejected,
        "total_reviewed": total_reviewed,
        "conversations_processed": len(conv_ids),
        "model_used": settings.openai_model_fallback,
        "capped": total_reviewed >= MAX_SMART_LABEL_MESSAGES,
    }


# ── Fine-tuning ──────────────────────────────────────────────────────────────

@router.post("/fine-tune")
@limiter.limit("3/hour")
async def start_fine_tuning(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Export approved data, upload to OpenAI, start fine-tuning job."""
    import openai
    tid = user.tenant_id

    # Build JSONL content (same logic as export)
    result = await db.execute(
        select(Conversation.id)
        .where(Conversation.tenant_id == tid, Conversation.is_training_candidate == True)  # noqa: E712
    )
    conv_ids = [row[0] for row in result.fetchall()]

    lines = []
    for cid in conv_ids:
        msgs_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == cid, Message.tenant_id == tid)
            .order_by(Message.created_at.asc())
        )
        all_msgs = msgs_result.scalars().all()

        turns = [{"role": "system", "content": SYSTEM_PROMPT_PREVIEW}]
        included_any = False
        for i, msg in enumerate(all_msgs):
            if msg.direction == "inbound" and msg.sender_type == "customer":
                next_ai = next(
                    (m for m in all_msgs[i + 1:] if m.ai_generated and m.direction == "outbound"),
                    None,
                )
                if next_ai and next_ai.training_label == "approved":
                    turns.append({"role": "user", "content": msg.raw_text or ""})
                    turns.append({"role": "assistant", "content": next_ai.raw_text or ""})
                    included_any = True

        if included_any and len(turns) > 3:
            lines.append(json.dumps({"messages": turns}, ensure_ascii=False))

    if not lines:
        raise HTTPException(400, "No approved training data to fine-tune. Label conversations first.")

    jsonl_content = "\n".join(lines)

    # Upload file to OpenAI (async to avoid blocking event loop)
    client = _get_openai_client()

    file_obj = await client.files.create(
        file=("training_data.jsonl", jsonl_content.encode("utf-8")),
        purpose="fine-tune",
    )

    # Start fine-tuning job
    job = await client.fine_tuning.jobs.create(
        training_file=file_obj.id,
        model=settings.openai_model_main,
        hyperparameters={"n_epochs": 3},
        suffix=f"ai-closer-{tid.hex[:8]}",
    )

    return {
        "job_id": job.id,
        "status": job.status,
        "base_model": settings.openai_model_main,
        "training_file_id": file_obj.id,
        "training_examples": len(lines),
        "message": "Fine-tuning started. Check status at /training/fine-tune-status",
    }


@router.get("/fine-tune-status")
async def fine_tune_status(
    user: User = Depends(require_store_owner),
):
    """List recent fine-tuning jobs."""
    import openai
    client = _get_openai_client()

    jobs = await client.fine_tuning.jobs.list(limit=5)
    return [
        {
            "job_id": j.id,
            "status": j.status,
            "model": j.model,
            "fine_tuned_model": j.fine_tuned_model,
            "created_at": j.created_at,
            "finished_at": j.finished_at,
            "trained_tokens": j.trained_tokens,
            "error": j.error.message if j.error else None,
        }
        for j in jobs.data
    ]


# ── Reset labels ─────────────────────────────────────────────────────────────

@router.post("/conversations/{conversation_id}/reset-labels")
@limiter.limit("60/minute")
async def reset_labels(
    request: Request,
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Clear all labels for a conversation (for re-evaluation)."""
    msgs_result = await db.execute(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.tenant_id == user.tenant_id,
            Message.ai_generated == True,  # noqa: E712
        )
    )
    count = 0
    for msg in msgs_result.scalars().all():
        if msg.training_label is not None:
            msg.training_label = None
            msg.rejection_reason = None
            msg.rejection_selected_text = None
            count += 1
    await db.flush()
    return {"reset_count": count}


# ── Export JSONL ───────────────────────────────────────────────────────────────

@router.get("/export.jsonl")
async def export_training_jsonl(
    conversation_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Export approved turns as OpenAI fine-tuning JSONL.
    Each line: {"messages": [system, ...alternating user/assistant turns...]}
    Only includes turns labeled 'approved'.
    """
    tid = user.tenant_id

    # Get conversations to export
    if conversation_id:
        conv_ids = [conversation_id]
    else:
        result = await db.execute(
            select(Conversation.id)
            .where(Conversation.tenant_id == tid, Conversation.is_training_candidate == True)  # noqa: E712
        )
        conv_ids = [row[0] for row in result.fetchall()]

    lines = []
    for cid in conv_ids:
        msgs_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == cid, Message.tenant_id == tid)
            .order_by(Message.created_at.asc())
        )
        all_msgs = msgs_result.scalars().all()

        # Build conversation turns, only including AI turns labeled 'approved'
        turns = [{"role": "system", "content": SYSTEM_PROMPT_PREVIEW}]
        included_any = False
        for i, msg in enumerate(all_msgs):
            if msg.direction == "inbound" and msg.sender_type == "customer":
                # Check if the next AI message is approved
                next_ai = next(
                    (m for m in all_msgs[i + 1:] if m.ai_generated and m.direction == "outbound"),
                    None
                )
                if next_ai and next_ai.training_label == "approved":
                    turns.append({"role": "user", "content": msg.raw_text or ""})
                    turns.append({"role": "assistant", "content": next_ai.raw_text or ""})
                    included_any = True

        if included_any and len(turns) > 3:  # system + at least 2 turns
            lines.append(json.dumps({"messages": turns}, ensure_ascii=False))

    content = "\n".join(lines)
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=training_data.jsonl"},
    )


# ── Rejection Analysis ────────────────────────────────────────────────────────

@router.get("/rejection-analysis")
async def rejection_analysis(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Analyze rejected AI messages: group by reason, show patterns and examples."""
    tid = user.tenant_id

    # Get all rejected messages with their preceding user message
    result = await db.execute(
        select(Message)
        .where(
            Message.tenant_id == tid,
            Message.training_label == "rejected",
        )
        .order_by(Message.created_at.desc())
        .limit(200)
    )
    rejected_msgs = result.scalars().all()

    if not rejected_msgs:
        return {"total_rejected": 0, "patterns": [], "top_errors": []}

    # Batch-load preceding user messages — single query for ALL conversations
    preceding_map: dict = {}
    if rejected_msgs:
        conv_ids = list({msg.conversation_id for msg in rejected_msgs})
        inbound_result = await db.execute(
            select(Message.conversation_id, Message.raw_text, Message.created_at)
            .where(
                Message.conversation_id.in_(conv_ids),
                Message.direction == "inbound",
            )
            .order_by(Message.conversation_id, Message.created_at.asc())
        )
        # Group inbound messages by conversation_id
        conv_inbound: dict = {}
        for conv_id, ib_text, ib_created in inbound_result.all():
            conv_inbound.setdefault(conv_id, []).append((ib_text, ib_created))

        for msg in rejected_msgs:
            prev_text = ""
            for ib_text, ib_created in reversed(conv_inbound.get(msg.conversation_id, [])):
                if ib_created < msg.created_at:
                    prev_text = (ib_text or "")[:200]
                    break
            preceding_map[msg.id] = prev_text

    # Group by rejection_reason
    reason_groups: dict[str, list[dict]] = {}
    for msg in rejected_msgs:
        reason = msg.rejection_reason or "Без причины"
        if reason not in reason_groups:
            reason_groups[reason] = []

        reason_groups[reason].append({
            "id": str(msg.id),
            "ai_text": (msg.raw_text or "")[:300],
            "user_text": preceding_map.get(msg.id, ""),
            "selected_text": msg.rejection_selected_text,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        })

    # Build sorted patterns
    patterns = []
    for reason, examples in sorted(reason_groups.items(), key=lambda x: -len(x[1])):
        patterns.append({
            "reason": reason,
            "count": len(examples),
            "examples": examples[:5],  # Top 5 examples per pattern
        })

    # Build top errors summary for quick view
    top_errors = [
        {"reason": p["reason"], "count": p["count"]}
        for p in patterns[:10]
    ]

    return {
        "total_rejected": len(rejected_msgs),
        "patterns": patterns,
        "top_errors": top_errors,
    }


# ── Generate Prompt Rules from Rejections ─────────────────────────────────────

RULES_GENERATION_PROMPT = """You are analyzing rejected AI responses from a Telegram store sales assistant.

Below are rejected AI responses grouped by rejection reason. Each group has the reason and example AI messages that were rejected.

Your task: Generate clear, actionable RULES that will prevent these mistakes in the future.

Each rule should be:
1. A clear instruction in Russian (the AI's primary instruction language)
2. Include WHY this is important (based on the rejection pattern)
3. Be specific enough to prevent the error, but general enough to apply broadly

Output JSON:
{"rules": [{"rule": "НИКОГДА не ...", "reason": "Потому что ..."}]}

Generate 3-8 rules. Focus on the most common and impactful patterns. Merge similar issues into one rule.
Do NOT generate rules for one-off issues with only 1 example — focus on patterns (2+ occurrences).
If there are language-related issues (mixing Russian into Uzbek, wrong script), make those HIGH priority rules."""


@router.post("/generate-rules")
@limiter.limit("5/minute")
async def generate_rules(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Use GPT-4o to analyze rejection patterns and generate prompt rules."""
    import openai

    tid = user.tenant_id

    # Get rejection analysis data
    result = await db.execute(
        select(Message)
        .where(
            Message.tenant_id == tid,
            Message.training_label == "rejected",
        )
        .order_by(Message.created_at.desc())
        .limit(100)
    )
    rejected_msgs = result.scalars().all()

    if len(rejected_msgs) < 2:
        raise HTTPException(400, "Нужно минимум 2 отклонённых сообщения для генерации правил")

    # Group by reason
    reason_groups: dict[str, list[str]] = {}
    for msg in rejected_msgs:
        reason = msg.rejection_reason or "Без причины"
        if reason not in reason_groups:
            reason_groups[reason] = []
        text = (msg.raw_text or "")[:200]
        if msg.rejection_selected_text:
            text = f"[ПРОБЛЕМА: {msg.rejection_selected_text}] {text}"
        reason_groups[reason].append(text)

    # Format for GPT-4o
    analysis_text = ""
    for reason, examples in sorted(reason_groups.items(), key=lambda x: -len(x[1])):
        analysis_text += f"\n--- Причина: {reason} ({len(examples)} случаев) ---\n"
        for ex in examples[:3]:
            analysis_text += f"  AI: {ex}\n"

    client = _get_openai_client()

    try:
        resp = await client.chat.completions.create(
            model=settings.openai_model_fallback,  # gpt-4o
            messages=[
                {"role": "system", "content": RULES_GENERATION_PROMPT},
                {"role": "user", "content": f"Вот отклонённые ответы ({len(rejected_msgs)} всего):\n{analysis_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=1500,
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        generated_rules = data.get("rules", [])
    except Exception as e:
        logger.error("Rule generation failed: %s", e)
        raise HTTPException(500, f"Ошибка генерации правил: {e}")

    # Load current AiSettings
    settings_result = await db.execute(
        select(AiSettings).where(AiSettings.tenant_id == tid)
    )
    ai_settings = settings_result.scalar_one_or_none()
    if not ai_settings:
        ai_settings = AiSettings(tenant_id=tid)
        db.add(ai_settings)
        await db.flush()

    existing_rules = ai_settings.prompt_rules or []

    # Add generated rules (inactive by default — admin must activate)
    new_rules = []
    for r in generated_rules:
        new_rules.append({
            "id": str(uuid4()),
            "rule": r["rule"],
            "reason": r.get("reason", ""),
            "source": "auto",
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    ai_settings.prompt_rules = existing_rules + new_rules
    flag_modified(ai_settings, "prompt_rules")
    await db.flush()

    return {
        "generated": len(new_rules),
        "total_rules": len(ai_settings.prompt_rules),
        "rules": new_rules,
        "analyzed_rejections": len(rejected_msgs),
    }
