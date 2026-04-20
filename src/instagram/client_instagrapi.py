"""Instagram client using instagrapi (unofficial API).

Drop-in replacement for InstagramApiClient while Meta Developer registration
is unavailable. Same interface — service.py works with either client.

DELETE THIS FILE when official Meta Graph API client is working.
"""

import asyncio
import json
import logging
import os
import time
from functools import partial
from pathlib import Path

logger = logging.getLogger(__name__)

_SESSION_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / "sessions"


class LoginRequiredError(Exception):
    """Raised when Instagram session is expired/invalid."""
    pass


class InstagrapiClient:
    """Async wrapper around instagrapi.Client (sync → asyncio.to_thread)."""

    def __init__(self, username: str, password: str = "", session_id: str = "", proxy: str = ""):
        from instagrapi import Client as IGClient

        self._cl = IGClient()
        self._username = username
        self._password = password
        self._session_id = session_id
        self._proxy = proxy
        self._logged_in = False
        self.ig_user_id: str = ""  # Set after login (PK as string)

        if proxy:
            self._cl.set_proxy(proxy)
            logger.info("Instagram proxy set: %s", proxy.split("@")[-1] if "@" in proxy else proxy)

    @property
    def _session_file(self) -> Path:
        return _SESSION_DIR / f"ig_{self._username}.json"

    async def login(self) -> None:
        """Login to Instagram — try sessionid first (from browser), then password."""
        _SESSION_DIR.mkdir(exist_ok=True)

        # Method 1: sessionid (from browser cookie — most reliable when account is flagged)
        if self._session_id:
            try:
                await asyncio.to_thread(
                    self._cl.login_by_sessionid, self._session_id
                )
                self._logged_in = True
                self.ig_user_id = str(self._cl.user_id)
                logger.info("Instagrapi logged in (sessionid) as @%s pk=%s",
                            self._username, self.ig_user_id)
                return
            except Exception as e:
                logger.warning("Sessionid login failed: %s", e)

        # Method 2: username/password login
        if self._password:
            try:
                if self._session_file.exists():
                    try:
                        self._cl.load_settings(str(self._session_file))
                    except Exception:
                        pass
                await asyncio.to_thread(self._cl.login, self._username, self._password)
                self._logged_in = True
                self.ig_user_id = str(self._cl.user_id)
                self._save_session()
                logger.info("Instagrapi logged in (password) as @%s pk=%s",
                            self._username, self.ig_user_id)
                return
            except Exception as e:
                logger.warning("Password login failed: %s", e)

        raise RuntimeError("No valid login method — provide password or session_id")

    async def relogin(self) -> bool:
        """Force fresh login — delete stale session and re-authenticate.

        Returns True on success, False on failure.
        """
        logger.info("Attempting relogin for @%s", self._username)

        # Delete stale session file
        try:
            if self._session_file.exists():
                self._session_file.unlink()
                logger.info("Deleted stale session file: %s", self._session_file)
        except Exception as e:
            logger.warning("Failed to delete session file: %s", e)

        # Create a fresh client instance to avoid stale internal state
        from instagrapi import Client as IGClient
        self._cl = IGClient()
        if self._proxy:
            self._cl.set_proxy(self._proxy)
        self._logged_in = False

        try:
            await self.login()
            return True
        except Exception as e:
            logger.error("Relogin failed for @%s: %s", self._username, e)
            return False

    def _save_session(self) -> None:
        """Save session to file for faster future logins."""
        try:
            self._cl.dump_settings(str(self._session_file))
        except Exception:
            pass

    async def close(self) -> None:
        """No persistent connection to close."""
        self._logged_in = False

    # ── Messaging (DMs) — same interface as client.py ───────────────────

    async def send_text_message(self, recipient_id: str, text: str) -> dict | None:
        """Send a text DM. recipient_id = user PK as string."""
        try:
            result = await asyncio.to_thread(
                self._cl.direct_send, text, user_ids=[int(recipient_id)]
            )
            return {"message_id": str(getattr(result, "id", ""))}
        except Exception as e:
            logger.error("instagrapi send_text error: %s", e)
            return {"error": str(e)}

    async def send_image_message(self, recipient_id: str, image_url: str) -> dict | None:
        """Send an image DM — download to temp file then send."""
        import httpx
        import tempfile

        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(image_url)
                if resp.status_code != 200:
                    return {"error": f"download failed: {resp.status_code}"}
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                tmp.write(resp.content)
                tmp_path = tmp.name
                tmp.close()

            result = await asyncio.to_thread(
                self._cl.direct_send_photo, tmp_path, user_ids=[int(recipient_id)]
            )

            try:
                os.unlink(tmp_path)
            except Exception:
                pass

            return {"message_id": str(getattr(result, "id", ""))}
        except Exception as e:
            logger.error("instagrapi send_image error: %s", e)
            return {"error": str(e)}

    # ── Comments — same interface as client.py ──────────────────────────

    async def reply_to_comment(
        self, comment_id: str, text: str, *, media_id: str | None = None,
    ) -> dict | None:
        """Reply to a comment. media_id required for instagrapi."""
        if not media_id:
            logger.warning("reply_to_comment: media_id required for instagrapi")
            return None
        try:
            result = await asyncio.to_thread(
                partial(
                    self._cl.media_comment,
                    media_id,
                    text,
                    replied_to_comment_id=int(comment_id),
                )
            )
            return {"comment_id": str(getattr(result, "pk", ""))}
        except Exception as e:
            logger.error("instagrapi reply_comment error: %s", e)
            return None

    # ── User Profile ────────────────────────────────────────────────────

    async def get_user_profile(self, user_id: str) -> dict | None:
        """Get Instagram user profile by PK."""
        try:
            user = await asyncio.to_thread(self._cl.user_info, int(user_id))
            return {
                "username": user.username,
                "name": user.full_name,
                "profile_picture_url": str(user.profile_pic_url) if user.profile_pic_url else None,
            }
        except Exception as e:
            logger.error("instagrapi get_profile error: %s", e)
            return None

    # ── Polling helpers (not in official client) ────────────────────────

    def _check_login_required(self, e: Exception) -> None:
        """Raise LoginRequiredError if the error indicates session expiry."""
        msg = str(e).lower()
        if "login_required" in msg or "please wait" in msg or "challenge" in msg:
            raise LoginRequiredError(str(e)) from e

    async def get_direct_threads(self, amount: int = 20) -> list:
        """Get recent DM threads for polling."""
        try:
            threads = await asyncio.to_thread(
                partial(self._cl.direct_threads, amount=amount)
            )
            return threads or []
        except Exception as e:
            self._check_login_required(e)
            logger.error("instagrapi get_threads error: %s", e)
            return []

    async def get_recent_media_ids(self, amount: int = 5) -> list[str]:
        """Get recent media PKs for comment polling."""
        try:
            medias = await asyncio.to_thread(
                partial(self._cl.user_medias, int(self.ig_user_id), amount=amount)
            )
            return [str(m.pk) for m in (medias or [])]
        except Exception as e:
            self._check_login_required(e)
            logger.error("instagrapi get_media error: %s", e)
            return []

    async def get_media_comments(self, media_id: str, amount: int = 20) -> list:
        """Get comments on a media post."""
        try:
            comments = await asyncio.to_thread(
                partial(self._cl.media_comments, media_id, amount=amount)
            )
            return comments or []
        except Exception as e:
            self._check_login_required(e)
            logger.error("instagrapi get_comments error: %s", e)
            return []
