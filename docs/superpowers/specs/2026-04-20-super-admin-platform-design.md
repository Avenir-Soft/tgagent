# Super Admin Platform — Design Spec

**Date:** 2026-04-20
**Status:** Approved
**Author:** Claude (brainstorming skill)

## Overview

Separate route group `(platform)` inside the existing Next.js app for super_admin users to manage the entire SaaS platform: tenants, users, AI monitoring, billing metrics, system logs, and global settings.

## Architecture

### Frontend Route Group
```
frontend/app/(platform)/
├── layout.tsx              — platform sidebar + impersonate banner
├── overview/page.tsx       — platform-wide KPIs
├── tenants/page.tsx        — tenant list + create
├── tenants/[id]/page.tsx   — tenant detail + stats + impersonate
├── users/page.tsx          — cross-tenant user management
├── ai-monitor/page.tsx     — AI usage logs across all tenants
├── billing/page.tsx        — usage metrics per tenant
├── logs/page.tsx           — audit trail + system events
└── settings/page.tsx       — global platform defaults
```

### Post-Login Routing
- `super_admin` → `/platform/overview`
- `store_owner` / `operator` → `/dashboard`

### Impersonate Flow
1. Super admin clicks "Enter as admin" on tenant detail
2. Backend `POST /tenants/{id}/impersonate` → returns scoped JWT with `impersonated_by` claim
3. Frontend saves `original_token` in sessionStorage
4. Redirects to `(admin)/dashboard` with impersonated token
5. Yellow banner: "Viewing as {tenant_name} [Exit]"
6. Exit → restore original_token → redirect `/platform/tenants`

### Security
- Impersonate token includes `impersonated_by: super_admin_user_id`
- All actions logged in audit_logs with `actor_type: "impersonated"`
- Impersonate token TTL: 30 minutes (shorter than normal)
- Only super_admin can impersonate

## Backend Endpoints (new)

```
GET  /platform/stats              — cross-tenant KPIs
GET  /platform/users              — all users (filterable by tenant)
POST /platform/users              — create user for any tenant
GET  /platform/ai-logs            — AI trace logs across tenants
GET  /platform/billing            — usage metrics per tenant
GET  /platform/audit-logs         — system-wide audit trail
GET  /platform/settings           — global defaults
PUT  /platform/settings           — update global defaults
POST /tenants/{id}/impersonate    — generate impersonate token
```

## Pages Detail

### 1. Overview
- Cards: total tenants, total users, total messages (24h), total orders (24h), total revenue
- Bar chart: messages per tenant (7 days)
- Recent events feed (last 20 audit log entries)

### 2. Tenants
- Table: name, slug, status, products count, conversations count, created_at
- Actions: create, edit, deactivate, impersonate
- Create form: name, slug, admin email, admin password

### 3. Tenant Detail
- Header: name, status badge, created date
- Stats cards: products, variants, conversations, orders, revenue
- Users list for this tenant
- Telegram accounts connected
- AI settings summary
- Button: "Enter as admin" (impersonate)

### 4. Users
- Table: email, full_name, role, tenant_name, is_active, last_login
- Filter by tenant, role
- Actions: edit role, deactivate, reset password

### 5. AI Monitor
- Table: tenant, conversation, user_message, tools_called, duration_ms, tokens, timestamp
- Filter by tenant, date range
- Totals: API calls today, tokens used, avg response time

### 6. Billing
- Table per tenant: messages_count, ai_calls, orders_count, storage_mb
- Date range filter
- No payment integration yet — just usage tracking

### 7. Logs
- Audit trail: who did what, when (admin actions, impersonations, settings changes)
- System events: errors, warnings
- Filter by tenant, actor, action type

### 8. Settings
- Default AI model (gpt-4o-mini)
- Default language
- Max products per tenant
- Max messages per day per tenant
- Platform maintenance mode toggle

## Design System
- Same palette as (admin): slate/indigo/violet
- Platform sidebar: darker shade (slate-950) to distinguish from tenant sidebar (slate-900)
- All cards use existing `.card` CSS class
- Impersonate banner: yellow/amber gradient, fixed top
