"use client";

import { Fragment, useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/lib/api";

/* ── Types ───────────────────────────────────────────────────────── */

interface AuditLog {
  id: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  tenant_name: string | null;
  tenant_id: string;
  meta_json: Record<string, any> | null;
  created_at: string;
}

interface TenantOption {
  id: string;
  name: string;
}

type PeriodValue = "1h" | "24h" | "7d" | "30d" | "custom";

/* ── Constants ───────────────────────────────────────────────────── */

const PERIODS: { value: PeriodValue; label: string }[] = [
  { value: "1h", label: "1\u0447" },
  { value: "24h", label: "24\u0447" },
  { value: "7d", label: "7\u0434" },
  { value: "30d", label: "30\u0434" },
  { value: "custom", label: "custom" },
];

const PERIOD_DISPLAY: Record<string, string> = {
  "1h": "1\u0447",
  "24h": "24\u0447",
  "7d": "7\u0434",
  "30d": "30\u0434",
};

const actionLabels: Record<string, string> = {
  // Auth
  login: "\u0412\u0445\u043e\u0434",
  logout: "\u0412\u044b\u0445\u043e\u0434",
  password_change: "\u0421\u043c\u0435\u043d\u0430 \u043f\u0430\u0440\u043e\u043b\u044f",
  // Orders
  "order.create": "\u0417\u0430\u043a\u0430\u0437 \u0441\u043e\u0437\u0434\u0430\u043d",
  "order.update": "\u0417\u0430\u043a\u0430\u0437 \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d",
  "order.delete": "\u0417\u0430\u043a\u0430\u0437 \u0443\u0434\u0430\u043b\u0451\u043d",
  // Products
  "product.create": "\u0422\u043e\u0432\u0430\u0440 \u0441\u043e\u0437\u0434\u0430\u043d",
  "product.update": "\u0422\u043e\u0432\u0430\u0440 \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d",
  "variant.create": "\u0412\u0430\u0440\u0438\u0430\u043d\u0442 \u0441\u043e\u0437\u0434\u0430\u043d",
  "variant.update": "\u0412\u0430\u0440\u0438\u0430\u043d\u0442 \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d",
  "variant.delete": "\u0412\u0430\u0440\u0438\u0430\u043d\u0442 \u0443\u0434\u0430\u043b\u0451\u043d",
  "delivery_rule.create": "\u041f\u0440\u0430\u0432\u0438\u043b\u043e \u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0438 +",
  "delivery_rule.update": "\u041f\u0440\u0430\u0432\u0438\u043b\u043e \u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0438 \u0438\u0437\u043c.",
  "delivery_rule.delete": "\u041f\u0440\u0430\u0432\u0438\u043b\u043e \u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0438 \u0443\u0434.",
  // Conversations
  "conversation.toggle_ai": "AI \u0432\u043a\u043b/\u0432\u044b\u043a\u043b",
  "conversation.reset": "\u0421\u0431\u0440\u043e\u0441 \u0434\u0438\u0430\u043b\u043e\u0433\u0430",
  "conversation.delete": "\u0414\u0438\u0430\u043b\u043e\u0433 \u0443\u0434\u0430\u043b\u0451\u043d",
  "message.send": "\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e",
  "message.edit": "\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u043e",
  // Telegram
  "telegram.connect": "Telegram \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0451\u043d",
  "telegram.disconnect": "Telegram \u043e\u0442\u043a\u043b\u044e\u0447\u0451\u043d",
  "telegram.reconnect": "Telegram \u043f\u0435\u0440\u0435\u043f\u043e\u0434\u043a\u043b.",
  // Settings
  "settings.update": "\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 AI",
  "api_key.set": "API \u043a\u043b\u044e\u0447 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d",
  "api_key.delete": "API \u043a\u043b\u044e\u0447 \u0443\u0434\u0430\u043b\u0451\u043d",
  // Tenants
  "tenant.create": "\u0422\u0435\u043d\u0430\u043d\u0442 \u0441\u043e\u0437\u0434\u0430\u043d",
  "tenant.update": "\u0422\u0435\u043d\u0430\u043d\u0442 \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d",
  "tenant.user_create": "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d",
  // Broadcast
  "broadcast.create": "\u0420\u0430\u0441\u0441\u044b\u043b\u043a\u0430 \u0441\u043e\u0437\u0434\u0430\u043d\u0430",
  "broadcast.cancel": "\u0420\u0430\u0441\u0441\u044b\u043b\u043a\u0430 \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u0430",
  // Platform
  "platform.settings_update": "\u041f\u043b\u0430\u0442\u0444\u043e\u0440\u043c\u0430 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438",
  "platform.user_create": "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u0441\u043e\u0437\u0434\u0430\u043d",
  "platform.user_update": "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u0438\u0437\u043c\u0435\u043d\u0451\u043d",
  "platform.user_bulk_status": "\u0411\u0443\u043b\u043a \u0441\u0442\u0430\u0442\u0443\u0441 \u043f\u043e\u043b\u044c\u0437.",
  // Legacy
  impersonate: "impersonate",
  create: "\u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435",
  update: "\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435",
  delete: "\u0423\u0434\u0430\u043b\u0435\u043d\u0438\u0435",
  broadcast: "\u0420\u0430\u0441\u0441\u044b\u043b\u043a\u0430",
  handoff: "\u041f\u0435\u0440\u0435\u0434\u0430\u0447\u0430",
  export: "\u042d\u043a\u0441\u043f\u043e\u0440\u0442",
  platform_settings_update: "platform_settings",
  comment_smart_reply: "comment_smart_reply",
};

const actionTone: Record<string, string> = {
  // Auth
  login: "info",
  logout: "dim",
  password_change: "warn",
  // Orders
  "order.create": "good",
  "order.update": "warn",
  "order.delete": "bad",
  // Products
  "product.create": "good",
  "product.update": "warn",
  "variant.create": "good",
  "variant.update": "warn",
  "variant.delete": "bad",
  "delivery_rule.create": "good",
  "delivery_rule.update": "warn",
  "delivery_rule.delete": "bad",
  // Conversations
  "conversation.toggle_ai": "info",
  "conversation.reset": "warn",
  "conversation.delete": "bad",
  "message.send": "info",
  "message.edit": "warn",
  // Telegram
  "telegram.connect": "good",
  "telegram.disconnect": "bad",
  "telegram.reconnect": "info",
  // Settings
  "settings.update": "warn",
  "api_key.set": "accent",
  "api_key.delete": "bad",
  // Tenants
  "tenant.create": "good",
  "tenant.update": "warn",
  "tenant.user_create": "good",
  // Broadcast
  "broadcast.create": "info",
  "broadcast.cancel": "warn",
  // Platform
  "platform.settings_update": "warn",
  "platform.user_create": "good",
  "platform.user_update": "warn",
  "platform.user_bulk_status": "warn",
  // Legacy
  impersonate: "accent",
  create: "good",
  update: "warn",
  delete: "bad",
  broadcast: "info",
  handoff: "warn",
  export: "info",
  platform_settings_update: "warn",
  comment_smart_reply: "info",
};

/* ── Helpers ─────────────────────────────────────────────────────── */

function getActionTone(action: string): string {
  if (actionTone[action]) return actionTone[action];
  if (action.startsWith("comment")) return "info";
  if (action.startsWith("tenant")) return "warn";
  if (action.startsWith("product") || action.startsWith("variant")) return "good";
  if (action.startsWith("order")) return "warn";
  if (action.startsWith("conversation")) return "info";
  if (action.startsWith("telegram")) return "info";
  if (action.startsWith("broadcast")) return "info";
  if (action.startsWith("settings") || action.startsWith("platform")) return "warn";
  if (action.startsWith("delivery_rule")) return "warn";
  if (action.startsWith("api_key")) return "accent";
  if (action.endsWith(".delete")) return "bad";
  if (action.endsWith(".create")) return "good";
  if (action === "impersonate") return "accent";
  return "dim";
}

function getActorInitials(log: AuditLog): string {
  if (log.actor_type === "ai" || log.actor_type === "system") return "AI";
  const email = log.meta_json?.admin_email || log.meta_json?.target_user_email || log.actor_id;
  if (!email) return "??";
  return email.slice(0, 2).toUpperCase();
}

function getActorEmail(log: AuditLog): string {
  return log.meta_json?.admin_email || log.actor_id || log.actor_type;
}

function getActorSub(log: AuditLog): string {
  const type = log.actor_type || "system";
  if (type === "ai" || type === "system") return "ai \u00b7 background";
  const ip = log.meta_json?.ip;
  return ip ? `${type} \u00b7 ip ${ip}` : type;
}

function getTraceId(log: AuditLog): string {
  const raw = log.meta_json?.session_id || log.meta_json?.trace_id || log.id;
  if (!raw) return "\u2014";
  const str = String(raw);
  return str.slice(0, 5) + "\u2026";
}

/* ── Chip ────────────────────────────────────────────────────────── */

function Chip({ tone, children }: { tone: string; children: React.ReactNode }) {
  if (tone === "dim") {
    return (
      <span
        className="inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-full mono text-[10.5px] font-medium leading-[1.4]"
        style={{ background: "var(--bg-2)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
      >
        {children}
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-full mono text-[10.5px] font-medium leading-[1.4]"
      style={{
        background: `var(--${tone}-soft)`,
        color: `var(--${tone})`,
        border: `1px solid color-mix(in oklab, var(--${tone}) 30%, transparent)`,
      }}
    >
      {children}
    </span>
  );
}

/* ── Skeleton ────────────────────────────────────────────────────── */

function LogsSkeleton() {
  return (
    <div className="flex flex-col gap-[14px] animate-pulse">
      <div className="h-8 w-36 skeleton rounded-[9px]" />
      <div className="h-[40px] skeleton rounded-[9px]" />
      <div className="space-y-2">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="h-[38px] skeleton rounded-[9px]" />
        ))}
      </div>
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────── */

const PAGE_SIZE = 50;

export default function AuditLogsPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterTenant, setFilterTenant] = useState("all");
  const [filterAction, setFilterAction] = useState("all");
  const [filterPeriod, setFilterPeriod] = useState<PeriodValue>("24h");
  const [customDateFrom, setCustomDateFrom] = useState("");
  const [customDateTo, setCustomDateTo] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [hasMore, setHasMore] = useState(true);
  const [copyMsg, setCopyMsg] = useState<string | null>(null);

  /* ── Load data ─────────────────────────────────────────────── */
  const load = useCallback(() => {
    setLoading(true);
    const tenantParam = filterTenant !== "all" ? `&tenant_id=${filterTenant}` : "";
    const actionParam = filterAction !== "all" ? `&action=${filterAction}` : "";
    let periodParams = "";
    if (filterPeriod === "custom") {
      if (customDateFrom) periodParams += `&date_from=${customDateFrom}`;
      if (customDateTo) periodParams += `&date_to=${customDateTo}`;
    } else {
      periodParams = `&period=${filterPeriod}`;
    }
    Promise.all([
      api.get<AuditLog[]>(
        `/platform/audit-logs?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}${tenantParam}${actionParam}${periodParams}`
      ),
      api.get<{ items: TenantOption[]; total: number }>("/tenants?limit=100&offset=0"),
    ])
      .then(([l, t]) => {
        setLogs(l);
        setTenants(t.items);
        setHasMore(l.length >= PAGE_SIZE);
        // Estimate total from first load
        if (page === 0 && l.length >= PAGE_SIZE) {
          setTotalCount(PAGE_SIZE * 10); // estimate
        } else if (page === 0) {
          setTotalCount(l.length);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [page, filterTenant, filterAction, filterPeriod, customDateFrom, customDateTo]);

  useEffect(() => {
    load();
  }, [load]);

  /* ── Client-side filtering (search + action) ───────────────── */
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return logs.filter((l) => {
      if (q) {
        const actorEmail = getActorEmail(l).toLowerCase();
        const entityId = (l.entity_id || "").toLowerCase();
        const traceId = (l.meta_json?.trace_id || l.meta_json?.session_id || l.id || "").toLowerCase();
        if (!actorEmail.includes(q) && !entityId.includes(q) && !traceId.includes(q)) {
          return false;
        }
      }
      return true;
    });
  }, [logs, search]);

  const uniqueActions = useMemo(() => [...new Set(logs.map((l) => l.action))], [logs]);

  /* ── Formatters ────────────────────────────────────────────── */
  const fmtTime = (d: string) => {
    const date = new Date(d);
    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }
    return (
      date.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" }) +
      " " +
      date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    );
  };

  /* ── CSV Export ─────────────────────────────────────────────── */
  const handleExport = useCallback(() => {
    if (filtered.length === 0) return;
    const header = ["\u0412\u0440\u0435\u043c\u044f", "\u0410\u043a\u0442\u043e\u0440", "\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435", "\u0421\u0443\u0449\u043d\u043e\u0441\u0442\u044c", "\u0422\u0435\u043d\u0430\u043d\u0442", "Trace", "Meta JSON"];
    const rows = filtered.map((l) => [
      l.created_at,
      getActorEmail(l),
      l.action,
      `${l.entity_type || ""} ${l.entity_id || ""}`.trim(),
      l.tenant_name || "",
      l.meta_json?.trace_id || l.meta_json?.session_id || l.id || "",
      l.meta_json ? JSON.stringify(l.meta_json) : "",
    ]);
    const csv = [header, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filtered]);

  /* ── Copy JSON to clipboard ────────────────────────────────── */
  const handleCopyJson = useCallback((meta: Record<string, any>) => {
    navigator.clipboard.writeText(JSON.stringify(meta, null, 2)).then(() => {
      setCopyMsg("\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u043e!");
      setTimeout(() => setCopyMsg(null), 1500);
    });
  }, []);

  /* ── Pager info ────────────────────────────────────────────── */
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE) + (hasMore ? 1 : 0));
  const periodDisplayLabel = filterPeriod === "custom"
    ? `${customDateFrom || "..."} \u2014 ${customDateTo || "..."}`
    : PERIOD_DISPLAY[filterPeriod] || filterPeriod;

  if (loading && logs.length === 0) return <LogsSkeleton />;

  return (
    <div className="flex flex-col gap-[14px]">
      {/* ═══════════ Header ═══════════ */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1
            className="text-[22px] font-semibold tracking-[-0.01em] flex items-center gap-[8px]"
            style={{ color: "var(--ink)" }}
          >
            {"\u0410\u0443\u0434\u0438\u0442 \u043b\u043e\u0433\u0438"}
            <span
              className="text-[11px] font-medium px-[7px] py-[2px] rounded-full"
              style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
            >
              {filtered.length}
            </span>
          </h1>
          <div className="text-[11.5px] mt-[3px]" style={{ color: "var(--ink-3)" }}>
            {"\u0417\u0430\u043f\u0438\u0441\u0435\u0439"} {totalCount > filtered.length ? totalCount.toLocaleString() : filtered.length}{" "}
            {"\u0432\u0441\u0435\u0433\u043e"} &middot; retention 90 {"\u0434\u043d\u0435\u0439"}
          </div>
        </div>
        <div className="flex items-center gap-[8px]">
          <button
            onClick={handleExport}
            className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-medium transition-colors"
            style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink)" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            {"\u042d\u043a\u0441\u043f\u043e\u0440\u0442"}
          </button>
          <button
            onClick={load}
            className="w-[28px] h-[28px] rounded-[6px] grid place-items-center transition-colors"
            style={{ color: "var(--ink-3)", border: "1px solid var(--line)" }}
            title={"\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c"}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* ═══════════ Error ═══════════ */}
      {error && (
        <div
          className="rounded-[9px] p-4"
          style={{ background: "var(--bad-soft)", border: "1px solid color-mix(in oklab, var(--bad) 30%, transparent)" }}
        >
          <p className="text-[12.5px]" style={{ color: "var(--bad)" }}>{error}</p>
        </div>
      )}

      {/* ═══════════ Toolbar ═══════════ */}
      <div className="flex flex-wrap items-center gap-[8px]">
        {/* Search */}
        <div className="relative" style={{ minWidth: 280 }}>
          <span
            className="absolute left-[10px] top-1/2 -translate-y-1/2 text-[12px]"
            style={{ color: "var(--ink-3)" }}
          >
            {"\u2315"}
          </span>
          <input
            type="text"
            placeholder="actor email \u00b7 entity id \u00b7 trace id\u2026"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-[7px] py-[7px] pl-[30px] pr-[10px] text-[12px] outline-none"
            style={{
              background: "var(--panel)",
              border: "1px solid var(--line)",
              color: "var(--ink)",
            }}
          />
        </div>

        {/* Tenant filter */}
        <select
          value={filterTenant}
          onChange={(e) => { setFilterTenant(e.target.value); setPage(0); }}
          className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none cursor-pointer"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
        >
          <option value="all">{"\u0412\u0441\u0435 \u0442\u0435\u043d\u0430\u043d\u0442\u044b"}</option>
          {tenants.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>

        {/* Action filter */}
        <select
          value={filterAction}
          onChange={(e) => { setFilterAction(e.target.value); setPage(0); }}
          className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none cursor-pointer"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
        >
          <option value="all">{"\u0412\u0441\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f"}</option>
          {uniqueActions.map((a) => (
            <option key={a} value={a}>{actionLabels[a] || a}</option>
          ))}
        </select>

        {/* Period segmented control */}
        <div
          className="inline-flex p-[2px] rounded-[7px]"
          style={{ background: "var(--bg-2)", border: "1px solid var(--line)" }}
        >
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => { setFilterPeriod(p.value); setPage(0); }}
              className="px-[10px] py-[4px] text-[11px] rounded-[5px] transition-all"
              style={{
                background: filterPeriod === p.value ? "var(--panel)" : "transparent",
                color: filterPeriod === p.value ? "var(--ink)" : "var(--ink-3)",
                boxShadow: filterPeriod === p.value ? "0 1px 2px #0002" : "none",
                border: "none",
                cursor: "pointer",
              }}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Custom date inputs */}
        {filterPeriod === "custom" && (
          <>
            <input
              type="date"
              value={customDateFrom}
              onChange={(e) => { setCustomDateFrom(e.target.value); setPage(0); }}
              className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none"
              style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
              title={"\u041e\u0442"}
            />
            <input
              type="date"
              value={customDateTo}
              onChange={(e) => { setCustomDateTo(e.target.value); setPage(0); }}
              className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none"
              style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
              title={"\u0414\u043e"}
            />
          </>
        )}
      </div>

      {/* ═══════════ Table ═══════════ */}
      <div
        className="rounded-[9px] overflow-hidden"
        style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
      >
        <div className="overflow-x-auto">
          <table className="w-full" style={{ borderCollapse: "collapse", fontSize: "12.5px" }}>
            <thead>
              <tr>
                <th
                  className="label-mono text-right py-[9px] px-[12px]"
                  style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}
                >
                  {"\u0412\u0420\u0415\u041c\u042f"}
                </th>
                <th
                  className="label-mono text-left py-[9px] px-[12px]"
                  style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}
                >
                  {"\u0410\u041a\u0422\u041e\u0420"}
                </th>
                <th
                  className="label-mono text-left py-[9px] px-[12px]"
                  style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}
                >
                  {"\u0414\u0415\u0419\u0421\u0422\u0412\u0418\u0415"}
                </th>
                <th
                  className="label-mono text-left py-[9px] px-[12px]"
                  style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}
                >
                  {"\u0421\u0423\u0429\u041d\u041e\u0421\u0422\u042c"}
                </th>
                <th
                  className="label-mono text-left py-[9px] px-[12px]"
                  style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}
                >
                  {"\u0422\u0415\u041d\u0410\u041d\u0422"}
                </th>
                <th
                  className="label-mono text-right py-[9px] px-[12px]"
                  style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}
                >
                  TRACE
                </th>
                <th
                  className="label-mono text-right py-[9px] px-[12px]"
                  style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)", width: 80 }}
                >
                  &nbsp;
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((log) => {
                const isExpanded = expandedIds.has(log.id);
                const tone = getActionTone(log.action);
                const isAi = log.actor_type === "ai" || log.actor_type === "system";

                return (
                  <Fragment key={log.id}>
                    {/* ── Main row ── */}
                    <tr
                      className="cursor-pointer transition-colors"
                      style={{ background: isExpanded ? "var(--bg-2)" : "transparent" }}
                      onClick={() => setExpandedIds(prev => { const next = new Set(prev); if (isExpanded) next.delete(log.id); else next.add(log.id); return next; })}
                      onMouseEnter={(e) => { if (!isExpanded) e.currentTarget.style.background = "var(--bg-2)"; }}
                      onMouseLeave={(e) => { if (!isExpanded) e.currentTarget.style.background = "transparent"; }}
                    >
                      {/* ВРЕМЯ */}
                      <td
                        className="py-[9px] px-[12px] mono text-[11px] tnum whitespace-nowrap text-right"
                        style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-3)" }}
                      >
                        {fmtTime(log.created_at)}
                      </td>

                      {/* АКТОР */}
                      <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                        <div className="flex items-center gap-[8px]">
                          <div
                            className="w-[24px] h-[24px] rounded-[5px] grid place-items-center text-[9.5px] font-semibold flex-shrink-0"
                            style={{
                              background: isAi ? "var(--accent-soft)" : "var(--accent-soft)",
                              color: "var(--accent)",
                            }}
                          >
                            {getActorInitials(log)}
                          </div>
                          <div className="min-w-0">
                            <div
                              className="mono text-[11.5px] truncate"
                              style={{ color: "var(--ink)", maxWidth: 200 }}
                            >
                              {getActorEmail(log)}
                            </div>
                            <div className="text-[10px]" style={{ color: "var(--ink-4)" }}>
                              {getActorSub(log)}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* ДЕЙСТВИЕ */}
                      <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                        <Chip tone={tone}>
                          {actionLabels[log.action] || log.action}
                        </Chip>
                      </td>

                      {/* СУЩНОСТЬ */}
                      <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                        <span className="mono text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                          {log.entity_type ? (
                            <>
                              <span className="capitalize">{log.entity_type}</span>
                              {log.entity_id && (
                                <span style={{ color: "var(--ink-4)" }}> {log.entity_id.slice(0, 7)}</span>
                              )}
                            </>
                          ) : (
                            "\u2014"
                          )}
                        </span>
                      </td>

                      {/* ТЕНАНТ */}
                      <td
                        className="py-[9px] px-[12px] text-[11.5px]"
                        style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-2)" }}
                      >
                        {log.tenant_name || "\u2014"}
                      </td>

                      {/* TRACE */}
                      <td
                        className="py-[9px] px-[12px] mono text-[10.5px] text-right"
                        style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-4)" }}
                      >
                        {getTraceId(log)}
                      </td>

                      {/* TOGGLE */}
                      <td
                        className="py-[9px] px-[12px] text-right"
                        style={{ borderBottom: "1px solid var(--hair)" }}
                      >
                        <span
                          className="text-[11px] transition-colors"
                          style={{ color: "var(--accent)", cursor: "pointer", borderBottom: "1px dotted color-mix(in oklab, var(--accent) 50%, transparent)" }}
                        >
                          {isExpanded
                            ? "\u0441\u043a\u0440\u044b\u0442\u044c \u25B4"
                            : "\u0440\u0430\u0441\u043a\u0440\u044b\u0442\u044c \u25BE"}
                        </span>
                      </td>
                    </tr>

                    {/* ── Expanded detail ── */}
                    {isExpanded && log.meta_json && (
                      <tr key={`${log.id}-detail`}>
                        <td
                          colSpan={7}
                          className="p-0"
                        >
                          <div className="mx-[12px] my-[10px] rounded-[8px] overflow-hidden" style={{ background: "var(--panel)", border: "1px solid var(--line)" }}>
                            {/* Detail pairs — clean table layout */}
                            <div className="p-[14px]">
                              <table className="w-full" style={{ borderCollapse: "collapse" }}>
                                <tbody>
                                  {(() => {
                                    const entries = Object.entries(log.meta_json);
                                    const rows: [string, any, string?, any?][] = [];
                                    for (let i = 0; i < entries.length; i += 2) {
                                      rows.push([entries[i][0], entries[i][1], entries[i + 1]?.[0], entries[i + 1]?.[1]]);
                                    }
                                    return rows.map((row, ri) => (
                                      <tr key={ri} style={{ borderBottom: ri < rows.length - 1 ? "1px dashed var(--hair)" : "none" }}>
                                        <td className="mono text-[9px] uppercase tracking-[0.12em] py-[7px] pr-[10px] align-top whitespace-nowrap" style={{ color: "var(--ink-4)", width: "140px" }}>{row[0]}</td>
                                        <td className="mono text-[12px] py-[7px] pr-[30px] align-top" style={{ color: "var(--ink)" }}>{typeof row[1] === "object" ? JSON.stringify(row[1]) : String(row[1] ?? "—")}</td>
                                        {row[2] !== undefined && (
                                          <>
                                            <td className="mono text-[9px] uppercase tracking-[0.12em] py-[7px] pr-[10px] align-top whitespace-nowrap" style={{ color: "var(--ink-4)", width: "140px" }}>{row[2]}</td>
                                            <td className="mono text-[12px] py-[7px] align-top" style={{ color: "var(--ink)" }}>{typeof row[3] === "object" ? JSON.stringify(row[3]) : String(row[3] ?? "—")}</td>
                                          </>
                                        )}
                                      </tr>
                                    ));
                                  })()}
                                </tbody>
                              </table>
                            </div>

                            {/* Detail footer */}
                            <div
                              className="px-[14px] py-[10px] text-[11.5px] flex items-center gap-[6px]"
                              style={{ borderTop: "1px solid var(--line)", background: "var(--bg-2)" }}
                            >
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleCopyJson(log.meta_json!);
                                }}
                                className="transition-colors"
                                style={{
                                  color: "var(--accent)",
                                  cursor: "pointer",
                                  background: "none",
                                  border: "none",
                                  borderBottom: "1px dotted color-mix(in oklab, var(--accent) 50%, transparent)",
                                  padding: 0,
                                  font: "inherit",
                                  fontSize: "11.5px",
                                }}
                              >
                                {copyMsg || "\u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c JSON"}
                              </button>
                              {log.action === "impersonate" && (
                                <>
                                  <span style={{ color: "var(--ink-4)" }}>&middot;</span>
                                  <button
                                    onClick={(e) => e.stopPropagation()}
                                    className="transition-colors"
                                    style={{
                                      color: "var(--accent)",
                                      cursor: "pointer",
                                      background: "none",
                                      border: "none",
                                      borderBottom: "1px dotted color-mix(in oklab, var(--accent) 50%, transparent)",
                                      padding: 0,
                                      font: "inherit",
                                      fontSize: "11.5px",
                                    }}
                                  >
                                    {"\u0437\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c \u0441\u0435\u0441\u0441\u0438\u044e"}
                                  </button>
                                </>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              {filtered.length === 0 && (
                <tr>
                  <td
                    colSpan={7}
                    className="px-[12px] py-[40px] text-center text-[12.5px]"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {"\u041d\u0435\u0442 \u0437\u0430\u043f\u0438\u0441\u0435\u0439"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* ═══════════ Pager ═══════════ */}
        {filtered.length > 0 && (
          <div
            className="flex items-center justify-between px-[14px] py-[10px]"
            style={{
              borderTop: "1px solid var(--line)",
              background: "var(--panel-2)",
              fontSize: "11.5px",
            }}
          >
            <span style={{ color: "var(--ink-3)" }}>
              {"\u041f\u043e\u043a\u0430\u0437\u0430\u043d\u043e"} {filtered.length} {"\u0438\u0437"}{" "}
              {totalCount > filtered.length ? totalCount.toLocaleString() : filtered.length}
              {" \u00b7 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 "}
              {periodDisplayLabel}
            </span>
            <div className="flex items-center gap-[4px]">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="w-[28px] h-[26px] rounded-[5px] grid place-items-center text-[11px] disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ border: "1px solid var(--line)", color: "var(--ink-2)" }}
              >
                &#8249;
              </button>
              {Array.from({ length: Math.min(totalPages, 5) }).map((_, i) => (
                <button
                  key={i}
                  onClick={() => setPage(i)}
                  className="w-[28px] h-[26px] rounded-[5px] grid place-items-center text-[11px] font-medium"
                  style={{
                    border: page === i ? "1px solid var(--accent)" : "1px solid var(--line)",
                    color: page === i ? "var(--accent)" : "var(--ink-2)",
                    background: page === i ? "var(--accent-soft)" : "transparent",
                  }}
                >
                  {i + 1}
                </button>
              ))}
              {totalPages > 5 && (
                <span className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>&hellip;</span>
              )}
              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={!hasMore}
                className="w-[28px] h-[26px] rounded-[5px] grid place-items-center text-[11px] disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ border: "1px solid var(--line)", color: "var(--ink-2)" }}
              >
                &#8250;
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
