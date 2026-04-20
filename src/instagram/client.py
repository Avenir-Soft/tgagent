"""Meta Graph API client for Instagram messaging and comments.

Handles DM sending, comment replies, user profile lookup, and token management.
Uses httpx for async HTTP requests with retry logic.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_GRAPH_API_BASE = "https://graph.instagram.com/v21.0"
_GRAPH_FB_BASE = "https://graph.facebook.com/v21.0"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class InstagramApiClient:
    """Async wrapper for Meta Graph API (Instagram Messaging + Comments)."""

    def __init__(self, access_token: str, ig_user_id: str, page_id: str | None = None):
        self.access_token = access_token
        self.ig_user_id = ig_user_id
        self.page_id = page_id
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    async def close(self):
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    # ── Messaging (DMs) ─────────────────────────────────────────────────

    async def send_text_message(self, recipient_id: str, text: str) -> dict | None:
        """Send a text DM to a user. Returns message ID or None on failure."""
        url = f"{_GRAPH_API_BASE}/{self.ig_user_id}/messages"
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        }
        return await self._post(url, payload, "send_text_message")

    async def send_image_message(self, recipient_id: str, image_url: str) -> dict | None:
        """Send an image DM to a user."""
        url = f"{_GRAPH_API_BASE}/{self.ig_user_id}/messages"
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {"url": image_url},
                }
            },
        }
        return await self._post(url, payload, "send_image_message")

    # ── Comments ─────────────────────────────────────────────────────────

    async def reply_to_comment(self, comment_id: str, text: str) -> dict | None:
        """Reply to a comment on a post."""
        url = f"{_GRAPH_API_BASE}/{comment_id}/replies"
        payload = {"message": text}
        return await self._post(url, payload, "reply_to_comment")

    # ── User Profile ─────────────────────────────────────────────────────

    async def get_user_profile(self, user_id: str) -> dict | None:
        """Get Instagram user profile (username, name)."""
        url = f"{_GRAPH_API_BASE}/{user_id}"
        params = {"fields": "username,name,profile_picture_url", "access_token": self.access_token}
        try:
            resp = await self._client.get(url, params=params)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("get_user_profile failed: %s %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("get_user_profile error: %s", e)
        return None

    # ── Token Management ─────────────────────────────────────────────────

    @staticmethod
    async def exchange_for_long_lived_token(
        short_token: str, app_id: str, app_secret: str,
    ) -> dict | None:
        """Exchange a short-lived token for a long-lived one (60 days).

        Returns {"access_token": str, "expires_in": int} or None.
        """
        url = f"{_GRAPH_FB_BASE}/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info("Token exchanged, expires_in=%s", data.get("expires_in"))
                    return data
                logger.error("Token exchange failed: %s %s", resp.status_code, resp.text[:200])
            except Exception as e:
                logger.error("Token exchange error: %s", e)
        return None

    @staticmethod
    async def refresh_long_lived_token(current_token: str) -> dict | None:
        """Refresh a long-lived token (must be at least 24h old, not expired).

        Returns {"access_token": str, "expires_in": int} or None.
        """
        url = f"{_GRAPH_FB_BASE}/oauth/access_token"
        params = {
            "grant_type": "ig_refresh_token",
            "access_token": current_token,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info("Token refreshed, expires_in=%s", data.get("expires_in"))
                    return data
                logger.error("Token refresh failed: %s %s", resp.status_code, resp.text[:200])
            except Exception as e:
                logger.error("Token refresh error: %s", e)
        return None

    @staticmethod
    def token_expiry_from_seconds(expires_in: int) -> datetime:
        """Convert expires_in seconds to absolute datetime."""
        return datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # ── Internal ─────────────────────────────────────────────────────────

    async def _post(self, url: str, payload: dict, op_name: str) -> dict | None:
        """POST with retry (1 retry on 5xx/timeout)."""
        for attempt in range(2):
            try:
                resp = await self._client.post(url, json=payload, headers=self._headers())
                if resp.status_code == 200:
                    return resp.json()
                body = resp.text[:300]
                if resp.status_code >= 500 and attempt == 0:
                    logger.warning("%s 5xx (attempt %d): %s", op_name, attempt, body)
                    continue
                logger.error("%s failed: %s %s", op_name, resp.status_code, body)
                return {"error": body, "status": resp.status_code}
            except httpx.TimeoutException:
                if attempt == 0:
                    logger.warning("%s timeout, retrying...", op_name)
                    continue
                logger.error("%s timeout after retry", op_name)
            except Exception as e:
                logger.error("%s error: %s", op_name, e)
                break
        return None
