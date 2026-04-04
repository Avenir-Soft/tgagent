"""Tenant context management for multi-tenant isolation."""

from contextvars import ContextVar
from uuid import UUID

_current_tenant_id: ContextVar[UUID | None] = ContextVar("current_tenant_id", default=None)


def get_current_tenant_id() -> UUID | None:
    return _current_tenant_id.get()


def set_current_tenant_id(tenant_id: UUID) -> None:
    _current_tenant_id.set(tenant_id)


def require_tenant_id() -> UUID:
    tid = _current_tenant_id.get()
    if tid is None:
        raise RuntimeError("No tenant context set — this operation requires a tenant")
    return tid
