"""Shared fixtures for API tests.

Provides session-scoped aiohttp client and auth tokens for:
- admin (store_owner): admin@gmail.com
- superadmin: superadmin@gmail.com
"""

from collections.abc import AsyncGenerator

import aiohttp
import pytest_asyncio

BASE_URL = "http://127.0.0.1:8001"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def session() -> AsyncGenerator[aiohttp.ClientSession, None]:
    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as s:
        yield s


# ── Store Owner (admin) ─────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def auth_token(session: aiohttp.ClientSession) -> str:
    """Login as store_owner and return a valid JWT token."""
    async with session.post(
        f"{BASE_URL}/auth/login",
        json={"email": "admin@gmail.com", "password": "admin123"},
    ) as resp:
        assert resp.status == 200, f"Login failed: {await resp.text()}"
        data = await resp.json()
        return data["access_token"]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def admin_user_data(session: aiohttp.ClientSession) -> dict:
    """Login as admin and return user + refresh token data."""
    async with session.post(
        f"{BASE_URL}/auth/login",
        json={"email": "admin@gmail.com", "password": "admin123"},
    ) as resp:
        assert resp.status == 200
        return await resp.json()


# ── Super Admin ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def superadmin_user_data(session: aiohttp.ClientSession) -> dict:
    """Login as superadmin and return user + tokens. Single login for all superadmin fixtures."""
    import asyncio
    await asyncio.sleep(2)  # Avoid rate limit from admin login fixtures
    async with session.post(
        f"{BASE_URL}/auth/login",
        json={"email": "superadmin@gmail.com", "password": "admin123"},
    ) as resp:
        assert resp.status == 200, f"Superadmin login failed: {await resp.text()}"
        return await resp.json()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def superadmin_token(superadmin_user_data: dict) -> str:
    """Extract token from superadmin login (no extra API call)."""
    return superadmin_user_data["access_token"]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def superadmin_headers(superadmin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {superadmin_token}"}


# ── Helpers ──────────────────────────────────────────────────────────────────

async def api_request(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    headers: dict | None = None,
    json_data: dict | None = None,
    timeout: int = 15,
) -> tuple[int, dict | str]:
    """Helper: make API request, return (status, data)."""
    async with session.request(
        method,
        f"{BASE_URL}{path}",
        headers=headers,
        json=json_data,
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as resp:
        try:
            data = await resp.json()
        except Exception:
            data = await resp.text()
        return resp.status, data
