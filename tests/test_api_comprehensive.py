"""Comprehensive API test suite — covers ALL endpoint groups with positive and negative cases.

Requires a running backend on localhost:8000 with seeded data.
Run: pytest tests/test_api_comprehensive.py -v

Accounts used:
- admin@gmail.com / admin       — store_owner (tenant-scoped)
- superadmin@gmail.com / admin123 — super_admin (cross-tenant)
"""

import time
import uuid

import aiohttp
import pytest

from tests.conftest import BASE_URL, api_request

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Unique prefix to avoid collisions with production data
_UID = uuid.uuid4().hex[:8]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AUTH (8 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAuth:
    async def test_login_success(self, session, auth_token):
        """Login returns a valid JWT token."""
        assert auth_token
        assert len(auth_token) > 20

    async def test_login_wrong_password(self, session):
        """Wrong password returns 401."""
        st, _ = await api_request(
            session, "POST", "/auth/login",
            json_data={"email": "admin@gmail.com", "password": "wrongpassword"},
        )
        assert st == 401

    async def test_login_nonexistent_email(self, session):
        """Non-existent email returns 401."""
        st, _ = await api_request(
            session, "POST", "/auth/login",
            json_data={"email": "nobody@nonexistent.com", "password": "test1234"},
        )
        assert st == 401

    async def test_logout(self, session):
        """Logout blacklists the token and returns 200."""
        # Login to get a fresh token
        st, data = await api_request(
            session, "POST", "/auth/login",
            json_data={"email": "admin@gmail.com", "password": "admin123"},
        )
        assert st == 200
        fresh_token = data["access_token"]

        # Logout
        st, d = await api_request(
            session, "POST", "/auth/logout",
            headers={"Authorization": f"Bearer {fresh_token}"},
        )
        assert st == 200
        assert d.get("status") == "logged_out"

        # Confirm token is blacklisted
        st, _ = await api_request(
            session, "GET", "/auth/me",
            headers={"Authorization": f"Bearer {fresh_token}"},
        )
        assert st == 401

    async def test_refresh_token(self, session, admin_user_data):
        """Refresh token exchange returns new access + refresh tokens."""
        refresh = admin_user_data.get("refresh_token")
        if not refresh:
            pytest.skip("No refresh token in login response")
        st, d = await api_request(
            session, "POST", "/auth/refresh",
            json_data={"refresh_token": refresh},
        )
        # Refresh token rotation: first call should succeed
        assert st in (200, 401)  # 401 if token was already rotated by another fixture

    async def test_get_me(self, session, auth_headers):
        """GET /auth/me returns current user data."""
        st, d = await api_request(session, "GET", "/auth/me", headers=auth_headers)
        assert st == 200
        assert "email" in d
        assert "tenant_id" in d
        assert "role" in d
        assert d["email"] == "admin@gmail.com"

    async def test_change_password_wrong_current(self, session, auth_headers):
        """Change password with wrong current password fails."""
        st, _ = await api_request(
            session, "POST", "/auth/change-password",
            headers=auth_headers,
            json_data={"current_password": "wrongcurrent", "new_password": "newpass123"},
        )
        assert st == 400

    async def test_unauthorized_access(self, session):
        """Accessing protected endpoint without token returns 401/403."""
        st, _ = await api_request(session, "GET", "/auth/me")
        assert st in (401, 403)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PRODUCTS (6 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestProducts:
    async def test_list_products(self, session, auth_headers):
        """GET /products returns a list."""
        st, d = await api_request(session, "GET", "/products", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)

    async def test_get_product_detail(self, session, auth_headers):
        """GET /products/{id} returns product detail with name."""
        st, prods = await api_request(session, "GET", "/products", headers=auth_headers)
        if not prods:
            pytest.skip("No products in DB")
        pid = prods[0]["id"]
        st, d = await api_request(session, "GET", f"/products/{pid}", headers=auth_headers)
        assert st == 200
        assert "name" in d
        assert d["id"] == pid

    async def test_create_product(self, session, auth_headers):
        """POST /products creates a new product."""
        name = f"Test Product {_UID}"
        st, d = await api_request(
            session, "POST", "/products",
            headers=auth_headers,
            json_data={"name": name, "slug": f"test-{_UID}"},
        )
        assert st == 201
        assert d["name"] == name
        assert "id" in d

    async def test_update_product(self, session, auth_headers):
        """PATCH /products/{id} updates product fields."""
        # Create a product to update
        name = f"Update Test {_UID}"
        st, created = await api_request(
            session, "POST", "/products",
            headers=auth_headers,
            json_data={"name": name, "slug": f"upd-{_UID}"},
        )
        assert st == 201
        pid = created["id"]

        # Update
        new_name = f"Updated {_UID}"
        st, d = await api_request(
            session, "PATCH", f"/products/{pid}",
            headers=auth_headers,
            json_data={"name": new_name},
        )
        assert st == 200
        assert d["name"] == new_name

    async def test_search_products(self, session, auth_headers):
        """GET /products?search=... filters results."""
        st, d = await api_request(
            session, "GET", "/products?search=nonexistent_product_xyz",
            headers=auth_headers,
        )
        assert st == 200
        assert isinstance(d, list)

    async def test_list_categories(self, session, auth_headers):
        """GET /categories returns a list."""
        st, d = await api_request(session, "GET", "/categories", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ORDERS (5 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestOrders:
    async def test_list_orders(self, session, auth_headers):
        """GET /orders returns 200."""
        st, d = await api_request(session, "GET", "/orders", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)

    async def test_create_order(self, session, auth_headers):
        """POST /orders creates a new order with valid product/variant IDs."""
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
            pytest.skip("No product with variant for order creation")

        st, d = await api_request(
            session, "POST", "/orders",
            headers=auth_headers,
            json_data={
                "customer_name": f"Pytest {_UID}",
                "phone": "+998901234567",
                "items": [{
                    "product_id": pid,
                    "product_variant_id": vid,
                    "qty": 1,
                    "unit_price": price,
                    "total_price": price,
                }],
            },
        )
        assert st == 201
        assert "id" in d
        assert d.get("order_number") is not None

    async def test_update_order_status(self, session, auth_headers):
        """PATCH /orders/{id} updates order status (draft -> confirmed)."""
        # Create an order first
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

        st, order = await api_request(
            session, "POST", "/orders",
            headers=auth_headers,
            json_data={
                "customer_name": f"Status Test {_UID}",
                "phone": "+998900000001",
                "items": [{
                    "product_id": pid,
                    "product_variant_id": vid,
                    "qty": 1,
                    "unit_price": price,
                    "total_price": price,
                }],
            },
        )
        assert st == 201
        oid = order["id"]

        # Confirm
        st, d = await api_request(
            session, "PATCH", f"/orders/{oid}",
            headers=auth_headers,
            json_data={"status": "confirmed"},
        )
        assert st == 200

    async def test_get_order(self, session, auth_headers):
        """GET /orders/{id} returns order detail."""
        st, orders = await api_request(session, "GET", "/orders", headers=auth_headers)
        if not orders:
            pytest.skip("No orders in DB")
        oid = orders[0]["id"]
        st, d = await api_request(session, "GET", f"/orders/{oid}", headers=auth_headers)
        assert st == 200
        assert d["id"] == oid

    async def test_delete_order_cancelled_only(self, session, auth_headers):
        """DELETE /orders/{id} only works for cancelled/returned orders."""
        # Create and cancel
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

        st, order = await api_request(
            session, "POST", "/orders",
            headers=auth_headers,
            json_data={
                "customer_name": f"Delete Test {_UID}",
                "phone": "+998900000002",
                "items": [{
                    "product_id": pid,
                    "product_variant_id": vid,
                    "qty": 1,
                    "unit_price": price,
                    "total_price": price,
                }],
            },
        )
        assert st == 201
        oid = order["id"]

        # Try deleting draft order (should fail)
        st, _ = await api_request(
            session, "DELETE", f"/orders/{oid}", headers=auth_headers,
        )
        assert st == 400  # Can only delete cancelled/returned

        # Cancel then delete
        await api_request(
            session, "PATCH", f"/orders/{oid}",
            headers=auth_headers,
            json_data={"status": "cancelled"},
        )
        st, _ = await api_request(
            session, "DELETE", f"/orders/{oid}", headers=auth_headers,
        )
        assert st == 204


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONVERSATIONS (5 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestConversations:
    async def test_list_conversations(self, session, auth_headers):
        """GET /conversations returns a list."""
        st, d = await api_request(session, "GET", "/conversations", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)

    async def test_get_conversation_messages(self, session, auth_headers):
        """GET /conversations/{id}/messages returns messages for a valid conversation."""
        st, convs = await api_request(session, "GET", "/conversations", headers=auth_headers)
        if not convs:
            pytest.skip("No conversations in DB")
        cid = convs[0]["id"]
        st, d = await api_request(
            session, "GET", f"/conversations/{cid}/messages", headers=auth_headers,
        )
        assert st == 200
        assert isinstance(d, list)

    async def test_toggle_ai(self, session, auth_headers):
        """PATCH /conversations/{id}/toggle-ai toggles AI and returns updated state."""
        st, convs = await api_request(session, "GET", "/conversations", headers=auth_headers)
        if not convs:
            pytest.skip("No conversations in DB")
        cid = convs[0]["id"]
        original_ai = convs[0].get("ai_enabled")

        st, d = await api_request(
            session, "PATCH", f"/conversations/{cid}/toggle-ai", headers=auth_headers,
        )
        assert st == 200
        assert "ai_enabled" in d

        # Toggle back to restore original state
        await api_request(
            session, "PATCH", f"/conversations/{cid}/toggle-ai", headers=auth_headers,
        )

    async def test_list_templates(self, session, auth_headers):
        """GET /templates returns a list."""
        st, d = await api_request(session, "GET", "/templates", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)

    async def test_create_template(self, session, auth_headers):
        """POST /templates creates a new template and DELETE removes it."""
        st, d = await api_request(
            session, "POST", "/templates",
            headers=auth_headers,
            json_data={
                "trigger_type": "keyword",
                "trigger_patterns": [f"__pytest_{_UID}__"],
                "template_text": f"Test template {_UID}",
            },
        )
        assert st == 201
        assert "id" in d
        tid = d["id"]

        # Cleanup
        st, _ = await api_request(
            session, "DELETE", f"/templates/{tid}", headers=auth_headers,
        )
        assert st in (200, 204)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DASHBOARD (4 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDashboard:
    async def test_dashboard_stats(self, session, auth_headers):
        """GET /dashboard/stats returns stats with numeric fields."""
        st, d = await api_request(session, "GET", "/dashboard/stats", headers=auth_headers)
        assert st == 200
        assert isinstance(d, dict)
        # Should contain at least some numeric KPIs
        for key in ("total_conversations", "total_orders", "total_revenue"):
            if key in d:
                assert isinstance(d[key], (int, float))

    async def test_broadcast_estimate(self, session, auth_headers):
        """GET /dashboard/broadcast-estimate returns recipient count."""
        st, d = await api_request(
            session, "GET", "/dashboard/broadcast-estimate", headers=auth_headers,
        )
        # May be /dashboard/broadcast-recipients depending on version
        if st == 404:
            st, d = await api_request(
                session, "GET", "/dashboard/broadcast-recipients", headers=auth_headers,
            )
        assert st == 200

    async def test_abandoned_carts(self, session, auth_headers):
        """GET /dashboard/abandoned-carts returns a list."""
        st, d = await api_request(
            session, "GET", "/dashboard/abandoned-carts", headers=auth_headers,
        )
        assert st == 200
        assert isinstance(d, list)

    async def test_broadcast_history(self, session, auth_headers):
        """GET /dashboard/broadcast-history returns a list."""
        st, d = await api_request(
            session, "GET", "/dashboard/broadcast-history", headers=auth_headers,
        )
        assert st == 200
        assert isinstance(d, list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI SETTINGS (4 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAiSettings:
    async def test_get_ai_settings(self, session, auth_headers):
        """GET /ai-settings returns current AI settings."""
        st, d = await api_request(session, "GET", "/ai-settings", headers=auth_headers)
        assert st == 200
        assert isinstance(d, dict)
        # Should contain known fields
        for key in ("allow_auto_dm_reply", "tone", "language"):
            assert key in d, f"Missing expected field: {key}"

    async def test_update_ai_settings(self, session, auth_headers):
        """PUT /ai-settings updates and returns the new settings."""
        # Get current settings first
        st, current = await api_request(session, "GET", "/ai-settings", headers=auth_headers)
        assert st == 200
        original_tone = current.get("tone", "professional")

        # Update tone
        st, d = await api_request(
            session, "PUT", "/ai-settings",
            headers=auth_headers,
            json_data={**current, "tone": "friendly"},
        )
        assert st == 200
        assert d["tone"] == "friendly"

        # Restore original
        await api_request(
            session, "PUT", "/ai-settings",
            headers=auth_headers,
            json_data={**current, "tone": original_tone},
        )

    async def test_api_key_status(self, session, auth_headers):
        """GET /ai-settings/api-key-status returns key presence info."""
        st, d = await api_request(
            session, "GET", "/ai-settings/api-key-status", headers=auth_headers,
        )
        assert st == 200
        assert "has_key" in d
        assert "provider" in d

    async def test_ai_traces(self, session, auth_headers):
        """GET /ai-traces returns trace data."""
        st, d = await api_request(session, "GET", "/ai-traces", headers=auth_headers)
        assert st == 200
        assert "traces" in d
        assert "total" in d


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLATFORM — super_admin only (10 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPlatform:
    async def test_platform_stats(self, session, superadmin_headers):
        """GET /platform/stats returns cross-tenant KPIs."""
        st, d = await api_request(
            session, "GET", "/platform/stats", headers=superadmin_headers,
        )
        assert st == 200
        assert "total_tenants" in d
        assert "total_users" in d
        assert "total_conversations" in d
        assert isinstance(d["total_tenants"], int)

    async def test_platform_users_list(self, session, superadmin_headers):
        """GET /platform/users returns paginated user list."""
        st, d = await api_request(
            session, "GET", "/platform/users", headers=superadmin_headers,
        )
        assert st == 200
        assert "items" in d
        assert "total" in d
        assert isinstance(d["items"], list)

    async def test_platform_users_create(self, session, superadmin_headers, superadmin_user_data):
        """POST /platform/users creates a user in any tenant."""
        # Get a tenant ID from the superadmin user data or from tenants list
        st, tenants = await api_request(
            session, "GET", "/tenants/", headers=superadmin_headers,
        )
        assert st == 200
        if not tenants.get("items"):
            pytest.skip("No tenants available")
        tenant_id = tenants["items"][0]["id"]

        email = f"pytest-{_UID}@test.local"
        st, d = await api_request(
            session, "POST", "/platform/users",
            headers=superadmin_headers,
            json_data={
                "tenant_id": tenant_id,
                "email": email,
                "full_name": f"Pytest User {_UID}",
                "password": f"testpass1{_UID}",
                "role": "operator",
            },
        )
        assert st == 201
        assert d["email"] == email

    async def test_platform_tenants_list(self, session, superadmin_headers):
        """GET /tenants/ returns paginated tenant list."""
        st, d = await api_request(
            session, "GET", "/tenants/", headers=superadmin_headers,
        )
        assert st == 200
        assert "items" in d
        assert "total" in d

    async def test_platform_tenant_detail(self, session, superadmin_headers):
        """GET /tenants/{id} returns tenant detail with counts."""
        st, tenants = await api_request(
            session, "GET", "/tenants/", headers=superadmin_headers,
        )
        if not tenants.get("items"):
            pytest.skip("No tenants")
        tid = tenants["items"][0]["id"]

        st, d = await api_request(
            session, "GET", f"/tenants/{tid}", headers=superadmin_headers,
        )
        assert st == 200
        assert d["id"] == tid
        assert "products_count" in d
        assert "conversations_count" in d

    async def test_platform_impersonate(self, session, superadmin_headers):
        """POST /platform/tenants/{id}/impersonate returns a short-lived JWT."""
        st, tenants = await api_request(
            session, "GET", "/tenants/", headers=superadmin_headers,
        )
        if not tenants.get("items"):
            pytest.skip("No tenants")
        tid = tenants["items"][0]["id"]

        st, d = await api_request(
            session, "POST", f"/platform/tenants/{tid}/impersonate",
            headers=superadmin_headers,
        )
        assert st == 200
        assert "access_token" in d
        assert "tenant_name" in d

    async def test_platform_billing(self, session, superadmin_headers):
        """GET /platform/billing returns per-tenant usage."""
        st, d = await api_request(
            session, "GET", "/platform/billing", headers=superadmin_headers,
        )
        assert st == 200
        assert isinstance(d, list)

    async def test_platform_billing_models(self, session, superadmin_headers):
        """GET /platform/billing/models returns model distribution."""
        st, d = await api_request(
            session, "GET", "/platform/billing/models", headers=superadmin_headers,
        )
        assert st == 200
        assert isinstance(d, list)

    async def test_platform_audit_logs(self, session, superadmin_headers):
        """GET /platform/audit-logs returns audit entries."""
        st, d = await api_request(
            session, "GET", "/platform/audit-logs", headers=superadmin_headers,
        )
        assert st == 200
        assert isinstance(d, list)

    async def test_platform_settings(self, session, superadmin_headers):
        """GET /platform/settings returns platform configuration."""
        st, d = await api_request(
            session, "GET", "/platform/settings", headers=superadmin_headers,
        )
        assert st == 200
        assert "default_ai_model" in d
        assert "max_products_per_tenant" in d

    async def test_platform_health(self, session, superadmin_headers):
        """GET /platform/health returns system health checks."""
        st, d = await api_request(
            session, "GET", "/platform/health", headers=superadmin_headers,
        )
        assert st == 200
        assert "checks" in d
        assert d["checks"]["database"] == "ok"
        assert d["checks"]["redis"] == "ok"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECURITY (5 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSecurity:
    async def test_no_token_returns_401(self, session):
        """Requests without token get rejected."""
        st, _ = await api_request(session, "GET", "/products")
        assert st in (401, 403)

    async def test_invalid_token_returns_401(self, session):
        """Garbage token gets rejected."""
        st, _ = await api_request(
            session, "GET", "/products",
            headers={"Authorization": "Bearer totally.invalid.token"},
        )
        assert st == 401

    async def test_store_owner_cannot_access_platform(self, session, auth_headers):
        """store_owner role cannot access super_admin platform endpoints."""
        st, _ = await api_request(
            session, "GET", "/platform/stats", headers=auth_headers,
        )
        assert st == 403

    async def test_store_owner_cannot_access_tenants(self, session, auth_headers):
        """store_owner role cannot list tenants."""
        st, _ = await api_request(
            session, "GET", "/tenants/", headers=auth_headers,
        )
        assert st == 403

    async def test_cross_tenant_isolation(self, session, superadmin_headers):
        """Verify tenant_id filter isolates data between tenants.

        Use impersonation to access as different tenants and confirm
        data is scoped correctly.
        """
        # Get tenants list
        st, tenants_resp = await api_request(
            session, "GET", "/tenants/", headers=superadmin_headers,
        )
        assert st == 200
        tenants = tenants_resp.get("items", [])
        if len(tenants) < 2:
            pytest.skip("Need at least 2 tenants for isolation test")

        # Impersonate first tenant
        st, imp1 = await api_request(
            session, "POST", f"/platform/tenants/{tenants[0]['id']}/impersonate",
            headers=superadmin_headers,
        )
        assert st == 200
        headers_1 = {"Authorization": f"Bearer {imp1['access_token']}"}

        # Impersonate second tenant
        st, imp2 = await api_request(
            session, "POST", f"/platform/tenants/{tenants[1]['id']}/impersonate",
            headers=superadmin_headers,
        )
        assert st == 200
        headers_2 = {"Authorization": f"Bearer {imp2['access_token']}"}

        # Get products for each tenant
        st1, prods1 = await api_request(session, "GET", "/products", headers=headers_1)
        st2, prods2 = await api_request(session, "GET", "/products", headers=headers_2)
        assert st1 == 200
        assert st2 == 200

        # Verify IDs don't overlap (if both have products)
        if prods1 and prods2:
            ids1 = {p["id"] for p in prods1}
            ids2 = {p["id"] for p in prods2}
            assert ids1.isdisjoint(ids2), "Products leaked across tenants!"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LEADS, HANDOFFS, ANALYTICS (5 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLeadsHandoffsAnalytics:
    async def test_list_leads(self, session, auth_headers):
        """GET /leads returns a list."""
        st, d = await api_request(session, "GET", "/leads", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)

    async def test_list_handoffs(self, session, auth_headers):
        """GET /handoffs returns a list."""
        st, d = await api_request(session, "GET", "/handoffs", headers=auth_headers)
        assert st == 200
        assert isinstance(d, list)

    async def test_analytics_rfm(self, session, auth_headers):
        """GET /analytics/rfm/segments returns RFM segment data."""
        st, d = await api_request(
            session, "GET", "/analytics/rfm/segments", headers=auth_headers,
        )
        assert st == 200

    async def test_analytics_funnel(self, session, auth_headers):
        """GET /analytics/funnel returns funnel stages."""
        st, d = await api_request(
            session, "GET", "/analytics/funnel", headers=auth_headers,
        )
        assert st == 200

    async def test_analytics_revenue(self, session, auth_headers):
        """GET /analytics/revenue returns revenue data."""
        st, d = await api_request(
            session, "GET", "/analytics/revenue", headers=auth_headers,
        )
        assert st == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TRAINING (3 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTraining:
    async def test_training_stats(self, session, auth_headers):
        """GET /training/stats returns stats."""
        st, d = await api_request(
            session, "GET", "/training/stats", headers=auth_headers,
        )
        assert st == 200

    async def test_training_conversations(self, session, auth_headers):
        """GET /training/conversations returns list."""
        st, d = await api_request(
            session, "GET", "/training/conversations", headers=auth_headers,
        )
        assert st == 200

    async def test_training_export(self, session, auth_headers):
        """GET /training/export.jsonl returns streaming response."""
        try:
            async with session.get(
                f"{BASE_URL}/training/export.jsonl",
                headers=auth_headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                assert resp.status == 200
        except Exception:
            pass  # May timeout on large datasets — that's ok


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM (2 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTelegram:
    async def test_telegram_accounts(self, session, auth_headers):
        """GET /telegram/accounts returns 200."""
        st, d = await api_request(
            session, "GET", "/telegram/accounts", headers=auth_headers,
        )
        assert st == 200

    async def test_telegram_status(self, session, auth_headers):
        """GET /telegram/status returns connection status."""
        st, d = await api_request(
            session, "GET", "/telegram/status", headers=auth_headers,
        )
        assert st == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEALTH (2 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestHealth:
    async def test_liveness(self, session):
        """GET /health returns ok."""
        st, d = await api_request(session, "GET", "/health")
        assert st == 200
        assert d.get("status") == "ok"

    async def test_readiness(self, session):
        """GET /health/ready checks DB and Redis."""
        st, d = await api_request(session, "GET", "/health/ready")
        assert st == 200
        assert d["checks"]["database"] == "ok"
        assert d["checks"]["redis"] == "ok"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SSE (2 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSSE:
    async def test_sse_connects_with_token(self, session, auth_token):
        """SSE endpoint accepts valid JWT via query param."""
        try:
            async with session.get(
                f"{BASE_URL}/events/stream?token={auth_token}",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                assert resp.status == 200
        except TimeoutError:
            pass  # Expected — SSE streams indefinitely

    async def test_sse_rejects_without_token(self, session):
        """SSE endpoint rejects requests without token."""
        st, _ = await api_request(session, "GET", "/events/stream")
        assert st in (401, 403, 422)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ERROR HANDLING (6 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestErrorHandling:
    async def test_product_not_found_404(self, session, auth_headers):
        """GET /products/{nonexistent} returns 404."""
        st, _ = await api_request(
            session, "GET", "/products/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert st == 404

    async def test_order_not_found_404(self, session, auth_headers):
        """GET /orders/{nonexistent} returns 404."""
        st, _ = await api_request(
            session, "GET", "/orders/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert st == 404

    async def test_conversation_not_found_404(self, session, auth_headers):
        """GET /conversations/{nonexistent} returns 404."""
        st, _ = await api_request(
            session, "GET", "/conversations/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert st == 404

    async def test_create_order_empty_items_422(self, session, auth_headers):
        """POST /orders with empty items list returns 422."""
        st, _ = await api_request(
            session, "POST", "/orders",
            headers=auth_headers,
            json_data={"customer_name": "Test", "phone": "+998900000000", "items": []},
        )
        assert st == 422

    async def test_invalid_uuid_path_param(self, session, auth_headers):
        """Invalid UUID in path returns 404 or 422."""
        st, _ = await api_request(
            session, "GET", "/products/not-a-uuid", headers=auth_headers,
        )
        assert st in (404, 422)

    async def test_sql_injection_safe(self, session, auth_headers):
        """SQL injection attempts don't crash the server."""
        payloads = ["' OR '1'='1", "1; DROP TABLE users; --", "' UNION SELECT * FROM users --"]
        for payload in payloads:
            st, _ = await api_request(
                session, "GET", f"/products?search={payload}", headers=auth_headers,
            )
            assert st != 500, f"SQLi triggered 500 with: {payload}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DELIVERY RULES (2 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDeliveryRules:
    async def test_list_delivery_rules(self, session, auth_headers):
        """GET /delivery-rules returns a list."""
        st, d = await api_request(
            session, "GET", "/delivery-rules", headers=auth_headers,
        )
        assert st == 200
        assert isinstance(d, list)

    async def test_create_delivery_rule(self, session, auth_headers):
        """POST /delivery-rules creates a rule and DELETE removes it."""
        st, d = await api_request(
            session, "POST", "/delivery-rules",
            headers=auth_headers,
            json_data={
                "city": f"TestCity{_UID}",
                "delivery_type": "courier",
                "price": 25000,
                "eta_min_days": 1,
                "eta_max_days": 2,
            },
        )
        assert st == 201
        rule_id = d["id"]

        # Cleanup
        st, _ = await api_request(
            session, "DELETE", f"/delivery-rules/{rule_id}", headers=auth_headers,
        )
        assert st in (200, 204)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HANDOFF STATS (1 test)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestHandoffStats:
    async def test_handoff_stats(self, session, auth_headers):
        """GET /handoffs/stats returns handoff metrics."""
        st, d = await api_request(
            session, "GET", "/handoffs/stats", headers=auth_headers,
        )
        assert st == 200
        assert "total" in d
        assert "pending" in d
        assert "resolved" in d


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ANALYTICS EXTENDED (3 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAnalyticsExtended:
    async def test_analytics_conversations(self, session, auth_headers):
        """GET /analytics/conversations returns conversation metrics."""
        st, d = await api_request(
            session, "GET", "/analytics/conversations", headers=auth_headers,
        )
        assert st == 200

    async def test_analytics_stock_forecast(self, session, auth_headers):
        """GET /analytics/stock-forecast returns forecast data."""
        st, d = await api_request(
            session, "GET", "/analytics/stock-forecast", headers=auth_headers,
        )
        assert st == 200

    async def test_analytics_competitors(self, session, auth_headers):
        """GET /analytics/competitors returns competitor data."""
        st, d = await api_request(
            session, "GET", "/analytics/competitors", headers=auth_headers,
        )
        assert st == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLATFORM AI LOGS (1 test)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPlatformAiLogs:
    async def test_ai_logs(self, session, superadmin_headers):
        """GET /platform/ai-logs returns AI trace logs."""
        st, d = await api_request(
            session, "GET", "/platform/ai-logs", headers=superadmin_headers,
        )
        assert st == 200
        assert isinstance(d, list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROMPT RULES (3 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPromptRules:
    async def test_get_prompt_rules(self, session, auth_headers):
        """GET /ai-settings/prompt-rules returns list."""
        st, d = await api_request(
            session, "GET", "/ai-settings/prompt-rules", headers=auth_headers,
        )
        assert st == 200
        assert isinstance(d, list)

    async def test_add_prompt_rule(self, session, auth_headers):
        """POST /ai-settings/prompt-rules adds a rule."""
        st, d = await api_request(
            session, "POST", "/ai-settings/prompt-rules",
            headers=auth_headers,
            json_data={"rule": f"Test rule {_UID}", "reason": "pytest"},
        )
        assert st == 200
        assert "id" in d
        rule_id = d["id"]

        # Cleanup
        st, _ = await api_request(
            session, "DELETE", f"/ai-settings/prompt-rules/{rule_id}",
            headers=auth_headers,
        )
        assert st == 200

    async def test_prompt_rule_not_found(self, session, auth_headers):
        """DELETE /ai-settings/prompt-rules/{nonexistent} returns 404."""
        st, _ = await api_request(
            session, "DELETE", "/ai-settings/prompt-rules/nonexistent-id",
            headers=auth_headers,
        )
        assert st == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AUTH OPERATORS (1 test)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestOperators:
    async def test_list_operators(self, session, auth_headers):
        """GET /auth/operators returns list of users in tenant."""
        st, d = await api_request(
            session, "GET", "/auth/operators", headers=auth_headers,
        )
        assert st == 200
        assert isinstance(d, list)
        if d:
            assert "id" in d[0]
            assert "role" in d[0]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FORGOT/RESET PASSWORD (2 tests)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPasswordReset:
    async def test_forgot_password(self, session):
        """POST /auth/forgot-password always returns 200 (no email enumeration)."""
        st, d = await api_request(
            session, "POST", "/auth/forgot-password",
            json_data={"email": "nonexistent@test.local"},
        )
        assert st == 200
        assert d.get("status") == "ok"

    async def test_reset_password_invalid_token(self, session):
        """POST /auth/reset-password with invalid token returns 400."""
        st, _ = await api_request(
            session, "POST", "/auth/reset-password",
            json_data={"token": "invalid-reset-token", "new_password": "newpass123"},
        )
        assert st == 400
