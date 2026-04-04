"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

// ── Types ──────────────────────────────────────────────────────────────

interface RFMSummary {
  segments: Record<string, number>;
  total_customers: number;
  top_customers: CustomerSegment[];
}

interface CustomerSegment {
  lead_id: string;
  customer_name: string | null;
  telegram_user_id: number;
  recency_days: number;
  frequency: number;
  monetary: number;
  r_score: number;
  f_score: number;
  m_score: number;
  rfm_score: number;
  segment: string;
}

interface ConversationAnalytics {
  period_days: number;
  avg_response_time_seconds: number | null;
  median_response_time_seconds: number | null;
  resolution_rate_pct: number;
  handoff_rate_pct: number;
  total_conversations: number;
  messages_by_sender: Record<string, number>;
  daily_trend: Array<{ date: string; conversations: number; resolved: number }>;
}

interface FunnelStage {
  name: string;
  label: string;
  count: number;
  pct: number;
}

interface FunnelResponse {
  period_days: number;
  stages: FunnelStage[];
}

interface StockForecastItem {
  variant_id: string;
  variant_title: string;
  product_name: string;
  available_stock: number;
  avg_daily_sales: number;
  days_until_stockout: number | null;
  forecasted_demand: number;
  risk: string;
}

interface StockForecast {
  forecast_days: number;
  items: StockForecastItem[];
  risk_summary: Record<string, number>;
}

interface CompetitorPrice {
  id: string;
  product_id: string | null;
  competitor_name: string;
  competitor_channel: string | null;
  product_title: string;
  competitor_price: number;
  our_price: number | null;
  currency: string;
  source: string;
  captured_at: string;
}

interface RevenueData {
  days: number;
  daily: Array<{ date: string; orders: number; revenue: number }>;
  total_revenue: number;
  total_orders: number;
}

interface CompetitorSummary {
  competitor_name: string;
  products_tracked: number;
  avg_price_diff_pct: number | null;
  cheaper_count: number;
  more_expensive_count: number;
}

// ── Helpers ────────────────────────────────────────────────────────────

function fmt(n: number) {
  return n.toLocaleString("ru-RU");
}

function fmtTime(seconds: number | null): string {
  if (seconds == null) return "--";
  if (seconds < 60) return `${Math.round(seconds)}с`;
  return `${Math.round(seconds / 60)}мин`;
}

const segmentConfig: Record<string, { label: string; color: string; bg: string }> = {
  vip: { label: "VIP", color: "text-amber-700", bg: "bg-amber-50" },
  loyal: { label: "Лояльный", color: "text-emerald-700", bg: "bg-emerald-50" },
  promising: { label: "Перспективный", color: "text-indigo-700", bg: "bg-indigo-50" },
  new: { label: "Новый", color: "text-cyan-700", bg: "bg-cyan-50" },
  at_risk: { label: "Под угрозой", color: "text-orange-700", bg: "bg-orange-50" },
  lost: { label: "Потерян", color: "text-rose-700", bg: "bg-rose-50" },
  regular: { label: "Обычный", color: "text-slate-700", bg: "bg-slate-50" },
};

const riskConfig: Record<string, { label: string; color: string; bg: string }> = {
  critical: { label: "Критично", color: "text-rose-700", bg: "bg-rose-50" },
  warning: { label: "Внимание", color: "text-amber-700", bg: "bg-amber-50" },
  watch: { label: "Наблюдение", color: "text-blue-700", bg: "bg-blue-50" },
  ok: { label: "Ок", color: "text-emerald-700", bg: "bg-emerald-50" },
};

const tabs = [
  { key: "overview", label: "Обзор" },
  { key: "customers", label: "Клиенты" },
  { key: "conversations", label: "Диалоги" },
  { key: "funnel", label: "Воронка" },
  { key: "stock", label: "Склад" },
  { key: "competitors", label: "Конкуренты" },
];

// ── Main Component ────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [tab, setTab] = useState("overview");
  const [days, setDays] = useState(30);
  const { toast } = useToast();

  // Data states
  const [rfm, setRfm] = useState<RFMSummary | null>(null);
  const [convAnalytics, setConvAnalytics] = useState<ConversationAnalytics | null>(null);
  const [funnel, setFunnel] = useState<FunnelResponse | null>(null);
  const [stock, setStock] = useState<StockForecast | null>(null);
  const [revenue, setRevenue] = useState<RevenueData | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorPrice[]>([]);
  const [competitorSummary, setCompetitorSummary] = useState<CompetitorSummary[]>([]);
  const [computing, setComputing] = useState(false);

  // Sorting
  const [stockSort, setStockSort] = useState<{ col: string; asc: boolean }>({ col: "days_until_stockout", asc: true });
  const [custSort, setCustSort] = useState<{ col: string; asc: boolean }>({ col: "monetary", asc: false });

  // Competitor form
  const [showCompForm, setShowCompForm] = useState(false);
  const [compForm, setCompForm] = useState({
    competitor_name: "",
    product_title: "",
    competitor_price: "",
    our_price: "",
    competitor_channel: "",
  });

  const loadAll = useCallback(() => {
    api.get<RFMSummary>("/analytics/rfm/segments").then(setRfm).catch(() => {});
    api.get<ConversationAnalytics>(`/analytics/conversations?days=${days}`).then(setConvAnalytics).catch(() => {});
    api.get<FunnelResponse>(`/analytics/funnel?days=${days}`).then(setFunnel).catch(() => {});
    api.get<StockForecast>("/analytics/stock-forecast?forecast_days=14").then(setStock).catch(() => {});
    api.get<RevenueData>(`/analytics/revenue?days=${days}`).then(setRevenue).catch(() => {});
    api.get<CompetitorPrice[]>("/analytics/competitors").then(setCompetitors).catch(() => {});
    api.get<CompetitorSummary[]>("/analytics/competitors/summary").then(setCompetitorSummary).catch(() => {});
  }, [days]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const computeRFM = async () => {
    setComputing(true);
    try {
      const r = await api.post<{ computed: number }>("/analytics/rfm/compute", {});
      toast(`RFM пересчитан: ${r.computed} клиентов`, "success");
      api.get<RFMSummary>("/analytics/rfm/segments").then(setRfm);
    } catch {
      toast("Ошибка вычисления RFM", "error");
    } finally {
      setComputing(false);
    }
  };

  const addCompetitorPrice = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/analytics/competitors", {
        competitor_name: compForm.competitor_name,
        product_title: compForm.product_title,
        competitor_price: parseFloat(compForm.competitor_price),
        our_price: compForm.our_price ? parseFloat(compForm.our_price) : null,
        competitor_channel: compForm.competitor_channel || null,
      });
      toast("Цена конкурента добавлена", "success");
      setShowCompForm(false);
      setCompForm({ competitor_name: "", product_title: "", competitor_price: "", our_price: "", competitor_channel: "" });
      api.get<CompetitorPrice[]>("/analytics/competitors").then(setCompetitors);
      api.get<CompetitorSummary[]>("/analytics/competitors/summary").then(setCompetitorSummary);
    } catch {
      toast("Ошибка добавления", "error");
    }
  };

  const deleteCompetitor = async (id: string) => {
    await api.delete(`/analytics/competitors/${id}`);
    setCompetitors((prev) => prev.filter((c) => c.id !== id));
  };

  // ── Tab: Overview ──

  const renderOverview = () => (
    <div className="space-y-6">
      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card p-4">
          <p className="text-xs text-slate-500">Среднее время ответа</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{fmtTime(convAnalytics?.avg_response_time_seconds ?? null)}</p>
        </div>
        <div className="card p-4">
          <p className="text-xs text-slate-500">Конверсия</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{convAnalytics?.resolution_rate_pct ?? 0}%</p>
        </div>
        <div className="card p-4">
          <p className="text-xs text-slate-500">Handoff</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{convAnalytics?.handoff_rate_pct ?? 0}%</p>
        </div>
        <div className="card p-4">
          <p className="text-xs text-slate-500">VIP клиентов</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{rfm?.segments?.vip ?? 0}</p>
        </div>
      </div>

      {/* Mini funnel + segments */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Funnel mini */}
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-900 mb-3">Воронка (30 дней)</h3>
          <div className="space-y-2">
            {(funnel?.stages || []).map((s, i) => (
              <div key={s.name} className="flex items-center gap-3">
                <span className="text-xs text-slate-500 w-24 shrink-0">{s.label}</span>
                <div className="flex-1 bg-slate-100 rounded-full h-5 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-indigo-500 to-indigo-400 rounded-full transition-all"
                    style={{ width: `${s.pct}%` }}
                  />
                </div>
                <span className="text-xs font-medium w-12 text-right">{s.count}</span>
                <span className="text-xs text-slate-400 w-10 text-right">{s.pct}%</span>
              </div>
            ))}
          </div>
        </div>

        {/* Segments overview */}
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-900 mb-3">Сегменты клиентов</h3>
          {rfm && rfm.total_customers > 0 ? (
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(rfm.segments).sort((a, b) => b[1] - a[1]).map(([seg, count]) => {
                const cfg = segmentConfig[seg] || segmentConfig.regular;
                return (
                  <div key={seg} className={`${cfg.bg} rounded-lg px-3 py-2`}>
                    <p className={`text-lg font-bold ${cfg.color}`}>{count}</p>
                    <p className="text-xs text-slate-500">{cfg.label}</p>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-slate-400">Нажмите &quot;Пересчитать RFM&quot; во вкладке Клиенты</p>
          )}
        </div>
      </div>

      {/* Revenue chart */}
      {revenue && revenue.daily.length > 0 && (
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-sm font-bold text-slate-900">Выручка по дням</h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Итого: {fmt(revenue.total_revenue)} UZS за {revenue.total_orders} заказов
              </p>
            </div>
            <button onClick={exportRevenue} className="text-xs text-indigo-600 hover:text-indigo-700 transition-colors">
              Экспорт CSV
            </button>
          </div>
          <RevenueBarChart data={revenue.daily} />
        </div>
      )}

      {/* Stock alerts */}
      {stock && (stock.risk_summary.critical > 0 || stock.risk_summary.warning > 0) && (
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-900 mb-3">Предупреждения по складу</h3>
          <div className="space-y-2">
            {stock.items.filter((i) => i.risk === "critical" || i.risk === "warning").slice(0, 5).map((item) => (
              <div key={item.variant_id} className="flex items-center gap-3">
                <span className={`px-2 py-0.5 rounded text-xs ${riskConfig[item.risk].bg} ${riskConfig[item.risk].color}`}>
                  {riskConfig[item.risk].label}
                </span>
                <span className="text-sm text-slate-900">{item.product_name} — {item.variant_title}</span>
                <span className="text-xs text-slate-400 ml-auto">
                  {item.available_stock} шт, ~{item.days_until_stockout ?? "?"} дней
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  // ── Tab: Customers ──

  const renderCustomers = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button
          onClick={computeRFM}
          disabled={computing}
          className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
        >
          {computing ? "Вычисление..." : "Пересчитать RFM"}
        </button>
        <span className="text-sm text-slate-400">
          {rfm ? `${rfm.total_customers} клиентов` : "Данных нет"}
        </span>
      </div>

      {/* Segment cards */}
      {rfm && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(segmentConfig).map(([seg, cfg]) => (
            <div key={seg} className={`${cfg.bg} rounded-xl px-4 py-3`}>
              <p className={`text-2xl font-bold ${cfg.color}`}>{rfm.segments[seg] || 0}</p>
              <p className="text-xs text-slate-500 mt-0.5">{cfg.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Top customers table */}
      {rfm && rfm.top_customers.length > 0 && (
        <div className="card overflow-x-auto">
          <div className="flex items-center justify-between px-4 pt-3">
            <span className="text-xs text-slate-400">{rfm.top_customers.length} клиентов</span>
            <button onClick={exportCustomers} className="text-xs text-indigo-600 hover:text-indigo-700 transition-colors">Экспорт CSV</button>
          </div>
          <table className="w-full text-sm min-w-[640px]">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="px-4 py-3 text-slate-500 font-medium">Клиент</th>
                <th className="px-4 py-3 text-slate-500 font-medium">Сегмент</th>
                {[
                  { col: "frequency", label: "Заказов" },
                  { col: "monetary", label: "Потрачено" },
                  { col: "recency_days", label: "Последний" },
                  { col: "rfm_score", label: "RFM" },
                ].map((h) => (
                  <th
                    key={h.col}
                    className="px-4 py-3 text-slate-500 font-medium cursor-pointer hover:text-indigo-600 select-none transition-colors"
                    onClick={() => setCustSort((s) => ({ col: h.col, asc: s.col === h.col ? !s.asc : false }))}
                  >
                    {h.label} {custSort.col === h.col ? (custSort.asc ? "↑" : "↓") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rfm.top_customers.slice().sort((a, b) => {
                const k = custSort.col as keyof CustomerSegment;
                const av = Number(a[k]) || 0;
                const bv = Number(b[k]) || 0;
                return custSort.asc ? av - bv : bv - av;
              }).map((c) => {
                const cfg = segmentConfig[c.segment] || segmentConfig.regular;
                return (
                  <tr key={c.lead_id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-medium text-slate-900">{c.customer_name || "Без имени"}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${cfg.bg} ${cfg.color}`}>{cfg.label}</span>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{c.frequency}</td>
                    <td className="px-4 py-3 text-slate-700">{fmt(Number(c.monetary))} UZS</td>
                    <td className="px-4 py-3 text-slate-400">{c.recency_days} дн. назад</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">{c.rfm_score}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  // ── Tab: Conversations ──

  const renderConversations = () => {
    const ca = convAnalytics;
    const totalMsgs = ca ? Object.values(ca.messages_by_sender).reduce((s, v) => s + v, 0) : 0;

    return (
      <div className="space-y-4">
        {/* Metric cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="card p-4">
            <p className="text-xs text-slate-500">Среднее время ответа</p>
            <p className="text-2xl font-bold text-slate-900 mt-1">{fmtTime(ca?.avg_response_time_seconds ?? null)}</p>
          </div>
          <div className="card p-4">
            <p className="text-xs text-slate-500">Медиана ответа</p>
            <p className="text-2xl font-bold text-slate-900 mt-1">{fmtTime(ca?.median_response_time_seconds ?? null)}</p>
          </div>
          <div className="card p-4">
            <p className="text-xs text-slate-500">Конверсия</p>
            <p className="text-2xl font-bold mt-1 text-emerald-600">{ca?.resolution_rate_pct ?? 0}%</p>
          </div>
          <div className="card p-4">
            <p className="text-xs text-slate-500">Handoff</p>
            <p className="text-2xl font-bold mt-1 text-orange-600">{ca?.handoff_rate_pct ?? 0}%</p>
          </div>
        </div>

        {/* Messages by sender */}
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-900 mb-3">Сообщения по типу ({fmt(totalMsgs)} всего)</h3>
          <div className="space-y-2">
            {ca && Object.entries(ca.messages_by_sender).sort((a, b) => b[1] - a[1]).map(([type, count]) => {
              const pct = totalMsgs > 0 ? (count / totalMsgs * 100) : 0;
              const colors: Record<string, string> = {
                ai: "bg-indigo-500", customer: "bg-emerald-500", human_admin: "bg-violet-500", system: "bg-slate-400",
              };
              const labels: Record<string, string> = {
                ai: "AI", customer: "Клиент", human_admin: "Оператор", system: "Система",
              };
              return (
                <div key={type} className="flex items-center gap-3">
                  <span className="text-xs text-slate-500 w-20 shrink-0">{labels[type] || type}</span>
                  <div className="flex-1 bg-slate-100 rounded-full h-4 overflow-hidden">
                    <div className={`h-full ${colors[type] || "bg-slate-300"} rounded-full`} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-xs font-medium w-16 text-right">{fmt(count)}</span>
                  <span className="text-xs text-slate-400 w-12 text-right">{pct.toFixed(1)}%</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Daily trend chart (SVG) */}
        {ca && ca.daily_trend.length > 0 && (
          <div className="card p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold text-slate-900">Диалоги за {days} дней</h3>
              <button onClick={exportConversations} className="text-xs text-indigo-600 hover:text-indigo-700 transition-colors">
                Экспорт CSV
              </button>
            </div>
            <MiniLineChart data={ca.daily_trend} />
          </div>
        )}
      </div>
    );
  };

  // ── Tab: Funnel ──

  const renderFunnel = () => {
    const stages = funnel?.stages || [];
    const maxCount = stages.length > 0 ? stages[0].count : 1;
    const funnelColors = [
      "bg-gradient-to-r from-indigo-600 to-indigo-500",
      "bg-gradient-to-r from-indigo-500 to-indigo-400",
      "bg-gradient-to-r from-violet-500 to-violet-400",
      "bg-gradient-to-r from-violet-500 to-violet-400",
      "bg-gradient-to-r from-emerald-500 to-emerald-400",
      "bg-gradient-to-r from-emerald-600 to-emerald-500",
    ];

    return (
      <div className="card p-6">
        <h3 className="text-lg font-bold text-slate-900 mb-6">Воронка конверсии ({days} дней)</h3>
        <div className="space-y-3 max-w-2xl mx-auto">
          {stages.map((s, i) => {
            const widthPct = maxCount > 0 ? Math.max(s.count / maxCount * 100, 4) : 4;
            const dropoff = i > 0 && stages[i - 1].count > 0
              ? Math.round((1 - s.count / stages[i - 1].count) * 100)
              : 0;
            return (
              <div key={s.name}>
                {i > 0 && dropoff > 0 && (
                  <div className="text-center text-xs text-rose-400 py-1">
                    -{dropoff}% отсев
                  </div>
                )}
                <div className="flex items-center gap-4">
                  <span className="text-sm text-slate-600 w-28 shrink-0 text-right">{s.label}</span>
                  <div className="flex-1">
                    <div
                      className={`${funnelColors[i] || "bg-gradient-to-r from-indigo-500 to-indigo-400"} h-10 rounded-lg flex items-center px-3 transition-all`}
                      style={{ width: `${widthPct}%` }}
                    >
                      <span className="text-white text-sm font-bold">{fmt(s.count)}</span>
                    </div>
                  </div>
                  <span className="text-sm text-slate-400 w-12 text-right">{s.pct}%</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  // ── Tab: Stock ──

  const renderStock = () => (
    <div className="space-y-4">
      {/* Risk summary */}
      {stock && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {(["critical", "warning", "watch", "ok"] as const).map((risk) => {
            const cfg = riskConfig[risk];
            return (
              <div key={risk} className={`${cfg.bg} rounded-xl px-4 py-3`}>
                <p className={`text-2xl font-bold ${cfg.color}`}>{stock.risk_summary[risk] || 0}</p>
                <p className="text-xs text-slate-500 mt-0.5">{cfg.label}</p>
              </div>
            );
          })}
        </div>
      )}

      {/* Stock table */}
      <div className="card overflow-x-auto">
        <div className="flex items-center justify-between px-4 pt-3">
          <span className="text-xs text-slate-400">{stock?.items.length ?? 0} вариантов</span>
          <button onClick={exportStock} className="text-xs text-indigo-600 hover:text-indigo-700 transition-colors">Экспорт CSV</button>
        </div>
        <table className="w-full text-sm min-w-[700px]">
          <thead className="bg-slate-50 text-left">
            <tr>
              <th className="px-4 py-3 text-slate-500 font-medium">Товар</th>
              <th className="px-4 py-3 text-slate-500 font-medium">Вариант</th>
              {[
                { col: "available_stock", label: "Остаток" },
                { col: "avg_daily_sales", label: "Продаж/день" },
                { col: "days_until_stockout", label: "До стокаута" },
                { col: "forecasted_demand", label: "Прогноз (14д)" },
              ].map((h) => (
                <th
                  key={h.col}
                  className="px-4 py-3 text-slate-500 font-medium cursor-pointer hover:text-indigo-600 select-none transition-colors"
                  onClick={() => setStockSort((s) => ({ col: h.col, asc: s.col === h.col ? !s.asc : true }))}
                >
                  {h.label} {stockSort.col === h.col ? (stockSort.asc ? "↑" : "↓") : ""}
                </th>
              ))}
              <th className="px-4 py-3 text-slate-500 font-medium">Риск</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {(stock?.items || []).slice().sort((a, b) => {
              const k = stockSort.col as keyof StockForecastItem;
              const av = a[k] ?? 9999;
              const bv = b[k] ?? 9999;
              return stockSort.asc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
            }).map((item) => {
              const cfg = riskConfig[item.risk] || riskConfig.ok;
              return (
                <tr key={item.variant_id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-900">{item.product_name}</td>
                  <td className="px-4 py-3 text-slate-600">{item.variant_title}</td>
                  <td className="px-4 py-3 text-slate-700">{item.available_stock} шт</td>
                  <td className="px-4 py-3 text-slate-700">{item.avg_daily_sales}</td>
                  <td className="px-4 py-3 font-medium text-slate-900">
                    {item.days_until_stockout != null ? `${item.days_until_stockout} дн.` : "--"}
                  </td>
                  <td className="px-4 py-3 text-slate-700">{item.forecasted_demand} шт</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs ${cfg.bg} ${cfg.color}`}>{cfg.label}</span>
                  </td>
                </tr>
              );
            })}
            {(!stock || stock.items.length === 0) && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-400">Нет данных по продажам</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );

  // ── Tab: Competitors ──

  const renderCompetitors = () => (
    <div className="space-y-4">
      {/* Summary cards */}
      {competitorSummary.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {competitorSummary.map((cs) => (
            <div key={cs.competitor_name} className="card p-4">
              <p className="font-bold text-sm text-slate-900">{cs.competitor_name}</p>
              <p className="text-xs text-slate-500 mt-1">{cs.products_tracked} товаров</p>
              <div className="flex gap-4 mt-2">
                <div>
                  <p className="text-xs text-emerald-600">{cs.cheaper_count} дешевле</p>
                </div>
                <div>
                  <p className="text-xs text-rose-600">{cs.more_expensive_count} дороже</p>
                </div>
                {cs.avg_price_diff_pct != null && (
                  <div>
                    <p className={`text-xs ${cs.avg_price_diff_pct > 0 ? "text-emerald-600" : "text-rose-600"}`}>
                      {cs.avg_price_diff_pct > 0 ? "+" : ""}{cs.avg_price_diff_pct.toFixed(1)}%
                    </p>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add button + form */}
      <button
        onClick={() => setShowCompForm(!showCompForm)}
        className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
      >
        + Добавить цену
      </button>

      {showCompForm && (
        <form onSubmit={addCompetitorPrice} className="card p-5 space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Новая цена конкурента</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input
              type="text"
              placeholder="Название конкурента"
              value={compForm.competitor_name}
              onChange={(e) => setCompForm({ ...compForm, competitor_name: e.target.value })}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              required
              maxLength={255}
            />
            <input
              type="text"
              placeholder="@channel (опционально)"
              value={compForm.competitor_channel}
              onChange={(e) => setCompForm({ ...compForm, competitor_channel: e.target.value })}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              maxLength={255}
            />
            <input
              type="text"
              placeholder="Название товара у конкурента"
              value={compForm.product_title}
              onChange={(e) => setCompForm({ ...compForm, product_title: e.target.value })}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              required
              maxLength={500}
            />
            <input
              type="number"
              placeholder="Цена конкурента"
              value={compForm.competitor_price}
              onChange={(e) => setCompForm({ ...compForm, competitor_price: e.target.value })}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              required
              min={0}
              step="any"
            />
            <input
              type="number"
              placeholder="Наша цена (опционально)"
              value={compForm.our_price}
              onChange={(e) => setCompForm({ ...compForm, our_price: e.target.value })}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              min={0}
              step="any"
            />
          </div>
          <div className="flex gap-2">
            <button type="submit" className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors">Добавить</button>
            <button type="button" onClick={() => setShowCompForm(false)} className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium transition-colors">Отмена</button>
          </div>
        </form>
      )}

      {/* Competitor prices table */}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-slate-50 text-left">
            <tr>
              <th className="px-4 py-3 text-slate-500 font-medium">Конкурент</th>
              <th className="px-4 py-3 text-slate-500 font-medium">Товар</th>
              <th className="px-4 py-3 text-slate-500 font-medium">Их цена</th>
              <th className="px-4 py-3 text-slate-500 font-medium">Наша цена</th>
              <th className="px-4 py-3 text-slate-500 font-medium">Разница</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {competitors.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">Нет данных по конкурентам</td></tr>
            ) : competitors.map((c) => {
              const diff = c.our_price ? ((c.competitor_price - c.our_price) / c.our_price * 100) : null;
              return (
                <tr key={c.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{c.competitor_name}</div>
                    {c.competitor_channel && <div className="text-xs text-indigo-600">{c.competitor_channel}</div>}
                  </td>
                  <td className="px-4 py-3 text-slate-700">{c.product_title}</td>
                  <td className="px-4 py-3 text-slate-700">{fmt(Number(c.competitor_price))} {c.currency}</td>
                  <td className="px-4 py-3 text-slate-700">{c.our_price ? `${fmt(Number(c.our_price))} ${c.currency}` : "--"}</td>
                  <td className="px-4 py-3">
                    {diff != null && (
                      <span className={diff > 0 ? "text-emerald-600" : "text-rose-600"}>
                        {diff > 0 ? "+" : ""}{diff.toFixed(1)}%
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => deleteCompetitor(c.id)}
                      className="text-rose-400 hover:text-rose-600 text-xs transition-colors"
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );

  const exportCSV = (filename: string, headers: string[], rows: string[][]) => {
    const bom = "\uFEFF";
    const csv = bom + [headers.join(";"), ...rows.map((r) => r.join(";"))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  };

  const exportRevenue = () => {
    if (!revenue) return;
    exportCSV("revenue.csv", ["Дата", "Заказов", "Выручка"], revenue.daily.map((r) => [r.date, String(r.orders), String(r.revenue)]));
  };

  const exportConversations = () => {
    if (!convAnalytics) return;
    exportCSV("conversations.csv", ["Дата", "Диалогов", "Конвертировано"], convAnalytics.daily_trend.map((d) => [d.date, String(d.conversations), String(d.resolved)]));
  };

  const exportStock = () => {
    if (!stock) return;
    exportCSV("stock.csv", ["Товар", "Вариант", "Остаток", "Продаж/день", "До стокаута", "Прогноз", "Риск"],
      stock.items.map((i) => [i.product_name, i.variant_title, String(i.available_stock), String(i.avg_daily_sales), String(i.days_until_stockout ?? ""), String(i.forecasted_demand), i.risk]));
  };

  const exportCustomers = () => {
    if (!rfm) return;
    exportCSV("customers.csv", ["Клиент", "Сегмент", "Заказов", "Потрачено", "Дней назад", "RFM"],
      rfm.top_customers.map((c) => [c.customer_name || "", c.segment, String(c.frequency), String(c.monetary), String(c.recency_days), String(c.rfm_score)]));
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Аналитика</h1>
          <p className="text-sm text-slate-500 mt-1">Клиенты, конверсия, склад и конкуренты</p>
        </div>
        {/* Date range picker */}
        <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-0.5">
          {[7, 14, 30, 60, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                days === d ? "bg-white shadow-sm text-indigo-700" : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {d}д
            </button>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 mb-6 bg-slate-100 rounded-xl p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === t.key ? "bg-white shadow-sm text-slate-900" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === "overview" && renderOverview()}
      {tab === "customers" && renderCustomers()}
      {tab === "conversations" && renderConversations()}
      {tab === "funnel" && renderFunnel()}
      {tab === "stock" && renderStock()}
      {tab === "competitors" && renderCompetitors()}
    </div>
  );
}


// ── SVG Mini Line Chart with Tooltips ────────────────────────────────

function MiniLineChart({ data }: { data: Array<{ date: string; conversations: number; resolved: number }> }) {
  const [hover, setHover] = useState<number | null>(null);
  if (data.length === 0) return null;

  const W = 600;
  const H = 140;
  const PAD = 25;

  const maxVal = Math.max(...data.map((d) => d.conversations), 1);

  const toX = (i: number) => PAD + (i / Math.max(data.length - 1, 1)) * (W - 2 * PAD);
  const toY = (v: number) => H - PAD - (v / maxVal) * (H - 2 * PAD);

  const convPoints = data.map((d, i) => `${toX(i)},${toY(d.conversations)}`).join(" ");
  const resolvedPoints = data.map((d, i) => `${toX(i)},${toY(d.resolved)}`).join(" ");

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-36" preserveAspectRatio="none"
        onMouseLeave={() => setHover(null)}
      >
        <polyline points={convPoints} fill="none" stroke="#6366f1" strokeWidth="2" />
        <polyline points={resolvedPoints} fill="none" stroke="#8b5cf6" strokeWidth="2" strokeDasharray="4 2" />
        {/* Hover targets */}
        {data.map((d, i) => (
          <g key={i} onMouseEnter={() => setHover(i)}>
            <rect x={toX(i) - 8} y={0} width={16} height={H} fill="transparent" />
            {hover === i && (
              <>
                <line x1={toX(i)} y1={PAD} x2={toX(i)} y2={H - PAD} stroke="#94a3b8" strokeWidth="1" strokeDasharray="3 3" />
                <circle cx={toX(i)} cy={toY(d.conversations)} r="4" fill="#6366f1" />
                <circle cx={toX(i)} cy={toY(d.resolved)} r="4" fill="#8b5cf6" />
                <rect x={toX(i) - 55} y={4} width={110} height={32} rx={6} fill="white" stroke="#e2e8f0" />
                <text x={toX(i)} y={16} textAnchor="middle" className="text-[9px] fill-slate-500">{d.date.slice(5)}</text>
                <text x={toX(i)} y={30} textAnchor="middle" className="text-[9px] fill-indigo-600 font-medium">{d.conversations} диал. / {d.resolved} конв.</text>
              </>
            )}
          </g>
        ))}
      </svg>
      <div className="flex gap-4 mt-1 text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-indigo-500 inline-block" /> Диалоги
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-violet-500 inline-block border-dashed" /> Конвертировано
        </span>
      </div>
    </div>
  );
}


// ── Revenue Bar Chart with Tooltips ──────────────────────────────────

function RevenueBarChart({ data }: { data: Array<{ date: string; orders: number; revenue: number }> }) {
  const [hover, setHover] = useState<number | null>(null);
  if (data.length === 0) return null;

  const W = 600;
  const H = 160;
  const PAD = 30;
  const maxRev = Math.max(...data.map((d) => d.revenue), 1);
  const barW = Math.max(2, (W - 2 * PAD) / data.length - 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-44" onMouseLeave={() => setHover(null)}>
      {/* Y-axis labels */}
      {[0, 0.5, 1].map((pct) => {
        const y = H - PAD - pct * (H - 2 * PAD);
        const val = Math.round(maxRev * pct);
        return (
          <g key={pct}>
            <line x1={PAD} y1={y} x2={W - PAD} y2={y} stroke="#f1f5f9" strokeWidth="1" />
            <text x={PAD - 4} y={y + 3} textAnchor="end" className="text-[8px] fill-slate-400">
              {val >= 1000000 ? `${(val / 1000000).toFixed(1)}M` : val >= 1000 ? `${(val / 1000).toFixed(0)}K` : val}
            </text>
          </g>
        );
      })}
      {/* Bars */}
      {data.map((d, i) => {
        const x = PAD + (i / data.length) * (W - 2 * PAD) + 1;
        const barH = (d.revenue / maxRev) * (H - 2 * PAD);
        const y = H - PAD - barH;
        return (
          <g key={i} onMouseEnter={() => setHover(i)}>
            <rect x={x} y={y} width={barW} height={barH} rx={2}
              fill={hover === i ? "#4f46e5" : "#818cf8"} className="transition-colors"
            />
            {/* X-axis label (every ~5th) */}
            {(data.length <= 14 || i % Math.ceil(data.length / 10) === 0) && (
              <text x={x + barW / 2} y={H - 8} textAnchor="middle" className="text-[7px] fill-slate-400">
                {d.date.slice(5)}
              </text>
            )}
            {/* Tooltip */}
            {hover === i && (
              <>
                <rect x={Math.min(x - 40, W - 100)} y={Math.max(y - 40, 0)} width={90} height={34} rx={6}
                  fill="white" stroke="#e2e8f0"
                />
                <text x={Math.min(x - 40, W - 100) + 45} y={Math.max(y - 40, 0) + 14} textAnchor="middle"
                  className="text-[9px] fill-slate-500">
                  {d.date.slice(5)} — {d.orders} зак.
                </text>
                <text x={Math.min(x - 40, W - 100) + 45} y={Math.max(y - 40, 0) + 28} textAnchor="middle"
                  className="text-[9px] fill-indigo-600 font-medium">
                  {d.revenue >= 1000000
                    ? `${(d.revenue / 1000000).toFixed(1)}M`
                    : d.revenue >= 1000
                      ? `${(d.revenue / 1000).toFixed(0)}K`
                      : d.revenue} UZS
                </text>
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}
