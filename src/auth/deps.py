"""Authentication and authorization dependencies."""

import logging
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.core.database import get_db
from src.core.security import decode_access_token, is_token_blacklisted
from src.core.logging_config import set_log_context
from src.core.tenant_context import set_current_tenant_id

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Check if token was revoked (logout)
    try:
        if await is_token_blacklisted(token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    except HTTPException:
        raise  # Re-raise auth errors
    except Exception:
        logger.error("Redis unavailable for token blacklist check — fail-closed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth service temporarily unavailable")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == UUID(user_id), User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Set tenant context for the request + logging
    set_current_tenant_id(user.tenant_id)
    set_log_context(tenant_id=str(user.tenant_id))

    # Set PostgreSQL GUC for Row-Level Security (transaction-scoped)
    # set_config() is a regular function — works with asyncpg bind params (SET LOCAL doesn't)
    from sqlalchemy import text
    await db.execute(text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": str(user.tenant_id)})

    # Per-tenant rate limit (Redis counter, fail-open)
    from src.core.rate_limit import check_tenant_rate_limit
    await check_tenant_rate_limit(str(user.tenant_id))

    return user


def require_role(*roles: str):
    """Dependency factory that checks user role."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _check


require_super_admin = require_role("super_admin")
require_store_owner = require_role("super_admin", "store_owner")
require_operator = require_role("super_admin", "store_owner", "operator")
