"""Cached platform settings loader.

Reads from platform_settings.json with a 30-second in-memory TTL.
All enforcement code should import `get_platform_settings()` from here
instead of reading the JSON file directly.
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_cache: dict = {"data": None, "ts": 0.0}
_TTL = 30  # seconds

_SETTINGS_FILE = Path(__file__).parent / "platform_settings.json"

_DEFAULTS = {
    "default_ai_model": "gpt-4o-mini",
    "fallback_model": "gpt-4o",
    "default_language": "ru",
    "default_timezone": "Asia/Tashkent",
    "max_products_per_tenant": 500,
    "max_users_per_tenant": 10,
    "max_messages_per_day": 5000,
    "trial_days": 14,
    "signup_enabled": True,
    "maintenance_mode": False,
    "read_only_mode": False,
}


def get_platform_settings() -> dict:
    """Return platform settings from cache or file.

    Reads JSON file at most once every 30 seconds.
    Falls back to defaults if file is missing or corrupted.
    """
    now = time.time()
    if _cache["data"] is not None and now - _cache["ts"] < _TTL:
        return _cache["data"]

    try:
        raw = _SETTINGS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        # Merge with defaults so new keys are always present
        merged = {**_DEFAULTS, **data}
        _cache["data"] = merged
    except FileNotFoundError:
        _cache["data"] = _DEFAULTS.copy()
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read platform settings, using defaults")
        _cache["data"] = _DEFAULTS.copy()

    _cache["ts"] = now
    return _cache["data"]


def invalidate_platform_settings_cache() -> None:
    """Force re-read on next access. Call after settings are updated."""
    _cache["data"] = None
    _cache["ts"] = 0.0
