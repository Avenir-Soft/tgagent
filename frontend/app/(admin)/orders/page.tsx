"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import Link from "next/link";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { timeAgo } from "@/lib/time-ago";

interface OrderItem {
  id: string;
  product_name: string | null;
  variant_title: string | null;
  qty: number;
  unit_price: string;
  total_price: string;
}

interface Order {
  id: string;
  order_number: string;
  customer_name: string;
  phone: string;
  city: string | null;
  address: string | null;
  delivery_type: string | null;
  total_amount: string;
  currency: string;
  status: string;
  items: OrderItem[];
  created_at: string;
  lead_id?: string | null;
  conversation_id?: string | null;
}

const statusLabels: Record<string, string> = {
  draft: "Черновик", confirmed: "Подтверждён", processing: "В обработке",
  shipped: "Отправлен", delivered: "Доставлен", cancelled: "Отменён", returned: "Возврат",
};

const statusColors: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700", confirmed: "bg-blue-50 text-blue-700",
  processing: "bg-amber-50 text-amber-700", shipped: "bg-violet-50 text-violet-700",
  delivered: "bg-emerald-50 text-emerald-700", cancelled: "bg-rose-50 text-rose-700",
  returned: "bg-orange-50 text-orange-700",
};

const validTransitions: Record<string, string[]> = {
  draft: ["confirmed", "processing", "cancelled"],
  confirmed: ["processing", "shipped", "cancelled"],
  processing: ["shipped", "delivered", "cancelled"],
  shipped: ["delivered"],
  delivered: ["returned"], cancelled: [],
};

const orderFilters = [
  { value: "all", label: "Все" },
  { value: "draft", label: "Черновик" },
  { value: "confirmed", label: "Подтверждён" },
  { value: "processing", label: "В обработке" },
  { value: "shipped", label: "Отправлен" },
  { value: "delivered", label: "Доставлен" },
  { value: "cancelled", label: "Отменён" },
];

function fmt(val: string | number): string {
  return Number(val).toLocaleString("ru-RU");
}

function plural(n: number, one: string, few: string, many: string): string {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs >= 11 && abs <= 19) return `${n} ${many}`;
  if (last === 1) return `${n} ${one}`;
  if (last >= 2 && last <= 4) return `${n} ${few}`;
  return `${n} ${many}`;
}

type SortKey = "date" | "amount";
type DateFilter = "all" | "today" | "week" | "month";

const dateFilters: { value: DateFilter; label: string }[] = [
  { value: "all", label: "Все время" },
  { value: "today", label: "Сегодня" },
  { value: "week", label: "Неделя" },
  { value: "month", label: "Месяц" },
];

function getDateCutoff(filter: DateFilter): Date | null {
  if (filter === "all") return null;
  const now = new Date();
  if (filter === "today") return new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (filter === "week") return new Date(now.getTime() - 7 * 86400000);
  return new Date(now.getTime() - 30 * 86400000);
}

const PAGE_SIZE = 50;

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [dateFilter, setDateFilter] = useState<DateFilter>("all");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("date");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const { toast } = useToast();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const fetchOrders = useCallback(() => {
    const params = statusFilter !== "all" ? `?status=${statusFilter}` : "";
    api.get<Order[]>(`/orders${params}`).then(setOrders).catch(console.error);
  }, [statusFilter]);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  // Auto-refresh 30s
  useEffect(() => {
    const timer = setInterval(fetchOrders, 30000);
    return () => clearInterval(timer);
  }, [fetchOrders]);

  const updateStatus = async (id: string, newStatus: string) => {
    const prev = orders.find((o) => o.id === id)?.status;
    setOrders((list) => list.map((o) => (o.id === id ? { ...o, status: newStatus } : o)));
    try {
      await api.patch(`/orders/${id}`, { status: newStatus });
      toast(`Статус: ${statusLabels[newStatus]}`, "success");
    } catch {
      if (prev) setOrders((list) => list.map((o) => (o.id === id ? { ...o, status: prev } : o)));
      toast("Ошибка при обновлении статуса", "error");
    }
  };

  const filtered = useMemo(() => {
    let list = orders;
    // Date filter
    const cutoff = getDateCutoff(dateFilter);
    if (cutoff) list = list.filter((o) => new Date(o.created_at) >= cutoff);
    // Search
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (o) =>
          o.order_number.toLowerCase().includes(q) ||
          o.customer_name.toLowerCase().includes(q) ||
          o.phone.includes(q) ||
          (o.city || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [orders, search, dateFilter]);

  // Sort + paginate
  const sorted = useMemo(() => {
    const arr = [...filtered];
    if (sortBy === "amount") arr.sort((a, b) => Number(b.total_amount) - Number(a.total_amount));
    else arr.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    return arr;
  }, [filtered, sortBy]);

  const paginated = useMemo(() => sorted.slice(0, visibleCount), [sorted, visibleCount]);
  const hasMoreOrders = visibleCount < sorted.length;

  // Reset pagination on filter change
  useEffect(() => { setVisibleCount(PAGE_SIZE); }, [statusFilter, dateFilter, search]);

  // Summary stats
  const totalRevenue = useMemo(
    () => filtered.reduce((s, o) => s + (o.status !== "cancelled" ? Number(o.total_amount) : 0), 0),
    [filtered]
  );
  const activeCount = filtered.filter((o) => !["cancelled", "delivered"].includes(o.status)).length;

  // CSV export
  const exportCSV = () => {
    const header = "Номер;Клиент;Телефон;Город;Статус;Сумма (сум);Товаров;Дата\n";
    const rows = sorted.map((o) =>
      `${o.order_number};${o.customer_name};${o.phone};${o.city || ""};${statusLabels[o.status] || o.status};${o.total_amount};${o.items.length};${new Date(o.created_at).toLocaleDateString("ru")}`
    ).join("\n");
    const blob = new Blob(["\uFEFF" + header + rows], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `orders_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast("CSV скачан", "success");
  };

  const toggle = (id: string) => setExpandedId(expandedId === id ? null : id);

  const cancelledCount = orders.filter((o) => o.status === "cancelled" || o.status === "returned").length;

  const deleteCancelled = async () => {
    try {
      const res = await api.delete<{ deleted: number }>("/orders");
      toast(`Удалено ${res.deleted} заказов`, "success");
      setOrders((prev) => prev.filter((o) => o.status !== "cancelled" && o.status !== "returned"));
    } catch {
      toast("Ошибка при удалении", "error");
    }
  };

  return (
    <div>
      <PageHeader title={`Заказы (${orders.length})`} action={{ label: "Экспорт CSV", onClick: exportCSV }} />

      {/* Search + stats */}
      <div className="flex flex-col md:flex-row items-stretch md:items-center gap-3 md:gap-5 mb-3">
        <div className="relative flex-1">
          <input
            type="text"
            placeholder="Поиск по номеру, имени, телефону..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-white border border-slate-200 rounded-lg px-4 py-2 pl-10 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
          />
          <svg className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
        <div className="flex gap-3 md:gap-6 shrink-0">
          <div className="text-center bg-indigo-50 rounded-xl px-5 py-2.5 border border-indigo-100/60">
            <p className="text-2xl font-bold text-indigo-700">{activeCount}</p>
            <p className="text-xs text-indigo-500 font-medium">активных</p>
          </div>
          <div className="text-center bg-emerald-50 rounded-xl px-5 py-2.5 border border-emerald-100/60">
            <p className="text-2xl font-bold text-emerald-700">{fmt(totalRevenue)}</p>
            <p className="text-xs text-emerald-500 font-medium">сум</p>
          </div>
        </div>
      </div>

      {/* Sort + Date filter + Status filter pills */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span>Сортировка:</span>
          <button type="button" onClick={() => setSortBy("date")} className={`px-2 py-1 rounded transition-colors ${sortBy === "date" ? "bg-indigo-100 text-indigo-700 font-medium" : "hover:bg-slate-100"}`}>по дате</button>
          <button type="button" onClick={() => setSortBy("amount")} className={`px-2 py-1 rounded transition-colors ${sortBy === "amount" ? "bg-indigo-100 text-indigo-700 font-medium" : "hover:bg-slate-100"}`}>по сумме</button>
        </div>
        <div className="flex items-center gap-1.5">
          {dateFilters.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setDateFilter(f.value)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                dateFilter === f.value
                  ? "bg-indigo-600 text-white"
                  : "bg-white text-slate-500 border border-slate-200 hover:bg-slate-50"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {orderFilters.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setStatusFilter(f.value)}
            className={`px-5 py-2 rounded-full text-sm font-medium transition-colors ${
              statusFilter === f.value
                ? "bg-indigo-600 text-white shadow-sm"
                : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
            }`}
          >
            {f.label}
          </button>
        ))}
        {cancelledCount > 0 && (
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className="ml-auto px-4 py-2 rounded-full text-xs font-medium text-rose-600 border border-rose-200 hover:bg-rose-50 transition-colors"
          >
            Очистить отменённые ({cancelledCount})
          </button>
        )}
      </div>

      {/* Orders list */}
      <div className="space-y-3">
        {paginated.length === 0 ? (
          <EmptyState message={search ? "Ничего не найдено" : "Нет заказов"} />
        ) : (
          paginated.map((o) => (
            <div key={o.id} className={`card overflow-hidden ${o.status === "cancelled" ? "opacity-60" : ""}`}>
              {/* Header */}
              <div className="flex items-center gap-4 px-5 py-4 cursor-pointer hover:bg-slate-50/50 transition-colors" onClick={() => toggle(o.id)}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-mono text-sm font-bold text-slate-900">{o.order_number}</span>
                    {(validTransitions[o.status] || []).length > 0 ? (
                      <select
                        value={o.status}
                        onChange={(e) => { e.stopPropagation(); updateStatus(o.id, e.target.value); }}
                        onClick={(e) => e.stopPropagation()}
                        className={`px-2 py-0.5 rounded text-xs border-none cursor-pointer ${statusColors[o.status] || "bg-slate-100"}`}
                      >
                        <option value={o.status}>{statusLabels[o.status]}</option>
                        {(validTransitions[o.status] || []).map((val) => (
                          <option key={val} value={val}>{statusLabels[val]}</option>
                        ))}
                      </select>
                    ) : (
                      <span className={`px-2 py-0.5 rounded text-xs ${statusColors[o.status] || "bg-slate-100"}`}>{statusLabels[o.status]}</span>
                    )}
                    <span className="text-xs text-slate-400">{plural(o.items.length, "товар", "товара", "товаров")}</span>
                  </div>
                  <div className="text-sm text-slate-500 mt-1 flex items-center gap-2 flex-wrap">
                    <span className="font-medium">{o.customer_name}</span>
                    <span className="text-slate-300">&middot;</span>
                    <span>{o.phone}</span>
                    {o.city && <><span className="text-slate-300">&middot;</span><span>{o.city}</span></>}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="font-bold text-lg text-slate-900">{fmt(o.total_amount)} <span className="text-xs font-normal text-slate-400">сум</span></div>
                  <div className="text-xs text-slate-400">{timeAgo(o.created_at)}</div>
                </div>
                <div className="text-slate-300 shrink-0 text-lg">{expandedId === o.id ? "\u25B2" : "\u25BC"}</div>
              </div>

              {/* Expanded */}
              {expandedId === o.id && (
                <div className="border-t border-slate-100 px-5 py-4 bg-slate-50/50">
                  <div className="mb-4">
                    <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">Товары</h3>
                    <div className="space-y-2">
                      {o.items.map((item) => (
                        <div key={item.id} className="flex items-center justify-between bg-white rounded-lg px-4 py-2.5 border border-slate-100">
                          <div>
                            <p className="font-medium text-sm text-slate-900">{item.variant_title || item.product_name || "Товар"}</p>
                            {item.product_name && item.variant_title && (
                              <p className="text-xs text-slate-400">{item.product_name}</p>
                            )}
                          </div>
                          <div className="text-right">
                            <p className="text-sm text-slate-900">
                              {item.qty > 1 && <span className="text-slate-500">{item.qty} x </span>}
                              {fmt(item.unit_price)} сум
                            </p>
                            {item.qty > 1 && <p className="text-xs text-slate-400">= {fmt(item.total_price)}</p>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {(o.address || o.delivery_type) && (
                    <div className="mb-3">
                      <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Доставка</h3>
                      <div className="text-sm space-y-0.5">
                        {o.delivery_type && (
                          <span className="px-2 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700">
                            {o.delivery_type === "courier" || o.delivery_type?.toLowerCase().includes("кур") || o.delivery_type === "Kuryer orqali"
                              ? "Курьер" : o.delivery_type === "pickup" || o.delivery_type?.toLowerCase().includes("само")
                              ? "Самовывоз" : o.delivery_type}
                          </span>
                        )}
                        {o.city && <p className="font-medium mt-1 text-slate-700">{o.city}{o.address && `, ${o.address}`}</p>}
                      </div>
                    </div>
                  )}

                  <div className="flex justify-between items-center pt-3 border-t border-slate-100">
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-slate-400">
                        {new Date(o.created_at).toLocaleString("ru", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })}
                      </span>
                      {o.conversation_id && (
                        <Link
                          href={`/conversations/${o.conversation_id}`}
                          className="text-xs text-indigo-600 hover:text-indigo-700 hover:underline font-medium transition-colors"
                          onClick={(e) => e.stopPropagation()}
                        >
                          Открыть диалог →
                        </Link>
                      )}
                      {o.lead_id && (
                        <Link
                          href="/leads"
                          className="text-xs text-emerald-600 hover:text-emerald-700 font-medium"
                          onClick={(e) => e.stopPropagation()}
                        >
                          Лид →
                        </Link>
                      )}
                    </div>
                    <div className="font-bold text-lg text-slate-900">{fmt(o.total_amount)} сум</div>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {hasMoreOrders && (
        <div className="text-center mt-4">
          <button
            type="button"
            onClick={() => setVisibleCount((prev) => prev + PAGE_SIZE)}
            className="bg-white border border-slate-200 hover:bg-slate-50 text-indigo-600 rounded-lg px-6 py-2 text-sm font-medium transition-colors shadow-sm"
          >
            Загрузить ещё ({sorted.length - visibleCount} осталось)
          </button>
        </div>
      )}

      {filtered.length > 0 && (
        <div className="text-xs text-slate-400 mt-2 text-right">
          Показано {Math.min(visibleCount, sorted.length)} из {filtered.length}{filtered.length !== orders.length ? ` (всего ${orders.length})` : ""}
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Удалить отменённые заказы"
        message={`Удалить ${cancelledCount} отменённых/возвращённых заказов? Это действие нельзя отменить.`}
        confirmText="Удалить"
        variant="danger"
        onConfirm={() => { setConfirmDelete(false); deleteCancelled(); }}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
