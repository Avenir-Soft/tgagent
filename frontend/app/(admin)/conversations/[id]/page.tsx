"use client";

import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api, API_BASE } from "@/lib/api";
import { LoadingSpinner } from "@/components/ui/loading-spinner";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { getInitial } from "@/lib/utils";

interface Message {
  id: string;
  direction: string;
  sender_type: string;
  raw_text: string | null;
  ai_generated: boolean;
  training_label: string | null;
  rejection_reason: string | null;
  rejection_selected_text: string | null;
  media_type: string | null;
  media_file_id: string | null;
  created_at: string;
}

interface Conversation {
  id: string;
  telegram_chat_id: number;
  telegram_user_id: number;
  telegram_username: string | null;
  telegram_first_name: string | null;
  source_type: string;
  status: string;
  state: string;
  state_context: Record<string, unknown> | null;
  ai_enabled: boolean;
  is_training_candidate: boolean;
}

interface CustomerHistory {
  customer_name: string | null;
  telegram_username: string | null;
  phone: string | null;
  city: string | null;
  lead_status: string | null;
  total_messages: number;
  total_orders: number;
  orders: Array<{
    order_number: string;
    status: string;
    total_amount: number;
    created_at: string | null;
    items: Array<{ product_name: string; variant_title: string; quantity: number; price: number }>;
  }>;
}

interface Anomaly {
  type: string;
  severity: string;
  detail: string;
  turn: string;
  ts: string;
}

const stateLabels: Record<string, string> = {
  idle: "Начало", browsing: "Просматривает", selection: "Выбирает",
  cart: "Корзина", checkout: "Оформление", post_order: "Есть заказ", handoff: "Оператор",
};

const stateColors: Record<string, string> = {
  browsing: "bg-indigo-50 text-indigo-700", selection: "bg-violet-50 text-violet-700",
  cart: "bg-violet-50 text-violet-700", checkout: "bg-amber-50 text-amber-700",
  post_order: "bg-emerald-50 text-emerald-700", handoff: "bg-amber-50 text-amber-700",
};

const statusLabels: Record<string, string> = {
  draft: "Черновик", confirmed: "Подтверждён", processing: "В обработке",
  shipped: "Отправлен", delivered: "Доставлен", cancelled: "Отменён",
};

function formatTime(d: string) { return new Date(d).toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" }); }
function formatDate(d: string) { return new Date(d).toLocaleDateString("ru", { day: "numeric", month: "long" }); }
function formatPrice(n: number) { return n.toLocaleString("ru"); }

export default function ConversationDetailPage() {
  const { id } = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [conv, setConv] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [history, setHistory] = useState<CustomerHistory | null>(null);
  const [msgLimit, setMsgLimit] = useState(100);
  const [hasMore, setHasMore] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [sending, setSending] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [showSidebar, setShowSidebar] = useState(true);
  // Rejection modal
  const [rejectingMsg, setRejectingMsg] = useState<Message | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectSelected, setRejectSelected] = useState("");
  // Anomaly navigation
  const [anomalyIdx, setAnomalyIdx] = useState(-1);
  const [highlightedMsgId, setHighlightedMsgId] = useState<string | null>(null);
  // Delete conversation
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const { toast } = useToast();

  const bottomRef = useRef<HTMLDivElement>(null);
  const msgRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const loadMessages = useCallback((limit: number) => {
    if (!id) return;
    api.get<Message[]>(`/conversations/${id}/messages?limit=${limit}`).then((msgs) => {
      setMessages(msgs);
      setHasMore(msgs.length >= limit);
    }).catch(console.error);
  }, [id]);

  const load = useCallback(() => {
    if (!id) return;
    api.get<Conversation>(`/conversations/${id}`).then(setConv).catch(console.error);
    loadMessages(msgLimit);
    api.get<CustomerHistory>(`/conversations/${id}/customer-history`).then(setHistory).catch(console.error);
  }, [id, msgLimit, loadMessages]);

  useEffect(() => { load(); }, [load]);

  // Mark as read in localStorage when messages load
  useEffect(() => {
    if (messages.length > 0 && id) {
      try {
        const readMap = JSON.parse(localStorage.getItem("conv_read_counts") || "{}");
        readMap[id as string] = messages.length;
        localStorage.setItem("conv_read_counts", JSON.stringify(readMap));
      } catch {}
    }
  }, [messages.length, id]);

  // Adaptive polling: 2s when focused, 15s when tab is blurred
  useEffect(() => {
    if (!id) return;
    let delay = 2000;
    let timer: ReturnType<typeof setTimeout>;

    const poll = () => {
      api.get<Message[]>(`/conversations/${id}/messages?limit=${msgLimit}`).then((newMsgs) => {
        setMessages((prev) => {
          if (newMsgs.length !== prev.length) return newMsgs;
          const a = newMsgs[newMsgs.length - 1];
          const b = prev[prev.length - 1];
          if (a && b && a.id !== b.id) return newMsgs;
          return prev;
        });
      }).catch(console.error);
      api.get<Conversation>(`/conversations/${id}`).then((c) => {
        setConv((prev) => {
          if (!prev) return c;
          if (prev.state !== c.state || prev.ai_enabled !== c.ai_enabled || prev.status !== c.status) return c;
          return prev;
        });
      }).catch(console.error);
      timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, delay);

    const onVisChange = () => {
      delay = document.hidden ? 15000 : 2000;
    };
    document.addEventListener("visibilitychange", onVisChange);
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", onVisChange); };
  }, [id, msgLimit]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages.length]);

  // Scroll to highlighted message from URL param (e.g., from activity log click)
  useEffect(() => {
    const hlId = searchParams.get("highlight");
    if (hlId && messages.length > 0) {
      setHighlightedMsgId(hlId);
      // Wait for DOM to render, then scroll
      setTimeout(() => {
        msgRefs.current[hlId]?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 300);
      // Auto-clear highlight after 4s
      const t = setTimeout(() => setHighlightedMsgId(null), 4000);
      return () => clearTimeout(t);
    }
  }, [searchParams, messages.length]);

  // Keyboard shortcuts: Esc to cancel edit
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && editingId) { setEditingId(null); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [editingId]);

  const toggleAi = async () => {
    if (!conv) return;
    await api.patch(`/conversations/${id}/toggle-ai`);
    setConv({ ...conv, ai_enabled: !conv.ai_enabled });
  };

  const loadMore = () => {
    const newLimit = msgLimit + 200;
    setMsgLimit(newLimit);
    loadMessages(newLimit);
  };

  const labelMessage = async (msgId: string, label: "approved" | "rejected") => {
    if (label === "rejected") {
      const msg = messages.find((m) => m.id === msgId);
      if (msg) { setRejectingMsg(msg); return; }
    }
    await api.patch(`/training/messages/${msgId}/label`, { label });
    setMessages((prev) => prev.map((m) => m.id === msgId ? { ...m, training_label: label, rejection_reason: null } : m));
  };

  const submitRejection = async () => {
    if (!rejectingMsg) return;
    await api.patch(`/training/messages/${rejectingMsg.id}/label`, {
      label: "rejected",
      reason: rejectReason || null,
      selected_text: rejectSelected || null,
    });
    setMessages((prev) => prev.map((m) => m.id === rejectingMsg.id
      ? { ...m, training_label: "rejected", rejection_reason: rejectReason, rejection_selected_text: rejectSelected }
      : m));
    setRejectingMsg(null);
    setRejectReason("");
    setRejectSelected("");
  };

  const saveEdit = async () => {
    if (!editingId || !editText.trim()) return;
    await api.patch(`/conversations/${id}/messages/${editingId}`, { raw_text: editText, sync_telegram: true });
    setMessages((prev) => prev.map((m) => m.id === editingId ? { ...m, raw_text: editText } : m));
    setEditingId(null);
  };

  const sendReply = async () => {
    if (!replyText.trim() || sending) return;
    setSending(true);
    try {
      await api.post(`/conversations/${id}/messages`, { raw_text: replyText, sync_telegram: true });
      setReplyText("");
      load();
    } finally { setSending(false); }
  };

  const deleteConversation = async () => {
    setDeleteLoading(true);
    try {
      await api.delete(`/conversations/${id}`);
      toast("Диалог удалён", "success");
      router.push("/conversations");
    } catch { toast("Не удалось удалить", "error"); }
    finally { setDeleteLoading(false); setShowDeleteDialog(false); }
  };

  // Message search
  const [msgSearch, setMsgSearch] = useState("");
  const [msgSearchIdx, setMsgSearchIdx] = useState(-1);
  const searchMatches = useMemo(() => {
    if (!msgSearch.trim()) return [];
    const q = msgSearch.toLowerCase();
    return messages
      .map((m, i) => (m.raw_text?.toLowerCase().includes(q) ? i : -1))
      .filter((i) => i >= 0);
  }, [messages, msgSearch]);
  const jumpToSearchResult = (idx: number) => {
    if (idx < 0 || idx >= searchMatches.length) return;
    setMsgSearchIdx(idx);
    const msg = messages[searchMatches[idx]];
    if (msg) {
      setHighlightedMsgId(msg.id);
      msgRefs.current[msg.id]?.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(() => setHighlightedMsgId(null), 3000);
    }
  };

  // Auto-search from URL ?search= param (e.g. from broadcast page)
  const _searchParam = searchParams.get("search");
  const _searchApplied = useRef(false);
  useEffect(() => {
    if (_searchParam && messages.length > 0 && !_searchApplied.current) {
      _searchApplied.current = true;
      setMsgSearch(_searchParam);
      // Wait for search matches to compute, then jump to last match
      setTimeout(() => {
        const q = _searchParam.toLowerCase();
        const matches = messages
          .map((m, i) => (m.raw_text?.toLowerCase().includes(q) ? i : -1))
          .filter((i) => i >= 0);
        if (matches.length > 0) {
          const lastIdx = matches.length - 1;
          setMsgSearchIdx(lastIdx);
          const msg = messages[matches[lastIdx]];
          if (msg) {
            setHighlightedMsgId(msg.id);
            msgRefs.current[msg.id]?.scrollIntoView({ behavior: "smooth", block: "center" });
            setTimeout(() => setHighlightedMsgId(null), 4000);
          }
        }
      }, 300);
    }
  }, [_searchParam, messages]);

  // Quick reply templates
  const [templates, setTemplates] = useState<Array<{ id: string; template_text: string }>>([]);
  useEffect(() => {
    api.get<Array<{ id: string; template_text: string }>>("/templates").then(setTemplates).catch(() => {});
  }, []);

  // Anomaly helpers — persist dismissed state in localStorage
  const allAnomalies: Anomaly[] = (conv?.state_context?._anomalies as Anomaly[]) || [];
  const dismissedKey = `anomalies_dismissed_${id}`;
  const [dismissedAnomalies, setDismissedAnomalies] = useState<Set<number>>(() => {
    if (typeof window === "undefined") return new Set<number>();
    try {
      const stored = localStorage.getItem(dismissedKey);
      return stored ? new Set(JSON.parse(stored) as number[]) : new Set<number>();
    } catch { return new Set<number>(); }
  });
  const [showAnomalyHistory, setShowAnomalyHistory] = useState(false);
  const anomalies = allAnomalies.filter((_, i) => !dismissedAnomalies.has(i));
  const dismissAnomaly = (globalIdx: number) => {
    setDismissedAnomalies((prev) => {
      const next = new Set([...prev, globalIdx]);
      try { localStorage.setItem(dismissedKey, JSON.stringify([...next])); } catch {}
      return next;
    });
  };

  const scrollToAnomaly = (idx: number) => {
    if (idx < 0 || idx >= anomalies.length) return;
    setAnomalyIdx(idx);
    const turn = anomalies[idx].turn?.toLowerCase();
    if (!turn) return;
    const targetMsg = messages.find((m) => m.direction === "inbound" && m.raw_text?.toLowerCase().includes(turn.slice(0, 30)));
    if (targetMsg) {
      setHighlightedMsgId(targetMsg.id);
      msgRefs.current[targetMsg.id]?.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(() => setHighlightedMsgId(null), 3000);
    }
  };

  if (!conv) return <LoadingSpinner />;

  const ctx = conv.state_context || {};
  const cart = (ctx.cart_items as Array<{ name: string; variant_title: string; qty: number }>) || [];
  const orders = (ctx.orders as Array<{ order_number: string; status: string }>) || [];
  const lang = ctx.language as string | undefined;

  let lastDate = "";

  return (
    <div className="flex gap-4 h-[calc(100vh-120px)]">
      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between mb-3 shrink-0">
          <div>
            <button type="button" onClick={() => router.push("/conversations")} className="text-sm text-indigo-600 hover:text-indigo-700 hover:underline mb-1 block transition-colors">&larr; Назад</button>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-slate-900">
                {conv.telegram_first_name || "Клиент"}{" "}
                {conv.telegram_username && <span className="text-indigo-500 text-sm font-normal">@{conv.telegram_username}</span>}
              </h1>
              {conv.telegram_username && (
                <a href={`https://t.me/${conv.telegram_username.replace(/^@/, "")}`} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-sky-50 text-sky-600 hover:bg-sky-100 transition-colors">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69.01-.03.01-.14-.07-.2-.08-.06-.19-.04-.27-.02-.12.03-1.99 1.27-5.63 3.72-.53.36-1.01.54-1.44.53-.47-.01-1.38-.27-2.06-.49-.83-.27-1.49-.42-1.43-.88.03-.24.37-.49 1.02-.75 3.98-1.73 6.63-2.87 7.95-3.44 3.79-1.58 4.57-1.85 5.08-1.86.11 0 .37.03.54.17.14.12.18.28.2.47-.01.06.01.24 0 .37z"/>
                  </svg>
                  Telegram
                </a>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {conv.state !== "idle" && (
              <span className={`px-2 py-1 rounded-lg text-xs ${stateColors[conv.state] || "bg-slate-100 text-slate-500"}`}>
                {stateLabels[conv.state] || conv.state}
              </span>
            )}
            {lang && <span className="px-2 py-1 rounded-lg text-xs bg-slate-100 text-slate-500">🌐 {lang === "ru" ? "RU" : lang === "en" ? "EN" : lang === "uz_latin" ? "UZ" : lang === "uz_cyrillic" ? "ЎЗ" : lang}</span>}
            <button type="button" onClick={toggleAi} className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${conv.ai_enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-500"}`}>
              AI {conv.ai_enabled ? "ON" : "OFF"}
            </button>
            <button type="button" onClick={() => setShowSidebar(!showSidebar)} className="px-3 py-1.5 rounded-lg text-xs bg-slate-100 text-slate-500 hover:bg-slate-200 transition-colors">
              {showSidebar ? "Скрыть" : "Клиент"}
            </button>
            <button type="button" title="Сбросить AI" onClick={async () => { if (!confirm("Сбросить?")) return; await api.post(`/conversations/${id}/reset`, {}); load(); }} className="px-3 py-1.5 rounded-lg text-xs bg-slate-100 text-slate-500 hover:bg-rose-50 hover:text-rose-600 transition-colors">
              Сброс
            </button>
            <button type="button" title="Удалить диалог" onClick={() => setShowDeleteDialog(true)} className="px-3 py-1.5 rounded-lg text-xs bg-slate-100 text-slate-500 hover:bg-rose-50 hover:text-rose-600 transition-colors">
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
            </button>
          </div>
        </div>

        {/* Banners */}
        {conv.status === "handoff" && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-2 mb-2 flex items-center justify-between shrink-0">
            <p className="text-xs text-amber-700">Диалог передан оператору. AI отключен.</p>
            <button type="button" onClick={async () => { await api.patch(`/conversations/${id}/toggle-ai`); setConv({ ...conv, ai_enabled: true, status: "active" }); }} className="px-3 py-1 bg-amber-500 text-white text-xs rounded-lg hover:bg-amber-600 transition-colors">Включить AI</button>
          </div>
        )}

        {/* Context bar */}
        {(cart.length > 0 || orders.length > 0) && (
          <div className="bg-indigo-50 border border-indigo-100 rounded-xl px-4 py-2 mb-1 shrink-0 flex items-center gap-4 text-xs flex-wrap">
            {cart.length > 0 && <span className="text-violet-700">🛒 {cart.map((i) => i.variant_title || i.name).join(", ")}</span>}
            {orders.map((o) => <span key={o.order_number} className="text-emerald-700">📦 {o.order_number}</span>)}
          </div>
        )}

        {/* Anomaly bar with navigation */}
        {/* Anomaly bar — only show when there are active (undismissed) anomalies */}
        {anomalies.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-2 mb-2 shrink-0">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-amber-800">
                ⚠️ {anomalies.length} активн.
              </span>
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => scrollToAnomaly(Math.max(0, anomalyIdx - 1))} disabled={anomalyIdx <= 0 && anomalyIdx !== -1} className="px-2 py-0.5 text-xs bg-amber-100 text-amber-700 rounded disabled:opacity-30 transition-colors">←</button>
                <span className="text-xs text-amber-600">{anomalyIdx >= 0 ? `${anomalyIdx + 1}/${anomalies.length}` : "—"}</span>
                <button type="button" onClick={() => scrollToAnomaly(anomalyIdx < 0 ? 0 : Math.min(anomalies.length - 1, anomalyIdx + 1))} className="px-2 py-0.5 text-xs bg-amber-100 text-amber-700 rounded disabled:opacity-30 transition-colors">→</button>
              </div>
            </div>
            <div className="space-y-0.5">
              {anomalies.slice(-3).map((a, i) => {
                const globalIdx = allAnomalies.indexOf(a);
                return (
                  <div key={i} className="flex items-center gap-1 text-xs hover:bg-amber-100 rounded px-1 py-0.5 transition-colors">
                    <button type="button" onClick={() => scrollToAnomaly(i)} className="flex-1 text-left flex gap-2">
                      <span className={`shrink-0 px-1.5 rounded ${a.severity === "high" ? "bg-rose-200 text-rose-800" : "bg-amber-100 text-amber-800"}`}>{a.type}</span>
                      <span className="text-amber-700 truncate">{a.detail}</span>
                    </button>
                    <button type="button" onClick={() => dismissAnomaly(globalIdx)} className="shrink-0 px-1.5 py-0.5 text-emerald-600 hover:bg-emerald-100 rounded transition-colors" title="Решено">✓</button>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {/* Dismissed anomaly history — small link when all resolved */}
        {anomalies.length === 0 && dismissedAnomalies.size > 0 && (
          <div className="mb-1 shrink-0">
            <button type="button" onClick={() => setShowAnomalyHistory(!showAnomalyHistory)} className="text-[11px] text-slate-400 hover:text-slate-600 transition-colors">
              {showAnomalyHistory ? "▾ Скрыть историю аномалий" : `▸ История аномалий (${dismissedAnomalies.size})`}
            </button>
            {showAnomalyHistory && (
              <div className="mt-1 bg-slate-50 border border-slate-100 rounded-lg px-3 py-2 space-y-0.5">
                {allAnomalies.filter((_, i) => dismissedAnomalies.has(i)).map((a, i) => (
                  <div key={i} className="text-[10px] text-slate-400 flex gap-2 line-through">
                    <span className="shrink-0">{a.type}</span>
                    <span className="truncate">{a.detail}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Message search bar */}
        {msgSearch !== "" || searchMatches.length > 0 ? null : null}
        <div className="flex items-center gap-2 mb-1 shrink-0">
          <div className="relative flex-1">
            <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
            </svg>
            <input
              type="text"
              placeholder="Поиск в сообщениях..."
              value={msgSearch}
              onChange={(e) => { setMsgSearch(e.target.value); setMsgSearchIdx(-1); }}
              className="w-full bg-white border border-slate-200 rounded-lg pl-8 pr-3 py-1.5 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
            />
          </div>
          {searchMatches.length > 0 && (
            <div className="flex items-center gap-1 text-xs text-slate-500 shrink-0">
              <button type="button" onClick={() => jumpToSearchResult(Math.max(0, msgSearchIdx - 1))} className="px-1.5 py-0.5 bg-slate-100 rounded hover:bg-slate-200 transition-colors">↑</button>
              <span>{msgSearchIdx >= 0 ? msgSearchIdx + 1 : 0}/{searchMatches.length}</span>
              <button type="button" onClick={() => jumpToSearchResult(msgSearchIdx < 0 ? 0 : Math.min(searchMatches.length - 1, msgSearchIdx + 1))} className="px-1.5 py-0.5 bg-slate-100 rounded hover:bg-slate-200 transition-colors">↓</button>
            </div>
          )}
          {msgSearch && searchMatches.length === 0 && (
            <span className="text-xs text-slate-400 shrink-0">Не найдено</span>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 bg-slate-100 rounded-xl overflow-y-auto p-4 space-y-1">
          {hasMore && (
            <div className="text-center mb-3">
              <button type="button" onClick={loadMore} className="px-4 py-1.5 bg-white text-indigo-600 text-xs rounded-full shadow-sm hover:bg-indigo-50 transition-colors">
                Загрузить ещё ↑
              </button>
            </div>
          )}
          {messages.length === 0 ? (
            <p className="text-slate-400 text-center py-8">Нет сообщений</p>
          ) : (
            messages.map((msg) => {
              const msgDate = formatDate(msg.created_at);
              let showDateSep = false;
              if (msgDate !== lastDate) { lastDate = msgDate; showDateSep = true; }
              const isOut = msg.direction === "outbound";
              const isHighlighted = msg.id === highlightedMsgId;

              return (
                <div key={msg.id} ref={(el) => { msgRefs.current[msg.id] = el; }}>
                  {showDateSep && (
                    <div className="text-center my-3">
                      <span className="bg-white px-3 py-1 rounded-full text-xs text-slate-400 shadow-sm">{msgDate}</span>
                    </div>
                  )}
                  <div className={`flex ${isOut ? "justify-end" : "justify-start"} group mb-1`}>
                    <div className="relative max-w-[75%]">
                      {editingId === msg.id ? (
                        <div className="bg-white rounded-2xl p-3 shadow-sm border-2 border-indigo-400">
                          <textarea value={editText} onChange={(e) => setEditText(e.target.value)} className="w-full text-sm bg-white border border-slate-200 rounded-lg p-2 resize-none outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all" rows={3} />
                          <div className="flex gap-2 mt-2 justify-end">
                            <button type="button" onClick={() => setEditingId(null)} className="px-3 py-1 text-xs text-slate-500 rounded-lg hover:bg-slate-50 transition-colors">Отмена</button>
                            <button type="button" onClick={saveEdit} className="px-3 py-1 text-xs bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors">Сохранить</button>
                          </div>
                        </div>
                      ) : (
                        <div className={`rounded-2xl px-4 py-2 transition-all duration-200 ${isHighlighted ? "ring-2 ring-rose-400 ring-offset-2" : ""} ${
                          isOut
                            ? msg.ai_generated ? "bg-indigo-500 text-white" : "bg-emerald-500 text-white"
                            : "bg-white text-slate-900 shadow-sm"
                        }`}>
                          {/* Media content */}
                          {msg.media_type && msg.media_file_id && (() => {
                            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
                            const mediaUrl = `${API_BASE}/telegram/media/${msg.id}?token=${token || ""}`;
                            const t = msg.media_type;
                            if (t === "photo") return (
                              <img src={mediaUrl} alt="Фото" className="max-w-[280px] max-h-[320px] rounded-xl mb-1 cursor-pointer" loading="lazy" onClick={() => window.open(mediaUrl, "_blank")} />
                            );
                            if (t === "sticker") return (
                              <img src={mediaUrl} alt="Стикер" className="w-32 h-32 object-contain mb-1" loading="lazy" />
                            );
                            if (t === "gif") return (
                              <video src={mediaUrl} autoPlay loop muted playsInline className="max-w-[240px] rounded-xl mb-1" />
                            );
                            if (t === "voice") return (
                              <div className="flex items-center gap-2 mb-1">
                                <svg className="w-4 h-4 shrink-0 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4M12 15a3 3 0 003-3V5a3 3 0 00-6 0v7a3 3 0 003 3z" /></svg>
                                <audio controls preload="none" src={mediaUrl} className="h-8 max-w-[220px]" />
                              </div>
                            );
                            if (t === "video_note") return (
                              <video src={mediaUrl} controls preload="none" className="w-40 h-40 rounded-full object-cover mb-1" />
                            );
                            if (t === "video") return (
                              <video src={mediaUrl} controls preload="none" className="max-w-[280px] max-h-[320px] rounded-xl mb-1" />
                            );
                            if (t === "document") return (
                              <a href={mediaUrl} target="_blank" rel="noopener noreferrer" className={`flex items-center gap-2 mb-1 text-xs underline ${isOut ? "text-white/80" : "text-indigo-600"}`}>
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                                Файл
                              </a>
                            );
                            return null;
                          })()}
                          {/* Text content */}
                          {msg.raw_text && !msg.raw_text.startsWith("[Клиент отправил") && (
                            <p className="text-sm whitespace-pre-wrap">{msg.raw_text}</p>
                          )}
                          {!msg.media_type && <p className="text-sm whitespace-pre-wrap">{msg.raw_text || "(пусто)"}</p>}
                          <div className="flex items-center gap-2 mt-1">
                            <span className={`text-[10px] ${isOut ? "opacity-60" : "text-slate-400"}`}>
                              {formatTime(msg.created_at)}
                              {msg.ai_generated && " · AI"}
                              {isOut && !msg.ai_generated && " · Оператор"}
                            </span>
                            {isOut && (() => {
                              const msgIdx = messages.indexOf(msg);
                              const hasReplyAfter = messages.slice(msgIdx + 1).some((m) => m.direction === "inbound");
                              return hasReplyAfter
                                ? <span className="text-[10px] text-sky-300 ml-0.5" title="Прочитано">✓✓</span>
                                : <span className="text-[10px] opacity-40 ml-0.5" title="Отправлено">✓</span>;
                            })()}
                            {msg.training_label === "approved" && <span className="text-[10px] bg-emerald-100 text-emerald-700 px-1 rounded">✓</span>}
                            {msg.training_label === "rejected" && (
                              <span className="text-[10px] bg-rose-100 text-rose-600 px-1.5 py-0.5 rounded cursor-help" title={msg.rejection_reason || "Причина не указана"}>
                                ✗ {msg.rejection_reason ? msg.rejection_reason.slice(0, 50) : "(без причины)"}
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                      {/* Action buttons — positioned below the message bubble */}
                      {isOut && editingId !== msg.id && (
                        <div className="flex gap-1 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity justify-end">
                          {msg.ai_generated && (
                            <>
                              <button type="button" onClick={() => labelMessage(msg.id, "approved")} className={`w-6 h-6 rounded-full flex items-center justify-center text-xs transition-colors ${msg.training_label === "approved" ? "bg-emerald-500 text-white" : "bg-white shadow-sm text-slate-400 hover:text-emerald-600"}`}>✓</button>
                              <button type="button" onClick={() => labelMessage(msg.id, "rejected")} className={`w-6 h-6 rounded-full flex items-center justify-center text-xs transition-colors ${msg.training_label === "rejected" ? "bg-rose-500 text-white" : "bg-white shadow-sm text-slate-400 hover:text-rose-600"}`}>✗</button>
                            </>
                          )}
                          <button type="button" onClick={() => { setEditingId(msg.id); setEditText(msg.raw_text || ""); }} className="w-6 h-6 rounded-full bg-white shadow-sm flex items-center justify-center text-slate-400 hover:text-indigo-600 text-xs transition-colors">✎</button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
          <div ref={bottomRef} />
        </div>

        {/* Quick reply templates */}
        {templates.length > 0 && (
          <div className="mt-2 flex gap-1.5 flex-wrap shrink-0">
            {templates.slice(0, 6).map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setReplyText(t.template_text)}
                className="px-2.5 py-1 bg-white border border-slate-200 rounded-lg text-[11px] text-slate-600 hover:bg-indigo-50 hover:border-indigo-200 hover:text-indigo-700 transition-colors truncate max-w-[200px]"
                title={t.template_text}
              >
                {t.template_text.length > 40 ? t.template_text.slice(0, 40) + "..." : t.template_text}
              </button>
            ))}
          </div>
        )}

        {/* Reply box */}
        <div className="mt-2 flex gap-2 shrink-0">
          <textarea value={replyText} onChange={(e) => setReplyText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey || !e.shiftKey)) { e.preventDefault(); sendReply(); }
            }}
            rows={1}
            placeholder="Написать от имени оператора... (Enter / Ctrl+Enter — отправить)"
            className="flex-1 bg-white border border-slate-200 rounded-xl px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all resize-none" />
          <button type="button" onClick={sendReply} disabled={sending || !replyText.trim()} className="px-5 py-2.5 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">
            {sending ? "..." : "Отправить"}
          </button>
        </div>
      </div>

      {/* Sidebar — customer info + order history */}
      {showSidebar && (
        <div className="w-72 shrink-0 card overflow-y-auto">
          {history ? (
            <div className="p-4 space-y-4">
              {/* Customer card */}
              <div>
                <div className="w-12 h-12 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-lg font-bold mb-2">
                  {getInitial(history.customer_name)}
                </div>
                <h3 className="font-semibold text-sm text-slate-900">{history.customer_name || conv.telegram_first_name}</h3>
                {history.telegram_username && <p className="text-xs text-indigo-500">@{history.telegram_username}</p>}
                {history.lead_status && (
                  <span className={`inline-block mt-1 text-[10px] px-2 py-0.5 rounded-full font-medium ${
                    history.lead_status === "converted" ? "bg-emerald-100 text-emerald-700"
                    : history.lead_status === "qualified" ? "bg-indigo-100 text-indigo-700"
                    : history.lead_status === "contacted" ? "bg-blue-100 text-blue-700"
                    : history.lead_status === "lost" ? "bg-slate-100 text-slate-500"
                    : "bg-amber-100 text-amber-700"
                  }`}>
                    {history.lead_status === "new" ? "Новый" : history.lead_status === "contacted" ? "Связались"
                      : history.lead_status === "qualified" ? "Квалифицирован" : history.lead_status === "converted" ? "Конвертирован"
                      : history.lead_status === "lost" ? "Потерян" : history.lead_status}
                  </span>
                )}
                {history.phone && <p className="text-xs text-slate-500 mt-1">📞 {history.phone}</p>}
                {history.city && <p className="text-xs text-slate-500">📍 {history.city}</p>}
                <div className="flex gap-3 mt-2 text-xs text-slate-400">
                  <span>{history.total_messages} сообщ.</span>
                  <span>{history.total_orders} заказ.</span>
                </div>
              </div>

              {/* Order history */}
              {history.orders.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-slate-500 uppercase mb-2">История заказов</h4>
                  <div className="space-y-2">
                    {history.orders.map((o) => (
                      <div key={o.order_number} className="border border-slate-200/60 rounded-xl p-2.5 transition-all duration-200 hover:border-slate-200">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-mono font-medium text-slate-900">{o.order_number}</span>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                            o.status === "delivered" ? "bg-emerald-100 text-emerald-700"
                            : o.status === "cancelled" ? "bg-rose-100 text-rose-600"
                            : o.status === "shipped" ? "bg-indigo-100 text-indigo-600"
                            : "bg-amber-50 text-amber-700"
                          }`}>{statusLabels[o.status] || o.status}</span>
                        </div>
                        <div className="space-y-0.5">
                          {o.items.map((item, i) => (
                            <p key={i} className="text-xs text-slate-500">{item.product_name} {item.variant_title && `· ${item.variant_title}`} {item.quantity > 1 && `×${item.quantity}`}</p>
                          ))}
                        </div>
                        <p className="text-xs font-medium mt-1 text-slate-900">{formatPrice(o.total_amount)} сум</p>
                        {o.created_at && <p className="text-[10px] text-slate-400">{new Date(o.created_at).toLocaleDateString("ru")}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {history.orders.length === 0 && (
                <p className="text-xs text-slate-400 text-center py-4">Нет заказов</p>
              )}
            </div>
          ) : (
            <LoadingSpinner message="Загрузка сообщений..." />
          )}
        </div>
      )}

      {/* Rejection modal */}
      {rejectingMsg && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setRejectingMsg(null)}>
          <div className="bg-white rounded-2xl shadow-xl w-[480px] max-h-[80vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-bold text-sm text-slate-900 mb-3">Почему этот ответ плохой?</h3>
            {/* Original message */}
            <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-3 mb-4 text-sm text-slate-700">
              <p className="text-xs text-slate-400 mb-1">Ответ AI:</p>
              <p className="whitespace-pre-wrap">{rejectingMsg.raw_text}</p>
            </div>
            {/* Select bad part */}
            <div className="mb-3">
              <label className="block text-xs text-slate-500 mb-1">Проблемная часть (необязательно)</label>
              <input
                type="text" value={rejectSelected}
                onChange={(e) => setRejectSelected(e.target.value)}
                placeholder="Скопируйте сюда конкретную плохую часть..."
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-rose-400 focus:border-rose-400 transition-all"
              />
            </div>
            {/* Reason */}
            <div className="mb-3">
              <label className="block text-xs text-slate-500 mb-1">Причина</label>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {["Неправильная цена", "Выдумал характеристики", "Не тот язык", "Слишком длинный ответ", "Не ответил на вопрос", "Грубый тон"].map((r) => (
                  <button key={r} type="button" onClick={() => setRejectReason(r)}
                    className={`px-2.5 py-1 rounded-full text-xs transition-colors ${rejectReason === r ? "bg-rose-100 text-rose-700 font-medium" : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}>
                    {r}
                  </button>
                ))}
              </div>
              <textarea value={rejectReason} onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Или напишите свою причину..."
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm h-16 resize-none outline-none focus:ring-2 focus:ring-rose-400 focus:border-rose-400 transition-all" />
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setRejectingMsg(null)} className="px-4 py-2 text-sm text-slate-500 hover:bg-slate-50 rounded-lg transition-colors">Отмена</button>
              <button type="button" onClick={submitRejection} className="px-4 py-2 text-sm bg-rose-600 text-white rounded-lg hover:bg-rose-700 transition-colors">Отклонить ✗</button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={showDeleteDialog}
        title="Удалить диалог?"
        message={`${conv.telegram_first_name || "Клиент"} — все сообщения, заказы, лиды и хэндоффы будут удалены. Это действие необратимо.`}
        confirmText="Удалить"
        variant="danger"
        loading={deleteLoading}
        onConfirm={deleteConversation}
        onCancel={() => setShowDeleteDialog(false)}
      />
    </div>
  );
}
