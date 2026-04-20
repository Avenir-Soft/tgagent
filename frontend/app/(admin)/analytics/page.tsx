"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import Link from "next/link";
import { formatPrice } from "@/lib/utils";

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
  product_id: string | null;
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

interface CustomerDetail {
  conversation_id: string | null;
  reason: string;
  messages: Array<{ text: string; sender_type: string; created_at: string | null }>;
}

interface ProductOption {
  id: string;
  name: string;
  variants: Array<{ id: string; title: string; price: number }>;
}

// ── Helpers ────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined) {
  if (n == null || Number.isNaN(n)) return "0";
  return formatPrice(n);
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

interface AiInsight {
  type: string;
  title: string;
  text: string;
  priority?: string;
}

interface AiInsightsData {
  period_days: number;
  generated_at: string;
  insights: AiInsight[];
  data_summary: {
    revenue: number;
    revenue_change_pct: number | null;
    orders: number;
    avg_check: number;
    conversations: number;
    conversion_rate: number;
    handoffs: number;
  };
}

const insightTypeConfig: Record<string, { icon: string; color: string; bg: string; border: string }> = {
  growth: { icon: "📈", color: "text-emerald-700", bg: "bg-emerald-50", border: "border-emerald-200" },
  warning: { icon: "⚠️", color: "text-amber-700", bg: "bg-amber-50", border: "border-amber-200" },
  opportunity: { icon: "💡", color: "text-indigo-700", bg: "bg-indigo-50", border: "border-indigo-200" },
  action: { icon: "🎯", color: "text-violet-700", bg: "bg-violet-50", border: "border-violet-200" },
};

const tabs = [
  { key: "ai-insights", label: "AI Инсайты" },
  { key: "overview", label: "Обзор" },
  { key: "customers", label: "Клиенты" },
  { key: "conversations", label: "Диалоги" },
  { key: "funnel", label: "Воронка" },
  { key: "stock", label: "Места" },
  { key: "competitors", label: "Конкуренты" },
];

// ── Main Component ────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [tab, setTab] = useState("ai-insights");
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
  const [loading, setLoading] = useState(true);

  // AI Insights
  const [aiInsights, setAiInsights] = useState<AiInsightsData | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);

  // Sorting: null = default (no active sort)
  const [stockSort, setStockSort] = useState<{ col: string; asc: boolean } | null>(null);
  const [custSort, setCustSort] = useState<{ col: string; asc: boolean } | null>(null);

  const cycleSort = (
    current: { col: string; asc: boolean } | null,
    col: string,
    defaultAsc: boolean,
  ): { col: string; asc: boolean } | null => {
    if (!current || current.col !== col) return { col, asc: defaultAsc };
    if (current.asc === defaultAsc) return { col, asc: !defaultAsc };
    return null; // 3rd click → reset
  };

  // Customer detail dropdown (keyed by lead_id)
  const [expandedCustomer, setExpandedCustomer] = useState<string | null>(null);
  const [customerDetail, setCustomerDetail] = useState<CustomerDetail | null>(null);
  const [customerDetailLoading, setCustomerDetailLoading] = useState(false);

  // Competitor expand
  const [expandedCompetitors, setExpandedCompetitors] = useState<Set<string>>(new Set());

  // Stock alerts expand
  const [showAllAlerts, setShowAllAlerts] = useState(false);

  // Competitor form
  const [showCompForm, setShowCompForm] = useState(false);
  const [compForm, setCompForm] = useState({
    competitor_name: "",
    product_title: "",
    competitor_price: "",
    our_price: "",
    competitor_channel: "",
    product_id: "" as string,
  });
  const [products, setProducts] = useState<ProductOption[]>([]);
  const [productsLoaded, setProductsLoaded] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([
        api.get<RFMSummary>("/analytics/rfm/segments").then(setRfm).catch(() => {}),
        api.get<ConversationAnalytics>(`/analytics/conversations?days=${days}`).then(setConvAnalytics).catch(() => {}),
        api.get<FunnelResponse>(`/analytics/funnel?days=${days}`).then(setFunnel).catch(() => {}),
        api.get<StockForecast>(`/analytics/stock-forecast?forecast_days=${days}`).then(setStock).catch(() => {}),
        api.get<RevenueData>(`/analytics/revenue?days=${days}`).then(setRevenue).catch(() => {}),
        api.get<CompetitorPrice[]>("/analytics/competitors").then(setCompetitors).catch(() => {}),
        api.get<CompetitorSummary[]>("/analytics/competitors/summary").then(setCompetitorSummary).catch(() => {}),
        // Load cached AI insights (no regeneration, fast — returns null if no cache)
        api.get<AiInsightsData | null>(`/analytics/ai-insights?days=${days}`)
          .then((data) => setAiInsights(data || null))
          .catch(() => setAiInsights(null)),
      ]);
    } finally {
      setLoading(false);
    }
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

  const loadProducts = () => {
    if (productsLoaded) return;
    api.get<ProductOption[]>("/products").then((data) => {
      setProducts(data.map((p: any) => ({
        id: p.id,
        name: p.name,
        variants: (p.variants || []).map((v: any) => ({ id: v.id, title: v.title, price: Number(v.price) })),
      })));
      setProductsLoaded(true);
    }).catch(() => {});
  };

  const onSelectProduct = (productId: string) => {
    const p = products.find((pr) => pr.id === productId);
    if (!p) return;
    const minPrice = p.variants.length > 0 ? Math.min(...p.variants.map((v) => v.price)) : 0;
    const maxPrice = p.variants.length > 0 ? Math.max(...p.variants.map((v) => v.price)) : 0;
    const priceStr = minPrice === maxPrice ? String(minPrice) : String(minPrice);
    setCompForm((f) => ({
      ...f,
      product_id: productId,
      product_title: f.product_title || p.name,
      our_price: priceStr,
    }));
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
        product_id: compForm.product_id || null,
      });
      toast("Цена конкурента добавлена", "success");
      setShowCompForm(false);
      setCompForm({ competitor_name: "", product_title: "", competitor_price: "", our_price: "", competitor_channel: "", product_id: "" });
      api.get<CompetitorPrice[]>("/analytics/competitors").then(setCompetitors);
      api.get<CompetitorSummary[]>("/analytics/competitors/summary").then(setCompetitorSummary);
    } catch {
      toast("Ошибка добавления", "error");
    }
  };

  const deleteCompetitor = async (id: string) => {
    try {
      await api.delete(`/analytics/competitors/${id}`);
    } catch (e: any) {
      toast(e?.detail || "Ошибка удаления", "error");
      return;
    }
    setCompetitors((prev) => {
      const updated = prev.filter((c) => c.id !== id);
      // Recalculate summary from remaining data
      const byName = new Map<string, CompetitorPrice[]>();
      updated.forEach((c) => {
        const arr = byName.get(c.competitor_name) || [];
        arr.push(c);
        byName.set(c.competitor_name, arr);
      });
      const newSummary: CompetitorSummary[] = [];
      byName.forEach((prices, name) => {
        let cheaper = 0, expensive = 0, diffs: number[] = [];
        prices.forEach((p) => {
          if (p.our_price && p.our_price > 0) {
            const diff = (p.competitor_price - p.our_price) / p.our_price * 100;
            diffs.push(diff);
            if (p.competitor_price < p.our_price) cheaper++;
            if (p.competitor_price > p.our_price) expensive++;
          }
        });
        newSummary.push({
          competitor_name: name,
          products_tracked: prices.length,
          avg_price_diff_pct: diffs.length > 0 ? diffs.reduce((a, b) => a + b, 0) / diffs.length : null,
          cheaper_count: cheaper,
          more_expensive_count: expensive,
        });
      });
      setCompetitorSummary(newSummary);
      return updated;
    });
  };

  const toggleCustomerDetail = async (leadId: string, telegramUserId: number) => {
    if (expandedCustomer === leadId) {
      setExpandedCustomer(null);
      setCustomerDetail(null);
      return;
    }
    setExpandedCustomer(leadId);
    setCustomerDetailLoading(true);
    try {
      const detail = await api.get<CustomerDetail>(`/analytics/rfm/customer-detail?telegram_user_id=${telegramUserId}`);
      setCustomerDetail(detail);
    } catch {
      setCustomerDetail(null);
    } finally {
      setCustomerDetailLoading(false);
    }
  };

  // ── CSV Export helper ──
  const exportCSV = (filename: string, headers: string[], rows: string[][]) => {
    const bom = "\uFEFF";
    const csv = bom + [headers.join(";"), ...rows.map((r) => r.join(";"))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── Tab: AI Insights ──

  const loadInsights = async () => {
    setInsightsLoading(true);
    try {
      const data = await api.get<AiInsightsData>(`/analytics/ai-insights?days=${days}&refresh=true`);
      setAiInsights(data);
    } catch {
      toast("Ошибка генерации инсайтов", "error");
    } finally {
      setInsightsLoading(false);
    }
  };

  const renderAiInsights = () => (
    <div className="space-y-6">
      {/* Header + generate button */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-slate-900">AI Аналитик</h2>
          <p className="text-sm text-slate-500">Автоматический анализ бизнес-данных за {days} дней</p>
        </div>
        <button
          type="button"
          onClick={loadInsights}
          disabled={insightsLoading}
          className="px-4 py-2.5 bg-gradient-to-r from-indigo-600 to-violet-600 text-white rounded-xl text-sm font-medium hover:from-indigo-500 hover:to-violet-500 disabled:opacity-50 transition-all shadow-lg shadow-indigo-500/25 flex items-center gap-2"
        >
          {insightsLoading ? (
            <>
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
              Анализирую...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" /></svg>
              {aiInsights ? "Обновить инсайты" : "Сгенерировать инсайты"}
            </>
          )}
        </button>
      </div>

      {!aiInsights && !insightsLoading && (
        <div className="card p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-100 to-violet-100 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" /></svg>
          </div>
          <h3 className="text-lg font-semibold text-slate-900 mb-2">AI анализ вашего бизнеса</h3>
          <p className="text-sm text-slate-500 max-w-md mx-auto mb-6">
            AI проанализирует выручку, конверсию, сегменты клиентов, наличие мест и причины handoff — и даст конкретные рекомендации
          </p>
          <button
            type="button"
            onClick={loadInsights}
            className="px-6 py-3 bg-gradient-to-r from-indigo-600 to-violet-600 text-white rounded-xl text-sm font-semibold hover:from-indigo-500 hover:to-violet-500 transition-all shadow-lg shadow-indigo-500/25"
          >
            Запустить анализ
          </button>
        </div>
      )}

      {insightsLoading && (
        <div className="space-y-4">
          {[1,2,3,4].map(i => (
            <div key={i} className="card p-6 animate-pulse">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-slate-200 shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-5 bg-slate-200 rounded w-1/3" />
                  <div className="h-4 bg-slate-100 rounded w-2/3" />
                  <div className="h-4 bg-slate-100 rounded w-1/2" />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {aiInsights && !insightsLoading && (
        <>
          {/* Summary KPIs */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="card p-4">
              <p className="text-xs text-slate-500">Выручка</p>
              <p className="text-lg font-bold text-slate-900">{fmt(aiInsights.data_summary.revenue)} сум</p>
              {aiInsights.data_summary.revenue_change_pct !== null ? (
                <p className={`text-xs font-medium ${aiInsights.data_summary.revenue_change_pct >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                  {aiInsights.data_summary.revenue_change_pct >= 0 ? "↑" : "↓"} {Math.abs(aiInsights.data_summary.revenue_change_pct)}% vs прошлый период
                </p>
              ) : (
                <p className="text-xs font-medium text-indigo-500">Новый период</p>
              )}
            </div>
            <div className="card p-4">
              <p className="text-xs text-slate-500">Заказы</p>
              <p className="text-lg font-bold text-slate-900">{aiInsights.data_summary.orders}</p>
              <p className="text-xs text-slate-400">ср. чек {fmt(aiInsights.data_summary.avg_check)} сум</p>
            </div>
            <div className="card p-4">
              <p className="text-xs text-slate-500">Конверсия</p>
              <p className="text-lg font-bold text-slate-900">{aiInsights.data_summary.conversion_rate}%</p>
              <p className="text-xs text-slate-400">{aiInsights.data_summary.conversations} диалогов</p>
            </div>
            <div className="card p-4">
              <p className="text-xs text-slate-500">Handoff</p>
              <p className="text-lg font-bold text-slate-900">{aiInsights.data_summary.handoffs}</p>
              <p className="text-xs text-slate-400">передач оператору</p>
            </div>
          </div>

          {/* Insight cards */}
          <div className="space-y-3">
            {aiInsights.insights.map((insight, i) => {
              const cfg = insightTypeConfig[insight.type] || insightTypeConfig.action;
              return (
                <div key={i} className={`card p-5 border-l-4 ${cfg.border}`}>
                  <div className="flex items-start gap-3">
                    <div className={`w-10 h-10 rounded-xl ${cfg.bg} flex items-center justify-center shrink-0 text-lg`}>
                      {cfg.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className={`font-semibold text-sm ${cfg.color}`}>{insight.title}</h3>
                        {insight.priority === "high" && (
                          <span className="px-1.5 py-0.5 bg-rose-100 text-rose-700 text-[10px] font-bold rounded">HIGH</span>
                        )}
                      </div>
                      <p className="text-sm text-slate-600 leading-relaxed">{insight.text}</p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Export + timestamp */}
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>Сгенерировано: {new Date(aiInsights.generated_at).toLocaleString("ru")}</span>
            <button
              type="button"
              onClick={() => {
                const rows = aiInsights.insights.map((ins) => [ins.type, ins.priority || "", ins.title, `"${ins.text.replace(/"/g, '""')}"`]);
                exportCSV(`ai-insights-${days}d.csv`, ["Тип", "Приоритет", "Заголовок", "Описание"], rows);
              }}
              className="px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 transition-colors text-xs font-medium"
            >
              Экспорт CSV
            </button>
          </div>
        </>
      )}
    </div>
  );

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
          <h3 className="text-sm font-bold text-slate-900 mb-3">Воронка ({days} дней)</h3>
          <div className="space-y-2">
            {(funnel?.stages || []).map((s, i) => {
              const pct = s.pct ?? 0;
              return (
                <div key={s.name} className="flex items-center gap-3">
                  <span className="text-xs text-slate-500 w-24 shrink-0">{s.label}</span>
                  <div className="flex-1 bg-slate-100 rounded-full h-5 overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 to-indigo-400 rounded-full transition-all"
                      style={{ width: `${Math.max(pct, s.count > 0 ? 4 : 0)}%` }}
                    />
                  </div>
                  <span className="text-xs font-medium w-12 text-right">{s.count}</span>
                  <span className="text-xs text-slate-400 w-10 text-right">{pct.toFixed(0)}%</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Segments overview */}
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-900 mb-3">Сегменты клиентов</h3>
          {rfm && rfm.total_customers > 0 ? (
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(rfm.segments || {}).sort((a, b) => b[1] - a[1]).map(([seg, count]) => {
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
      {stock && ((stock.risk_summary?.critical ?? 0) > 0 || (stock.risk_summary?.warning ?? 0) > 0) && (() => {
        const alertItems = stock.items.filter((i) => i.risk === "critical" || i.risk === "warning");
        const visibleItems = showAllAlerts ? alertItems : alertItems.slice(0, 5);
        return (
          <div className="card p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold text-slate-900">Предупреждения по местам</h3>
              {alertItems.length > 5 && (
                <button
                  onClick={() => setShowAllAlerts(!showAllAlerts)}
                  className="text-xs text-indigo-600 hover:text-indigo-700 transition-colors"
                >
                  {showAllAlerts ? "Свернуть" : `Смотреть все (${alertItems.length})`}
                </button>
              )}
            </div>
            <div className="space-y-2">
              {visibleItems.map((item) => {
                const rc = riskConfig[item.risk] || riskConfig.ok;
                return (
                <div key={item.variant_id} className="flex items-center gap-3">
                  <span className={`px-2 py-0.5 rounded text-xs ${rc.bg} ${rc.color}`}>
                    {rc.label}
                  </span>
                  {item.product_id ? (
                    <Link href={`/products/${item.product_id}`} className="text-sm text-slate-900 hover:text-indigo-600 transition-colors">
                      {item.product_name} — {item.variant_title}
                    </Link>
                  ) : (
                    <span className="text-sm text-slate-900">{item.product_name} — {item.variant_title}</span>
                  )}
                  <span className="text-xs text-slate-400 ml-auto">
                    {item.available_stock} шт, ~{item.days_until_stockout ?? "?"} дней
                  </span>
                </div>
                );
              })}
            </div>
          </div>
        );
      })()}
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
                    onClick={() => setCustSort((s) => cycleSort(s, h.col, false))}
                  >
                    {h.label}{custSort?.col === h.col ? (custSort.asc ? " ↑" : " ↓") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rfm.top_customers.slice().sort((a, b) => {
                if (!custSort) return 0;
                const k = custSort.col as keyof CustomerSegment;
                const av = Number(a[k]) || 0;
                const bv = Number(b[k]) || 0;
                return custSort.asc ? av - bv : bv - av;
              }).map((c) => {
                const cfg = segmentConfig[c.segment] || segmentConfig.regular;
                const isExpanded = expandedCustomer === c.lead_id;
                return (
                  <tr key={c.lead_id} className="hover:bg-slate-50 transition-colors group">
                    <td className="px-4 py-3 relative" colSpan={isExpanded ? 6 : 1}>
                      {isExpanded ? (
                        /* Expanded detail row */
                        <div>
                          <button
                            onClick={() => toggleCustomerDetail(c.lead_id, c.telegram_user_id)}
                            className="font-medium text-indigo-600 hover:text-indigo-700 mb-3 flex items-center gap-1"
                          >
                            <span className="text-xs">▼</span> {c.customer_name || "Без имени"}
                          </button>
                          {customerDetailLoading ? (
                            <p className="text-xs text-slate-400">Загрузка...</p>
                          ) : customerDetail ? (
                            <div className="space-y-3 max-w-xl">
                              {/* Segment + reason */}
                              <div className="flex items-start gap-2">
                                <span className={`px-2 py-0.5 rounded text-xs ${cfg.bg} ${cfg.color} shrink-0`}>{cfg.label}</span>
                                <p className="text-xs text-slate-600">{customerDetail.reason || "Нет данных"}</p>
                              </div>
                              {/* RFM scores */}
                              <div className="flex gap-4 text-xs text-slate-500">
                                <span>Заказов: <b className="text-slate-700">{c.frequency}</b></span>
                                <span>Потрачено: <b className="text-slate-700">{fmt(Number(c.monetary))} UZS</b></span>
                                <span>Был: <b className="text-slate-700">{c.recency_days} дн. назад</b></span>
                                <span>RFM: <b className="font-mono text-slate-700">{c.rfm_score}</b></span>
                              </div>
                              {/* Recent messages */}
                              {customerDetail.messages.length > 0 && (
                                <div>
                                  <p className="text-xs font-medium text-slate-500 mb-1">Последние сообщения:</p>
                                  <div className="space-y-1 max-h-40 overflow-y-auto">
                                    {customerDetail.messages.map((m, i) => (
                                      <div key={i} className={`text-xs px-2 py-1 rounded ${
                                        m.sender_type === "customer" ? "bg-slate-100 text-slate-700" : "bg-indigo-50 text-indigo-700"
                                      }`}>
                                        <span className="font-medium">{m.sender_type === "customer" ? "Клиент" : "AI"}:</span>{" "}
                                        {m.text}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {/* Link to chat */}
                              {customerDetail.conversation_id && (
                                <Link
                                  href={`/conversations/${customerDetail.conversation_id}`}
                                  className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-700 font-medium transition-colors"
                                >
                                  Перейти в чат →
                                </Link>
                              )}
                              <Link href="/leads" className="text-xs text-emerald-600 hover:text-emerald-700 font-medium transition-colors ml-3">Карточка лида →</Link>
                            </div>
                          ) : (
                            <p className="text-xs text-slate-400">Данные не найдены</p>
                          )}
                        </div>
                      ) : (
                        <button
                          onClick={() => toggleCustomerDetail(c.lead_id, c.telegram_user_id)}
                          className="font-medium text-slate-900 hover:text-indigo-600 transition-colors flex items-center gap-1"
                        >
                          <span className="text-xs text-slate-300 group-hover:text-indigo-400">▶</span> {c.customer_name || "Без имени"}
                        </button>
                      )}
                    </td>
                    {!isExpanded && (
                      <>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded text-xs ${cfg.bg} ${cfg.color}`}>{cfg.label}</span>
                        </td>
                        <td className="px-4 py-3 text-slate-700">{c.frequency}</td>
                        <td className="px-4 py-3 text-slate-700">{fmt(Number(c.monetary))} UZS</td>
                        <td className="px-4 py-3 text-slate-400">{c.recency_days} дн. назад</td>
                        <td className="px-4 py-3 font-mono text-xs text-slate-500">{c.rfm_score}</td>
                      </>
                    )}
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
    const senderMap = ca?.messages_by_sender || {};
    const totalMsgs = Object.values(senderMap).reduce((s, v) => s + (v || 0), 0);

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
            {ca && Object.entries(senderMap).sort((a, b) => b[1] - a[1]).map(([type, count]) => {
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
        {ca && (ca.daily_trend?.length ?? 0) > 0 && (
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
                  <span className="text-sm text-slate-400 w-12 text-right">{(s.pct ?? 0).toFixed(0)}%</span>
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
                <p className={`text-2xl font-bold ${cfg.color}`}>{stock.risk_summary?.[risk] ?? 0}</p>
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
              <th className="px-4 py-3 text-slate-500 font-medium">Тур</th>
              <th className="px-4 py-3 text-slate-500 font-medium">Вариант</th>
              {[
                { col: "available_stock", label: "Остаток" },
                { col: "avg_daily_sales", label: "Продаж/день" },
                { col: "days_until_stockout", label: "До стокаута" },
                { col: "forecasted_demand", label: `Прогноз (${days}д)` },
              ].map((h) => (
                <th
                  key={h.col}
                  className="px-4 py-3 text-slate-500 font-medium cursor-pointer hover:text-indigo-600 select-none transition-colors"
                  onClick={() => setStockSort((s) => cycleSort(s, h.col, h.col === "days_until_stockout"))}
                >
                  {h.label}{stockSort?.col === h.col ? (stockSort.asc ? " ↑" : " ↓") : ""}
                </th>
              ))}
              <th className="px-4 py-3 text-slate-500 font-medium">Риск</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {(stock?.items || []).slice().sort((a, b) => {
              if (!stockSort) return 0; // default order from API
              const k = stockSort.col as keyof StockForecastItem;
              const av = a[k] ?? 9999;
              const bv = b[k] ?? 9999;
              return stockSort.asc ? (av > bv ? 1 : av < bv ? -1 : 0) : (av < bv ? 1 : av > bv ? -1 : 0);
            }).map((item) => {
              const cfg = riskConfig[item.risk] || riskConfig.ok;
              return (
                <tr key={item.variant_id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-medium">
                    {item.product_id ? (
                      <Link href={`/products/${item.product_id}`} className="text-slate-900 hover:text-indigo-600 transition-colors">
                        {item.product_name}
                      </Link>
                    ) : (
                      <span className="text-slate-900">{item.product_name}</span>
                    )}
                  </td>
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
      {/* Summary cards — expandable */}
      {competitorSummary.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {competitorSummary.map((cs) => {
            const isExpanded = expandedCompetitors.has(cs.competitor_name);
            const compProducts = competitors.filter((c) => c.competitor_name === cs.competitor_name);
            return (
              <div key={cs.competitor_name} className="card overflow-hidden">
                <button
                  onClick={() => setExpandedCompetitors((prev) => { const next = new Set(prev); if (next.has(cs.competitor_name)) next.delete(cs.competitor_name); else next.add(cs.competitor_name); return next; })}
                  className="w-full text-left p-4 hover:bg-slate-50 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <p className="font-bold text-sm text-slate-900">{cs.competitor_name}</p>
                    <span className="text-xs text-slate-400">{isExpanded ? "▲" : "▼"}</span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">{cs.products_tracked} товаров</p>
                  <div className="flex gap-4 mt-2">
                    <p className="text-xs text-emerald-600">{cs.cheaper_count} дешевле</p>
                    <p className="text-xs text-rose-600">{cs.more_expensive_count} дороже</p>
                    {cs.avg_price_diff_pct != null && (
                      <p className={`text-xs ${cs.avg_price_diff_pct > 0 ? "text-emerald-600" : "text-rose-600"}`}>
                        {cs.avg_price_diff_pct > 0 ? "+" : ""}{cs.avg_price_diff_pct.toFixed(1)}%
                      </p>
                    )}
                  </div>
                </button>
                {isExpanded && compProducts.length > 0 && (
                  <div className="border-t border-slate-100 px-4 py-3 space-y-2 bg-slate-50/50">
                    {compProducts.map((cp) => {
                      const diff = cp.our_price ? ((cp.competitor_price - cp.our_price) / cp.our_price * 100) : null;
                      return (
                        <div key={cp.id} className="flex items-center justify-between text-xs">
                          <div className="flex-1 min-w-0">
                            <p className="text-slate-900 font-medium truncate">{cp.product_title}</p>
                            {cp.competitor_channel && <p className="text-indigo-500 text-[10px]">{cp.competitor_channel}</p>}
                          </div>
                          <div className="flex items-center gap-3 shrink-0 ml-3">
                            <span className="text-slate-500">{fmt(Number(cp.competitor_price))}</span>
                            {cp.our_price && <span className="text-slate-400">vs {fmt(Number(cp.our_price))}</span>}
                            {diff != null && (
                              <span className={`font-medium ${diff > 0 ? "text-emerald-600" : "text-rose-600"}`}>
                                {diff > 0 ? "+" : ""}{diff.toFixed(0)}%
                              </span>
                            )}
                            <button
                              onClick={(e) => { e.stopPropagation(); deleteCompetitor(cp.id); }}
                              className="text-rose-400 hover:text-rose-600"
                            >
                              ×
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                {isExpanded && compProducts.length === 0 && (
                  <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-400">
                    Нет товаров
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Add button + form */}
      <button
        onClick={() => { setShowCompForm(!showCompForm); loadProducts(); }}
        className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
      >
        + Добавить цену
      </button>

      {showCompForm && (
        <form onSubmit={addCompetitorPrice} className="card p-5 space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Сравнить цену конкурента</h3>
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
              placeholder="@channel конкурента (опционально)"
              value={compForm.competitor_channel}
              onChange={(e) => setCompForm({ ...compForm, competitor_channel: e.target.value })}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              maxLength={255}
            />
            {/* Our product selector — auto-fills price */}
            <div>
              <select
                value={compForm.product_id}
                onChange={(e) => onSelectProduct(e.target.value)}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              >
                <option value="">Наш товар (для авто-цены)</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — {p.variants.length > 0 ? `от ${fmt(Math.min(...p.variants.map((v) => v.price)))} UZS` : "нет вариантов"}
                  </option>
                ))}
              </select>
            </div>
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
              placeholder="Цена у конкурента"
              value={compForm.competitor_price}
              onChange={(e) => setCompForm({ ...compForm, competitor_price: e.target.value })}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              required
              min={0}
              step="any"
            />
            <input
              type="number"
              placeholder="Наша цена"
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
              <th className="px-4 py-3 text-slate-500 font-medium">Тур</th>
              <th className="px-4 py-3 text-slate-500 font-medium">Их цена</th>
              <th className="px-4 py-3 text-slate-500 font-medium">Наша цена</th>
              <th className="px-4 py-3 text-slate-500 font-medium">Кто выгоднее</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {competitors.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">Добавьте цены конкурентов для сравнения</td></tr>
            ) : competitors.map((c) => {
              const cp = Number(c.competitor_price);
              const op = c.our_price ? Number(c.our_price) : null;
              const diff = op && op > 0 ? ((cp - op) / op * 100) : null;
              // positive diff = competitor more expensive = we are cheaper (good)
              // negative diff = competitor cheaper = we are more expensive (bad)
              let verdict = "";
              let verdictClass = "text-slate-400";
              if (diff != null) {
                if (diff > 1) { verdict = `Мы дешевле на ${diff.toFixed(1)}%`; verdictClass = "text-emerald-600"; }
                else if (diff < -1) { verdict = `Мы дороже на ${Math.abs(diff).toFixed(1)}%`; verdictClass = "text-rose-600"; }
                else { verdict = `Цены ~равны`; verdictClass = "text-slate-500"; }
              }
              return (
                <tr key={c.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{c.competitor_name}</div>
                    {c.competitor_channel && <div className="text-xs text-indigo-500">{c.competitor_channel}</div>}
                  </td>
                  <td className="px-4 py-3 text-slate-700">{c.product_title}</td>
                  <td className="px-4 py-3 font-medium text-slate-900">{fmt(cp)} {c.currency}</td>
                  <td className="px-4 py-3 font-medium text-slate-900">{op ? `${fmt(op)} ${c.currency}` : <span className="text-slate-400">не указана</span>}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-medium ${verdictClass}`}>{verdict || "--"}</span>
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
    exportCSV("stock.csv", ["Тур", "Дата", "Мест", "Броней/день", "До заполнения", "Прогноз", "Риск"],
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
          <p className="text-sm text-slate-500 mt-1">Клиенты, конверсия, места и конкуренты</p>
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
      {loading ? (
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="card p-6 animate-pulse">
              <div className="h-4 bg-slate-200 rounded w-1/3 mb-3" />
              <div className="h-8 bg-slate-200 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : (
        <>
          {tab === "ai-insights" && renderAiInsights()}
          {tab === "overview" && renderOverview()}
          {tab === "customers" && renderCustomers()}
          {tab === "conversations" && renderConversations()}
          {tab === "funnel" && renderFunnel()}
          {tab === "stock" && renderStock()}
          {tab === "competitors" && renderCompetitors()}
        </>
      )}
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
