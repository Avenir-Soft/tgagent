"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { api } from "@/lib/api";

interface AILog {
  id: string;
  tenant_name: string | null;
  tenant_id: string;
  conversation_id: string | null;
  trace_id: string;
  user_message: string;
  detected_language: string;
  model: string;
  state_before: string;
  state_after: string;
  tools_called: string[];
  total_duration_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  created_at: string;
}

interface TenantOption {
  id: string;
  name: string;
}

type PeriodValue = "1h" | "6h" | "24h" | "7d" | "30d" | "custom";

const PERIOD_OPTIONS: { value: PeriodValue; label: string }[] = [
  { value: "1h", label: "1 час" },
  { value: "6h", label: "6 часов" },
  { value: "24h", label: "24 часа" },
  { value: "7d", label: "7 дней" },
  { value: "30d", label: "30 дней" },
  { value: "custom", label: "Период..." },
];

const PERIOD_SHORT_LABELS: Record<PeriodValue, string> = {
  "1h": "1Ч",
  "6h": "6Ч",
  "24h": "24Ч",
  "7d": "7Д",
  "30d": "30Д",
  "custom": "",
};

/* ---------- Sparkline ---------- */
function Sparkline({ data }: { data: number[] }) {
  const max = Math.max(...data, 1);
  return (
    <div className="flex items-end gap-[2px]" style={{ height: 16, marginTop: 4 }}>
      {data.map((v, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            height: `${Math.max((v / max) * 100, 4)}%`,
            minHeight: 2,
            background: "var(--accent)",
            opacity: 0.5,
            borderRadius: 1,
          }}
        />
      ))}
    </div>
  );
}

/* ---------- Build sparkline data from logs ---------- */
function buildSparklineBuckets(logs: AILog[], bucketCount: number, extractValue: (log: AILog) => number): number[] {
  if (logs.length === 0) return Array(bucketCount).fill(0);
  const sorted = [...logs].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  const minT = new Date(sorted[0].created_at).getTime();
  const maxT = new Date(sorted[sorted.length - 1].created_at).getTime();
  const range = Math.max(maxT - minT, 1);
  const buckets = Array(bucketCount).fill(0);
  for (const log of sorted) {
    const t = new Date(log.created_at).getTime();
    const idx = Math.min(Math.floor(((t - minT) / range) * bucketCount), bucketCount - 1);
    buckets[idx] += extractValue(log);
  }
  return buckets;
}

/* ---------- Status logic ---------- */
function getLogStatus(log: AILog): { label: string; tone: string } {
  // error if explicitly broken or extreme timeout
  if ((log.total_duration_ms || 0) > 10000) return { label: "error", tone: "bad" };
  // no tools + short = no AI call
  if ((!log.tools_called || log.tools_called.length === 0) && (log.total_duration_ms || 0) < 500)
    return { label: "\u2014 no call", tone: "dim" };
  // slow
  if ((log.total_duration_ms || 0) > 5000) return { label: "slow", tone: "warn" };
  // no model = no call
  if (!log.model) return { label: "\u2014 no call", tone: "dim" };
  return { label: "ok", tone: "good" };
}

/* ---------- Chip ---------- */
function Chip({ tone, children }: { tone: string; children: React.ReactNode }) {
  if (tone === "dim") {
    return (
      <span
        className="inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-full text-[10.5px] font-medium leading-[1.4]"
        style={{ background: "var(--bg-2)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
      >
        {children}
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-full text-[10.5px] font-medium leading-[1.4]"
      style={{
        background: `var(--${tone}-soft)`,
        color: `var(--${tone})`,
        border: `1px solid color-mix(in oklab, var(--${tone}) 30%, transparent)`,
      }}
    >
      <span style={{ fontSize: "7px" }}>&#9679;</span>
      {children}
    </span>
  );
}

/* ---------- Skeleton ---------- */
function MonitorSkeleton() {
  return (
    <div className="flex flex-col gap-[14px] animate-pulse">
      <div className="h-8 w-48 skeleton rounded-[9px]" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-[10px]">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-[90px] skeleton rounded-[9px]" />
        ))}
      </div>
      <div className="h-[40px] skeleton rounded-[9px]" />
      <div className="space-y-2">
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="h-[38px] skeleton rounded-[9px]" />
        ))}
      </div>
    </div>
  );
}

const PAGE_SIZE = 50;

export default function AIMonitorPage() {
  const [logs, setLogs] = useState<AILog[]>([]);
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterTenant, setFilterTenant] = useState("all");
  const [filterStatus, setFilterStatus] = useState("all");
  const [filterModel, setFilterModel] = useState("all");
  const [filterPeriod, setFilterPeriod] = useState<PeriodValue>("1h");
  const [customDateFrom, setCustomDateFrom] = useState("");
  const [customDateTo, setCustomDateTo] = useState("");
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [paused, setPaused] = useState(false);
  const [countdown, setCountdown] = useState(15);
  const countdownRef = useRef(15);

  /* ---------- Period label helper ---------- */
  const periodLabel = useMemo(() => {
    if (filterPeriod === "custom") {
      const from = customDateFrom || "...";
      const to = customDateTo || "...";
      return `${from} — ${to}`;
    }
    return PERIOD_SHORT_LABELS[filterPeriod];
  }, [filterPeriod, customDateFrom, customDateTo]);

  /* ---------- Data loading ---------- */
  const load = useCallback(() => {
    setLoading(true);
    const tenantParam = filterTenant !== "all" ? `&tenant_id=${filterTenant}` : "";
    let periodParams = "";
    if (filterPeriod === "custom") {
      if (customDateFrom) periodParams += `&date_from=${customDateFrom}`;
      if (customDateTo) periodParams += `&date_to=${customDateTo}`;
    } else {
      periodParams = `&period=${filterPeriod}`;
    }
    Promise.all([
      api.get<AILog[]>(`/platform/ai-logs?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}${tenantParam}${periodParams}`),
      api.get<{ items: TenantOption[]; total: number }>("/tenants?limit=100&offset=0"),
    ])
      .then(([l, t]) => {
        setLogs(l);
        setTenants(t.items);
        setHasMore(l.length >= PAGE_SIZE);
        countdownRef.current = 15;
        setCountdown(15);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [page, filterTenant, filterPeriod, customDateFrom, customDateTo]);

  /* Auto-refresh interval */
  useEffect(() => {
    load();
    if (paused) return;
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, [load, paused]);

  /* Countdown timer */
  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => {
      countdownRef.current = Math.max(0, countdownRef.current - 1);
      setCountdown(countdownRef.current);
    }, 1000);
    return () => clearInterval(id);
  }, [paused]);

  /* ---------- Unique models for filter ---------- */
  const uniqueModels = useMemo(() => {
    const models = new Set<string>();
    logs.forEach((l) => { if (l.model) models.add(l.model); });
    return [...models].sort();
  }, [logs]);

  /* ---------- Filtered data ---------- */
  const filtered = useMemo(() => {
    return logs.filter((l) => {
      if (filterTenant !== "all" && l.tenant_id !== filterTenant) return false;
      if (filterModel !== "all" && l.model !== filterModel) return false;
      if (filterStatus !== "all") {
        const s = getLogStatus(l);
        if (filterStatus === "ok" && s.tone !== "good") return false;
        if (filterStatus === "error" && s.tone !== "bad") return false;
        if (filterStatus === "slow" && s.tone !== "warn") return false;
      }
      return true;
    });
  }, [logs, filterTenant, filterStatus, filterModel]);

  /* ---------- KPI computations ---------- */
  const kpis = useMemo(() => {
    if (logs.length === 0)
      return { totalCalls: 0, p95: 0, totalTokens: 0, promptTokens: 0, completionTokens: 0, cost: 0, timeouts: 0, errors: 0, errPct: 0 };

    const totalCalls = logs.length;

    // P95 latency
    const durations = logs.map((l) => l.total_duration_ms || 0).sort((a, b) => a - b);
    const p95Idx = Math.floor(durations.length * 0.95);
    const p95 = durations[Math.min(p95Idx, durations.length - 1)];

    // Tokens
    const promptTokens = logs.reduce((s, l) => s + (l.prompt_tokens || 0), 0);
    const completionTokens = logs.reduce((s, l) => s + (l.completion_tokens || 0), 0);
    const totalTokens = promptTokens + completionTokens;
    // Cost estimate: ~$0.15/1M input, ~$0.60/1M output for gpt-4o-mini
    const cost = (promptTokens * 0.00015 + completionTokens * 0.0006) / 1000;

    // Timeouts (>5s) and errors (>10s or status error)
    const timeouts = logs.filter((l) => (l.total_duration_ms || 0) > 5000 && (l.total_duration_ms || 0) <= 10000).length;
    const errors = logs.filter((l) => (l.total_duration_ms || 0) > 10000).length;
    const errPct = Math.round(((timeouts + errors) / totalCalls) * 1000) / 10;

    return { totalCalls, p95, totalTokens, promptTokens, completionTokens, cost, timeouts, errors, errPct };
  }, [logs]);

  /* ---------- Sparkline data ---------- */
  const SPARK_BUCKETS = 7;
  const sparkCalls = useMemo(() => buildSparklineBuckets(logs, SPARK_BUCKETS, () => 1), [logs]);
  const sparkLatency = useMemo(() => buildSparklineBuckets(logs, SPARK_BUCKETS, (l) => l.total_duration_ms || 0), [logs]);
  const sparkTokens = useMemo(() => buildSparklineBuckets(logs, SPARK_BUCKETS, (l) => (l.prompt_tokens || 0) + (l.completion_tokens || 0)), [logs]);
  const sparkErrors = useMemo(() => buildSparklineBuckets(logs, SPARK_BUCKETS, (l) => (l.total_duration_ms || 0) > 5000 ? 1 : 0), [logs]);

  /* ---------- Formatters ---------- */
  const fmtTime = (d: string) => {
    const date = new Date(d);
    return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };
  const fmtDate = (d: string) => {
    const date = new Date(d);
    const today = new Date();
    if (date.toDateString() === today.toDateString()) return fmtTime(d);
    return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" }) + " " + fmtTime(d);
  };

  const fmtP95 = (ms: number) => {
    if (ms >= 1000) return (ms / 1000).toFixed(2) + "s";
    return ms + "ms";
  };

  /* ---------- Total pages ---------- */
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE) + (hasMore ? 1 : 0));

  if (loading && logs.length === 0) return <MonitorSkeleton />;

  return (
    <div className="flex flex-col gap-[14px]">
      {/* ========== Header ========== */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1
            className="text-[22px] font-semibold tracking-[-0.01em] flex items-center gap-[8px]"
            style={{ color: "var(--ink)" }}
          >
            AI Монитор
            <span
              className="text-[11px] font-medium px-[7px] py-[2px] rounded-full"
              style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
            >
              {logs.length}
            </span>
          </h1>
          <div
            className="text-[11.5px] mt-[3px] flex items-center gap-[6px]"
            style={{ color: "var(--ink-3)" }}
          >
            <span
              className="w-[6px] h-[6px] rounded-full flex-shrink-0"
              style={{
                background: paused ? "var(--ink-4)" : "var(--good)",
                boxShadow: paused ? "none" : "0 0 0 2px color-mix(in oklab, var(--good) 25%, transparent)",
                animation: paused ? "none" : "pulse-soft 2s ease-in-out infinite",
              }}
            />
            {paused ? (
              "На паузе"
            ) : (
              <>
                Авто-обновление &middot; каждые{" "}
                <span className="tnum">15с</span> &middot; следующее через{" "}
                <span className="tnum">{countdown}с</span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-[8px]">
          <button
            onClick={() => setPaused(!paused)}
            className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-medium transition-colors"
            style={{
              background: "transparent",
              border: "1px solid var(--line)",
              color: "var(--ink)",
            }}
          >
            {paused ? "\u25B6 Продолжить" : "\u23F8 Пауза"}
          </button>
          <button
            onClick={() => { load(); countdownRef.current = 15; setCountdown(15); }}
            className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-medium transition-colors"
            style={{
              background: "transparent",
              border: "1px solid var(--line)",
              color: "var(--ink)",
            }}
          >
            &#8635; Обновить
          </button>
        </div>
      </div>

      {/* ========== Error ========== */}
      {error && (
        <div
          className="rounded-[9px] p-4"
          style={{
            background: "var(--bad-soft)",
            border: "1px solid color-mix(in oklab, var(--bad) 30%, transparent)",
          }}
        >
          <p className="text-[12.5px]" style={{ color: "var(--bad)" }}>
            {error}
          </p>
        </div>
      )}

      {/* ========== KPI Cards ========== */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-[10px]">
        {/* Calls */}
        <div
          className="rounded-[9px] p-[12px_13px] flex flex-col gap-[4px]"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
        >
          <div className="label-mono">ВЫЗОВОВ {periodLabel && <>&middot; {periodLabel}</>}</div>
          <div
            className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em] mt-[2px]"
            style={{ color: "var(--ink)" }}
          >
            {kpis.totalCalls.toLocaleString()}
          </div>
          <div className="flex items-center gap-[8px]">
            <span className="mono text-[10.5px]" style={{ color: "var(--ink-3)" }}>
              {filtered.length} на странице
            </span>
          </div>
          <Sparkline data={sparkCalls} />
        </div>

        {/* P95 Latency */}
        <div
          className="rounded-[9px] p-[12px_13px] flex flex-col gap-[4px]"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
        >
          <div className="label-mono">P95 LATENCY {periodLabel && <>&middot; {periodLabel}</>}</div>
          <div
            className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em] mt-[2px]"
            style={{
              color: kpis.p95 > 10000 ? "var(--bad)" : kpis.p95 > 4000 ? "var(--warn)" : "var(--good)",
            }}
          >
            {fmtP95(kpis.p95)}
          </div>
          <div className="flex items-center gap-[8px]">
            <span className="mono text-[10.5px]" style={{ color: kpis.p95 > 10000 ? "var(--bad)" : kpis.p95 > 4000 ? "var(--warn)" : "var(--ink-3)" }}>
              {kpis.p95 > 10000 ? "превышен" : kpis.p95 > 4000 ? "внимание" : "нормальный"} &middot; лимит 10с
            </span>
          </div>
          <Sparkline data={sparkLatency} />
        </div>

        {/* Tokens */}
        <div
          className="rounded-[9px] p-[12px_13px] flex flex-col gap-[4px]"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
        >
          <div className="label-mono">ТОКЕНОВ {periodLabel && <>&middot; {periodLabel}</>}</div>
          <div
            className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em] mt-[2px]"
            style={{ color: "var(--ink)" }}
          >
            {kpis.totalTokens.toLocaleString()}
          </div>
          <div className="flex items-center gap-[8px]">
            <span className="mono text-[10.5px]" style={{ color: "var(--ink-3)" }}>
              prompt + completion &middot; ${kpis.cost.toFixed(2)}
            </span>
          </div>
          <Sparkline data={sparkTokens} />
        </div>

        {/* Timeout / Err */}
        <div
          className="rounded-[9px] p-[12px_13px] flex flex-col gap-[4px]"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
        >
          <div className="label-mono">TIMEOUT / ERR {periodLabel && <>&middot; {periodLabel}</>}</div>
          <div
            className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em] mt-[2px]"
            style={{
              color: kpis.errPct > 3 ? "var(--bad)" : kpis.errPct > 1 ? "var(--warn)" : "var(--good)",
            }}
          >
            {kpis.errPct}%
          </div>
          <div className="flex items-center gap-[8px]">
            <span className="mono text-[10.5px]" style={{ color: "var(--ink-3)" }}>
              {kpis.timeouts} timeouts &middot; {kpis.errors} errors
            </span>
          </div>
          <Sparkline data={sparkErrors} />
        </div>
      </div>

      {/* ========== Toolbar ========== */}
      <div className="flex flex-wrap items-center gap-[8px]">
        <select
          value={filterTenant}
          onChange={(e) => { setFilterTenant(e.target.value); setPage(0); }}
          className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none cursor-pointer"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
        >
          <option value="all">Все тенанты</option>
          {tenants.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        <select
          value={filterStatus}
          onChange={(e) => { setFilterStatus(e.target.value); setPage(0); }}
          className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none cursor-pointer"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
        >
          <option value="all">Все статусы</option>
          <option value="ok">ok</option>
          <option value="slow">slow</option>
          <option value="error">error</option>
        </select>
        <select
          value={filterModel}
          onChange={(e) => { setFilterModel(e.target.value); setPage(0); }}
          className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none cursor-pointer"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
        >
          <option value="all">Все модели</option>
          {uniqueModels.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <select
          value={filterPeriod}
          onChange={(e) => { setFilterPeriod(e.target.value as PeriodValue); setPage(0); }}
          className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none cursor-pointer"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
        >
          {PERIOD_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        {filterPeriod === "custom" && (
          <>
            <input
              type="date"
              value={customDateFrom}
              onChange={(e) => { setCustomDateFrom(e.target.value); setPage(0); }}
              className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none"
              style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
              placeholder="от"
              title="От"
            />
            <input
              type="date"
              value={customDateTo}
              onChange={(e) => { setCustomDateTo(e.target.value); setPage(0); }}
              className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none"
              style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
              placeholder="до"
              title="До"
            />
          </>
        )}
        <div className="ml-auto text-[10.5px]" style={{ color: "var(--ink-3)" }}>
          Показаны успешные &middot; ошибки &middot; медленные (&gt;5с)
        </div>
      </div>

      {/* ========== Table ========== */}
      <div
        className="rounded-[9px] overflow-hidden"
        style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
      >
        <div className="overflow-x-auto">
          <table className="w-full" style={{ borderCollapse: "collapse", fontSize: "12.5px" }}>
            <thead>
              <tr>
                <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>ВРЕМЯ</th>
                <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>ТЕНАНТ</th>
                <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>USER MSG</th>
                <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>ИНСТРУМЕНТЫ</th>
                <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>MS</th>
                <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>ТОКЕНЫ</th>
                <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>СТАТУС</th>
                <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>МОДЕЛЬ</th>
                <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)", width: "32px" }}></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((log) => {
                const st = getLogStatus(log);
                const isErr = st.tone === "bad";
                const isSlow = st.tone === "warn";
                const ms = log.total_duration_ms || 0;
                const tokens = (log.prompt_tokens || 0) + (log.completion_tokens || 0);
                const toolNames = (log.tools_called || []).map((t: any) =>
                  typeof t === "string" ? t : t?.name || "tool"
                );
                return (
                  <tr
                    key={log.id}
                    className="transition-colors"
                    style={{
                      background: isErr
                        ? "color-mix(in oklab, var(--bad) 6%, transparent)"
                        : "transparent",
                    }}
                    onMouseEnter={(e) => {
                      if (!isErr) e.currentTarget.style.background = "var(--bg-2)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = isErr
                        ? "color-mix(in oklab, var(--bad) 6%, transparent)"
                        : "transparent";
                    }}
                  >
                    {/* TIME */}
                    <td
                      className="py-[8px] px-[12px] mono text-[11px] tnum whitespace-nowrap text-right"
                      style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-3)" }}
                    >
                      {fmtDate(log.created_at)}
                    </td>
                    {/* TENANT */}
                    <td
                      className="py-[8px] px-[12px] text-[11.5px] whitespace-nowrap"
                      style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-2)" }}
                    >
                      {log.tenant_name || "\u2014"}
                    </td>
                    {/* USER MSG */}
                    <td className="py-[8px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                      <span
                        className="text-[12px] overflow-hidden text-ellipsis whitespace-nowrap block"
                        style={{ maxWidth: "320px", color: "var(--ink)" }}
                        title={log.user_message}
                      >
                        {log.user_message || "\u2014"}
                      </span>
                    </td>
                    {/* TOOLS */}
                    <td className="py-[8px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                      {toolNames.length > 0 ? (
                        <span className="mono text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                          {toolNames.join(" \u00b7 ")}
                        </span>
                      ) : (
                        <span className="text-[10.5px]" style={{ color: "var(--ink-4)" }}>&mdash;</span>
                      )}
                    </td>
                    {/* MS */}
                    <td
                      className="py-[8px] px-[12px] text-right mono text-[11.5px] tnum"
                      style={{
                        borderBottom: "1px solid var(--hair)",
                        color: ms > 5000 ? "var(--bad)" : ms > 1000 ? "var(--warn)" : "var(--good)",
                      }}
                    >
                      {ms.toLocaleString()}
                    </td>
                    {/* TOKENS */}
                    <td
                      className="py-[8px] px-[12px] text-right mono text-[11px] tnum"
                      style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-3)" }}
                    >
                      {tokens.toLocaleString()}
                    </td>
                    {/* STATUS */}
                    <td className="py-[8px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                      <Chip tone={st.tone}>{st.label}</Chip>
                    </td>
                    {/* MODEL */}
                    <td
                      className="py-[8px] px-[12px] mono text-[10.5px]"
                      style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-3)" }}
                    >
                      {log.model || "\u2014"}
                    </td>
                    {/* DETAIL LINK */}
                    <td
                      className="py-[8px] px-[12px] text-right"
                      style={{ borderBottom: "1px solid var(--hair)" }}
                    >
                      {log.conversation_id ? (
                        <a
                          className="text-[12px] cursor-pointer transition-colors"
                          style={{ color: "var(--accent)" }}
                          title="Открыть диалог"
                        >
                          &#8599;
                        </a>
                      ) : (
                        <span style={{ color: "var(--ink-4)" }}>&mdash;</span>
                      )}
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr>
                  <td
                    colSpan={9}
                    className="px-[12px] py-[40px] text-center text-[12.5px]"
                    style={{ color: "var(--ink-3)" }}
                  >
                    Нет записей
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* ========== Pager ========== */}
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
              Показано {filtered.length} из {logs.length} {periodLabel && <>&middot; {periodLabel}</>}
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
                    border: "1px solid var(--line)",
                    color: page === i ? "white" : "var(--ink-2)",
                    background: page === i ? "var(--accent)" : "transparent",
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
