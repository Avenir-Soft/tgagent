"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { timeAgo } from "@/lib/time-ago";
import { plural } from "@/lib/utils";

interface AbandonedCart {
  id: string;
  customer: string;
  username: string | null;
  state: string;
  cart_items: Array<{ title: string; qty: number }>;
  cart_total: number;
  hours_idle: number | null;
}

interface BroadcastResult {
  sent: number;
  failed: number;
  total_targets: number;
  truncated?: boolean;
  total_audience?: number;
}

interface HistoryRecipient {
  name: string;
  username: string | null;
  conversation_id: string;
  sent: boolean;
}

interface BroadcastHistoryItem {
  id: string;
  message_text: string;
  image_url: string | null;
  filter_type: string;
  sent_count: number;
  failed_count: number;
  total_targets: number;
  status: string;
  scheduled_at: string | null;
  sent_at: string | null;
  created_at: string | null;
  recipients: HistoryRecipient[];
}

interface Recipient {
  id: string;
  name: string;
  username: string | null;
  telegram_chat_id: number;
  state: string;
  orders: number;
  last_message_at: string | null;
}

const statusConfig: Record<string, { label: string; color: string }> = {
  sent: { label: "Отправлено", color: "bg-emerald-100 text-emerald-700" },
  sending: { label: "Отправка...", color: "bg-blue-100 text-blue-700" },
  scheduled: { label: "Запланировано", color: "bg-violet-100 text-violet-700" },
  cancelled: { label: "Отменено", color: "bg-slate-100 text-slate-500" },
  failed: { label: "Ошибка", color: "bg-rose-100 text-rose-700" },
};

export default function BroadcastPage() {
  const [abandonedCarts, setAbandonedCarts] = useState<AbandonedCart[]>([]);
  const [broadcastText, setBroadcastText] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [broadcastFilter, setBroadcastFilter] = useState<"ordered" | "all">("ordered");
  const [sending, setSending] = useState(false);
  const [broadcastResult, setBroadcastResult] = useState<BroadcastResult | null>(null);
  const [recovering, setRecovering] = useState<string | null>(null);
  const [recoveredIds, setRecoveredIds] = useState<Set<string>>(new Set());
  const [history, setHistory] = useState<BroadcastHistoryItem[]>([]);
  const [scheduleMode, setScheduleMode] = useState(false);
  const [scheduledAt, setScheduledAt] = useState("");
  const [showConfirm, setShowConfirm] = useState(false);

  // Recipients
  const [recipients, setRecipients] = useState<Recipient[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [loadingRecipients, setLoadingRecipients] = useState(false);
  const [recipientSearch, setRecipientSearch] = useState("");
  const [showRecipients, setShowRecipients] = useState(false);
  const [expandedHistoryId, setExpandedHistoryId] = useState<string | null>(null);

  // Audience estimate (detects 5000 cap truncation)
  const [totalAudience, setTotalAudience] = useState<number | null>(null);

  // Delete conversation state
  const [deletingRecipient, setDeletingRecipient] = useState<Recipient | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const { toast } = useToast();

  // Load carts + history
  useEffect(() => {
    api.get<AbandonedCart[]>("/dashboard/abandoned-carts").then(setAbandonedCarts).catch(console.error);
    loadHistory();
    const timer = setInterval(() => {
      api.get<AbandonedCart[]>("/dashboard/abandoned-carts").then(setAbandonedCarts).catch(console.error);
    }, 30000);
    return () => clearInterval(timer);
  }, []);

  const loadHistory = () => {
    api.get<BroadcastHistoryItem[]>("/dashboard/broadcast-history").then(setHistory).catch(console.error);
  };

  // Load recipients when filter changes
  const loadRecipients = useCallback(() => {
    setLoadingRecipients(true);
    api.get<Recipient[]>(`/dashboard/broadcast-recipients?filter=${broadcastFilter}`)
      .then((r) => {
        setRecipients(r);
        setSelectedIds(new Set(r.map((x) => x.id))); // select all by default
      })
      .catch(console.error)
      .finally(() => setLoadingRecipients(false));
    // Check actual audience size (may be > 5000)
    api.get<{ count: number; truncated?: boolean }>(`/dashboard/broadcast-estimate?filter=${broadcastFilter}`)
      .then((r) => setTotalAudience(r.count))
      .catch(() => setTotalAudience(null));
  }, [broadcastFilter]);

  useEffect(() => { loadRecipients(); }, [loadRecipients]);

  // Filtered recipients by search
  const filteredRecipients = useMemo(() => {
    if (!recipientSearch.trim()) return recipients;
    const q = recipientSearch.toLowerCase();
    return recipients.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        (r.username && r.username.toLowerCase().includes(q))
    );
  }, [recipients, recipientSearch]);

  const toggleAll = () => {
    const visibleIds = filteredRecipients.map((r) => r.id);
    const allSelected = visibleIds.every((id) => selectedIds.has(id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        visibleIds.forEach((id) => next.delete(id));
      } else {
        visibleIds.forEach((id) => next.add(id));
      }
      return next;
    });
  };

  const toggleOne = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const sendBroadcast = async () => {
    if (!broadcastText.trim() || selectedIds.size === 0) return;
    setShowConfirm(false);
    setSending(true);
    setBroadcastResult(null);
    try {
      const payload: Record<string, unknown> = {
        text: broadcastText,
        filter: broadcastFilter,
        conversation_ids: Array.from(selectedIds),
      };
      if (imageUrl.trim()) payload.image_url = imageUrl.trim();
      if (scheduleMode && scheduledAt) payload.scheduled_at = new Date(scheduledAt).toISOString();

      if (scheduleMode && scheduledAt) {
        await api.post("/dashboard/broadcast", payload);
        toast("Рассылка запланирована", "success");
        setBroadcastText("");
        setImageUrl("");
        setScheduledAt("");
        setScheduleMode(false);
      } else {
        const r = await api.post<BroadcastResult>("/dashboard/broadcast", payload);
        setBroadcastResult(r);
        toast(`Отправлено ${r.sent} из ${r.total_targets}`, "success");
      }
      loadHistory();
      loadRecipients();
    } catch {
      toast("Ошибка при отправке рассылки", "error");
    } finally {
      setSending(false);
    }
  };

  const cancelScheduled = async (id: string) => {
    try {
      await api.delete(`/dashboard/broadcast-history/${id}`);
      toast("Рассылка отменена", "success");
      loadHistory();
    } catch {
      toast("Ошибка отмены", "error");
    }
  };

  const recoverCart = async (id: string) => {
    setRecovering(id);
    try {
      const r = await api.post<{ sent: boolean }>(`/dashboard/abandoned-carts/${id}/recover`, {});
      if (r.sent) {
        setRecoveredIds((prev) => new Set([...prev, id]));
      } else {
        toast("Не удалось отправить — Telegram не подключён?", "error");
      }
    } finally {
      setRecovering(null);
    }
  };

  const deleteRecipient = async () => {
    if (!deletingRecipient) return;
    setDeleteLoading(true);
    try {
      await api.delete(`/conversations/${deletingRecipient.id}`);
      setRecipients((prev) => prev.filter((r) => r.id !== deletingRecipient.id));
      setSelectedIds((prev) => { const n = new Set(prev); n.delete(deletingRecipient.id); return n; });
      toast("Клиент удалён", "success");
    } catch {
      toast("Ошибка удаления", "error");
    } finally {
      setDeleteLoading(false);
      setDeletingRecipient(null);
    }
  };

  const minSchedule = new Date(Date.now() + 5 * 60000).toISOString().slice(0, 16);
  const allVisibleSelected = filteredRecipients.length > 0 && filteredRecipients.every((r) => selectedIds.has(r.id));

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-slate-900">Рассылки и брошенные корзины</h1>

      {/* Abandoned Carts */}
      <section>
        <h2 className="text-lg font-semibold text-slate-900 mb-3">
          Брошенные корзины
          {abandonedCarts.length > 0 && (
            <span className="ml-2 bg-amber-100 text-amber-700 text-xs px-2 py-0.5 rounded-full">
              {abandonedCarts.length}
            </span>
          )}
        </h2>
        {abandonedCarts.length === 0 ? (
          <div className="card p-6 text-center text-slate-400">
            Нет брошенных корзин (2+ часа без активности)
          </div>
        ) : (
          <div className="space-y-2">
            {abandonedCarts.map((c) => (
              <div key={c.id} className="card px-5 py-4 flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm text-slate-900">{c.customer}</span>
                    {c.username && <span className="text-xs text-indigo-600">@{c.username}</span>}
                    <span className={`px-2 py-0.5 rounded text-xs ${c.state === "checkout" ? "bg-amber-50 text-amber-700" : "bg-violet-50 text-violet-700"}`}>
                      {c.state === "checkout" ? "Оформление" : "Корзина"}
                    </span>
                    {c.hours_idle && (
                      <span className="text-xs text-slate-400">{c.hours_idle}ч назад</span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    {c.cart_items.map((i) => `${i.title}${i.qty > 1 ? ` ×${i.qty}` : ""}`).join(", ")}
                    {c.cart_total > 0 && (
                      <span className="ml-2 font-medium">{Number(c.cart_total).toLocaleString("ru")} сум</span>
                    )}
                  </div>
                </div>
                {recoveredIds.has(c.id) ? (
                  <span className="text-emerald-600 text-sm">Отправлено</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => recoverCart(c.id)}
                    disabled={recovering === c.id}
                    className="px-3 py-1.5 text-xs bg-amber-50 text-amber-700 hover:bg-amber-100 rounded-lg transition-colors"
                  >
                    {recovering === c.id ? "..." : "Напомнить"}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Broadcast */}
      <section>
        <h2 className="text-lg font-semibold text-slate-900 mb-3">Рассылка сообщений</h2>
        <div className="card p-5 space-y-4">
          {/* Filter + selected count */}
          <div className="flex items-center gap-3">
            {(["ordered", "all"] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setBroadcastFilter(f)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  broadcastFilter === f ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {f === "ordered" ? "Покупателям" : "Всем клиентам"}
              </button>
            ))}
            <span className="ml-auto text-sm font-medium text-indigo-600">
              {selectedIds.size} из {recipients.length} выбрано
            </span>
          </div>

          {/* 5000 cap warning */}
          {totalAudience !== null && totalAudience > 5000 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5 flex items-center gap-2 text-sm text-amber-700">
              <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
              </svg>
              <span>
                Всего клиентов: <strong>{totalAudience.toLocaleString("ru")}</strong>, но за одну рассылку можно отправить максимум <strong>5 000</strong>. Остальные {(totalAudience - 5000).toLocaleString("ru")} не будут охвачены.
              </span>
            </div>
          )}

          {/* Recipients list toggle */}
          <button
            type="button"
            onClick={() => setShowRecipients(!showRecipients)}
            className="flex items-center gap-2 text-sm text-slate-600 hover:text-indigo-600 transition-colors"
          >
            <span className="text-xs">{showRecipients ? "▾" : "▸"}</span>
            <span>Получатели ({selectedIds.size}/{recipients.length})</span>
          </button>

          {showRecipients && (
          <div className="border border-slate-200 rounded-xl overflow-hidden">
            {/* Header: search + select all */}
            <div className="bg-slate-50 px-4 py-2.5 flex items-center gap-3 border-b border-slate-200">
              <label className="flex items-center gap-2 shrink-0">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleAll}
                  className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="text-xs text-slate-500">Все</span>
              </label>
              <div className="relative flex-1">
                <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
                </svg>
                <input
                  type="text"
                  placeholder="Поиск по имени или @username..."
                  value={recipientSearch}
                  onChange={(e) => setRecipientSearch(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                />
              </div>
              <div className="flex gap-1.5 shrink-0">
                <button
                  type="button"
                  onClick={() => setSelectedIds(new Set(recipients.map((r) => r.id)))}
                  className="px-2 py-1 text-[10px] bg-indigo-50 text-indigo-600 rounded hover:bg-indigo-100 transition-colors"
                >
                  Выбрать всех
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedIds(new Set())}
                  className="px-2 py-1 text-[10px] bg-slate-100 text-slate-500 rounded hover:bg-slate-200 transition-colors"
                >
                  Снять все
                </button>
              </div>
            </div>

            {/* Recipient rows */}
            <div className="max-h-64 overflow-y-auto divide-y divide-slate-100">
              {loadingRecipients ? (
                <div className="px-4 py-8 text-center text-sm text-slate-400">Загрузка...</div>
              ) : filteredRecipients.length === 0 ? (
                <div className="px-4 py-8 text-center text-sm text-slate-400">
                  {recipientSearch ? "Никого не найдено" : "Нет получателей"}
                </div>
              ) : (
                filteredRecipients.map((r) => (
                  <label
                    key={r.id}
                    className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors group ${
                      selectedIds.has(r.id) ? "bg-indigo-50/50" : "hover:bg-slate-50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(r.id)}
                      onChange={() => toggleOne(r.id)}
                      className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 shrink-0"
                    />
                    <div className="flex-1 min-w-0 flex items-center gap-2">
                      <span className="text-sm text-slate-900 truncate">{r.name}</span>
                      {r.username && (
                        <span className="text-xs text-indigo-500 shrink-0">@{r.username}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {r.orders > 0 && (
                        <span className="text-[10px] px-1.5 py-0.5 bg-emerald-50 text-emerald-600 rounded">
                          {r.orders} заказ{r.orders === 1 ? "" : r.orders < 5 ? "а" : "ов"}
                        </span>
                      )}
                      {r.last_message_at && (
                        <span className="text-[10px] text-slate-400">{timeAgo(r.last_message_at)}</span>
                      )}
                      <button
                        type="button"
                        title="Удалить клиента"
                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setDeletingRecipient(r); }}
                        className="w-5 h-5 rounded flex items-center justify-center text-slate-300 hover:text-rose-500 hover:bg-rose-50 transition-all opacity-0 group-hover:opacity-100"
                      >
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  </label>
                ))
              )}
            </div>
          </div>
          )}

          {/* Message */}
          <textarea
            value={broadcastText}
            onChange={(e) => setBroadcastText(e.target.value)}
            placeholder="Текст сообщения для рассылки..."
            rows={4}
            className="w-full bg-white border border-slate-200 rounded-lg px-4 py-3 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all resize-none"
            required
            minLength={1}
            maxLength={4096}
          />

          {/* Image URL */}
          <div>
            <label className="block text-xs text-slate-500 mb-1">Фото (URL, необязательно)</label>
            <input
              value={imageUrl}
              onChange={(e) => setImageUrl(e.target.value)}
              placeholder="https://example.com/promo.jpg"
              className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
            />
            {imageUrl.trim() && (
              <div className="mt-2 flex items-center gap-3">
                <img
                  src={imageUrl}
                  alt="Preview"
                  className="w-16 h-16 object-cover rounded-lg border border-slate-200"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
                <span className="text-xs text-slate-400">Превью фото</span>
              </div>
            )}
          </div>

          {/* Schedule toggle */}
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={scheduleMode}
                onChange={(e) => setScheduleMode(e.target.checked)}
                className="rounded border-slate-300"
              />
              Запланировать на время
            </label>
            {scheduleMode && (
              <input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
                min={minSchedule}
                className="bg-white border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-indigo-500 outline-none"
              />
            )}
          </div>

          {/* Send / Schedule button */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">
              {selectedIds.size === recipients.length
                ? broadcastFilter === "ordered"
                  ? "Все покупатели"
                  : "Все клиенты"
                : `${selectedIds.size} получател${selectedIds.size === 1 ? "ь" : selectedIds.size < 5 ? "я" : "ей"}`}
            </span>
            <button
              type="button"
              onClick={() => setShowConfirm(true)}
              disabled={sending || !broadcastText.trim() || selectedIds.size === 0 || (scheduleMode && !scheduledAt)}
              className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-5 py-2 text-sm font-medium transition-colors disabled:opacity-50"
            >
              {sending ? "Отправка..." : scheduleMode ? "Запланировать" : `Отправить (${selectedIds.size})`}
            </button>
          </div>

          {/* Result */}
          {broadcastResult && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm">
              <p className="font-semibold text-emerald-700">Рассылка завершена</p>
              <p className="text-emerald-600 mt-1">
                Отправлено: {broadcastResult.sent} / {broadcastResult.total_targets}
                {broadcastResult.failed > 0 && (
                  <span className="text-rose-500 ml-2">({broadcastResult.failed} {plural(broadcastResult.failed, "ошибка", "ошибки", "ошибок")})</span>
                )}
              </p>
              {broadcastResult.truncated && broadcastResult.total_audience && (
                <p className="text-amber-600 mt-1">
                  Аудитория была ограничена до 5 000 из {broadcastResult.total_audience.toLocaleString("ru")} клиентов
                </p>
              )}
            </div>
          )}
        </div>
      </section>

      {/* Confirmation dialog */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 mx-4">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">
              {scheduleMode ? "Запланировать рассылку?" : "Отправить рассылку?"}
            </h3>
            <div className="space-y-2 mb-4">
              <p className="text-sm text-slate-600">
                <span className="font-medium">Получатели:</span> {selectedIds.size} из {recipients.length} ({broadcastFilter === "ordered" ? "покупатели" : "все клиенты"})
              </p>
              {imageUrl.trim() && (
                <p className="text-sm text-slate-600">
                  <span className="font-medium">Фото:</span> прикреплено
                </p>
              )}
              {scheduleMode && scheduledAt && (
                <p className="text-sm text-slate-600">
                  <span className="font-medium">Время:</span> {new Date(scheduledAt).toLocaleString("ru")}
                </p>
              )}
              <div className="bg-slate-50 rounded-lg p-3 text-sm text-slate-700 max-h-32 overflow-y-auto whitespace-pre-wrap">
                {broadcastText}
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-medium transition-colors"
              >
                Отмена
              </button>
              <button
                onClick={sendBroadcast}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors"
              >
                {scheduleMode ? "Запланировать" : `Отправить (${selectedIds.size})`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Broadcast History */}
      {history.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">История рассылок</h2>
          <div className="space-y-2">
            {history.map((h) => {
              const st = statusConfig[h.status] || statusConfig.sent;
              return (
                <div key={h.id} className="card px-5 py-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded-lg text-xs font-medium ${st.color}`}>
                        {st.label}
                      </span>
                      <span className="px-2 py-0.5 rounded-lg text-xs bg-slate-100 text-slate-600">
                        {h.filter_type === "ordered" ? "Покупатели" : "Все"}
                      </span>
                      {h.image_url && (
                        <span className="px-2 py-0.5 rounded-lg text-xs bg-blue-50 text-blue-600">
                          С фото
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      {h.status === "sent" && (
                        <span className="text-xs text-emerald-600 font-medium">
                          {h.sent_count}/{h.total_targets}
                          {h.failed_count > 0 && <span className="text-rose-500 ml-1">({h.failed_count} {plural(h.failed_count, "ошибка", "ошибки", "ошибок")})</span>}
                        </span>
                      )}
                      {h.status === "scheduled" && h.scheduled_at && (
                        <span className="text-xs text-violet-600">
                          {new Date(h.scheduled_at).toLocaleString("ru")}
                        </span>
                      )}
                      <span className="text-xs text-slate-400">
                        {h.sent_at ? timeAgo(h.sent_at) : h.created_at ? timeAgo(h.created_at) : ""}
                      </span>
                      {h.status === "scheduled" && (
                        <button
                          onClick={() => cancelScheduled(h.id)}
                          className="text-xs px-2 py-0.5 bg-rose-50 text-rose-500 rounded-lg hover:bg-rose-100 transition-colors"
                        >
                          Отменить
                        </button>
                      )}
                    </div>
                  </div>
                  <p className="text-sm text-slate-700 line-clamp-2">{h.message_text}</p>
                  {/* Recipients toggle */}
                  <div className="mt-2">
                    <button
                      type="button"
                      onClick={() => setExpandedHistoryId(expandedHistoryId === h.id ? null : h.id)}
                      className="text-xs text-slate-400 hover:text-indigo-600 transition-colors"
                    >
                      {expandedHistoryId === h.id
                        ? "▾ Скрыть получателей"
                        : h.recipients && h.recipients.length > 0
                          ? `▸ Получатели (${h.recipients.length})`
                          : `▸ Получатели (${h.total_targets})`}
                    </button>
                    {expandedHistoryId === h.id && (
                      h.recipients && h.recipients.length > 0 ? (
                        <div className="mt-1.5 bg-slate-50 rounded-lg border border-slate-100 max-h-48 overflow-y-auto divide-y divide-slate-100">
                          {h.recipients.map((r, ri) => (
                            <div key={ri} className="flex items-center gap-2 px-3 py-1.5 text-xs">
                              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${r.sent ? "bg-emerald-500" : "bg-rose-400"}`} />
                              <span className="text-slate-700">{r.name}</span>
                              {r.username && <span className="text-indigo-500">@{r.username}</span>}
                              <a
                                href={`/conversations/${r.conversation_id}?search=${encodeURIComponent(h.message_text.slice(0, 30))}`}
                                className="ml-auto text-indigo-500 hover:text-indigo-700 transition-colors"
                                title="Открыть диалог"
                              >
                                Открыть &rarr;
                              </a>
                              {!r.sent && <span className="text-rose-500">ошибка</span>}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="mt-1.5 bg-slate-50 rounded-lg border border-slate-100 px-3 py-3 text-xs text-slate-400">
                          Список получателей недоступен для старых рассылок (отправлено: {h.sent_count})
                        </div>
                      )
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}
      <ConfirmDialog
        open={!!deletingRecipient}
        title="Удалить клиента?"
        message={`${deletingRecipient?.name || "Клиент"} будет удалён вместе со всеми сообщениями, заказами и лидами. Это действие необратимо.`}
        confirmText="Удалить"
        variant="danger"
        loading={deleteLoading}
        onConfirm={deleteRecipient}
        onCancel={() => setDeletingRecipient(null)}
      />
    </div>
  );
}
