"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useEventSource, SSEEvent } from "@/lib/use-event-source";
import Link from "next/link";
import { PageHeader } from "@/components/ui/page-header";
import { SSEStatusBadge } from "@/components/ui/sse-status";
import { FilterBar } from "@/components/ui/filter-bar";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Avatar } from "@/components/ui/avatar";
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
  avatar_url: string | null;
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

interface CommentInteraction {
  id: string;
  action: string;
  trigger_text: string;
  reply_text: string;
  sender_name: string | null;
  sender_username: string | null;
  chat_title: string | null;
  product_name: string | null;
  created_at: string | null;
}

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

  // Comment interactions
  const [comments, setComments] = useState<CommentInteraction[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(false);

  // Track known IDs for "new conversation" animation
  const knownIdsRef = useRef<Set<string>>(new Set());
  const [newIds, setNewIds] = useState<Set<string>>(new Set());

  // Delete state
  const [deletingConv, setDeletingConv] = useState<Conversation | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  // Bulk select
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkDeleteLoading, setBulkDeleteLoading] = useState(false);
  const [showBulkConfirm, setShowBulkConfirm] = useState(false);
  const { toast } = useToast();

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const bulkDelete = async () => {
    if (selected.size === 0) return;
    setBulkDeleteLoading(true);
    try {
      const res = await api.post<{ deleted: number }>("/conversations/bulk-delete", { conversation_ids: [...selected] });
      toast(`Удалено ${res.deleted} диалогов`, "success");
      setSelected(new Set());
      fetchConversations();
    } catch {
      toast("Ошибка удаления", "error");
    } finally {
      setBulkDeleteLoading(false);
    }
  };

  const pageRef = useRef(0);

  const fetchConversations = useCallback(
    async (reset = true) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      if (!reset) params.set("offset", String((pageRef.current + 1) * PAGE_SIZE));
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (sourceFilter !== "all") params.set("source_type", sourceFilter);

      try {
        const data = await api.get<Conversation[]>(`/conversations?${params}`);
        if (reset) {
          // Detect newly appeared conversations
          if (knownIdsRef.current.size > 0) {
            const fresh = data.filter((c) => !knownIdsRef.current.has(c.id)).map((c) => c.id);
            if (fresh.length > 0) {
              setNewIds(new Set(fresh));
              setTimeout(() => setNewIds(new Set()), 2000);
            }
          }
          data.forEach((c) => knownIdsRef.current.add(c.id));
          setConversations(data);
          pageRef.current = 0;
          setPage(0);
        } else {
          data.forEach((c) => knownIdsRef.current.add(c.id));
          setConversations((prev) => [...prev, ...data]);
          pageRef.current += 1;
          setPage((p) => p + 1);
        }
        setHasMore(data.length >= PAGE_SIZE);
      } catch {
        // silently handle — page stays with current data
      } finally {
        setLoading(false);
      }
    },
    [statusFilter, sourceFilter],
  );

  // Initial load + filter change
  useEffect(() => {
    setLoading(true);
    fetchConversations(true);
  }, [fetchConversations]);

  // Load comments when comment_thread filter is active
  useEffect(() => {
    if (sourceFilter === "comment_thread") {
      setCommentsLoading(true);
      api.get<CommentInteraction[]>("/conversations/comments?limit=50")
        .then(setComments)
        .catch(() => {})
        .finally(() => setCommentsLoading(false));
    }
  }, [sourceFilter]);

  // SSE: real-time updates for conversation list (debounced to avoid rapid re-fetches)
  const sseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSSE = useCallback((event: SSEEvent) => {
    if (event.event === "new_conversation" || event.event === "conversation_updated" || event.event === "new_message") {
      if (sseTimerRef.current) clearTimeout(sseTimerRef.current);
      sseTimerRef.current = setTimeout(() => fetchConversations(true), 500);
    }
  }, [fetchConversations]);
  const { status: sseStatus } = useEventSource(undefined, handleSSE);

  // Slow fallback poll (30s) in case SSE is disconnected
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) fetchConversations(true);
    }, 30_000);
    return () => clearInterval(timer);
  }, [fetchConversations]);

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

  const toggleSelectAll = () => {
    if (selected.size === filtered.length) setSelected(new Set());
    else setSelected(new Set(filtered.map((c) => c.id)));
  };

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
        <SSEStatusBadge status={sseStatus} />
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

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 mb-4 px-4 py-2.5 bg-rose-50 border border-rose-200 rounded-xl">
          <span className="text-sm text-rose-700 font-medium">Выбрано: {selected.size}</span>
          <button
            type="button"
            onClick={() => setShowBulkConfirm(true)}
            disabled={bulkDeleteLoading}
            className="px-3 py-1.5 bg-rose-600 text-white text-xs font-medium rounded-lg hover:bg-rose-700 disabled:opacity-50 transition-colors"
          >
            {bulkDeleteLoading ? "Удаление..." : "Удалить выбранные"}
          </button>
          <button
            type="button"
            onClick={() => setSelected(new Set())}
            className="px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100 rounded-lg transition-colors"
          >
            Снять выделение
          </button>
          <button
            type="button"
            onClick={toggleSelectAll}
            className="px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100 rounded-lg transition-colors"
          >
            {selected.size === filtered.length ? "Снять все" : "Выбрать все"}
          </button>
        </div>
      )}

      {/* Comments view */}
      {sourceFilter === "comment_thread" ? (
        <div className="space-y-2">
          {commentsLoading ? (
            <>
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </>
          ) : comments.length === 0 ? (
            <EmptyState
              message="Нет ответов на комментарии"
              description="Когда AI ответит на комментарий в канале, он появится здесь. Включите «Умные ответы» в настройках."
              action={{ label: "Настройки AI", href: "/settings" }}
            />
          ) : (
            comments.map((c) => (
              <div key={c.id} className="card px-5 py-4 space-y-3">
                {/* Header: sender + channel + time */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-full bg-violet-50 flex items-center justify-center shrink-0">
                      <svg className="w-4 h-4 text-violet-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
                      </svg>
                    </div>
                    <div>
                      <span className="font-medium text-sm text-slate-900">
                        {c.sender_name || c.sender_username || "Пользователь"}
                      </span>
                      {c.sender_username && c.sender_name && (
                        <span className="text-xs text-indigo-500 ml-1.5">@{c.sender_username}</span>
                      )}
                    </div>
                    {c.chat_title && (
                      <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-500 text-[11px] truncate max-w-[160px]">
                        {c.chat_title}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                      c.action === "comment_smart_reply"
                        ? "bg-indigo-50 text-indigo-700"
                        : "bg-slate-100 text-slate-600"
                    }`}>
                      {c.action === "comment_smart_reply" ? "AI" : "Шаблон"}
                    </span>
                    <span className="text-xs text-slate-400">
                      {c.created_at ? timeAgo(c.created_at) : ""}
                    </span>
                  </div>
                </div>
                {/* Messages: trigger + reply */}
                <div className="space-y-2 pl-10">
                  {/* Customer message */}
                  <div className="flex gap-2">
                    <div className="w-1 rounded-full bg-slate-200 shrink-0" />
                    <p className="text-sm text-slate-700">{c.trigger_text}</p>
                  </div>
                  {/* AI reply */}
                  <div className="flex gap-2">
                    <div className="w-1 rounded-full bg-indigo-400 shrink-0" />
                    {c.reply_text ? (
                      <p className="text-sm text-slate-600">{c.reply_text}</p>
                    ) : (
                      <p className="text-sm text-slate-400 italic">Ответ не был записан (старый формат логов)</p>
                    )}
                  </div>
                </div>
                {/* Product tag */}
                {c.product_name && (
                  <div className="pl-10">
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-violet-50 text-violet-700 text-xs">
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path d="M7.875 1.5L3.75 5.25v13.5A1.5 1.5 0 005.25 20.25h13.5a1.5 1.5 0 001.5-1.5V5.25L16.125 1.5H7.875z" />
                      </svg>
                      {c.product_name}
                    </span>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      ) : (

      /* Conversation list */
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
          <EmptyState
            message={
              search ? "Ничего не найдено"
              : statusFilter === "handoff" ? "Нет диалогов на операторе"
              : statusFilter === "closed" ? "Нет закрытых диалогов"
              : "Нет диалогов"
            }
            description={
              search ? undefined
              : statusFilter === "handoff" ? "Когда AI передаёт диалог оператору, он появится здесь"
              : statusFilter === "closed" ? "Закрытые диалоги появятся здесь после завершения"
              : "Подключите Telegram аккаунт и AI начнёт общаться с клиентами автоматически"
            }
            action={
              search ? undefined
              : statusFilter !== "all" ? undefined
              : { label: "Подключить Telegram", href: "/telegram" }
            }
          />
        ) : (
          filtered.map((c) => {
            const cartCount = getCartItemsCount(c.state_context);
            const ordersCount = getOrdersCount(c.state_context);
            const unread = c.unread_count || 0;

            return (
              <Link key={c.id} href={`/conversations/${c.id}`} className="block group">
                <div className={`card px-5 py-4 flex items-center gap-4 transition-all group-hover:shadow-md group-hover:border-slate-300 ${
                  unread > 0 ? "border-l-3 border-l-indigo-500" : ""
                } ${selected.has(c.id) ? "ring-2 ring-indigo-400 bg-indigo-50/30" : ""} ${newIds.has(c.id) ? "animate-slide-in-highlight" : ""}`}>
                  {/* Checkbox */}
                  <div onClick={(e) => { e.preventDefault(); e.stopPropagation(); }} className="shrink-0">
                    <input
                      type="checkbox"
                      checked={selected.has(c.id)}
                      onChange={() => toggleSelect(c.id)}
                      className="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                    />
                  </div>
                  {/* Avatar */}
                  <div className="relative shrink-0">
                    <Avatar
                      src={c.avatar_url}
                      name={c.telegram_first_name}
                      fallback={c.source_type === "dm" ? "D" : "C"}
                      colors={c.source_type === "dm"
                        ? { bg: "bg-indigo-50", text: "text-indigo-600" }
                        : { bg: "bg-violet-50", text: "text-violet-600" }
                      }
                    />
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
      )}

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

      <ConfirmDialog
        open={showBulkConfirm}
        title={`Удалить ${selected.size} диалогов?`}
        message="Все выбранные диалоги будут удалены вместе с сообщениями, заказами, лидами и хэндоффами. Это действие необратимо."
        confirmText="Удалить все"
        variant="danger"
        loading={bulkDeleteLoading}
        onConfirm={async () => { await bulkDelete(); setShowBulkConfirm(false); }}
        onCancel={() => setShowBulkConfirm(false)}
      />
    </div>
  );
}
