"use client";

import { Fragment, useEffect, useState, useMemo, useCallback } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { timeAgo } from "@/lib/time-ago";
import { getInitial } from "@/lib/utils";

interface Lead {
  id: string;
  customer_name: string | null;
  telegram_user_id: number;
  telegram_username: string | null;
  phone: string | null;
  city: string | null;
  status: string;
  source: string;
  notes: string | null;
  conversation_id: string | null;
  interested_product_id: string | null;
  created_at: string;
  updated_at: string;
}

interface Order {
  id: string;
  order_number: string;
  status: string;
  total_amount: number;
  created_at: string;
}

const statusConfig: Record<string, { label: string; color: string; bg: string; dot: string }> = {
  new:        { label: "Новый",          color: "text-blue-700",    bg: "bg-blue-50",     dot: "bg-blue-500" },
  contacted:  { label: "Связались",      color: "text-amber-700",   bg: "bg-amber-50",    dot: "bg-amber-500" },
  qualified:  { label: "Квалифицирован", color: "text-violet-700",  bg: "bg-violet-50",   dot: "bg-violet-500" },
  converted:  { label: "Конвертирован",  color: "text-emerald-700", bg: "bg-emerald-50",  dot: "bg-emerald-500" },
  lost:       { label: "Потерян",        color: "text-rose-700",    bg: "bg-rose-50",     dot: "bg-rose-400" },
};

const statusOrder = ["new", "contacted", "qualified", "converted", "lost"];

const sourceLabels: Record<string, string> = { dm: "DM", comment: "Коммент", manual: "Вручную" };

const orderStatusLabels: Record<string, string> = {
  draft: "Черновик", confirmed: "Подтверждён", processing: "В обработке",
  shipped: "Отправлен", delivered: "Доставлен", cancelled: "Отменён",
};

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sortBy, setSortBy] = useState<"date" | "name">("date");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [ordersMap, setOrdersMap] = useState<Record<string, Order[]>>({});
  const [loadingOrders, setLoadingOrders] = useState<string | null>(null);
  const [editingNotes, setEditingNotes] = useState<string | null>(null);
  const [notesText, setNotesText] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  const { toast } = useToast();

  const load = useCallback(() => {
    const params = filter !== "all" ? `?status=${filter}` : "";
    api.get<Lead[]>(`/leads${params}`).then(setLeads).catch(console.error);
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);

  // Load orders when expanding a lead
  const toggleExpand = async (lead: Lead) => {
    if (expandedId === lead.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(lead.id);
    if (!ordersMap[lead.id]) {
      setLoadingOrders(lead.id);
      try {
        const orders = await api.get<Order[]>("/orders");
        // Filter orders by matching customer name or phone
        const leadOrders = orders.filter(
          (o: Order & { customer_name?: string; phone?: string }) =>
            (lead.customer_name && (o as any).customer_name === lead.customer_name) ||
            (lead.phone && (o as any).phone === lead.phone)
        );
        setOrdersMap((prev) => ({ ...prev, [lead.id]: leadOrders }));
      } catch {
        setOrdersMap((prev) => ({ ...prev, [lead.id]: [] }));
      }
      setLoadingOrders(null);
    }
  };

  const exportCSV = () => {
    const header = "Имя;Username;Телефон;Город;Статус;Источник;Заметки;Дата\n";
    const rows = filtered.map((l) =>
      `${l.customer_name || ""};${l.telegram_username || ""};${l.phone || ""};${l.city || ""};${statusConfig[l.status]?.label || l.status};${sourceLabels[l.source] || l.source};${(l.notes || "").replace(/;/g, ",")};${new Date(l.created_at).toLocaleDateString("ru")}`
    ).join("\n");
    const blob = new Blob(["\uFEFF" + header + rows], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `leads_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const updateStatus = async (id: string, status: string) => {
    try {
      await api.patch(`/leads/${id}`, { status });
      setLeads((prev) => prev.map((l) => (l.id === id ? { ...l, status } : l)));
      toast(`Статус изменён: ${statusConfig[status]?.label || status}`, "success");
    } catch {
      toast("Ошибка обновления статуса", "error");
    }
  };

  const bulkUpdateStatus = async (status: string) => {
    if (selected.size === 0) return;
    try {
      await Promise.all([...selected].map((id) => api.patch(`/leads/${id}`, { status })));
      setLeads((prev) => prev.map((l) => selected.has(l.id) ? { ...l, status } : l));
      toast(`${selected.size} лидов -> ${statusConfig[status]?.label}`, "success");
      setSelected(new Set());
    } catch {
      toast("Ошибка массового обновления", "error");
    }
  };

  const saveNotes = async (id: string) => {
    setSavingNotes(true);
    try {
      await api.patch(`/leads/${id}`, { notes: notesText || null });
      setLeads((prev) => prev.map((l) => (l.id === id ? { ...l, notes: notesText || null } : l)));
      setEditingNotes(null);
      toast("Заметка сохранена", "success");
    } catch {
      toast("Ошибка сохранения заметки", "error");
    }
    setSavingNotes(false);
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((l) => l.id)));
    }
  };

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: leads.length };
    for (const l of leads) c[l.status] = (c[l.status] || 0) + 1;
    return c;
  }, [leads]);

  const filtered = useMemo(() => {
    let list = leads;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (l) =>
          (l.customer_name || "").toLowerCase().includes(q) ||
          (l.telegram_username || "").toLowerCase().includes(q) ||
          (l.phone || "").includes(q) ||
          (l.city || "").toLowerCase().includes(q) ||
          (l.notes || "").toLowerCase().includes(q)
      );
    }
    return [...list].sort((a, b) => {
      if (sortBy === "name") return (a.customer_name || "").localeCompare(b.customer_name || "");
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [leads, search, sortBy]);

  return (
    <div>
      <PageHeader title={`Лиды (${leads.length})`} action={{ label: "Экспорт CSV", onClick: exportCSV }} />

      {/* Pipeline cards */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mb-4">
        <button
          type="button"
          onClick={() => setFilter("all")}
          className={`rounded-xl px-3 py-3 text-center transition-all duration-200 ${filter === "all" ? "bg-slate-900 text-white shadow-sm" : "card cursor-pointer"}`}
        >
          <p className="text-xl font-bold">{counts.all || 0}</p>
          <p className="text-[10px] mt-0.5 opacity-70">Все</p>
        </button>
        {statusOrder.map((s) => {
          const cfg = statusConfig[s];
          const isActive = filter === s;
          return (
            <button
              key={s}
              type="button"
              onClick={() => setFilter(s)}
              className={`rounded-xl px-3 py-3 text-center transition-all duration-200 ${isActive ? `${cfg.bg} ring-2 ring-offset-1 ring-current ${cfg.color}` : "card cursor-pointer"}`}
            >
              <p className="text-xl font-bold">{counts[s] || 0}</p>
              <p className={`text-[10px] mt-0.5 ${isActive ? cfg.color : "text-slate-500"}`}>{cfg.label}</p>
            </button>
          );
        })}
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="relative flex-1">
          <input
            type="text"
            placeholder="Поиск по имени, username, телефону, городу, заметкам..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-white border border-slate-200 rounded-lg px-4 py-2.5 pl-10 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
          />
          <svg className="absolute left-3 top-3 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as "date" | "name")}
          className="bg-white border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
          aria-label="Сортировка"
        >
          <option value="date">По дате</option>
          <option value="name">По имени</option>
        </select>
        {selected.size > 0 && (
          <div className="flex items-center gap-2 bg-indigo-50 rounded-xl px-3 py-2">
            <span className="text-xs text-indigo-700 font-medium">{selected.size} выбрано</span>
            {statusOrder.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => bulkUpdateStatus(s)}
                className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${statusConfig[s].bg} ${statusConfig[s].color} hover:opacity-80`}
              >
                {statusConfig[s].label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Table */}
      <div className="card overflow-x-auto">
        {filtered.length === 0 ? (
          <EmptyState message={search ? "Ничего не найдено" : "Нет лидов"} />
        ) : (
          <table className="w-full text-sm min-w-[760px]">
            <thead>
              <tr className="border-b border-slate-100">
                <th className="pl-4 py-3 w-8">
                  <input
                    type="checkbox"
                    checked={selected.size === filtered.length && filtered.length > 0}
                    onChange={toggleSelectAll}
                    className="rounded"
                  />
                </th>
                <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Клиент</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Контакты</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Источник</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Заметки</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Дата</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-36">Статус</th>
                <th className="px-3 py-3 w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((l) => {
                const cfg = statusConfig[l.status] || statusConfig.new;
                const isExpanded = expandedId === l.id;
                return (
                  <Fragment key={l.id}>
                    <tr className={`hover:bg-slate-50/50 transition-colors ${selected.has(l.id) ? "bg-indigo-50/50" : ""} ${isExpanded ? "bg-slate-50/30" : ""}`}>
                      <td className="pl-4 py-3">
                        <input
                          type="checkbox"
                          checked={selected.has(l.id)}
                          onChange={() => toggleSelect(l.id)}
                          className="rounded"
                        />
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-3">
                          <div className={`w-8 h-8 rounded-full ${cfg.bg} ${cfg.color} flex items-center justify-center text-sm font-bold shrink-0`}>
                            {getInitial(l.customer_name)}
                          </div>
                          <div className="min-w-0">
                            <p className="font-medium text-sm text-slate-900 truncate">{l.customer_name || "Без имени"}</p>
                            {l.telegram_username && (
                              <a
                                href={`https://t.me/${l.telegram_username.replace(/^@/, "")}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-indigo-500 hover:text-indigo-700 truncate block"
                              >
                                @{l.telegram_username}
                              </a>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="space-y-0.5">
                          {l.phone && <p className="text-xs text-slate-600">{l.phone}</p>}
                          {l.city && <p className="text-xs text-slate-400">{l.city}</p>}
                          {!l.phone && !l.city && <span className="text-xs text-slate-300">-</span>}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-1.5">
                          <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-slate-100 text-slate-600">
                            {sourceLabels[l.source] || l.source}
                          </span>
                          {l.conversation_id && (
                            <Link
                              href={`/conversations/${l.conversation_id}`}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-indigo-50 text-indigo-600 hover:bg-indigo-100 transition-colors"
                              title="Открыть диалог"
                            >
                              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                              </svg>
                              Диалог
                            </Link>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-3 max-w-[200px]">
                        {editingNotes === l.id ? (
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              value={notesText}
                              onChange={(e) => setNotesText(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") saveNotes(l.id);
                                if (e.key === "Escape") setEditingNotes(null);
                              }}
                              placeholder="Заметка..."
                              className="flex-1 border border-indigo-300 rounded px-2 py-1 text-xs focus:ring-1 focus:ring-indigo-500 outline-none"
                              autoFocus
                              disabled={savingNotes}
                            />
                            <button
                              type="button"
                              onClick={() => saveNotes(l.id)}
                              disabled={savingNotes}
                              className="text-emerald-600 hover:text-emerald-800 p-0.5"
                              title="Сохранить"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                              </svg>
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingNotes(null)}
                              className="text-slate-400 hover:text-slate-600 p-0.5"
                              title="Отмена"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => { setEditingNotes(l.id); setNotesText(l.notes || ""); }}
                            className="text-left w-full group"
                            title="Редактировать заметку"
                          >
                            {l.notes ? (
                              <span className="text-xs text-slate-600 truncate block group-hover:text-indigo-600 transition-colors">{l.notes}</span>
                            ) : (
                              <span className="text-xs text-slate-300 group-hover:text-indigo-400 transition-colors">+ заметка</span>
                            )}
                          </button>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <span className="text-xs text-slate-400" title={new Date(l.created_at).toLocaleString("ru")}>
                          {timeAgo(l.created_at)}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <select
                          title="Статус лида"
                          value={l.status}
                          onChange={(e) => updateStatus(l.id, e.target.value)}
                          className={`px-2.5 py-1 rounded-lg text-xs font-medium border-none cursor-pointer transition-colors ${cfg.bg} ${cfg.color}`}
                        >
                          {statusOrder.map((s) => (
                            <option key={s} value={s}>{statusConfig[s].label}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-2 py-3">
                        <button
                          type="button"
                          onClick={() => toggleExpand(l)}
                          className={`p-1 rounded-md transition-colors ${isExpanded ? "bg-indigo-100 text-indigo-600" : "text-slate-400 hover:text-slate-600 hover:bg-slate-100"}`}
                          title="История"
                        >
                          <svg className={`w-4 h-4 transition-transform ${isExpanded ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                          </svg>
                        </button>
                      </td>
                    </tr>

                    {/* Expanded row: contact history + orders */}
                    {isExpanded && (
                      <tr>
                        <td colSpan={8} className="bg-slate-50/80 px-4 py-4">
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-4xl ml-12">
                            {/* Lead details */}
                            <div>
                              <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Информация</h4>
                              <div className="space-y-1.5 text-xs">
                                <div className="flex justify-between">
                                  <span className="text-slate-400">Telegram ID</span>
                                  <span className="text-slate-700 font-mono">{l.telegram_user_id}</span>
                                </div>
                                {l.telegram_username && (
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Username</span>
                                    <a href={`https://t.me/${l.telegram_username.replace(/^@/, "")}`} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline">@{l.telegram_username}</a>
                                  </div>
                                )}
                                {l.phone && (
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Телефон</span>
                                    <span className="text-slate-700">{l.phone}</span>
                                  </div>
                                )}
                                {l.city && (
                                  <div className="flex justify-between">
                                    <span className="text-slate-400">Город</span>
                                    <span className="text-slate-700">{l.city}</span>
                                  </div>
                                )}
                                <div className="flex justify-between">
                                  <span className="text-slate-400">Создан</span>
                                  <span className="text-slate-700">{new Date(l.created_at).toLocaleString("ru")}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-slate-400">Обновлён</span>
                                  <span className="text-slate-700">{new Date(l.updated_at).toLocaleString("ru")}</span>
                                </div>
                                {l.conversation_id && (
                                  <div className="pt-2">
                                    <Link
                                      href={`/conversations/${l.conversation_id}`}
                                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
                                    >
                                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                                      </svg>
                                      Открыть диалог
                                    </Link>
                                  </div>
                                )}
                              </div>
                            </div>

                            {/* Orders history */}
                            <div>
                              <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Заказы</h4>
                              {loadingOrders === l.id ? (
                                <p className="text-xs text-slate-400">Загрузка...</p>
                              ) : (ordersMap[l.id] || []).length === 0 ? (
                                <p className="text-xs text-slate-400">Нет заказов</p>
                              ) : (
                                <div className="space-y-2">
                                  {(ordersMap[l.id] || []).map((o) => (
                                    <div key={o.id} className="flex items-center justify-between bg-white rounded-lg px-3 py-2 border border-slate-100">
                                      <div>
                                        <span className="text-xs font-mono font-medium text-slate-700">{o.order_number}</span>
                                        <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                          o.status === "delivered" ? "bg-emerald-50 text-emerald-700" :
                                          o.status === "cancelled" ? "bg-rose-50 text-rose-700" :
                                          "bg-slate-100 text-slate-600"
                                        }`}>
                                          {orderStatusLabels[o.status] || o.status}
                                        </span>
                                      </div>
                                      <div className="text-right">
                                        <p className="text-xs font-medium text-slate-700">{Number(o.total_amount).toLocaleString("ru")} сум</p>
                                        <p className="text-[10px] text-slate-400">{new Date(o.created_at).toLocaleDateString("ru")}</p>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {filtered.length > 0 && (
        <div className="text-xs text-slate-400 mt-2 text-right">
          Показано {filtered.length} из {leads.length}
        </div>
      )}
    </div>
  );
}
