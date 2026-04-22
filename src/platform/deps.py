"""Platform-level FastAPI dependencies.

These are cross-cutting guards that enforce platform settings
on tenant-level endpoints.
"""

from fastapi import HTTPException

from src.platform.settings_cache import get_platform_settings


async def check_not_read_only():
    """Raise 403 if platform is in read-only mode.

    Apply as a dependency to POST/PUT/PATCH/DELETE endpoints on:
    - orders/router.py
    - catalog/router.py
    - conversations/router.py

    Do NOT apply to:
    - auth endpoints (login/logout must always work)
    - platform admin endpoints (super_admin should always work)
    """
    if get_platform_settings().get("read_only_mode"):
        raise HTTPException(
            status_code=403,
            detail="Платформа в режиме read-only. Изменения заблокированы.",
        )
