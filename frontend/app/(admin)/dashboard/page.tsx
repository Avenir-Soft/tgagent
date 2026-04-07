"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

interface DailyCount { date: string; count: number }
interface RecentOrder { order_number: string; customer: string; amount: number; status: string; created_at: string | null }
interface Stats {
  total_conversations: number; dm_conversations: number; active_conversations: number;
  total_leads: number; total_orders: number;
  pending_handoffs: number; anomaly_conversations_7d: number; abandoned_carts: number;
  conversion_rate_pct: number; total_revenue: number;
  today_orders: number; today_revenue: number; today_messages: number;
  yesterday_orders: number; yesterday_revenue: number; yesterday_messages: number;
  orders_by_status: Record<string, { count: number; revenue: number }>;
  leads_by_status: Record<string, number>;
  recent_orders: RecentOrder[]; orders_daily: DailyCount[]; leads_daily: DailyCount[];
}
interface LowStockItem { variant_id: string; product_id: string; title: string; available: number; reserved: number; total: number }

const statusLabels: Record<string, string> = { draft: "Черновик", confirmed: "Подтверждён", processing: "В обработке", shipped: "Отправлен", delivered: "Доставлен", cancelled: "Отменён" };
const statusColors: Record<string, string> = { draft: "bg-slate-400", confirmed: "bg-blue-500", processing: "bg-amber-500", shipped: "bg-violet-500", delivered: "bg-emerald-500", cancelled: "bg-rose-400" };
const statusDots: Record<string, string> = { draft: "bg-slate-300", confirmed: "bg-blue-400", processing: "bg-amber-400", shipped: "bg-violet-400", delivered: "bg-emerald-400", cancelled: "bg-rose-300" };
const leadLabels: Record<string, string> = { new: "Новые", contacted: "Связались", qualified: "Квалиф.", converted: "Конверт.", lost: "Потерян" };

function fmtPrice(val: number) { return val.toLocaleString("ru-RU"); }

/* ── Trend Badge ─────────────────────────────── */
function TrendBadge({ current, previous, suffix = "" }: { current: number; previous: number; suffix?: string }) {
  if (previous === 0 && current === 0) return null;
  if (previous === 0) return <span className="text-[10px] text-emerald-500 font-medium">новое</span>;
  const pct = Math.round(((current - previous) / previous) * 100);
  if (pct === 0) return <span className="text-[10px] text-slate-400">= вчера</span>;
  const isUp = pct > 0;
  return (
    <span className={`text-[10px] font-medium ${isUp ? "text-emerald-500" : "text-rose-500"}`}>
      {isUp ? "↑" : "↓"} {Math.abs(pct)}%{suffix}
    </span>
  );
}

/* ── Skeleton ──────────────────────────────────── */
function DashSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="h-8 w-40 skeleton" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="h-24 skeleton" /><div className="h-24 skeleton" /><div className="h-24 skeleton" /><div className="h-24 skeleton" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
        <div className="md:col-span-2 h-44 skeleton" />
        <div className="h-44 skeleton" />
        <div className="h-44 skeleton" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div className="h-24 skeleton" /><div className="h-24 skeleton" /><div className="h-24 skeleton" />
      </div>
    </div>
  );
}

/* ── Mini Bar Chart with Leads & Conversion lines ───── */
function MiniBarChart({ data, lineData, height = 120 }: { data: DailyCount[]; lineData?: DailyCount[]; height?: number }) {
  if (!data.length) return <div className="text-xs text-slate-300 text-center py-4">Нет данных</div>;

  const maxBar = Math.max(...data.map((d) => d.count), 1);
  const days = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

  // Build leads line values aligned to bar dates
  const lineMap = new Map<string, number>();
  if (lineData) lineData.forEach((d) => lineMap.set(d.date, d.count));
  const lineVals = data.map((d) => lineMap.get(d.date) ?? 0);
  const maxLine = Math.max(...lineVals, 1);
  const hasLine = lineVals.some((v) => v > 0);

  // Compute conversion rate: orders / leads * 100 for each day
  const convVals = data.map((d, i) => {
    const leads = lineVals[i];
    if (leads <= 0) return 0;
    return Math.min(100, Math.round((d.count / leads) * 100));
  });
  const hasConv = convVals.some((v) => v > 0);
  const maxConv = 100; // percentage scale, always 0-100

  const W = 500;
  const H = height;
  const pt = 18; // top padding for value labels
  const pb = 16; // bottom for day labels
  const ch = H - pt - pb;
  const n = data.length;
  const colW = W / n;
  const barW = colW * 0.4;

  // Leads line points
  const linePts = hasLine
    ? lineVals.map((v, i) => ({
        x: (i + 0.5) * colW,
        y: pt + ch - Math.max(2, (v / maxLine) * ch * 0.85),
        v,
      }))
    : [];

  // Conversion line points
  const convPts = hasConv
    ? convVals.map((v, i) => ({
        x: (i + 0.5) * colW,
        y: pt + ch - Math.max(2, (v / maxConv) * ch * 0.85),
        v,
      }))
    : [];

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} preserveAspectRatio="xMidYMid meet">
        {data.map((d, i) => {
          const bh = Math.max(2, (d.count / maxBar) * ch * 0.85);
          const cx = (i + 0.5) * colW;
          const by = pt + ch - bh;
          return (
            <g key={i}>
              <rect x={cx - barW / 2} y={by} width={barW} height={bh} rx={3} fill="#818cf8" opacity={0.85}>
                <title>{d.date}: {d.count} заказов</title>
              </rect>
              {d.count > 0 && (
                <text x={cx} y={by - 4} textAnchor="middle" fill="#94a3b8" fontSize={10} fontWeight={500}>{d.count}</text>
              )}
              <text x={cx} y={H - 2} textAnchor="middle" fill="#94a3b8" fontSize={10}>{days[new Date(d.date).getDay()]}</text>
            </g>
          );
        })}

        {/* Leads line (emerald) */}
        {hasLine && linePts.length > 1 && (
          <>
            <polyline
              points={linePts.map((p) => `${p.x},${p.y}`).join(" ")}
              fill="none" stroke="#34d399" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" opacity={0.8}
            />
            {linePts.map((p, i) => (
              <g key={`l${i}`}>
                <circle cx={p.x} cy={p.y} r={3} fill="#34d399" stroke="white" strokeWidth={1.5}>
                  <title>{data[i]?.date}: {p.v} лидов</title>
                </circle>
              </g>
            ))}
          </>
        )}

        {/* Conversion line (amber, dashed) */}
        {hasConv && convPts.length > 1 && (
          <>
            <polyline
              points={convPts.map((p) => `${p.x},${p.y}`).join(" ")}
              fill="none" stroke="#f59e0b" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" strokeDasharray="6 3" opacity={0.8}
            />
            {convPts.map((p, i) => (
              <g key={`c${i}`}>
                <circle cx={p.x} cy={p.y} r={3} fill="#f59e0b" stroke="white" strokeWidth={1.5}>
                  <title>{data[i]?.date}: {p.v}% конверсия</title>
                </circle>
                {p.v > 0 && (
                  <text x={p.x} y={p.y - 7} textAnchor="middle" fill="#f59e0b" fontSize={9} fontWeight={600}>{p.v}%</text>
                )}
              </g>
            ))}
          </>
        )}
      </svg>

      {/* Legend */}
      <div className="flex items-center gap-3 mt-1 justify-center text-[10px] text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-2 rounded-sm bg-indigo-400 inline-block" />
          Заказы
        </span>
        {hasLine && (
          <span className="flex items-center gap-1.5">
            <span className="w-4 h-0.5 bg-emerald-400 rounded inline-block" />
            Лиды
          </span>
        )}
        {hasConv && (
          <span className="flex items-center gap-1.5">
            <span className="w-4 h-0.5 bg-amber-400 rounded inline-block border-dashed" style={{ borderTopWidth: 2, height: 0, borderColor: "#f59e0b" }} />
            Конверсия
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Status Bar ────────────────────────────────── */
function StatusBar({ data }: { data: Record<string, { count: number; revenue: number }> }) {
  const total = Object.values(data).reduce((s, v) => s + v.count, 0) || 1;
  const order = ["confirmed", "processing", "shipped", "delivered", "draft", "cancelled"];
  return (
    <div className="space-y-3">
      <div className="h-2 rounded-full overflow-hidden flex bg-slate-100">
        {order.map((s) => {
          const pct = ((data[s]?.count || 0) / total) * 100;
          return pct > 0 ? <div key={s} className={`${statusColors[s]} transition-all`} style={{ width: `${pct}%` }} /> : null;
        })}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1.5">
        {order.filter((s) => data[s]?.count).map((s) => (
          <div key={s} className="flex items-center gap-1.5 text-xs text-slate-500">
            <div className={`w-2 h-2 rounded-full ${statusDots[s]}`} />
            <span>{statusLabels[s]}</span>
            <span className="font-semibold text-slate-700">{data[s].count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Alert Card ────────────────────────────────── */
function AlertCard({ href, count, label, icon, color }: {
  href: string; count: number; label: string; icon: React.ReactNode; color: string;
}) {
  const hasAlert = count > 0;
  const colorMap: Record<string, { bg: string; border: string; iconBg: string; hover: string }> = {
    orange: { bg: "bg-amber-50", border: "border-amber-200", iconBg: "bg-amber-100 text-amber-600", hover: "hover:bg-amber-100/70" },
    purple: { bg: "bg-violet-50", border: "border-violet-200", iconBg: "bg-violet-100 text-violet-600", hover: "hover:bg-violet-100/70" },
    red: { bg: "bg-rose-50", border: "border-rose-200", iconBg: "bg-rose-100 text-rose-600", hover: "hover:bg-rose-100/70" },
  };
  const c = colorMap[color];
  return (
    <Link href={href}>
      <div className={`rounded-xl p-5 transition-all duration-200 ${hasAlert ? `${c.bg} border ${c.border} ${c.hover}` : "card"}`}>
        <div className="flex items-center gap-4">
          <div className={`w-11 h-11 rounded-xl flex items-center justify-center ${hasAlert ? c.iconBg : "bg-slate-100 text-slate-400"}`}>
            {icon}
          </div>
          <div>
            <p className="text-2xl font-bold text-slate-900">{count}</p>
            <p className="text-xs text-slate-500">{label}</p>
          </div>
        </div>
      </div>
    </Link>
  );
}

/* ── Today Card ───────────────────────────────── */
function TodayCard({ label, value, sub, trend, icon }: {
  label: string; value: string | number; sub?: string;
  trend?: React.ReactNode; icon: React.ReactNode;
}) {
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">{label}</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{value}</p>
          <div className="flex items-center gap-2 mt-0.5">
            {sub && <p className="text-xs text-slate-400">{sub}</p>}
            {trend}
          </div>
        </div>
        <div className="w-10 h-10 rounded-xl bg-slate-50 flex items-center justify-center text-slate-400">
          {icon}
        </div>
      </div>
    </div>
  );
}

/* ── Period Selector ─────────────────────────────── */
function PeriodSelector({ value, onChange }: { value: number; onChange: (d: number) => void }) {
  const options = [
    { days: 7, label: "7д" },
    { days: 14, label: "14д" },
    { days: 30, label: "30д" },
  ];
  return (
    <div className="flex gap-1 bg-slate-100 rounded-lg p-0.5">
      {options.map((o) => (
        <button
          key={o.days}
          type="button"
          onClick={() => onChange(o.days)}
          className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
            value === o.days ? "bg-white shadow-sm text-slate-900" : "text-slate-500 hover:text-slate-700"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ── Icons ─────────────────────────────────────── */
const icons = {
  orders: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5V6a3.75 3.75 0 10-7.5 0v4.5m11.356-1.993l1.263 12c.07.665-.45 1.243-1.119 1.243H4.25a1.125 1.125 0 01-1.12-1.243l1.264-12A1.125 1.125 0 015.513 7.5h12.974c.576 0 1.059.435 1.119 1.007zM8.625 10.5a.375.375 0 11-.75 0 .375.375 0 01.75 0zm7.5 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" /></svg>,
  revenue: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" /></svg>,
  messages: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" /></svg>,
  active: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" /></svg>,
  handoff: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" /></svg>,
  cart: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 00-16.536-1.84M7.5 14.25L5.106 5.272M6 20.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm12.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z" /></svg>,
  anomaly: <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0-10.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" /></svg>,
};

/* ── Page ──────────────────────────────────────── */
export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [lowStock, setLowStock] = useState<LowStockItem[]>([]);
  const [chartDays, setChartDays] = useState(7);

  const load = (days?: number) => {
    const d = days ?? chartDays;
    api.get<Stats>(`/dashboard/stats?days=${d}`).then(setStats).catch(console.error);
    api.get<LowStockItem[]>("/dashboard/low-stock").then(setLowStock).catch(console.error);
  };

  useEffect(() => { load(); const id = setInterval(() => load(), 30_000); return () => clearInterval(id); }, []);

  const handlePeriodChange = (days: number) => {
    setChartDays(days);
    api.get<Stats>(`/dashboard/stats?days=${days}`).then(setStats).catch(console.error);
  };

  if (!stats) return <DashSkeleton />;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Дашборд</h1>
        <p className="text-sm text-slate-400 mt-0.5">Обзор вашего магазина</p>
      </div>

      {/* Row 1: Today stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <TodayCard
          label="Заказов сегодня"
          value={stats.today_orders}
          trend={<TrendBadge current={stats.today_orders} previous={stats.yesterday_orders} />}
          icon={icons.orders}
        />
        <TodayCard
          label="Выручка сегодня"
          value={stats.today_revenue > 0 ? fmtPrice(stats.today_revenue) : "0"}
          sub={stats.today_revenue > 0 ? "UZS" : undefined}
          trend={<TrendBadge current={stats.today_revenue} previous={stats.yesterday_revenue} />}
          icon={icons.revenue}
        />
        <TodayCard
          label="Сообщений сегодня"
          value={stats.today_messages}
          trend={<TrendBadge current={stats.today_messages} previous={stats.yesterday_messages} />}
          icon={icons.messages}
        />
        <TodayCard
          label="Активные диалоги"
          value={stats.active_conversations}
          sub="за последние 30 мин"
          icon={icons.active}
        />
      </div>

      {/* Row 2: Revenue hero + KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
        {/* Revenue card */}
        <div className="md:col-span-2 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white rounded-2xl p-7 relative overflow-hidden">
          {/* Decorative circles */}
          <div className="absolute -top-12 -right-12 w-40 h-40 rounded-full bg-indigo-500/10" />
          <div className="absolute -bottom-8 -left-8 w-32 h-32 rounded-full bg-violet-500/10" />
          <div className="relative">
            <p className="text-sm text-slate-400 mb-1">Общий доход</p>
            <p className="text-3xl font-bold tracking-tight">{fmtPrice(stats.total_revenue)} <span className="text-lg font-normal text-slate-500">UZS</span></p>
            <div className="flex gap-8 mt-5">
              {[
                { v: stats.total_orders, l: "заказов" },
                { v: stats.dm_conversations, l: "диалогов" },
                { v: `${stats.conversion_rate_pct}%`, l: "конверсия" },
              ].map(({ v, l }) => (
                <div key={l}>
                  <p className="text-xl font-bold">{v}</p>
                  <p className="text-[11px] text-slate-500">{l}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Leads pipeline */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-semibold text-slate-700">Лиды</p>
            <Link href="/leads" className="text-xs text-indigo-600 hover:text-indigo-700 font-medium">Все →</Link>
          </div>
          <p className="text-2xl font-bold text-slate-900 mb-3">{stats.total_leads}</p>
          <div className="space-y-2">
            {Object.entries(stats.leads_by_status || {}).filter(([, v]) => v > 0).map(([s, count]) => (
              <div key={s} className="flex items-center justify-between text-xs">
                <span className="text-slate-400">{leadLabels[s] || s}</span>
                <span className="font-semibold text-slate-600">{count}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Orders chart */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-semibold text-slate-700">Заказы</p>
            <PeriodSelector value={chartDays} onChange={handlePeriodChange} />
          </div>
          <MiniBarChart data={stats.orders_daily} lineData={stats.leads_daily} height={120} />
        </div>
      </div>

      {/* Row 3: Alerts */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <AlertCard href="/handoffs" count={stats.pending_handoffs} label="Ожидают оператора" color="orange" icon={icons.handoff} />
        <AlertCard href="/broadcast" count={stats.abandoned_carts} label="Брошенных корзин" color="purple" icon={icons.cart} />
        <AlertCard href="/training" count={stats.anomaly_conversations_7d} label="Аномалий AI (7д)" color="red" icon={icons.anomaly} />
      </div>

      {/* Row 4: Order status + Recent orders */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="card p-6">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">Заказы по статусам</h2>
          <StatusBar data={stats.orders_by_status} />
        </div>

        <div className="card overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-700">Последние заказы</h2>
            <Link href="/orders" className="text-xs text-indigo-600 hover:text-indigo-700 font-medium">Все заказы →</Link>
          </div>
          {stats.recent_orders.length === 0 ? (
            <div className="px-6 py-8 text-center text-slate-300 text-sm">Нет заказов</div>
          ) : (
            <div className="divide-y divide-slate-100">
              {stats.recent_orders.map((o) => (
                <div key={o.order_number} className="px-6 py-3.5 flex items-center justify-between hover:bg-slate-50/50 transition-colors">
                  <div className="flex items-center gap-3">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDots[o.status] || "bg-slate-300"}`} />
                    <div>
                      <span className="font-mono text-xs font-semibold text-slate-700">{o.order_number}</span>
                      <span className="text-xs text-slate-400 ml-2">{o.customer}</span>
                    </div>
                  </div>
                  <span className="text-sm font-semibold text-slate-700">{fmtPrice(o.amount)} <span className="text-slate-400 text-xs font-normal">UZS</span></span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Row 5: Low stock */}
      {lowStock.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-700">Заканчивается на складе <span className="ml-1.5 text-xs font-normal bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">{lowStock.length}</span></h2>
            <Link href="/products" className="text-xs text-indigo-600 hover:text-indigo-700 font-medium">Управление →</Link>
          </div>
          <div className="divide-y divide-slate-100">
            {lowStock.slice(0, 8).map((item) => (
              <div key={item.variant_id} className="px-6 py-3.5 flex items-center justify-between hover:bg-slate-50/50 transition-colors">
                <span className="text-sm font-medium text-slate-700">{item.title}</span>
                <div className="flex items-center gap-3 text-xs">
                  {item.reserved > 0 && <span className="text-amber-600">{item.reserved} резерв</span>}
                  <span className={`font-semibold px-2.5 py-1 rounded-md ${item.available <= 0 ? "bg-rose-50 text-rose-600" : "bg-amber-50 text-amber-600"}`}>
                    {item.available <= 0 ? "Нет в наличии" : `${item.available} шт`}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
