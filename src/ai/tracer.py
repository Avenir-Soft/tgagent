"""AI Trace Monitor — persistent DB storage for AI pipeline traces.

Captures every step of the orchestrator pipeline:
- Tool calls with args and results
- Timing for each step
- Photo handling decisions
- Final response

Traces are stored in PostgreSQL (ai_trace_logs table) — persistent across restarts.
"""

import logging
import time
from dataclasses import dataclass, field, asdict
from uuid import UUID, uuid4

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_RESULT_PREVIEW = 5000  # chars


@dataclass
class TraceStep:
    """Single step in an AI trace."""
    type: str  # "tool_call", "tool_result", "llm_call", "photo", "guard", "state", "info"
    label: str
    detail: str = ""
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return asdict(self)


@dataclass
class AITrace:
    """Complete trace of one AI interaction."""
    trace_id: str = field(default_factory=lambda: str(uuid4())[:8])
    conversation_id: str = ""
    user_message: str = ""
    detected_language: str = ""
    steps: list[TraceStep] = field(default_factory=list)
    final_response: str = ""
    image_urls: list[str] = field(default_factory=list)
    total_duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)
    tools_called: list[str] = field(default_factory=list)
    model: str = ""
    state_before: str = ""
    state_after: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add_step(self, type: str, label: str, detail: str = "", duration_ms: int = 0):
        self.steps.append(TraceStep(
            type=type,
            label=label,
            detail=detail[:MAX_RESULT_PREVIEW] if detail else "",
            duration_ms=duration_ms,
        ))

    def to_dict(self):
        d = asdict(self)
        d["steps"] = [s.to_dict() for s in self.steps]
        return d


def start_trace(tenant_id: UUID, conversation_id: UUID, user_message: str) -> AITrace:
    """Create a new trace for an AI interaction."""
    trace = AITrace(
        conversation_id=str(conversation_id),
        user_message=user_message[:200],
    )
    return trace


async def finish_trace(tenant_id: UUID, trace: AITrace, db: AsyncSession):
    """Finalize and persist the trace to DB."""
    try:
        from src.ai.models import AITraceLog

        log = AITraceLog(
            tenant_id=tenant_id,
            conversation_id=UUID(trace.conversation_id) if trace.conversation_id else None,
            trace_id=trace.trace_id,
            user_message=trace.user_message,
            detected_language=trace.detected_language,
            model=trace.model,
            state_before=trace.state_before,
            state_after=trace.state_after,
            tools_called=trace.tools_called,
            steps=[s.to_dict() for s in trace.steps],
            final_response=trace.final_response,
            image_urls=trace.image_urls,
            total_duration_ms=trace.total_duration_ms,
            prompt_tokens=trace.prompt_tokens,
            completion_tokens=trace.completion_tokens,
        )
        db.add(log)
        await db.flush()
        logger.debug("AI trace %s persisted (%d steps, %dms)", trace.trace_id, len(trace.steps), trace.total_duration_ms)
    except Exception:
        logger.warning("Failed to persist AI trace %s (non-fatal)", trace.trace_id, exc_info=True)


async def get_traces(tenant_id: UUID, db: AsyncSession, limit: int = 30, offset: int = 0) -> tuple[list[dict], int]:
    """Get traces for a tenant from DB. Returns (traces_list, total_count)."""
    from src.ai.models import AITraceLog

    # Total count
    count_result = await db.execute(
        select(func.count(AITraceLog.id)).where(AITraceLog.tenant_id == tenant_id)
    )
    total = count_result.scalar() or 0

    # Traces (newest first)
    result = await db.execute(
        select(AITraceLog)
        .where(AITraceLog.tenant_id == tenant_id)
        .order_by(AITraceLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.scalars().all()

    traces = []
    for row in rows:
        traces.append({
            "trace_id": row.trace_id,
            "conversation_id": str(row.conversation_id) if row.conversation_id else "",
            "user_message": row.user_message,
            "detected_language": row.detected_language,
            "steps": row.steps or [],
            "final_response": row.final_response,
            "image_urls": row.image_urls or [],
            "total_duration_ms": row.total_duration_ms,
            "timestamp": row.created_at.timestamp() if row.created_at else 0,
            "tools_called": row.tools_called or [],
            "model": row.model,
            "state_before": row.state_before,
            "state_after": row.state_after,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
        })

    return traces, total


async def clear_traces(tenant_id: UUID, db: AsyncSession):
    """Clear all traces for a tenant."""
    from src.ai.models import AITraceLog

    await db.execute(
        delete(AITraceLog).where(AITraceLog.tenant_id == tenant_id)
    )
    await db.flush()
