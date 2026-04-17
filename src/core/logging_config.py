"""Structured logging configuration.

In production (LOG_FORMAT=json), emits JSON lines for easy parsing by
Datadog / ELK / CloudWatch. In development (default), uses human-readable format.

Request context (request_id, tenant_id) is automatically attached via
ContextVar-backed filter — no manual ``extra=`` needed at call sites.

Usage: call ``setup_logging()`` once at startup (before any logger is used).
"""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from src.core.config import settings

# ── Context vars — set by middleware, read by log filter ─────────────────────

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
log_tenant_id_var: ContextVar[str | None] = ContextVar("log_tenant_id", default=None)
log_conversation_id_var: ContextVar[str | None] = ContextVar("log_conversation_id", default=None)


def set_log_context(
    *,
    request_id: str | None = None,
    tenant_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """Set logging context for the current async task / request."""
    if request_id is not None:
        request_id_var.set(request_id)
    if tenant_id is not None:
        log_tenant_id_var.set(tenant_id)
    if conversation_id is not None:
        log_conversation_id_var.set(conversation_id)


def generate_request_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Filter that injects context vars into every LogRecord ────────────────────

class _ContextFilter(logging.Filter):
    """Attach request_id, tenant_id, conversation_id from ContextVars."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get(None)  # type: ignore[attr-defined]
        record.tenant_id = log_tenant_id_var.get(None)  # type: ignore[attr-defined]
        record.conversation_id = log_conversation_id_var.get(None)  # type: ignore[attr-defined]
        return True


# ── Formatters ───────────────────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line — no external dependencies."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Context fields (set by _ContextFilter)
        for field in ("request_id", "tenant_id", "conversation_id"):
            val = getattr(record, field, None)
            if val is not None:
                log_entry[field] = val
        return json.dumps(log_entry, ensure_ascii=False)


_DEV_FORMAT = "%(asctime)s %(name)s %(levelname)s [%(request_id)s] %(message)s"


class _DevFormatter(logging.Formatter):
    """Human-readable formatter that gracefully handles missing context."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id") or record.request_id is None:  # type: ignore[attr-defined]
            record.request_id = "-"  # type: ignore[attr-defined]
        return super().format(record)


# ── Setup ────────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    """Configure root logger based on LOG_FORMAT env var."""
    log_format = getattr(settings, "log_format", "text")
    log_level = getattr(settings, "log_level", "INFO")

    root = logging.getLogger()
    root.setLevel(log_level.upper())

    # Remove existing handlers to avoid duplicates on reload
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(_DevFormatter(_DEV_FORMAT))

    # Attach context filter to root so every logger gets context vars
    handler.addFilter(_ContextFilter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    for noisy in ("telethon", "httpx", "httpcore", "openai", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
