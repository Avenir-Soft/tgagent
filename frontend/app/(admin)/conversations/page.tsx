"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import Link from "next/link";
import { PageHeader } from "@/components/ui/page-header";
import { FilterBar } from "@/components/ui/filter-bar";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { timeAgo } from "@/lib/time-ago";

interface Conversation {
  id: string;
  telegram_chat_id: number;
  telegram_user_id: number;
  telegram_username: string | null;
  telegram_first_name: string | null;
  source_type: string;
  status: string;
  state: string;
  state_context: Record<string, any> | null;
  ai_enabled: boolean;
  last_message_at: string | null;
  created_at: string;
  last_message_text: string | null;
  last_message_sender_type: string | null;
  unread_count: number;
}

const statusColors: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-700",
  handoff: "bg-amber-50 text-amber-700",
  closed: "bg-slate-100 text-slate-500",
};

const statusLabels: Record<string, string> = {
  active: "Активен",
  handoff: "Оператор",
  closed: "Закрыт",
};

const stateLabels: Record<string, string> = {
  idle: "Ожидание",
  browsing: "Просматривает",
  selection: "Выбирает",
  cart: "Корзина",
  checkout: "Оформление",
  post_order: "Заказ",
  handoff: "Оператор",
};

const stateColors: Record<string, string> = {
  idle: "bg-slate-100 text-slate-400",
  browsing: "bg-blue-50 text-blue-600",
  selection: "bg-indigo-50 text-indigo-600",
  cart: "bg-violet-50 text-violet-700",
  checkout: "bg-amber-50 text-amber-700",
  post_order: "bg-emerald-50 text-emerald-700",
  handoff: "bg-amber-50 text-amber-600",
};

const senderLabels: Record<string, string> = {
  customer: "Клиент",
  ai: "AI",
  human_admin: "Оператор",
  system: "Система",
};

const statusFilters = [
  { value: "all", label: "Все" },
  { value: "active", label: "Активные" },
  { value: "handoff", label: "Оператор" },
  { value: "closed", label: "Закрытые" },
];

const sourceFilters = [
  { value: "all", label: "Все" },
  { value: "dm", label: "Личные" },
  { value: "comment_thread", label: "Комменты" },
];

function getCartItemsCount(ctx: Record<string, any> | null): number {
  if (!ctx?.cart_items) return 0;
  return (ctx.cart_items as any[]).reduce((sum: number, item: any) => sum + (item.qty || 1), 0);
}

function getOrdersCount(ctx: Record<string, any> | null): number {
  if (!ctx?.orders) return 0;
  return (ctx.orders as any[]).length;
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "...";
}

/* Skeleton card */
function SkeletonCard() {
  return (
    <div className="card px-5 py-4 flex items-center gap-4 animate-pulse">
      <div className="w-10 h-10 rounded-full bg-slate-200 shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="h-4 bg-slate-200 rounded w-1/3" />
        <div className="h-3 bg-slate-100 rounded w-2/3" />
      </div>
      <div className="w-10 h-5 bg-slate-200 rounded-full shrink-0" />
    </div>
  );
}

function getReadCounts(): Record<string, number> {
  try { return JSON.parse(localStorage.getItem("conv_read_counts") || "{}"); } catch { return {}; }
}

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"activity" | "created">("activity");
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const PAGE_SIZE = 50;
  const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const focusedRef = useRef(true);

  // Delete state
  const [deletingConv, setDeletingConv] = useState<Conversation | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const { toast } = useToast();

  const fetchConversations = useCallback(
    async (reset = true) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      if (!reset) params.set("offset", String((page + 1) * PAGE_SIZE));
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (sourceFilter !== "all") params.set("source_type", sourceFilter);

      try {
        const data = await api.get<Conversation[]>(`/conversations?${params}`);
        if (reset) {
          setConversations(data);
          setPage(0);
        } else {
          setConversations((prev) => [...prev, ...data]);
          setPage((p) => p + 1);
        }
        setHasMore(data.length >= PAGE_SIZE);
      } catch {
        // handled by api interceptor
      } finally {
        setLoading(false);
      }
    },
    [statusFilter, sourceFilter, page],
  );

  // Initial load + filter change
  useEffect(() => {
    setLoading(true);
    setPage(0);
    fetchConversations(true);
  }, [statusFilter, sourceFilter]);

  // Auto-refresh: 5s focused, 20s blurred
  useEffect(() => {
    const tick = () => {
      if (document.hidden) return;
      fetchConversations(true);
    };
    const startInterval = () => {
      if (refreshRef.current) clearInterval(refreshRef.current);
      refreshRef.current = setInterval(tick, focusedRef.current ? 5000 : 20000);
    };
    const onVisibility = () => {
      focusedRef.current = !document.hidden;
      startInterval();
    };
    startInterval();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      if (refreshRef.current) clearInterval(refreshRef.current);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [statusFilter, sourceFilter]);

  const toggleAi = async (id: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await api.patch(`/conversations/${id}/toggle-ai`);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, ai_enabled: !c.ai_enabled } : c)),
      );
    } catch {
      // handled
    }
  };

  const deleteConversation = async () => {
    if (!deletingConv) return;
    setDeleteLoading(true);
    try {
      await api.delete(`/conversations/${deletingConv.id}`);
      setConversations((prev) => prev.filter((c) => c.id !== deletingConv.id));
      toast("Диалог удалён", "success");
    } catch {
      toast("Ошибка удаления", "error");
    } finally {
      setDeleteLoading(false);
      setDeletingConv(null);
    }
  };

  const filtered = useMemo(() => {
    let list = conversations;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (c) =>
          (c.telegram_first_name || "").toLowerCase().includes(q) ||
          (c.telegram_username || "").toLowerCase().includes(q) ||
          String(c.telegram_user_id).includes(q),
      );
    }
    return [...list].sort((a, b) => {
      if (sortBy === "activity") {
        const at = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
        const bt = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
        return bt - at;
      }
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [conversations, search, sortBy]);

  const totalUnread = useMemo(
    () => conversations.reduce((sum, c) => sum + (c.unread_count || 0), 0),
    [conversations],
  );

  // Status counts from loaded data (approximate)
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: conversations.length, active: 0, handoff: 0, closed: 0 };
    for (const c of conversations) counts[c.status] = (counts[c.status] || 0) + 1;
    return counts;
  }, [conversations]);

  return (
    <div>
      <PageHeader title="Диалоги" badge={totalUnread}>
        <FilterBar filters={sourceFilters} selected={sourceFilter} onChange={setSourceFilter} size="xs" />
      </PageHeader>

      {/* Status filter + search */}
      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <div className="flex gap-1.5">
          {statusFilters.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setStatusFilter(f.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                statusFilter === f.value
                  ? "bg-indigo-600 text-white"
                  : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex-1">
          <div className="relative">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
            </svg>
            <input
              type="text"
              placeholder="Поиск по имени, username..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-white border border-slate-200 rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
            />
          </div>
        </div>
        <div className="flex items-center gap-1 text-xs text-slate-500 shrink-0">
          <span>Сорт:</span>
          <button type="button" onClick={() => setSortBy("activity")} className={`px-2 py-1 rounded transition-colors ${sortBy === "activity" ? "bg-indigo-100 text-indigo-700 font-medium" : "hover:bg-slate-100"}`}>активность</button>
          <button type="button" onClick={() => setSortBy("created")} className={`px-2 py-1 rounded transition-colors ${sortBy === "created" ? "bg-indigo-100 text-indigo-700 font-medium" : "hover:bg-slate-100"}`}>дата</button>
        </div>
      </div>

      {/* Conversation list */}
      <div className="space-y-2">
        {loading && conversations.length === 0 ? (
          <>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </>
        ) : filtered.length === 0 ? (
          <EmptyState message={search ? "Ничего не найдено" : "Нет диалогов"} />
        ) : (
          filtered.map((c) => {
            const cartCount = getCartItemsCount(c.state_context);
            const ordersCount = getOrdersCount(c.state_context);
            const unread = c.unread_count || 0;

            return (
              <Link key={c.id} href={`/conversations/${c.id}`} className="block group">
                <div className={`card px-5 py-4 flex items-center gap-4 transition-all group-hover:shadow-md group-hover:border-slate-300 ${
                  unread > 0 ? "border-l-3 border-l-indigo-500" : ""
                }`}>
                  {/* Avatar */}
                  <div className="relative shrink-0">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold ${
                      c.source_type === "dm"
                        ? "bg-indigo-50 text-indigo-600"
                        : "bg-violet-50 text-violet-600"
                    }`}>
                      {c.telegram_first_name
                        ? c.telegram_first_name.charAt(0).toUpperCase()
                        : c.source_type === "dm" ? "D" : "C"}
                    </div>
                    {unread > 0 && (
                      <span className="absolute -top-1 -right-1 w-5 h-5 bg-indigo-600 text-white text-[10px] font-bold rounded-full flex items-center justify-center">
                        {unread > 9 ? "9+" : unread}
                      </span>
                    )}
                  </div>

                  {/* Main content */}
                  <div className="flex-1 min-w-0">
                    {/* First line: name + badges */}
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`font-medium text-sm ${unread > 0 ? "text-slate-900" : "text-slate-700"}`}>
                        {c.telegram_first_name || (c.source_type === "dm" ? "Личное сообщение" : "Комментарий")}
                      </span>
                      {c.telegram_username && (
                        <span className="text-xs text-indigo-500">@{c.telegram_username}</span>
                      )}
                      {!c.telegram_username && !c.telegram_first_name && (
                        <span className="text-xs text-slate-400 font-mono">#{c.telegram_user_id}</span>
                      )}

                      {/* Cart badge */}
                      {cartCount > 0 && (
                        <span className="inline-flex items-center gap-1 bg-violet-50 text-violet-700 text-xs px-1.5 py-0.5 rounded-full">
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z" />
                          </svg>
                          {cartCount}
                        </span>
                      )}
                      {/* Order badge */}
                      {ordersCount > 0 && (
                        <span className="inline-flex items-center gap-1 bg-emerald-50 text-emerald-700 text-xs px-1.5 py-0.5 rounded-full">
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                          </svg>
                          {ordersCount}
                        </span>
                      )}

                      <StatusBadge status={c.status} colorMap={statusColors} labels={statusLabels} />
                      {c.state && c.state !== "idle" && (
                        <StatusBadge status={c.state} colorMap={stateColors} labels={stateLabels} />
                      )}
                    </div>

                    {/* Second line: last message preview */}
                    {c.last_message_text && (
                      <p className={`text-xs mt-1 truncate max-w-[500px] ${unread > 0 ? "text-slate-600 font-medium" : "text-slate-400"}`}>
                        <span className="text-slate-400 font-normal">
                          {senderLabels[c.last_message_sender_type || ""] || ""}:{" "}
                        </span>
                        {truncate(c.last_message_text, 80)}
                      </p>
                    )}
                  </div>

                  {/* Right side: time + AI toggle */}
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-xs text-slate-400 whitespace-nowrap">
                      {timeAgo(c.last_message_at)}
                    </span>

                    {/* AI toggle */}
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-slate-400 uppercase tracking-wide">AI</span>
                      <button
                        type="button"
                        title={c.ai_enabled ? "Выключить AI" : "Включить AI"}
                        onClick={(e) => toggleAi(c.id, e)}
                        className={`w-9 h-5 rounded-full transition-colors ${
                          c.ai_enabled ? "bg-emerald-500" : "bg-slate-300"
                        }`}
                      >
                        <div
                          className={`w-3.5 h-3.5 bg-white rounded-full shadow-sm transform transition-transform ${
                            c.ai_enabled ? "translate-x-[18px]" : "translate-x-[3px]"
                          }`}
                        />
                      </button>
                    </div>

                    {/* Delete */}
                    <button
                      type="button"
                      title="Удалить диалог"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); setDeletingConv(c); }}
                      className="w-7 h-7 rounded-full flex items-center justify-center text-slate-300 hover:text-rose-500 hover:bg-rose-50 opacity-0 group-hover:opacity-100 transition-all"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                      </svg>
                    </button>

                    {/* Arrow */}
                    <svg className="w-4 h-4 text-slate-300 group-hover:text-slate-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path d="M9 5l7 7-7 7" />
                    </svg>
                  </div>
                </div>
              </Link>
            );
          })
        )}

        {hasMore && !search && (
          <div className="text-center mt-4">
            <button
              type="button"
              onClick={() => fetchConversations(false)}
              className="bg-white border border-slate-200 hover:bg-slate-50 text-indigo-600 rounded-lg px-6 py-2 text-sm font-medium transition-colors shadow-sm"
            >
              Загрузить ещё
            </button>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!deletingConv}
        title="Удалить диалог?"
        message={`Диалог с ${deletingConv?.telegram_first_name || "клиентом"} будет удалён вместе со всеми сообщениями, заказами и лидами. Это действие необратимо.`}
        confirmText="Удалить"
        variant="danger"
        loading={deleteLoading}
        onConfirm={deleteConversation}
        onCancel={() => setDeletingConv(null)}
      />
    </div>
  );
}
