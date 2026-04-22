"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/lib/api";

interface BillingRow {
  tenant_id: string;
  tenant_name: string;
  messages_count: number;
  ai_calls_count: number;
  orders_count: number;
  conversations_count: number;
  tokens_total: number;
  estimated_cost_usd: number;
}

interface ModelDistItem {
  model: string;
  calls: number;
  tokens: number;
  cost_usd: number;
}

interface DailyItem {
  date: string;
  ai_calls: number;
  messages: number;
  tokens: number;
}

/* ── Delta color helper ───────────────────────────────────────── */
function getDeltaColor(value: number, metric: "growth" | "cost" | "error"): string {
  if (metric === "growth") return value > 0 ? "var(--good)" : value < 0 ? "var(--bad)" : "var(--ink-3)";
  if (metric === "cost") return value > 0 ? "var(--warn)" : value < 0 ? "var(--good)" : "var(--ink-3)";
  if (metric === "error") return value > 3 ? "var(--bad)" : value > 1 ? "var(--warn)" : "var(--good)";
  return "var(--ink-3)";
}

/* ── Sparkline (pure CSS bars, 16px tall) ──────────────────────── */
function Sparkline({ data, tone = "accent" }: { data: number[]; tone?: string }) {
  const max = Math.max(...data, 1);
  return (
    <div className="flex items-end gap-[2px]" style={{ height: "16px", marginTop: "6px", opacity: 0.75 }}>
      {data.map((v, i) => (
        <span
          key={i}
          style={{
            flex: 1,
            background: `var(--${tone})`,
            opacity: 0.8,
            height: `${Math.max((v / max) * 100, 4)}%`,
            borderRadius: "1px",
          }}
        />
      ))}
    </div>
  );
}

/* ── Segmented control ─────────────────────────────────────────── */
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

/* ── Skeleton ──────────────────────────────────────────────────── */
function BillingSkeleton() {
  return (
    <div className="flex flex-col gap-[14px] animate-pulse">
      <div className="h-8 w-36 skeleton rounded-[9px]" />
      <div className="h-[62px] skeleton rounded-[9px]" />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-[10px]">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-[110px] skeleton rounded-[9px]" />
        ))}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[1.5fr_1fr] gap-[12px]">
        <div className="h-[160px] skeleton rounded-[9px]" />
        <div className="h-[160px] skeleton rounded-[9px]" />
      </div>
      <div className="h-64 skeleton rounded-[9px]" />
    </div>
  );
}

export default function BillingPage() {
  const [data, setData] = useState<BillingRow[] | null>(null);
  const [models, setModels] = useState<ModelDistItem[]>([]);
  const [daily, setDaily] = useState<DailyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 30); return d.toISOString().split("T")[0];
  });
  const [dateTo, setDateTo] = useState(() => new Date().toISOString().split("T")[0]);
  const [quickPeriod, setQuickPeriod] = useState("30d");

  const load = useCallback(() => {
    setLoading(true);
    const qs = `start_date=${dateFrom}&end_date=${dateTo}`;
    Promise.all([
      api.get<BillingRow[]>(`/platform/billing?${qs}`),
      api.get<ModelDistItem[]>(`/platform/billing/models?${qs}`),
      api.get<DailyItem[]>(`/platform/billing/daily?${qs}`),
    ])
      .then(([b, m, d]) => {
        setData(b);
        setModels(m);
        setDaily(d);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [dateFrom, dateTo]);

  useEffect(() => { load(); }, [load]);

  const fmtNum = (n: number) => n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");

  /* Quick period handler */
  const handleQuickPeriod = useCallback((value: string) => {
    setQuickPeriod(value);
    const today = new Date();
    const to = today.toISOString().split("T")[0];
    let from: string;
    if (value === "7d") {
      const d = new Date(); d.setDate(d.getDate() - 7); from = d.toISOString().split("T")[0];
    } else if (value === "30d") {
      const d = new Date(); d.setDate(d.getDate() - 30); from = d.toISOString().split("T")[0];
    } else if (value === "90d") {
      const d = new Date(); d.setDate(d.getDate() - 90); from = d.toISOString().split("T")[0];
    } else {
      // YTD
      from = `${today.getFullYear()}-01-01`;
    }
    setDateFrom(from);
    setDateTo(to);
  }, []);

  /* Period label */
  const periodLabel = useMemo(() => {
    const from = new Date(dateFrom);
    const to = new Date(dateTo);
    const days = Math.round((to.getTime() - from.getTime()) / 86400000);
    const fmtShort = (d: Date) => d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
    return `${fmtShort(from)} \u2014 ${fmtShort(to)} \u00B7 ${days} дней`;
  }, [dateFrom, dateTo]);

  /* Days in period */
  const periodDays = useMemo(() => {
    const from = new Date(dateFrom);
    const to = new Date(dateTo);
    return Math.max(Math.round((to.getTime() - from.getTime()) / 86400000), 1);
  }, [dateFrom, dateTo]);

  /* Totals — use real token/cost data from backend */
  const totals = useMemo(() => {
    if (!data) return { messages: 0, aiCalls: 0, orders: 0, convos: 0, tokens: 0, cost: 0 };
    const messages = data.reduce((s, r) => s + r.messages_count, 0);
    const aiCalls = data.reduce((s, r) => s + r.ai_calls_count, 0);
    const orders = data.reduce((s, r) => s + r.orders_count, 0);
    const convos = data.reduce((s, r) => s + r.conversations_count, 0);
    const tokens = data.reduce((s, r) => s + r.tokens_total, 0);
    const cost = data.reduce((s, r) => s + r.estimated_cost_usd, 0);
    return { messages, aiCalls, orders, convos, tokens, cost };
  }, [data]);

  /* CSV export */
  const exportCSV = useCallback(() => {
    if (!data || data.length === 0) return;
    const header = "Тенант,Сообщения,AI вызовы,Заказы,Диалоги,Токены,Стоимость ($)";
    const rows = data.map((r) => {
      return `"${r.tenant_name}",${r.messages_count},${r.ai_calls_count},${r.orders_count},${r.conversations_count},${r.tokens_total},${r.estimated_cost_usd.toFixed(4)}`;
    });
    const footer = `"Итого",${totals.messages},${totals.aiCalls},${totals.orders},${totals.convos},${totals.tokens},${totals.cost.toFixed(4)}`;
    const csv = [header, ...rows, footer].join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `billing_${dateFrom}_${dateTo}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [data, totals, dateFrom, dateTo]);

  /* PDF export (print) */
  const exportPDF = useCallback(() => {
    window.print();
  }, []);

  /* Chart bars from daily data */
  const chartBars = useMemo(() => {
    return daily.map((d) => d.ai_calls);
  }, [daily]);

  const chartMax = Math.max(...chartBars, 1);
  const chartAvg = chartBars.length > 0 ? Math.round(totals.aiCalls / chartBars.length) : 0;

  /* Model distribution with tone assignments */
  const modelTones = ["accent", "info", "good", "warn"];
  const modelItems = useMemo(() => {
    return models.map((m, i) => ({
      ...m,
      tone: modelTones[i % modelTones.length],
    }));
  }, [models]);

  /* Slug from tenant name */
  const toSlug = (name: string) =>
    name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "").slice(0, 20);

  /* Initials from tenant name */
  const toInitials = (name: string) =>
    name.split(/\s+/).map((w) => w[0]).join("").toUpperCase().slice(0, 2);

  /* Sparkline data from daily for KPI cards */
  const sparkMessages = useMemo(() => daily.length > 0 ? daily.map((d) => d.messages) : [], [daily]);
  const sparkAI = useMemo(() => daily.length > 0 ? daily.map((d) => d.ai_calls) : [], [daily]);
  const sparkTokens = useMemo(() => daily.length > 0 ? daily.map((d) => d.tokens) : [], [daily]);
  // For orders/convos, use tenant breakdown as sparkline
  const sparkOrders = useMemo(() => data ? data.map((r) => r.orders_count) : [], [data]);
  const sparkConvos = useMemo(() => data ? data.map((r) => r.conversations_count) : [], [data]);
  const defaultSpark = [30, 42, 28, 60, 45, 80, 72];

  if (loading && !data) return <BillingSkeleton />;

  return (
    <div className="flex flex-col gap-[14px]">
      {/* -- Header --------------------------------------------------- */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-[22px] font-semibold tracking-[-0.01em]" style={{ color: "var(--ink)" }}>
            Биллинг
          </h1>
          <div className="text-[11.5px] mt-[3px] flex items-center gap-[6px] flex-wrap" style={{ color: "var(--ink-3)" }}>
            Период: {periodLabel}
          </div>
        </div>
        <div className="flex items-center gap-[8px]">
          <button
            onClick={exportCSV}
            className="inline-flex items-center gap-[6px] rounded-[6px] cursor-pointer transition-all"
            style={{
              padding: "6px 11px",
              fontSize: "12px",
              fontWeight: 500,
              border: "1px solid var(--line)",
              background: "transparent",
              color: "var(--ink)",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            Экспорт CSV
          </button>
          <button
            onClick={exportPDF}
            className="inline-flex items-center gap-[6px] rounded-[6px] cursor-pointer transition-all"
            style={{
              padding: "6px 11px",
              fontSize: "12px",
              fontWeight: 500,
              border: "1px solid var(--line)",
              background: "transparent",
              color: "var(--ink)",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            Экспорт PDF
          </button>
        </div>
      </div>

      {/* -- Error ----------------------------------------------------- */}
      {error && (
        <div className="rounded-[9px] p-4" style={{ background: "var(--bad-soft)", border: "1px solid color-mix(in oklab, var(--bad) 30%, transparent)" }}>
          <p className="text-[12.5px]" style={{ color: "var(--bad)" }}>{error}</p>
        </div>
      )}

      {/* -- Period card ----------------------------------------------- */}
      <div className="rounded-[9px] p-[14px]" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
        <div className="flex items-center justify-between gap-[10px] mb-[10px] flex-wrap">
          <div className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>Период</div>
        </div>
        <div className="flex items-center gap-[12px] flex-wrap">
          <div className="flex items-center gap-[8px]">
            <label className="label-mono" style={{ letterSpacing: "0.1em" }}>С</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => { setDateFrom(e.target.value); setQuickPeriod(""); }}
              className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none"
              style={{ background: "var(--bg)", border: "1px solid var(--line)", color: "var(--ink)" }}
            />
          </div>
          <div className="flex items-center gap-[8px]">
            <label className="label-mono" style={{ letterSpacing: "0.1em" }}>По</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => { setDateTo(e.target.value); setQuickPeriod(""); }}
              className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none"
              style={{ background: "var(--bg)", border: "1px solid var(--line)", color: "var(--ink)" }}
            />
          </div>
          <SegmentedControl
            items={[
              { label: "7д", value: "7d" },
              { label: "30д", value: "30d" },
              { label: "90д", value: "90d" },
              { label: "YTD", value: "ytd" },
            ]}
            active={quickPeriod}
            onChange={handleQuickPeriod}
          />
          <button
            onClick={load}
            className="rounded-[6px] text-[11.5px] font-medium text-white border-0 cursor-pointer transition-all"
            style={{ padding: "4px 9px", background: "var(--accent)" }}
            onMouseEnter={(e) => { e.currentTarget.style.filter = "brightness(1.1)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.filter = "none"; }}
          >
            Обновить
          </button>
        </div>
      </div>

      {data && (
        <>
          {/* -- 5 KPI Cards -------------------------------------------- */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-[10px]">
            {/* MESSAGES */}
            <div
              className="rounded-[9px] flex flex-col gap-[4px]"
              style={{ padding: "12px 13px", background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
            >
              <div className="label-mono">СООБЩЕНИЙ</div>
              <div className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em]" style={{ color: "var(--ink)", marginTop: "2px" }}>
                {fmtNum(totals.messages)}
              </div>
              <div className="flex items-center gap-[8px] mono text-[10.5px]">
                <span style={{ color: "var(--ink-3)" }}>вх. + исх.</span>
              </div>
              <Sparkline data={sparkMessages.length > 1 ? sparkMessages : defaultSpark} tone="accent" />
            </div>

            {/* AI CALLS */}
            <div
              className="rounded-[9px] flex flex-col gap-[4px]"
              style={{ padding: "12px 13px", background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
            >
              <div className="label-mono">AI ВЫЗОВОВ</div>
              <div className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em]" style={{ color: "var(--ink)", marginTop: "2px" }}>
                {fmtNum(totals.aiCalls)}
              </div>
              <div className="flex items-center gap-[8px] mono text-[10.5px]">
                <span style={{ color: "var(--ink-3)" }}>
                  {totals.messages > 0 ? `\u2248 ${Math.round((totals.aiCalls / totals.messages) * 100)}% от сообщений` : "\u2014"}
                </span>
              </div>
              <Sparkline data={sparkAI.length > 1 ? sparkAI : defaultSpark} tone="accent" />
            </div>

            {/* ORDERS */}
            <div
              className="rounded-[9px] flex flex-col gap-[4px]"
              style={{ padding: "12px 13px", background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
            >
              <div className="label-mono">ЗАКАЗОВ</div>
              <div className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em]" style={{ color: "var(--ink)", marginTop: "2px" }}>
                {fmtNum(totals.orders)}
              </div>
              <div className="flex items-center gap-[8px] mono text-[10.5px]">
                <span style={{ color: "var(--ink-3)" }}>
                  конв. {totals.messages > 0 ? ((totals.orders / totals.messages) * 100).toFixed(2) : "0"}%
                </span>
              </div>
              <Sparkline data={sparkOrders.length > 1 ? sparkOrders : defaultSpark} tone="accent" />
            </div>

            {/* CONVERSATIONS */}
            <div
              className="rounded-[9px] flex flex-col gap-[4px]"
              style={{ padding: "12px 13px", background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
            >
              <div className="label-mono">ДИАЛОГОВ</div>
              <div className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em]" style={{ color: "var(--ink)", marginTop: "2px" }}>
                {fmtNum(totals.convos)}
              </div>
              <div className="flex items-center gap-[8px] mono text-[10.5px]">
                <span style={{ color: "var(--ink-3)" }}>
                  avg {totals.convos > 0 ? (totals.orders / totals.convos).toFixed(2) : "0"} заказа/диалог
                </span>
              </div>
              <Sparkline data={sparkConvos.length > 1 ? sparkConvos : defaultSpark} tone="accent" />
            </div>

            {/* COST (accent tone) */}
            <div
              className="rounded-[9px] flex flex-col gap-[4px]"
              style={{ padding: "12px 13px", background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
            >
              <div className="label-mono" style={{ color: "var(--accent)" }}>СТОИМОСТЬ</div>
              <div className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em]" style={{ color: "var(--accent)", marginTop: "2px" }}>
                ${totals.cost.toFixed(2)}
              </div>
              <div className="flex items-center gap-[8px] mono text-[10.5px]">
                <span style={{ color: "var(--ink-3)" }}>{fmtNum(totals.tokens)} токенов</span>
              </div>
              <Sparkline data={sparkTokens.length > 1 ? sparkTokens : defaultSpark} tone="accent" />
            </div>
          </div>

          {/* -- Row 2: AI calls chart + Model distribution ------------- */}
          <div className="grid grid-cols-1 md:grid-cols-[1.5fr_1fr] gap-[12px]">
            {/* AI calls chart from daily data */}
            <div
              className="rounded-[9px]"
              style={{ padding: "14px 14px 8px", background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
            >
              <div className="flex items-center justify-between gap-[10px] mb-[10px] flex-wrap">
                <div>
                  <div className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>
                    AI вызовы &middot; {periodDays} дней
                  </div>
                  <div className="mono text-[10.5px] mt-[2px]" style={{ color: "var(--ink-3)", letterSpacing: "0.02em" }}>
                    итого {fmtNum(totals.aiCalls)} &middot; avg {chartAvg}/день
                  </div>
                </div>
              </div>

              {/* Chart body -- compact 90px */}
              {chartBars.length > 0 ? (
                <div
                  className="relative"
                  style={{
                    height: "160px",
                    borderLeft: "1px solid var(--line)",
                    borderBottom: "1px solid var(--line)",
                  }}
                >
                  {/* Bars */}
                  <div className="absolute flex items-end gap-[3px]" style={{ inset: "6px 4px 0 4px" }}>
                    {chartBars.map((v, i) => {
                      const pct = Math.max((v / chartMax) * 100, 1);
                      const d = daily[i];
                      const dayLabel = d ? new Date(d.date).toLocaleDateString("ru-RU", { day: "2-digit", month: "short" }) : "";
                      return (
                        <div
                          key={i}
                          className="flex-1 flex flex-col items-center justify-end gap-[2px] group relative"
                          style={{ height: "100%" }}
                        >
                          {/* Tooltip on hover */}
                          <div className="absolute bottom-full mb-1 hidden group-hover:flex flex-col items-center z-10 pointer-events-none">
                            <div className="rounded-[5px] px-[6px] py-[3px] text-[10px] mono tnum whitespace-nowrap" style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)", boxShadow: "0 4px 12px rgba(0,0,0,0.3)" }}>
                              {d?.date || ""}<br/>{v} вызовов
                            </div>
                          </div>
                          <div
                            className="w-full transition-all duration-150 group-hover:opacity-100"
                            style={{
                              height: `${pct}%`,
                              minHeight: "2px",
                              background: "var(--accent)",
                              opacity: 0.6,
                              borderRadius: "2px 2px 0 0",
                            }}
                          />
                          {i % 5 === 0 && (
                            <span className="absolute mono text-[8px]" style={{ bottom: "-16px", color: "var(--ink-4)" }}>{dayLabel}</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center mono text-[11px]" style={{ height: "160px", color: "var(--ink-4)" }}>
                  нет данных
                </div>
              )}
            </div>

            {/* Model distribution — real data from /platform/billing/models */}
            <div
              className="rounded-[9px]"
              style={{ padding: "14px", background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
            >
              <div className="flex items-center justify-between gap-[10px] mb-[10px] flex-wrap">
                <div className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>
                  Распределение по моделям
                </div>
              </div>

              <div className="flex flex-col gap-[6px]">
                {modelItems.length > 0 ? (
                  modelItems.map((m) => {
                    const totalModelCalls = models.reduce((s, x) => s + x.calls, 0);
                    return (
                      <div
                        key={m.model}
                        className="grid items-center gap-[8px]"
                        style={{ gridTemplateColumns: "100px 1fr 50px 60px", fontSize: "11.5px" }}
                      >
                        {/* Model chip */}
                        <span
                          className="inline-flex items-center rounded-full mono text-[10.5px] font-medium"
                          style={{
                            padding: "2px 8px",
                            lineHeight: "1.4",
                            background: `var(--${m.tone}-soft)`,
                            color: `var(--${m.tone})`,
                            border: `1px solid color-mix(in oklab, var(--${m.tone}) 30%, transparent)`,
                          }}
                        >
                          {m.model}
                        </span>
                        {/* Progress bar */}
                        <div
                          style={{
                            height: "6px",
                            background: "var(--bg-2)",
                            borderRadius: "3px",
                            overflow: "hidden",
                          }}
                        >
                          <div
                            style={{
                              height: "100%",
                              width: `${totalModelCalls > 0 ? (m.calls / totalModelCalls) * 100 : 0}%`,
                              background: `var(--${m.tone})`,
                              borderRadius: "3px",
                            }}
                          />
                        </div>
                        {/* Count */}
                        <span className="tnum text-right" style={{ color: "var(--ink)" }}>
                          {fmtNum(m.calls)}
                        </span>
                        {/* Cost */}
                        <span className="tnum text-right" style={{ color: getDeltaColor(m.cost_usd, "cost") }}>
                          ${m.cost_usd.toFixed(3)}
                        </span>
                      </div>
                    );
                  })
                ) : (
                  <div className="mono text-[11px] py-4 text-center" style={{ color: "var(--ink-4)" }}>
                    нет данных
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* -- Table: Usage by tenants -------------------------------- */}
          <div
            className="rounded-[9px] overflow-hidden"
            style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)", padding: 0 }}
          >
            <div className="flex items-center justify-between gap-[10px] flex-wrap" style={{ padding: "13px 14px 10px" }}>
              <div className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>
                Использование по тенантам
              </div>
              <a
                href="/platform-tenants"
                className="mono text-[11px] transition-colors"
                style={{
                  color: "var(--accent)",
                  textDecoration: "none",
                  borderBottom: "1px dotted color-mix(in oklab, var(--accent) 40%, transparent)",
                }}
              >
                все &rarr;
              </a>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full" style={{ borderCollapse: "collapse", fontSize: "12.5px" }}>
                <thead>
                  <tr>
                    <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>ТЕНАНТ</th>
                    <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>СООБЩЕНИЯ</th>
                    <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>AI ВЫЗОВЫ</th>
                    <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>ЗАКАЗЫ</th>
                    <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>ДИАЛОГИ</th>
                    <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)", color: "var(--ink-3)" }}>ТОКЕНЫ</th>
                    <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)", color: "var(--accent)" }}>СТОИМОСТЬ</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((row, idx) => {
                    const initials = toInitials(row.tenant_name);
                    const slug = toSlug(row.tenant_name);
                    return (
                      <tr
                        key={row.tenant_id}
                        className="transition-colors"
                        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                      >
                        {/* Identity column: avatar + name + slug */}
                        <td className="py-[10px] px-[12px]" style={{ borderBottom: idx < data.length - 1 ? "1px solid var(--hair)" : "none", verticalAlign: "middle" }}>
                          <div className="flex items-center gap-[10px] min-w-0">
                            <span
                              className="inline-grid place-items-center flex-shrink-0"
                              style={{
                                width: "28px",
                                height: "28px",
                                borderRadius: "6px",
                                background: "var(--accent-soft)",
                                color: "var(--accent)",
                                fontSize: "10.5px",
                                fontWeight: 600,
                              }}
                            >
                              {initials}
                            </span>
                            <div className="min-w-0">
                              <div className="text-[12.5px] overflow-hidden text-ellipsis whitespace-nowrap" style={{ color: "var(--ink)", maxWidth: "240px" }}>
                                {row.tenant_name}
                              </div>
                              <div className="mono text-[10.5px]" style={{ color: "var(--ink-3)", marginTop: "1px" }}>
                                {slug}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="py-[10px] px-[12px] text-right mono tnum" style={{ borderBottom: idx < data.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--ink-2)" }}>
                          {fmtNum(row.messages_count)}
                        </td>
                        <td className="py-[10px] px-[12px] text-right mono tnum" style={{ borderBottom: idx < data.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--ink-2)" }}>
                          {fmtNum(row.ai_calls_count)}
                        </td>
                        <td className="py-[10px] px-[12px] text-right mono tnum" style={{ borderBottom: idx < data.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--ink-2)" }}>
                          {row.orders_count}
                        </td>
                        <td className="py-[10px] px-[12px] text-right mono tnum" style={{ borderBottom: idx < data.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--ink-2)" }}>
                          {row.conversations_count}
                        </td>
                        <td className="py-[10px] px-[12px] text-right mono tnum" style={{ borderBottom: idx < data.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--ink-3)" }}>
                          {fmtNum(row.tokens_total)}
                        </td>
                        <td className="py-[10px] px-[12px] text-right mono tnum font-semibold" style={{ borderBottom: idx < data.length - 1 ? "1px solid var(--hair)" : "none", color: "var(--accent)" }}>
                          ${row.estimated_cost_usd.toFixed(4)}
                        </td>
                      </tr>
                    );
                  })}
                  {data.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-[12px] py-[40px] text-center text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                        Нет данных за выбранный период
                      </td>
                    </tr>
                  )}
                </tbody>
                {/* Footer totals */}
                {data.length > 0 && (
                  <tfoot>
                    <tr>
                      <td className="py-[10px] px-[12px] font-semibold text-[12px]" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)", color: "var(--ink)" }}>
                        Всего
                      </td>
                      <td className="py-[10px] px-[12px] text-right mono tnum font-semibold text-[12px]" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)", color: "var(--ink)" }}>
                        {fmtNum(totals.messages)}
                      </td>
                      <td className="py-[10px] px-[12px] text-right mono tnum font-semibold text-[12px]" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)", color: "var(--ink)" }}>
                        {fmtNum(totals.aiCalls)}
                      </td>
                      <td className="py-[10px] px-[12px] text-right mono tnum font-semibold text-[12px]" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)", color: "var(--ink)" }}>
                        {totals.orders}
                      </td>
                      <td className="py-[10px] px-[12px] text-right mono tnum font-semibold text-[12px]" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)", color: "var(--ink)" }}>
                        {totals.convos}
                      </td>
                      <td className="py-[10px] px-[12px] text-right mono tnum font-semibold text-[12px]" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)", color: "var(--ink)" }}>
                        {fmtNum(totals.tokens)}
                      </td>
                      <td className="py-[10px] px-[12px] text-right mono tnum font-semibold text-[12px]" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)", color: "var(--accent)" }}>
                        ${totals.cost.toFixed(4)}
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
