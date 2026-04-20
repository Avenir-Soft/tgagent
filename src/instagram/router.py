"""Instagram webhook receiver, OAuth callback, and account management endpoints.

Webhook: Meta sends POST /instagram/webhook for DMs and comments.
         GET  /instagram/webhook for verification (challenge-response).
OAuth:   POST /instagram/auth/connect — exchange short-lived token for long-lived.
Mgmt:    GET/DELETE /instagram/accounts, POST refresh-token.
"""

import hashlib
import hmac
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.config import settings
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.instagram.models import InstagramAccount
from src.instagram.schemas import InstagramAccountOut, InstagramConnectRequest
from src.instagram.service import instagram_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/instagram", tags=["instagram"])


# ── Webhook Verification (Meta requirement) ─────────────────────────────────

@router.get("/webhook")
async def webhook_verify(
    request: Request,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Verify webhook subscription — Meta sends GET with challenge."""
    if hub_mode == "subscribe" and hub_verify_token == settings.instagram_webhook_verify_token:
        logger.info("Instagram webhook verified")
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


# ── Webhook Event Receiver ───────────────────────────────────────────────────

@router.post("/webhook")
async def webhook_receive(request: Request):
    """Receive webhook events from Meta (DMs + comments).

    Meta expects 200 within 20 seconds — process async.
    """
    body = await request.body()

    # Verify HMAC signature (if app_secret is configured)
    if settings.instagram_app_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(body, signature, settings.instagram_app_secret):
            logger.warning("Invalid webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

    import json
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Meta sends: {"object": "instagram", "entry": [...]}
    if payload.get("object") != "instagram":
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        try:
            await instagram_manager.handle_webhook_event(entry)
        except Exception:
            logger.exception("Error handling webhook entry")

    return {"status": "ok"}


# ── OAuth / Token Exchange ───────────────────────────────────────────────────

@router.post("/auth/connect", response_model=InstagramAccountOut)
@limiter.limit("5/minute")
async def connect_account(
    request: Request,
    data: InstagramConnectRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Connect an Instagram account by exchanging a short-lived token.

    User provides access_token from Facebook Login / Graph API Explorer.
    We exchange it for a 60-day long-lived token and save the account.
    """
    from src.instagram.client import InstagramApiClient

    # Exchange for long-lived token
    long_lived = await InstagramApiClient.exchange_for_long_lived_token(
        short_token=data.access_token,
        app_id=settings.instagram_app_id,
        app_secret=settings.instagram_app_secret,
    )

    if not long_lived:
        raise HTTPException(status_code=400, detail="Failed to exchange token. Check App ID/Secret and token validity.")

    access_token = long_lived["access_token"]
    expires_in = long_lived.get("expires_in", 5184000)  # default 60 days

    # Get Instagram user profile to determine user ID and username
    temp_client = InstagramApiClient(access_token=access_token, ig_user_id="me")
    ig_user_id = data.instagram_user_id

    if not ig_user_id:
        # Try to get from /me endpoint
        import httpx
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                "https://graph.instagram.com/v21.0/me",
                params={"fields": "id,username,name", "access_token": access_token},
            )
            if resp.status_code == 200:
                me = resp.json()
                ig_user_id = me.get("id")
            else:
                await temp_client.close()
                raise HTTPException(status_code=400, detail="Could not determine Instagram user ID")

    profile = await temp_client.get_user_profile(ig_user_id)
    await temp_client.close()

    ig_username = profile.get("username") if profile else None
    ig_name = profile.get("name") if profile else None

    # Check if account already exists
    existing = await db.execute(
        select(InstagramAccount).where(
            InstagramAccount.tenant_id == user.tenant_id,
            InstagramAccount.instagram_user_id == ig_user_id,
        )
    )
    account = existing.scalar_one_or_none()

    if account:
        # Update token
        account.access_token = access_token
        account.token_expires_at = InstagramApiClient.token_expiry_from_seconds(expires_in)
        account.status = "connected"
        if ig_username:
            account.instagram_username = ig_username
        if ig_name:
            account.display_name = ig_name
    else:
        account = InstagramAccount(
            tenant_id=user.tenant_id,
            instagram_user_id=ig_user_id,
            instagram_username=ig_username,
            display_name=ig_name,
            access_token=access_token,
            token_expires_at=InstagramApiClient.token_expiry_from_seconds(expires_in),
            status="connected",
            is_primary=True,
        )
        db.add(account)

    await db.commit()
    await db.refresh(account)

    # Start the client
    await instagram_manager.start_client(account)

    return account


# ── Account Management ───────────────────────────────────────────────────────

@router.get("/accounts", response_model=list[InstagramAccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List connected Instagram accounts for current tenant."""
    result = await db.execute(
        select(InstagramAccount).where(InstagramAccount.tenant_id == user.tenant_id)
    )
    return result.scalars().all()


@router.delete("/accounts/{account_id}")
async def disconnect_account(
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Disconnect an Instagram account."""
    result = await db.execute(
        select(InstagramAccount).where(
            InstagramAccount.id == account_id,
            InstagramAccount.tenant_id == user.tenant_id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    await instagram_manager.stop_client(user.tenant_id)
    account.status = "disconnected"
    account.access_token = None
    await db.commit()

    return {"status": "disconnected"}


@router.post("/accounts/{account_id}/refresh-token")
async def refresh_token(
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Manually refresh the access token."""
    from src.instagram.client import InstagramApiClient

    result = await db.execute(
        select(InstagramAccount).where(
            InstagramAccount.id == account_id,
            InstagramAccount.tenant_id == user.tenant_id,
        )
    )
    account = result.scalar_one_or_none()
    if not account or not account.access_token:
        raise HTTPException(status_code=404, detail="Account not found or no token")

    refreshed = await InstagramApiClient.refresh_long_lived_token(account.access_token)
    if not refreshed:
        raise HTTPException(status_code=400, detail="Token refresh failed")

    account.access_token = refreshed["access_token"]
    account.token_expires_at = InstagramApiClient.token_expiry_from_seconds(
        refreshed.get("expires_in", 5184000)
    )
    account.status = "connected"
    await db.commit()

    # Restart client with new token
    await instagram_manager.stop_client(user.tenant_id)
    await instagram_manager.start_client(account)

    return {"status": "refreshed", "expires_at": str(account.token_expires_at)}


@router.get("/status")
async def instagram_status(
    user: User = Depends(get_current_user),
):
    """Get Instagram connection status for current tenant."""
    account = instagram_manager.get_account(user.tenant_id)
    client = instagram_manager.get_client(user.tenant_id)

    if not account:
        return {"connected": False, "status": "no_account"}

    return {
        "connected": client is not None,
        "status": account.status,
        "username": account.instagram_username,
        "display_name": account.display_name,
        "token_expires_at": str(account.token_expires_at) if account.token_expires_at else None,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _verify_signature(body: bytes, signature: str, app_secret: str) -> bool:
    """Verify Meta webhook HMAC SHA-256 signature."""
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
