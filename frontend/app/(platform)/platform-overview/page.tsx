"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";

interface MessagesByDay {
  date: string;
  count: number;
}

interface PlatformStats {
  total_tenants: number;
  total_users: number;
  total_conversations: number;
  total_orders: number;
  total_messages_24h: number;
  total_revenue: number;
  orders_24h: number;
  revenue_24h: number;
  tenants_by_status: Record<string, number>;
  messages_by_day: MessagesByDay[];
  conversations_by_day: MessagesByDay[];
  orders_by_day: MessagesByDay[];
}

interface TenantBilling {
  tenant_id: string;
  tenant_name: string;
  messages_count: number;
  ai_calls_count: number;
  orders_count: number;
  conversations_count: number;
}

interface HealthChecks {
  checks: Record<string, string>;
}

interface AuditLogEntry {
  id: string;
  tenant_id: string;
  tenant_name: string | null;
  actor_type: string;
  actor_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  meta_json: Record<string, unknown> | null;
  created_at: string;
}

function OverviewSkeleton() {
  return (
    <div className="flex flex-col gap-[14px] animate-pulse">
      <div className="h-8 w-48 skeleton" />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-[10px]">
        {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-[110px] skeleton rounded-[9px]" />)}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[1.5fr_1fr] gap-[12px]">
        <div className="h-[260px] skeleton rounded-[9px]" />
        <div className="h-[260px] skeleton rounded-[9px]" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[1.5fr_1fr] gap-[12px]">
        <div className="h-[200px] skeleton rounded-[9px]" />
        <div className="h-[200px] skeleton rounded-[9px]" />
      </div>
    </div>
  );
}

/* ── Sparkline mini-chart (pure CSS bars, 16px tall) ──────────────── */
function Sparkline({ data, tone = "accent" }: { data: number[]; tone?: string }) {
  const max = Math.max(...data, 1);
  return (
    <div className="flex items-end gap-[2px] relative" style={{ height: "16px", marginTop: "6px", opacity: 0.75 }}>
      {data.map((v, i) => (
        <span
          key={i}
          className="group relative cursor-pointer"
          style={{
            flex: 1,
            background: `var(--${tone})`,
            opacity: 0.8,
            height: `${Math.max((v / max) * 100, 4)}%`,
            borderRadius: "1px",
            transition: "opacity 0.1s",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
          onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.8"; }}
          title={`${v}`}
        />
      ))}
    </div>
  );
}

/* ── Segmented control ───────────────────────────────────────────── */
function SegmentedControl({
  items,
  active,
  onChange,
}: {
  items: { label: string; value: string }[];
  active: string;
  onChange: (v: string) => void;
}) {
  return (
    <div
      className="inline-flex rounded-[7px]"
      style={{ padding: "2px", background: "var(--bg-2)", border: "1px solid var(--line)" }}
    >
      {items.map((item) => (
        <button
          key={item.value}
          onClick={() => onChange(item.value)}
          className="rounded-[5px] border-0 cursor-pointer transition-all"
          style={{
            padding: "4px 10px",
            fontSize: "11px",
            background: active === item.value ? "var(--panel)" : "transparent",
            color: active === item.value ? "var(--ink)" : "var(--ink-3)",
            boxShadow: active === item.value ? "0 1px 2px #0002" : "none",
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export default function PlatformOverviewPage() {
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [topTenants, setTopTenants] = useState<TenantBilling[]>([]);
  const [health, setHealth] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState("");
  const [lastUpdate, setLastUpdate] = useState<string>("");
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [periodFilter, setPeriodFilter] = useState("24h");
  const [chartTab, setChartTab] = useState("messages");

  const load = useCallback(() => {
    const today = new Date().toISOString().slice(0, 10);
    const billingDays = periodFilter === "30d" ? 30 : periodFilter === "7d" ? 7 : 1;
    const billingStart = new Date(Date.now() - billingDays * 86400000).toISOString().slice(0, 10);
    Promise.all([
      api.get<PlatformStats>(`/platform/stats?period=${periodFilter}`),
      api.get<TenantBilling[]>(`/platform/billing?start_date=${billingStart}&end_date=${today}`),
      api.get<HealthChecks>("/platform/health").catch(() => null),
      api.get<AuditLogEntry[]>("/platform/audit-logs?limit=5").catch(() => []),
    ])
      .then(([s, b, h, logs]) => {
        setStats(s);
        const sorted = [...b].sort((a, b) => b.messages_count - a.messages_count).slice(0, 5);
        setTopTenants(sorted);
        if (h) setHealth(h.checks);
        setAuditLogs(logs || []);
        setLastUpdate(new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
      })
      .catch((e) => setError(e.message || "Не удалось загрузить статистику"));
  }, [periodFilter]);

  useEffect(() => { load(); const id = setInterval(load, 60_000); return () => clearInterval(id); }, [load]);

  if (error) {
    return (
      <div className="flex flex-col gap-[14px]">
        <h1 className="text-[22px] font-semibold tracking-[-0.01em]" style={{ color: "var(--ink)" }}>Обзор платформы</h1>
        <div className="rounded-[9px] p-8 text-center" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
          <p className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>{error}</p>
          <button onClick={load} className="mt-3 text-[12px] font-medium transition-colors" style={{ color: "var(--accent)" }}>Повторить</button>
        </div>
      </div>
    );
  }

  if (!stats) return <OverviewSkeleton />;

  const fmtNum = (n: number | undefined | null) => (n ?? 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");

  const days = stats.messages_by_day || [];
  const totalWeek = days.reduce((s, d) => s + d.count, 0);
  const avgPerDay = days.length > 0 ? (totalWeek / days.length).toFixed(1) : "0";
  const maxCount = Math.max(...days.map((d) => d.count), 1);
  const dayNames = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

  // Find peak day
  const peakDay = days.reduce((best, d) => d.count > (best?.count ?? 0) ? d : best, days[0]);
  const peakDayName = peakDay ? dayNames[new Date(peakDay.date).getDay()] : "";

  // Week-over-week delta placeholder (compute from data if available)
  const weekMessages = totalWeek;
  const prevWeekMessages = 0; // would need historical data
  const weekDelta = prevWeekMessages > 0
    ? Math.round(((weekMessages - prevWeekMessages) / prevWeekMessages) * 100)
    : 0;

  // Sparkline data for KPI cards — use last 7 days message counts or synthetic
  const sparkData = days.length > 0 ? days.map((d) => d.count) : [30, 42, 28, 60, 45, 80, 72];

  // Delta color helper: growth metrics — positive = good, negative = bad
  const getDeltaColor = (value: number, metric: "growth" | "cost" | "error") => {
    if (metric === "growth") return value > 0 ? "var(--good)" : value < 0 ? "var(--bad)" : "var(--ink-3)";
    if (metric === "cost") return value > 0 ? "var(--warn)" : value < 0 ? "var(--good)" : "var(--ink-3)";
    if (metric === "error") return value > 3 ? "var(--bad)" : value > 1 ? "var(--warn)" : "var(--good)";
    return "var(--ink-3)";
  };

  const kpiData = [
    {
      label: "ТЕНАНТЫ",
      value: stats.total_tenants.toString(),
      sub: `всего \u00B7 ${(stats.tenants_by_status || {})["suspended"] ?? 0} suspended`,
      delta: "",
      deltaColor: "var(--ink-3)",
      tone: "accent" as const,
      spark: [30, 42, 28, 60, 45, 80, 72],
    },
    {
      label: "ПОЛЬЗОВАТЕЛИ",
      value: stats.total_users.toString(),
      sub: "активных",
      delta: "",
      deltaColor: "var(--ink-3)",
      tone: "accent" as const,
      spark: [20, 35, 35, 40, 38, 42, 45],
    },
    {
      label: `СООБЩЕНИЙ ${periodFilter === "30d" ? "30Д" : periodFilter === "7d" ? "7Д" : "24Ч"}`,
      value: fmtNum(stats.total_messages_24h),
      sub: `из ${fmtNum(totalWeek)} за неделю`,
      delta: weekDelta !== 0 ? `${weekDelta > 0 ? "\u25B2" : "\u25BC"} ${weekDelta > 0 ? "+" : ""}${weekDelta}%` : "",
      deltaColor: getDeltaColor(weekDelta, "growth"),
      tone: "accent" as const,
      spark: sparkData,
    },
    {
      label: `ЗАКАЗОВ ${periodFilter === "30d" ? "30Д" : periodFilter === "7d" ? "7Д" : "24Ч"}`,
      value: (stats.orders_24h ?? 0).toString(),
      sub: "\u2014",
      delta: "",
      deltaColor: "var(--ink-3)",
      tone: "accent" as const,
      spark: (stats.orders_by_day || []).map(d => d.count),
    },
    {
      label: `ВЫРУЧКА ${periodFilter === "30d" ? "30Д" : periodFilter === "7d" ? "7Д" : "24Ч"}`,
      value: (stats.revenue_24h ?? 0) > 0 ? fmtNum(stats.revenue_24h) : "0",
      sub: "UZS",
      delta: "",
      deltaColor: "var(--ink-3)",
      tone: "accent" as const,
      spark: [5, 12, 8, 18, 14, 20, 16],
    },
  ];

  // Y-axis labels for chart
  const yTicks = [maxCount, Math.round(maxCount * 0.75), Math.round(maxCount * 0.5), Math.round(maxCount * 0.25), 0];

  // Health service labels and meta
  const healthLabels: Record<string, string> = {
    database: "PostgreSQL",
    redis: "Redis",
    telegram: "Telegram Bot",
    backend: "Backend API",
  };
  const healthMeta: Record<string, string> = {
    database: "primary",
    redis: "cluster",
    telegram: `${stats.total_tenants} tenants`,
    backend: "uptime",
  };

  // Format audit log time
  const fmtTime = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return "—";
    }
  };

  // Chip tone for audit action
  const actionChipStyle = (action: string) => {
    if (action.includes("impersonate")) return { background: "var(--accent-soft)", color: "var(--accent)", border: "1px solid color-mix(in oklab, var(--accent) 30%, transparent)" };
    if (action.includes("ai") || action.includes("reply")) return { background: "var(--good-soft)", color: "var(--good)", border: "1px solid color-mix(in oklab, var(--good) 30%, transparent)" };
    if (action.includes("delete") || action.includes("error")) return { background: "var(--bad-soft)", color: "var(--bad)", border: "1px solid color-mix(in oklab, var(--bad) 30%, transparent)" };
    return { background: "var(--bg-2)", color: "var(--ink-3)", border: "1px solid var(--line)" };
  };

  // Audit log description
  const auditDesc = (log: AuditLogEntry) => {
    const meta = log.meta_json || {};
    if (log.action === "impersonate" && meta.target_email) return `superadmin \u2192 ${meta.target_email as string}`;
    if (log.entity_type) return `${log.entity_type}${log.entity_id ? ` · ${(log.entity_id as string).slice(0, 8)}` : ""}`;
    return log.action;
  };

  // All health checks OK?
  const allHealthOk = health && Object.values(health).every((s) => s.startsWith("ok") || s === "closed");

  return (
    <div className="flex flex-col gap-[14px]">
      {/* ── Header ──────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-[22px] font-semibold tracking-[-0.01em]" style={{ color: "var(--ink)" }}>
            Обзор платформы
          </h1>
          <div className="text-[11.5px] mt-[3px] flex items-center gap-[6px] flex-wrap" style={{ color: "var(--ink-3)" }}>
            Последнее обновление: <span className="mono tnum">{lastUpdate || "..."}</span> &middot;{" "}
            <button onClick={load} className="transition-colors border-0 bg-transparent cursor-pointer" style={{ color: "var(--accent)", fontSize: "11.5px" }}>
              обновить &#8635;
            </button>
          </div>
        </div>
        <SegmentedControl
          items={[
            { label: "24ч", value: "24h" },
            { label: "7д", value: "7d" },
            { label: "30д", value: "30d" },
          ]}
          active={periodFilter}
          onChange={setPeriodFilter}
        />
      </div>

      {/* ── 5 KPI Cards ─────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-[10px]">
        {kpiData.map((k) => (
          <div
            key={k.label}
            className="rounded-[9px] flex flex-col gap-[4px]"
            style={{
              padding: "12px 13px",
              background: "var(--panel)",
              border: "1px solid var(--line)",
              boxShadow: "var(--shadow)",
            }}
          >
            <div className="label-mono">{k.label}</div>
            <div
              className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em]"
              style={{ color: "var(--ink)", marginTop: "2px" }}
            >
              {k.value}
            </div>
            <div className="flex items-center gap-[8px] mono text-[10.5px]">
              {k.delta && (
                <span
                  className="font-medium"
                  style={{ color: k.deltaColor }}
                >
                  {k.delta}
                </span>
              )}
              <span style={{ color: "var(--ink-3)" }}>{k.sub}</span>
            </div>
            <Sparkline data={k.spark} tone={k.tone} />
          </div>
        ))}
      </div>

      {/* ── Row 2: Chart + System Health ─────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-[1.5fr_1fr] gap-[12px]">
        {/* Messages chart */}
        <div
          className="rounded-[9px]"
          style={{
            padding: "14px 14px 8px",
            background: "var(--panel)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow)",
          }}
        >
          {/* Chart header */}
          <div className="flex items-center justify-between gap-[10px] mb-[10px] flex-wrap">
            <div>
              {(() => {
                const chartLabel = chartTab === "dialogs" ? "Диалоги" : chartTab === "orders" ? "Заказы" : "Сообщения";
                const cd = chartTab === "dialogs" ? (stats.conversations_by_day || [])
                  : chartTab === "orders" ? (stats.orders_by_day || []) : days;
                const cdTotal = cd.reduce((s, d) => s + d.count, 0);
                const cdAvg = cd.length > 0 ? (cdTotal / cd.length).toFixed(1) : "0";
                const cdPeak = cd.length > 0 ? cd.reduce((a, b) => b.count > a.count ? b : a, cd[0]) : null;
                const cdPeakName = cdPeak ? dayNames[new Date(cdPeak.date).getDay()] : "";
                return (
                  <>
                    <div className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>
                      {chartLabel} &middot; 7 дней
                    </div>
                    <div className="mono text-[10.5px] mt-[2px]" style={{ color: "var(--ink-3)", letterSpacing: "0.02em" }}>
                      {fmtNum(cdTotal)} всего &middot; avg {cdAvg}/день
                      {cdPeak && cdPeak.count > 0 ? ` · пик ${cdPeak.count} в ${cdPeakName}` : ""}
                    </div>
                  </>
                );
              })()}
            </div>
            <SegmentedControl
              items={[
                { label: "Сообщ.", value: "messages" },
                { label: "Диалоги", value: "dialogs" },
                { label: "Заказы", value: "orders" },
              ]}
              active={chartTab}
              onChange={setChartTab}
            />
          </div>

          {/* Y-axis + bars */}
          {(() => {
            const chartData = chartTab === "dialogs" ? (stats.conversations_by_day || [])
              : chartTab === "orders" ? (stats.orders_by_day || [])
              : days;
            const chartMax = Math.max(...chartData.map(d => d.count), 1);
            const chartTicks = [chartMax, Math.round(chartMax * 0.75), Math.round(chartMax * 0.5), Math.round(chartMax * 0.25), 0];
            return chartData.length > 0 ? (
            <>
              <div className="grid gap-[8px]" style={{ gridTemplateColumns: "36px 1fr", height: "180px", marginTop: "6px" }}>
                {/* Y-axis */}
                <div className="flex flex-col justify-between mono text-[9.5px] text-right" style={{ color: "var(--ink-4)", padding: "4px 0" }}>
                  {chartTicks.map((v, i) => (
                    <span key={i} className="tnum">{v}</span>
                  ))}
                </div>
                {/* Chart body */}
                <div className="relative" style={{ borderLeft: "1px solid var(--line)", borderBottom: "1px solid var(--line)" }}>
                  {/* Dashed grid lines */}
                  <div className="absolute inset-0 grid grid-rows-4 pointer-events-none">
                    {[0, 1, 2, 3].map((i) => (
                      <div key={i} style={{ borderTop: "1px dashed var(--hair)" }} />
                    ))}
                  </div>
                  {/* Bars */}
                  <div className="absolute flex items-end gap-[6px]" style={{ inset: "6px 4px 0 4px" }}>
                    {chartData.map((d) => {
                      const pct = Math.max((d.count / chartMax) * 100, 1);
                      const dt = new Date(d.date);
                      const dayLabel = `${dayNames[dt.getDay()]} ${dt.getDate()}`;
                      return (
                        <div
                          key={d.date}
                          className="flex-1 flex flex-col items-center justify-end gap-[3px] relative group"
                          style={{ height: "100%" }}
                          title={`${dayLabel}: ${d.count}`}
                        >
                          <span className="mono text-[9.5px] tnum" style={{ color: "var(--ink-3)" }}>
                            {d.count || ""}
                          </span>
                          <div
                            className="w-full rounded-t-[2px] transition-all duration-150"
                            style={{
                              height: `${pct}%`,
                              minHeight: "1px",
                              background: "var(--accent)",
                              opacity: 0.7,
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.7"; }}
                          />
                          <span className="absolute mono text-[9.5px]" style={{ bottom: "-18px", color: "var(--ink-3)" }}>
                            {dayLabel}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
              <div style={{ height: "22px" }} />
            </>
          ) : (
            <div className="flex items-center justify-center mono text-[11px]" style={{ height: "180px", color: "var(--ink-4)" }}>
              нет данных
            </div>
          );
          })()}
        </div>

        {/* System Health */}
        <div
          className="rounded-[9px]"
          style={{
            padding: "14px",
            background: "var(--panel)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow)",
          }}
        >
          {/* Health header */}
          <div className="flex items-center justify-between gap-[10px] mb-[10px] flex-wrap">
            <div className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>
              Состояние системы
            </div>
            {health && (
              <span
                className="inline-flex items-center gap-[4px] rounded-full text-[10.5px] font-medium"
                style={{
                  padding: "2px 8px",
                  lineHeight: "1.4",
                  background: allHealthOk ? "var(--good-soft)" : "var(--warn-soft)",
                  color: allHealthOk ? "var(--good)" : "var(--warn)",
                  border: `1px solid color-mix(in oklab, ${allHealthOk ? "var(--good)" : "var(--warn)"} 30%, transparent)`,
                }}
              >
                {allHealthOk ? "все работает" : "есть проблемы"}
              </span>
            )}
          </div>

          {/* Health rows */}
          <div className="flex flex-col gap-[2px]">
            {health ? (
              Object.entries(health).map(([service, status], idx, arr) => {
                const isOk = status.startsWith("ok") || status === "closed";
                const isWarn = status === "no_clients";
                const dotColor = isOk ? "var(--good)" : isWarn ? "var(--warn)" : "var(--bad)";
                return (
                  <div
                    key={service}
                    className="grid items-center gap-[10px]"
                    style={{
                      gridTemplateColumns: "16px 1fr auto",
                      padding: "8px 0",
                      borderBottom: idx < arr.length - 1 ? "1px dashed var(--hair)" : "none",
                    }}
                  >
                    <span
                      className="w-[6px] h-[6px] rounded-full mx-auto"
                      style={{
                        background: dotColor,
                        boxShadow: `0 0 0 2px color-mix(in oklab, ${dotColor} 25%, transparent)`,
                      }}
                    />
                    <div className="min-w-0">
                      <div className="text-[12.5px]" style={{ color: "var(--ink)" }}>
                        {healthLabels[service] || service}
                      </div>
                      <div className="mono text-[10.5px]" style={{ color: "var(--ink-3)", marginTop: "1px" }}>
                        {healthMeta[service] || (isOk ? "ok" : status)}
                      </div>
                    </div>
                    <span className="mono text-[11px] tnum" style={{ color: "var(--ink-2)", textAlign: "right" }}>
                      {isOk ? "ok" : isWarn ? "warn" : "error"}
                    </span>
                  </div>
                );
              })
            ) : (
              <div className="mono text-[11px] py-4 text-center" style={{ color: "var(--ink-4)" }}>
                загрузка...
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Row 3: Top Tenants + Recent Events ───────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-[1.5fr_1fr] gap-[12px]">
        {/* Top tenants */}
        <div
          className="rounded-[9px] overflow-hidden"
          style={{
            background: "var(--panel)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow)",
          }}
        >
          <div className="flex items-center justify-between gap-[10px] flex-wrap" style={{ padding: "13px 14px 10px" }}>
            <div className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>
              Топ тенанты &middot; 24ч
            </div>
            <a
              href="/platform-tenants"
              className="mono text-[11px] transition-colors"
              style={{ color: "var(--accent)", textDecoration: "none", borderBottom: "1px dotted color-mix(in oklab, var(--accent) 40%, transparent)" }}
            >
              все &rarr;
            </a>
          </div>

          <table className="w-full" style={{ borderCollapse: "collapse", fontSize: "12.5px" }}>
            <thead>
              <tr>
                <th className="label-mono text-left" style={{ padding: "9px 12px", borderBottom: "1px solid var(--line)", background: "var(--panel-2)" }}>
                  Тенант
                </th>
                <th className="label-mono text-right" style={{ padding: "9px 12px", borderBottom: "1px solid var(--line)", background: "var(--panel-2)" }}>
                  Сообщ.
                </th>
                <th className="label-mono text-right" style={{ padding: "9px 12px", borderBottom: "1px solid var(--line)", background: "var(--panel-2)" }}>
                  Заказы
                </th>
                <th className="label-mono text-right" style={{ padding: "9px 12px", borderBottom: "1px solid var(--line)", background: "var(--panel-2)" }}>
                  Диалоги
                </th>
              </tr>
            </thead>
            <tbody>
              {topTenants.length > 0 ? (
                topTenants.map((t, idx) => (
                  <tr
                    key={t.tenant_id}
                    className="transition-colors"
                    onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                  >
                    <td style={{ padding: "10px 12px", borderBottom: idx < topTenants.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--ink)", verticalAlign: "middle" }}>
                      <a href={`/platform-tenants/${t.tenant_id}`} className="flex items-center gap-[8px]" style={{ textDecoration: "none", color: "inherit" }}>
                        <span
                          className="inline-grid place-items-center mono text-[10px] flex-shrink-0"
                          style={{
                            width: "18px",
                            height: "18px",
                            borderRadius: "50%",
                            background: "var(--bg-2)",
                            border: "1px solid var(--line)",
                            color: "var(--ink-3)",
                          }}
                        >
                          {idx + 1}
                        </span>
                        <span className="text-[12.5px]" style={{ color: "var(--ink)" }}>{t.tenant_name}</span>
                      </a>
                    </td>
                    <td className="tnum font-semibold text-right" style={{ padding: "10px 12px", borderBottom: idx < topTenants.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--ink)" }}>
                      {t.messages_count}
                    </td>
                    <td className="tnum text-right" style={{ padding: "10px 12px", borderBottom: idx < topTenants.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--ink-3)" }}>
                      {t.orders_count}
                    </td>
                    <td className="tnum text-right" style={{ padding: "10px 12px", borderBottom: idx < topTenants.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--ink-3)" }}>
                      {t.conversations_count}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="text-center mono text-[11px]" style={{ padding: "20px 12px", color: "var(--ink-4)" }}>
                    нет данных за 24ч
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Recent Events (Audit Logs) */}
        <div
          className="rounded-[9px]"
          style={{
            padding: "14px",
            background: "var(--panel)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow)",
          }}
        >
          <div className="flex items-center justify-between gap-[10px] mb-[10px] flex-wrap">
            <div className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>
              Последние события
            </div>
            <a
              href="/platform-logs"
              className="mono text-[11px] transition-colors"
              style={{ color: "var(--accent)", textDecoration: "none", borderBottom: "1px dotted color-mix(in oklab, var(--accent) 40%, transparent)" }}
            >
              аудит лог &rarr;
            </a>
          </div>

          <div className="flex flex-col gap-[2px]">
            {auditLogs.length > 0 ? (
              auditLogs.map((log, idx) => (
                <div
                  key={log.id}
                  className="grid items-center gap-[10px]"
                  style={{
                    gridTemplateColumns: "60px auto 1fr auto",
                    padding: "7px 0",
                    borderBottom: idx < auditLogs.length - 1 ? "1px dashed var(--hair)" : "none",
                    fontSize: "12px",
                  }}
                >
                  {/* Time */}
                  <span className="mono tnum text-[11px]" style={{ color: "var(--ink-4)" }}>
                    {fmtTime(log.created_at)}
                  </span>
                  {/* Action chip */}
                  <span
                    className="inline-flex items-center rounded-full mono text-[10px] font-medium whitespace-nowrap"
                    style={{
                      padding: "2px 8px",
                      lineHeight: "1.4",
                      ...actionChipStyle(log.action),
                    }}
                  >
                    {log.action}
                  </span>
                  {/* Description */}
                  <span
                    className="overflow-hidden text-ellipsis whitespace-nowrap"
                    style={{ color: "var(--ink)", maxWidth: "320px", display: "inline-block", verticalAlign: "middle" }}
                  >
                    {auditDesc(log)}
                  </span>
                  {/* Tenant name */}
                  <span className="text-right whitespace-nowrap" style={{ color: "var(--ink-4)", fontSize: "11px" }}>
                    {log.tenant_name || "—"}
                  </span>
                </div>
              ))
            ) : (
              <div className="mono text-[11px] py-6 text-center" style={{ color: "var(--ink-4)" }}>
                нет событий
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
