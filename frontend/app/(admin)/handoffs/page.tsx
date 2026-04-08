"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import Link from "next/link";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page-header";
import { FilterBar } from "@/components/ui/filter-bar";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { timeAgo } from "@/lib/time-ago";

interface Handoff {
  id: string;
  conversation_id: string;
  conversation_name: string | null;
  reason: string;
  summary: string | null;
  priority: string;
  status: string;
  assigned_to_user_id: string | null;
  assigned_to_user_name: string | null;
  resolution_notes: string | null;
  linked_order_id: string | null;
  linked_order_number: string | null;
  created_at: string;
  resolved_at: string | null;
}

interface Operator {
  id: string;
  full_name: string;
  role: string;
  email: string;
}

const priorityConfig: Record<string, { label: string; color: string; icon: string }> = {
  low: { label: "Низкий", color: "bg-slate-100 text-slate-700", icon: "↓" },
  normal: { label: "Обычный", color: "bg-blue-100 text-blue-700", icon: "—" },
  high: { label: "Высокий", color: "bg-amber-100 text-amber-700", icon: "↑" },
  urgent: { label: "Срочный", color: "bg-rose-100 text-rose-700", icon: "!!" },
};

const handoffStatusColors: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  assigned: "bg-blue-100 text-blue-700",
  resolved: "bg-emerald-100 text-emerald-700",
};

const handoffStatusLabels: Record<string, string> = {
  pending: "Ожидает",
  assigned: "Назначен",
  resolved: "Решён",
};

const handoffFilters = [
  { value: "all", label: "Все" },
  { value: "pending", label: "Ожидают" },
  { value: "resolved", label: "Решённые" },
];

const priorityOrder: Record<string, number> = { urgent: 0, high: 1, normal: 2, low: 3 };

function timePending(created: string): string {
  const ms = Date.now() - new Date(created).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "только что";
  if (mins < 60) return `${mins} мин`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} ч ${mins % 60} мин`;
  return `${Math.floor(hrs / 24)} дн ${hrs % 24} ч`;
}

export default function HandoffsPage() {
  const { toast } = useToast();
  const [handoffs, setHandoffs] = useState<Handoff[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [operators, setOperators] = useState<Operator[]>([]);
  const knownPendingIds = useRef<Set<string>>(new Set());
  const initialLoadDone = useRef(false);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const audioBufferRef = useRef<AudioBuffer | null>(null);
  const [muted, setMuted] = useState(false);
  const [soundReady, setSoundReady] = useState(false);

  // Resolve dialog state
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolveNotes, setResolveNotes] = useState("");

  // Load notification sound into Web Audio API buffer
  const initAudio = useCallback(async () => {
    if (audioCtxRef.current) return;
    const ctx = new AudioContext();
    audioCtxRef.current = ctx;
    try {
      const resp = await fetch("/sounds/notification.wav");
      const buf = await resp.arrayBuffer();
      audioBufferRef.current = await ctx.decodeAudioData(buf);
      setSoundReady(true);
    } catch (e) {
      console.error("Failed to load notification sound", e);
    }
  }, []);

  // Play sound via Web Audio API (works in background tabs)
  const playSound = useCallback(() => {
    const ctx = audioCtxRef.current;
    const buffer = audioBufferRef.current;
    if (!ctx || !buffer) return;
    if (ctx.state === "suspended") ctx.resume();
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    const gain = ctx.createGain();
    gain.gain.value = 1.0;
    source.connect(gain);
    gain.connect(ctx.destination);
    source.start(0);
  }, []);

  // Also send browser notification
  const sendBrowserNotification = useCallback((title: string, body: string) => {
    if (Notification.permission === "granted") {
      new Notification(title, { body, icon: "/favicon.ico" });
    }
  }, []);

  // Request notification permission + init audio on first click anywhere
  useEffect(() => {
    const handler = () => {
      initAudio();
      if (Notification.permission === "default") {
        Notification.requestPermission();
      }
    };
    document.addEventListener("click", handler, { once: true });
    return () => document.removeEventListener("click", handler);
  }, [initAudio]);

  // Load operators once
  useEffect(() => {
    api.get<Operator[]>("/auth/operators").then(setOperators).catch(console.error);
  }, []);

  const load = useCallback(() => {
    const params = filter !== "all" ? `?status=${filter}` : "";
    api.get<Handoff[]>(`/handoffs${params}`).then((data) => {
      data.sort((a, b) => {
        if (a.status === "pending" && b.status !== "pending") return -1;
        if (a.status !== "pending" && b.status === "pending") return 1;
        const pa = priorityOrder[a.priority] ?? 2;
        const pb = priorityOrder[b.priority] ?? 2;
        if (pa !== pb) return pa - pb;
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      });

      // Sound notification on new pending handoffs (track by ID)
      const currentPendingIds = new Set(data.filter((h) => h.status === "pending").map((h) => h.id));
      if (initialLoadDone.current) {
        const newIds = [...currentPendingIds].filter((id) => !knownPendingIds.current.has(id));
        if (newIds.length > 0 && !muted) {
          playSound();
          const newH = data.find((h) => h.id === newIds[0]);
          sendBrowserNotification(
            "Новый хендофф!",
            newH ? `${newH.conversation_name || "Клиент"}: ${newH.reason}` : "Требуется внимание оператора"
          );
        }
      }
      knownPendingIds.current = currentPendingIds;
      initialLoadDone.current = true;

      setHandoffs(data);
    }).catch(console.error);
  }, [filter, muted]);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh: 5s
  useEffect(() => {
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  const resolve = async (id: string, notes: string) => {
    try {
      await api.patch(`/handoffs/${id}`, {
        status: "resolved",
        resolution_notes: notes || null,
      });
      setHandoffs((prev) =>
        prev.map((h) =>
          h.id === id ? { ...h, status: "resolved", resolution_notes: notes || null } : h
        )
      );
      setResolvingId(null);
      setResolveNotes("");
    } catch (e: any) {
      toast(e?.detail || "Ошибка при закрытии", "error");
    }
  };

  const assignOperator = async (handoffId: string, operatorId: string) => {
    const op = operators.find((o) => o.id === operatorId);
    try {
      await api.patch(`/handoffs/${handoffId}`, {
        assigned_to_user_id: operatorId,
        status: "assigned",
      });
      setHandoffs((prev) =>
        prev.map((h) =>
          h.id === handoffId
            ? { ...h, assigned_to_user_id: operatorId, assigned_to_user_name: op?.full_name || null, status: "assigned" }
            : h
        )
      );
    } catch (e: any) {
      toast(e?.detail || "Ошибка назначения оператора", "error");
    }
  };

  const pendingCount = handoffs.filter((h) => h.status === "pending").length;

  return (
    <div>
      <PageHeader title="Передача оператору" badge={pendingCount}>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              initAudio().then(() => playSound());
            }}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-50 text-violet-700 hover:bg-violet-100 transition-colors"
            title="Прослушать звук уведомления"
          >
            🔊 Тест звука
          </button>
          <button
            type="button"
            onClick={() => setMuted(!muted)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              muted
                ? "bg-slate-100 text-slate-500"
                : "bg-indigo-50 text-indigo-700"
            }`}
            title={muted ? "Звук выключен" : "Звук включён"}
          >
            {muted ? "🔇 Без звука" : "🔔 Звук"}
          </button>
          <FilterBar
            filters={handoffFilters}
            selected={filter}
            onChange={setFilter}
          />
        </div>
      </PageHeader>

      {/* Resolve dialog */}
      {resolvingId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 mx-4">
            <h3 className="text-lg font-semibold text-slate-900 mb-1">Решение хандоффа</h3>
            <p className="text-sm text-slate-500 mb-4">
              Добавьте заметки о том, как была решена проблема (необязательно)
            </p>
            <textarea
              value={resolveNotes}
              onChange={(e) => setResolveNotes(e.target.value)}
              placeholder="Клиент хотел изменить адрес, обновлено вручную..."
              className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-sm h-28 resize-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              autoFocus
              maxLength={2000}
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={() => { setResolvingId(null); setResolveNotes(""); }}
                className="px-4 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-medium transition-colors"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={() => resolve(resolvingId, resolveNotes)}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm font-medium transition-colors"
              >
                Решено
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {handoffs.length === 0 ? (
          <EmptyState message="Нет запросов на передачу оператору" />
        ) : (
          handoffs.map((h) => {
            const priority = priorityConfig[h.priority] || priorityConfig.normal;

            return (
              <div
                key={h.id}
                className={`card px-5 py-4 ${
                  h.status === "pending" ? "border-l-4 border-l-amber-400" : ""
                }`}
              >
                {/* Top row: priority + status + time */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`px-2 py-0.5 rounded-lg text-xs font-medium ${priority.color}`}>
                      {priority.icon} {priority.label}
                    </span>
                    <StatusBadge status={h.status} colorMap={handoffStatusColors} labels={handoffStatusLabels} />
                    {h.linked_order_number && (
                      <span className="px-2 py-0.5 rounded-lg text-xs bg-violet-100 text-violet-700">
                        {h.linked_order_number}
                      </span>
                    )}
                    {h.assigned_to_user_name && (
                      <span className="px-2 py-0.5 rounded-lg text-xs bg-indigo-50 text-indigo-600">
                        👤 {h.assigned_to_user_name}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    {h.status === "pending" && (
                      <span className="text-xs text-amber-600 font-medium">
                        ⏱ {timePending(h.created_at)}
                      </span>
                    )}
                    <span className="text-xs text-slate-400">{timeAgo(h.created_at)}</span>
                  </div>
                </div>

                {/* Conversation name + reason */}
                <div className="mb-2">
                  {h.conversation_name && (
                    <Link
                      href={`/conversations/${h.conversation_id}`}
                      className="text-sm font-medium text-indigo-600 hover:text-indigo-700 transition-colors"
                    >
                      {h.conversation_name}
                    </Link>
                  )}
                  <p className="text-sm text-slate-700 mt-1">{h.reason}</p>
                </div>

                {/* Summary */}
                {h.summary && (
                  <p className="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2 mb-2">{h.summary}</p>
                )}

                {/* Resolution notes */}
                {h.resolution_notes && (
                  <div className="text-xs bg-emerald-50 text-emerald-700 rounded-lg px-3 py-2 mb-2">
                    <span className="font-medium">Заметки: </span>{h.resolution_notes}
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-3 mt-2 flex-wrap">
                  <Link
                    href={`/conversations/${h.conversation_id}`}
                    className="text-xs text-indigo-600 hover:text-indigo-700 transition-colors"
                  >
                    Открыть диалог
                  </Link>

                  {/* Operator assignment dropdown */}
                  {h.status !== "resolved" && operators.length > 0 && (
                    <select
                      value={h.assigned_to_user_id || ""}
                      onChange={(e) => {
                        if (e.target.value) assignOperator(h.id, e.target.value);
                      }}
                      className="text-xs bg-white border border-slate-200 rounded-lg px-2 py-1 outline-none focus:ring-2 focus:ring-indigo-500 transition-all"
                    >
                      <option value="">Назначить...</option>
                      {operators.map((op) => (
                        <option key={op.id} value={op.id}>
                          {op.full_name} ({op.role})
                        </option>
                      ))}
                    </select>
                  )}

                  {h.status !== "resolved" && (
                    <button
                      type="button"
                      onClick={() => { setResolvingId(h.id); setResolveNotes(""); }}
                      className="text-xs px-3 py-1 bg-emerald-50 text-emerald-700 rounded-lg hover:bg-emerald-100 transition-colors"
                    >
                      Решено
                    </button>
                  )}

                  {h.resolved_at && (
                    <span className="text-xs text-slate-400">
                      Решено: {new Date(h.resolved_at).toLocaleString("ru")}
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
