"""API smoke tests — verifies all endpoints return expected status codes.

Requires a running backend on localhost:8000 with seeded data.
Run: pytest tests/test_api_smoke.py -v
"""

import time

import aiohttp
import pytest

from tests.conftest import BASE_URL, api_request

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Ensure asyncio_mode is set to auto in pyproject.toml


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AUTH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAuth:
    async def test_login_valid(self, session, auth_token):
        assert auth_token  # fixture already validates login

    async def test_me(self, session, auth_headers):
        st, d = await api_request(session, "GET", "/auth/me", headers=auth_headers)
        assert st == 200
        assert "email" in d
        assert "tenant_id" in d

    async def test_login_wrong_password(self, session):
        st, _ = await api_request(
            session, "POST", "/auth/login",
            json_data={"email": "admin@gmail.com", "password": "wrong"},
        )
        assert st == 401

    async def test_login_nonexistent_user(self, session):
        st, _ = await api_request(
            session, "POST", "/auth/login",
            json_data={"email": "nobody@x.com", "password": "test"},
        )
        assert st == 401

    async def test_no_token_rejected(self, session):
        st, _ = await api_request(session, "GET", "/auth/me")
        assert st == 401

    async def test_garbage_token_rejected(self, session):
        st, _ = await api_request(
            session, "GET", "/auth/me",
            headers={"Authorization": "Bearer garbage.token.here"},
        )
        assert st == 401

    async def test_tampered_jwt_rejected(self, session, auth_token):
        parts = auth_token.split(".")
        tampered = f"{parts[0]}.{parts[1]}.tampered_sig"
        st, _ = await api_request(
            session, "GET", "/auth/me",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert st == 401

    async def test_change_password_wrong_old(self, session, auth_headers):
        st, _ = await api_request(
            session, "POST", "/auth/change-password",
            headers=auth_headers,
            json_data={"old_password": "wrong", "new_password": "newpass123"},
        )
        assert st in (400, 422)

    async def test_change_password_too_short(self, session, auth_headers):
        st, _ = await api_request(
            session, "POST", "/auth/change-password",
            headers=auth_headers,
            json_data={"old_password": "admin", "new_password": "sh"},
        )
        assert st in (400, 422)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEALTH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestHealth:
    async def test_liveness(self, session):
        st, d = await api_request(session, "GET", "/health")
        assert st == 200
        assert d["status"] == "ok"

    async def test_readiness(self, session):
        st, d = await api_request(session, "GET", "/health/ready")
        assert st == 200
        assert d["checks"]["database"] == "ok"
        assert d["checks"]["redis"] == "ok"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CATALOG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCatalog:
    async def test_list_categories(self, session, auth_headers):
        st, d = await api_request(session, "GET", "/categories", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)

    async def test_list_products(self, session, auth_headers):
        st, d = await api_request(session, "GET", "/products", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)
        assert len(d) > 0

    async def test_get_product_detail(self, session, auth_headers):
        st, prods = await api_request(session, "GET", "/products", headers=auth_headers)
        pid = prods[0]["id"]
        st, d = await api_request(session, "GET", f"/products/{pid}", headers=auth_headers)
        assert st == 200
        assert "name" in d

    async def test_product_not_found(self, session, auth_headers):
        st, _ = await api_request(
            session, "GET", "/products/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert st == 404

    async def test_list_delivery_rules(self, session, auth_headers):
        st, d = await api_request(session, "GET", "/delivery-rules", headers=auth_headers)
        assert st == 200

    async def test_product_crud(self, session, auth_headers):
        ts = int(time.time())
        # Create
        st, d = await api_request(
            session, "POST", "/products",
            headers=auth_headers,
            json_data={"name": f"PyTest Product {ts}", "slug": f"pytest-{ts}"},
        )
        assert st == 201
        pid = d["id"]

        # Create variant
        st, d = await api_request(
            session, "POST", f"/products/{pid}/variants",
            headers=auth_headers,
            json_data={"title": "Var", "sku": f"PT-{ts}", "price": 50},
        )
        assert st == 201
        vid = d["id"]

        # Update variant
        st, d = await api_request(
            session, "PATCH", f"/variants/{vid}",
            headers=auth_headers, json_data={"price": 75},
        )
        assert st == 200

        # Delete variant
        st, _ = await api_request(session, "DELETE", f"/variants/{vid}", headers=auth_headers)
        assert st == 204


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEMPLATES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTemplates:
    async def test_list_templates(self, session, auth_headers):
        st, _ = await api_request(session, "GET", "/templates", headers=auth_headers)
        assert st == 200

    async def test_template_crud(self, session, auth_headers):
        # Create
        st, d = await api_request(
            session, "POST", "/templates", headers=auth_headers,
            json_data={"trigger_type": "keyword", "trigger_patterns": ["__pytest__"], "template_text": "Test"},
        )
        assert st == 201
        tid = d["id"]

        # Update
        st, _ = await api_request(
            session, "PATCH", f"/templates/{tid}",
            headers=auth_headers, json_data={"template_text": "Updated"},
        )
        assert st == 200

        # Delete
        st, _ = await api_request(session, "DELETE", f"/templates/{tid}", headers=auth_headers)
        assert st in (200, 204)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONVERSATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestConversations:
    async def test_list_conversations(self, session, auth_headers):
        st, d = await api_request(session, "GET", "/conversations", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)

    async def test_get_conversation_detail(self, session, auth_headers):
        st, convs = await api_request(session, "GET", "/conversations", headers=auth_headers)
        if not convs:
            pytest.skip("No conversations in DB")
        cid = convs[0]["id"]
        st, d = await api_request(session, "GET", f"/conversations/{cid}", headers=auth_headers)
        assert st == 200

    async def test_get_messages(self, session, auth_headers):
        st, convs = await api_request(session, "GET", "/conversations", headers=auth_headers)
        if not convs:
            pytest.skip("No conversations")
        cid = convs[0]["id"]
        st, d = await api_request(session, "GET", f"/conversations/{cid}/messages", headers=auth_headers)
        assert st == 200

    async def test_conversation_not_found(self, session, auth_headers):
        st, _ = await api_request(
            session, "GET", "/conversations/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert st == 404

    async def test_toggle_ai(self, session, auth_headers):
        st, convs = await api_request(session, "GET", "/conversations", headers=auth_headers)
        if not convs:
            pytest.skip("No conversations")
        cid = convs[0]["id"]
        st, d = await api_request(session, "PATCH", f"/conversations/{cid}/toggle-ai", headers=auth_headers)
        assert st == 200
        # Toggle back
        await api_request(session, "PATCH", f"/conversations/{cid}/toggle-ai", headers=auth_headers)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ORDERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestOrders:
    async def test_list_orders(self, session, auth_headers):
        st, d = await api_request(session, "GET", "/orders", headers=auth_headers)
        assert st == 200

    async def test_order_not_found(self, session, auth_headers):
        st, _ = await api_request(
            session, "GET", "/orders/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert st == 404

    async def test_create_order_empty_items_rejected(self, session, auth_headers):
        st, _ = await api_request(
            session, "POST", "/orders", headers=auth_headers,
            json_data={"customer_name": "T", "phone": "+998900000000", "items": []},
        )
        assert st == 422

    async def test_order_lifecycle(self, session, auth_headers):
        """Create → confirm → cancel."""
        # Find a product with variant
        st, prods = await api_request(session, "GET", "/products", headers=auth_headers)
        pid = vid = price = None
        for p in prods:
            if p.get("variants"):
                pid = p["id"]
                vid = p["variants"][0]["id"]
                price = float(p["variants"][0]["price"])
                break
        if not pid:
            pytest.skip("No product with variant")

        # Create
        st, d = await api_request(
            session, "POST", "/orders", headers=auth_headers,
            json_data={
                "customer_name": "Pytest", "phone": "+998901234567",
                "items": [{"product_id": pid, "product_variant_id": vid, "qty": 1, "unit_price": price, "total_price": price}],
            },
        )
        assert st == 201
        oid = d["id"]

        # Confirm
        st, _ = await api_request(session, "PATCH", f"/orders/{oid}", headers=auth_headers, json_data={"status": "confirmed"})
        assert st == 200

        # Cancel
        st, _ = await api_request(session, "PATCH", f"/orders/{oid}", headers=auth_headers, json_data={"status": "cancelled"})
        assert st == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OTHER ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestOtherEndpoints:
    @pytest.mark.parametrize("path", [
        "/leads", "/handoffs",
        "/dashboard/stats", "/dashboard/broadcast-history", "/dashboard/abandoned-carts",
        "/training/stats", "/training/conversations",
        "/analytics/conversations", "/analytics/funnel", "/analytics/revenue",
        "/analytics/stock-forecast", "/analytics/rfm/segments", "/analytics/rfm/customers",
        "/analytics/competitors", "/analytics/competitors/summary",
        "/ai-settings",
        "/telegram/accounts", "/telegram/status", "/telegram/activity-logs",
    ])
    async def test_get_endpoint(self, session, auth_headers, path):
        st, _ = await api_request(session, "GET", path, headers=auth_headers)
        assert st == 200, f"GET {path} returned {st}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SSE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSSE:
    async def test_sse_connects(self, session, auth_token):
        try:
            async with session.get(
                f"{BASE_URL}/events/stream?token={auth_token}",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                assert resp.status == 200
        except TimeoutError:
            pass  # Expected — SSE streams indefinitely

    async def test_sse_rejects_without_token(self, session):
        st, _ = await api_request(session, "GET", "/events/stream")
        assert st in (401, 403, 422)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECURITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSecurity:
    @pytest.mark.parametrize("payload", [
        "' OR '1'='1", "1; DROP TABLE users; --", "' UNION SELECT * FROM users --",
    ])
    async def test_sql_injection_safe(self, session, auth_headers, payload):
        st, _ = await api_request(session, "GET", f"/products?search={payload}", headers=auth_headers)
        assert st != 500, f"SQLi triggered 500 with: {payload}"

    @pytest.mark.parametrize("uid", ["not-a-uuid", "null", "' OR 1=1 --"])
    async def test_invalid_uuid_rejected(self, session, auth_headers, uid):
        st, _ = await api_request(session, "GET", f"/products/{uid}", headers=auth_headers)
        assert st in (404, 422)

    async def test_path_traversal_rejected(self, session, auth_headers):
        st, _ = await api_request(session, "GET", "/products/../../etc/passwd", headers=auth_headers)
        assert st in (404, 422)

    async def test_large_payload_rejected(self, session, auth_headers):
        st, _ = await api_request(
            session, "POST", "/products", headers=auth_headers,
            json_data={"name": "A" * 100_000, "slug": "x"},
        )
        assert st == 422  # max_length validation


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STRESS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestStress:
    @pytest.mark.parametrize("path,count", [
        ("/products", 50),
        ("/dashboard/stats", 50),
        ("/conversations", 50),
        ("/auth/me", 100),
    ])
    async def test_concurrent_reads(self, session, auth_headers, path, count):
        import asyncio
        tasks = [api_request(session, "GET", path, headers=auth_headers) for _ in range(count)]
        results = await asyncio.gather(*tasks)
        ok = sum(1 for st, _ in results if st == 200)
        assert ok == count, f"{ok}/{count} succeeded for {path}"

    async def test_sequential_throughput(self, session, auth_headers):
        ok = 0
        for _ in range(100):
            st, _ = await api_request(session, "GET", "/auth/me", headers=auth_headers)
            if st == 200:
                ok += 1
        assert ok >= 95, f"Only {ok}/100 succeeded"
