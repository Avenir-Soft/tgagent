"use client";

import { useEffect, useState, useCallback } from "react";
import { api, API_BASE } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import Link from "next/link";

interface TrainingStats {
  candidate_conversations: number;
  total_ai_messages: number;
  labeled: { approved: number; rejected: number };
  unlabeled_in_candidates: number;
  coverage_pct: number;
}

interface CandidateConv {
  id: string;
  customer: string;
  username: string | null;
  last_message_at: string | null;
  ai_messages: number;
  approved: number;
  rejected: number;
  unlabeled: number;
}

interface ConvMessage {
  id: string;
  direction: string;
  sender_type: string;
  raw_text: string | null;
  ai_generated: boolean;
  training_label: string | null;
  created_at: string;
}

interface FineTuneJob {
  job_id: string;
  status: string;
  model: string;
  fine_tuned_model: string | null;
  trained_tokens: number | null;
  error: string | null;
}

interface RejectionPattern {
  reason: string;
  count: number;
  examples: {
    id: string;
    ai_text: string;
    user_text: string;
    selected_text: string | null;
  }[];
}

interface RejectionAnalysis {
  total_rejected: number;
  patterns: RejectionPattern[];
  top_errors: { reason: string; count: number }[];
}

interface PromptRule {
  id: string;
  rule: string;
  reason: string;
  source: "auto" | "manual";
  active: boolean;
  created_at: string;
}

export default function TrainingPage() {
  const [stats, setStats] = useState<TrainingStats | null>(null);
  const [convs, setConvs] = useState<CandidateConv[]>([]);
  const [exporting, setExporting] = useState(false);
  const [smartLabeling, setSmartLabeling] = useState<string | null>(null);
  const [smartLabelingAll, setSmartLabelingAll] = useState(false);
  const [fineTuning, setFineTuning] = useState(false);
  const [ftJobs, setFtJobs] = useState<FineTuneJob[]>([]);
  const [activeTab, setActiveTab] = useState<"label" | "finetune" | "rules">("label");
  const [resetting, setResetting] = useState<string | null>(null);

  // Rules tab state
  const [analysis, setAnalysis] = useState<RejectionAnalysis | null>(null);
  const [rules, setRules] = useState<PromptRule[]>([]);
  const [generating, setGenerating] = useState(false);
  const [newRule, setNewRule] = useState("");
  const [newReason, setNewReason] = useState("");
  const [expandedPattern, setExpandedPattern] = useState<string | null>(null);

  // Inline labeling state
  const [expandedConvId, setExpandedConvId] = useState<string | null>(null);
  const [convMessages, setConvMessages] = useState<ConvMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [labelingMsgId, setLabelingMsgId] = useState<string | null>(null);

  // Rejection reason dialog
  const [rejectingMsgId, setRejectingMsgId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectSelected, setRejectSelected] = useState("");
  const [pendingConfirm, setPendingConfirm] = useState<{ title: string; message: string; variant: "danger" | "warning" | "info"; action: () => void } | null>(null);

  const { toast } = useToast();

  const refresh = () => {
    api.get<TrainingStats>("/training/stats").then(setStats).catch(() => toast("Не удалось загрузить статистику обучения", "error"));
    api.get<CandidateConv[]>("/training/conversations").then(setConvs).catch(() => toast("Не удалось загрузить диалоги", "error"));
  };

  const refreshRules = () => {
    api.get<PromptRule[]>("/ai-settings/prompt-rules").then(setRules).catch(() => toast("Не удалось загрузить правила", "error"));
    api.get<RejectionAnalysis>("/training/rejection-analysis").then(setAnalysis).catch(() => toast("Не удалось загрузить анализ", "error"));
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (activeTab === "finetune") {
      api.get<FineTuneJob[]>("/training/fine-tune-status").then(setFtJobs).catch(() => {});
    }
    if (activeTab === "rules") {
      refreshRules();
    }
  }, [activeTab]);

  const smartLabel = async (id: string) => {
    setSmartLabeling(id);
    try {
      const r = await api.post<{ approved: number; rejected: number; total_reviewed: number; model_used: string }>(
        `/training/conversations/${id}/smart-label`,
        {}
      );
      toast(`GPT-4o: +${r.approved} одобрено, -${r.rejected} отклонено (${r.total_reviewed} ответов)`, "success");
      refresh();
    } catch {
      toast("Ошибка при умной разметке", "error");
    } finally {
      setSmartLabeling(null);
    }
  };

  const smartLabelAll = () => {
    setPendingConfirm({
      title: "Автооценка GPT-4o",
      message: "Запустить GPT-4o оценку ВСЕХ неразмеченных ответов?\nЭто может занять 1-2 минуты. Стоимость: ~$0.01 за сообщение (GPT-4o input).",
      variant: "warning",
      action: async () => {
        setSmartLabelingAll(true);
        try {
          const r = await api.post<{ approved: number; rejected: number; total_reviewed: number; conversations_processed: number }>(
            "/training/smart-label-all",
            {}
          );
          toast(`Готово! ${r.conversations_processed} диалогов: +${r.approved} / -${r.rejected}`, "success");
          refresh();
        } catch {
          toast("Ошибка", "error");
        } finally {
          setSmartLabelingAll(false);
        }
      },
    });
  };

  const resetLabels = (id: string) => {
    setPendingConfirm({
      title: "Сброс меток",
      message: "Сбросить все метки для этого диалога? Можно будет переразметить.",
      variant: "warning",
      action: async () => {
        setResetting(id);
        try {
          const r = await api.post<{ reset_count: number }>(`/training/conversations/${id}/reset-labels`, {});
          toast(`Сброшено ${r.reset_count} меток`, "success");
          refresh();
        } catch {
          toast("Ошибка", "error");
        } finally {
          setResetting(null);
        }
      },
    });
  };

  const toggleExpand = async (convId: string) => {
    if (expandedConvId === convId) {
      setExpandedConvId(null);
      return;
    }
    setExpandedConvId(convId);
    setLoadingMessages(true);
    try {
      const msgs = await api.get<ConvMessage[]>(`/conversations/${convId}/messages`);
      setConvMessages(msgs);
    } catch {
      toast("Ошибка загрузки сообщений", "error");
    } finally {
      setLoadingMessages(false);
    }
  };

  const inlineLabel = async (msgId: string, label: "approved" | "rejected", reason?: string, selectedText?: string) => {
    setLabelingMsgId(msgId);
    try {
      const body: Record<string, string | null> = { label };
      if (label === "rejected") {
        body.reason = reason || null;
        body.selected_text = selectedText || null;
      }
      await api.patch(`/training/messages/${msgId}/label`, body);
      setConvMessages((prev) =>
        prev.map((m) => (m.id === msgId ? { ...m, training_label: label } : m))
      );
      refresh();
    } catch {
      toast("Ошибка", "error");
    } finally {
      setLabelingMsgId(null);
    }
  };

  const openRejectDialog = (msgId: string) => {
    setRejectingMsgId(msgId);
    setRejectReason("");
    setRejectSelected("");
  };

  const submitReject = () => {
    if (!rejectingMsgId) return;
    inlineLabel(rejectingMsgId, "rejected", rejectReason, rejectSelected);
    setRejectingMsgId(null);
  };

  const exportJSONL = async () => {
    setExporting(true);
    try {
      let token: string | null = null;
      try { token = localStorage.getItem("token"); } catch { /* SSR / disabled storage */ }
      const res = await fetch(`${API_BASE}/training/export.jsonl`, {
        headers: { Authorization: `Bearer ${token || ""}` },
      });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `training_${new Date().toISOString().slice(0, 10)}.jsonl`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast("Ошибка экспорта", "error");
    } finally {
      setExporting(false);
    }
  };

  const startFineTune = () => {
    setPendingConfirm({
      title: "Fine-tuning",
      message: "Запустить fine-tuning на основе одобренных данных?\nOpenAI возьмёт ~$0.50-5 в зависимости от объёма.",
      variant: "warning",
      action: async () => {
        setFineTuning(true);
        try {
          const r = await api.post<{ job_id: string; training_examples: number; status: string }>(
            "/training/fine-tune",
            {}
          );
          toast(`Fine-tuning запущен! ${r.training_examples} примеров`, "success");
          api.get<FineTuneJob[]>("/training/fine-tune-status").then(setFtJobs).catch(() => {});
        } catch (e: any) {
          toast(e?.message || "Ошибка при запуске fine-tuning", "error");
        } finally {
          setFineTuning(false);
        }
      },
    });
  };

  // Rules actions
  const generateRules = () => {
    setPendingConfirm({
      title: "Генерация правил",
      message: "GPT-4o проанализирует отклонённые ответы и создаст правила для промпта.\nСтоимость ~$0.10-0.50.",
      variant: "info",
      action: async () => {
        setGenerating(true);
        try {
          const r = await api.post<{ generated: number; total_rules: number; rules: PromptRule[] }>(
            "/training/generate-rules",
            {}
          );
          toast(`Создано ${r.generated} правил из анализа ошибок`, "success");
          refreshRules();
        } catch (e: any) {
          toast(e?.message || "Ошибка генерации правил", "error");
        } finally {
          setGenerating(false);
        }
      },
    });
  };

  const addManualRule = async () => {
    if (!newRule.trim()) return;
    try {
      await api.post("/ai-settings/prompt-rules", {
        rule: newRule.trim(),
        reason: newReason.trim(),
      });
      setNewRule("");
      setNewReason("");
      refreshRules();
    } catch {
      toast("Ошибка", "error");
    }
  };

  const toggleRule = useCallback(async (id: string, active: boolean) => {
    try {
      await api.patch(`/ai-settings/prompt-rules/${id}`, { active });
      setRules((prev) => prev.map((r) => (r.id === id ? { ...r, active } : r)));
    } catch {
      toast("Ошибка", "error");
    }
  }, [toast]);

  const deleteRule = (id: string) => {
    setPendingConfirm({
      title: "Удалить правило",
      message: "Удалить это правило?",
      variant: "danger",
      action: async () => {
        try {
          await api.delete(`/ai-settings/prompt-rules/${id}`);
          setRules((prev) => prev.filter((r) => r.id !== id));
        } catch {
          toast("Ошибка", "error");
        }
      },
    });
  };

  const statusColors: Record<string, string> = {
    succeeded: "bg-emerald-100 text-emerald-700",
    running: "bg-indigo-100 text-indigo-700",
    queued: "bg-amber-100 text-amber-700",
    failed: "bg-rose-100 text-rose-700",
    cancelled: "bg-slate-100 text-slate-500",
    validating_files: "bg-violet-100 text-violet-700",
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Обучение AI</h1>
          <p className="text-sm text-slate-500 mt-1">Разметка, правила и fine-tuning модели</p>
        </div>
        <div className="flex gap-1 bg-slate-100 rounded-xl p-1">
          <button
            type="button"
            onClick={() => setActiveTab("label")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === "label" ? "bg-white shadow-sm text-slate-900" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            Разметка
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("rules")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === "rules" ? "bg-white shadow-sm text-slate-900" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            Правила
            {rules.filter((r) => r.active).length > 0 && (
              <span className="ml-1.5 bg-amber-500 text-white text-[10px] px-1.5 py-0.5 rounded-full">
                {rules.filter((r) => r.active).length}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("finetune")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === "finetune" ? "bg-white shadow-sm text-slate-900" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            Fine-tuning
          </button>
        </div>
      </div>

      {/* Stats + Pie Chart */}
      {stats && (
        <div className="flex gap-4 mb-6">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 flex-1">
            <StatCard label="Диалогов" value={stats.candidate_conversations} color="indigo" />
            <StatCard label="AI ответов" value={stats.total_ai_messages} color="indigo" />
            <StatCard label="Одобрено" value={stats.labeled.approved} color="emerald" />
            <StatCard label="Отклонено" value={stats.labeled.rejected} color="rose" />
            <StatCard
              label="Покрытие"
              value={`${stats.coverage_pct}%`}
              color={stats.coverage_pct > 50 ? "emerald" : "amber"}
            />
            <StatCard
              label="GPT-4o расход"
              value={`~$${((stats.labeled.approved + stats.labeled.rejected) * 0.015).toFixed(2)}`}
              color="amber"
            />
          </div>
          {/* Pie chart */}
          {stats.total_ai_messages > 0 && (
            <div className="card p-4 flex flex-col items-center justify-center w-48 shrink-0">
              <LabelPie
                approved={stats.labeled.approved}
                rejected={stats.labeled.rejected}
                unlabeled={stats.total_ai_messages - stats.labeled.approved - stats.labeled.rejected}
              />
              <div className="flex gap-3 mt-2 text-[10px]">
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Одобр.</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-rose-400 inline-block" /> Откл.</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-slate-200 inline-block" /> Нет</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* === LABEL TAB === */}
      {activeTab === "label" && (
        <>
          {/* Workflow steps */}
          <div className="bg-gradient-to-r from-indigo-50 to-violet-50 border border-indigo-100 rounded-xl p-5 mb-6">
            <p className="font-semibold text-indigo-800 mb-3">Пайплайн обучения</p>
            <div className="flex items-center gap-2 text-sm">
              <Step n={1} label="Диалоги с бронированиями" done={(stats?.candidate_conversations ?? 0) > 0} />
              <Arrow />
              <Step n={2} label="GPT-4o разметка" done={(stats?.coverage_pct ?? 0) > 50} />
              <Arrow />
              <Step n={3} label="Правила из ошибок" done={rules.filter((r) => r.active).length > 0} />
              <Arrow />
              <Step n={4} label="Fine-tuning" done={false} />
              <Arrow />
              <Step n={5} label="Своя модель" done={false} />
            </div>
          </div>

          {/* Global actions */}
          <div className="flex gap-3 mb-4">
            <button
              type="button"
              onClick={smartLabelAll}
              disabled={smartLabelingAll || (stats?.unlabeled_in_candidates ?? 0) === 0}
              className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
            >
              {smartLabelingAll
                ? "GPT-4o анализирует..."
                : `GPT-4o: разметить все (${stats?.unlabeled_in_candidates ?? 0} ответов)`}
            </button>
            <button
              type="button"
              onClick={exportJSONL}
              disabled={exporting || !stats?.labeled.approved}
              className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
            >
              {exporting ? "Экспорт..." : `Экспорт JSONL (${stats?.labeled.approved ?? 0})`}
            </button>
          </div>

          {/* Candidate conversations */}
          <div className="space-y-2">
            {convs.length === 0 ? (
              <div className="card p-8 text-center text-slate-400">
                Нет диалогов-кандидатов. Они появятся после первых бронирований через AI.
              </div>
            ) : (
              convs.map((c) => (
                <div key={c.id} className="card overflow-hidden">
                  <div className="px-5 py-4 flex items-center gap-4">
                    <button
                      type="button"
                      onClick={() => toggleExpand(c.id)}
                      className="text-slate-400 hover:text-slate-600 transition-colors shrink-0"
                      title="Инлайн-разметка"
                    >
                      {expandedConvId === c.id ? "▼" : "▶"}
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm text-slate-900">{c.customer}</span>
                        {c.username && <span className="text-xs text-indigo-600">@{c.username}</span>}
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-xs text-slate-400">
                        <span>{c.ai_messages} AI</span>
                        {c.approved > 0 && <span className="text-emerald-600">+ {c.approved}</span>}
                        {c.rejected > 0 && <span className="text-rose-500">- {c.rejected}</span>}
                        {c.unlabeled > 0 && (
                          <span className="bg-amber-50 text-amber-700 px-1.5 py-0.5 rounded">
                            {c.unlabeled} ждут
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Progress bar */}
                    {c.ai_messages > 0 && (
                      <div className="w-20 shrink-0">
                        <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden flex">
                          <div
                            className="h-full bg-emerald-500"
                            style={{ width: `${Math.round((c.approved / c.ai_messages) * 100)}%` }}
                          />
                          <div
                            className="h-full bg-rose-400"
                            style={{ width: `${Math.round((c.rejected / c.ai_messages) * 100)}%` }}
                          />
                        </div>
                        <div className="text-[10px] text-center text-slate-400 mt-0.5">
                          {Math.round(((c.approved + c.rejected) / c.ai_messages) * 100)}%
                        </div>
                      </div>
                    )}

                    <div className="flex gap-1.5 shrink-0">
                      <button
                        type="button"
                        onClick={() => smartLabel(c.id)}
                        disabled={smartLabeling === c.id || c.unlabeled === 0}
                        className="px-2.5 py-1.5 text-xs bg-indigo-50 text-indigo-600 hover:bg-indigo-100 rounded-lg disabled:opacity-40 transition-colors"
                        title="GPT-4o оценит каждый ответ AI"
                      >
                        {smartLabeling === c.id ? "..." : "GPT-4o"}
                      </button>
                      {(c.approved > 0 || c.rejected > 0) && (
                        <button
                          type="button"
                          onClick={() => resetLabels(c.id)}
                          disabled={resetting === c.id}
                          className="px-2.5 py-1.5 text-xs bg-slate-50 text-slate-500 hover:bg-slate-100 rounded-lg transition-colors"
                          title="Сбросить все метки"
                        >
                          {resetting === c.id ? "..." : "Сброс"}
                        </button>
                      )}
                      <Link
                        href={`/conversations/${c.id}`}
                        className="px-2.5 py-1.5 text-xs bg-indigo-50 text-indigo-600 hover:bg-indigo-100 rounded-lg transition-colors"
                      >
                        Открыть
                      </Link>
                    </div>
                  </div>

                  {/* Inline messages for labeling */}
                  {expandedConvId === c.id && (
                    <div className="border-t border-slate-100 bg-slate-50 px-5 py-3 max-h-96 overflow-y-auto space-y-2">
                      {loadingMessages ? (
                        <p className="text-xs text-slate-400 py-4 text-center">Загрузка...</p>
                      ) : (
                        convMessages.map((m) => {
                          const isAI = m.ai_generated;
                          const isCustomer = m.sender_type === "customer";
                          return (
                            <div
                              key={m.id}
                              className={`flex ${isCustomer ? "justify-start" : "justify-end"}`}
                            >
                              <div className={`max-w-[80%] rounded-xl px-3 py-2 text-sm ${
                                isCustomer
                                  ? "bg-white border border-slate-200 text-slate-700"
                                  : m.training_label === "approved"
                                    ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                                    : m.training_label === "rejected"
                                      ? "bg-rose-100 text-rose-800 border border-rose-200"
                                      : "bg-indigo-50 text-slate-700 border border-indigo-100"
                              }`}>
                                {!isCustomer && (
                                  <div className="text-[10px] mb-0.5 opacity-60">
                                    {m.sender_type === "ai" || isAI ? "AI" : m.sender_type}
                                  </div>
                                )}
                                <p className="whitespace-pre-wrap text-xs">{m.raw_text || "—"}</p>
                                {/* Label buttons for AI messages */}
                                {isAI && (
                                  <div className="flex items-center gap-1.5 mt-1.5 pt-1.5 border-t border-current/10">
                                    {m.training_label === "approved" ? (
                                      <span className="text-[10px] text-emerald-600 font-medium">Одобрено</span>
                                    ) : m.training_label === "rejected" ? (
                                      <span className="text-[10px] text-rose-600 font-medium">Отклонено</span>
                                    ) : (
                                      <>
                                        <button
                                          type="button"
                                          onClick={() => inlineLabel(m.id, "approved")}
                                          disabled={labelingMsgId === m.id}
                                          className="text-[10px] px-2 py-0.5 bg-emerald-500 text-white rounded hover:bg-emerald-600 transition-colors"
                                        >
                                          {labelingMsgId === m.id ? "..." : "+"}
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => openRejectDialog(m.id)}
                                          disabled={labelingMsgId === m.id}
                                          className="text-[10px] px-2 py-0.5 bg-rose-500 text-white rounded hover:bg-rose-600 transition-colors"
                                        >
                                          {labelingMsgId === m.id ? "..." : "-"}
                                        </button>
                                      </>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </>
      )}

      {/* === RULES TAB === */}
      {activeTab === "rules" && (
        <>
          {/* How it works */}
          <div className="bg-gradient-to-r from-amber-50 to-rose-50 border border-amber-100 rounded-xl p-5 mb-6">
            <p className="font-semibold text-amber-800 mb-2">Обучение на ошибках</p>
            <p className="text-sm text-amber-700">
              AI анализирует отклонённые ответы, находит паттерны ошибок и создаёт правила.
              Эти правила автоматически добавляются в системный промпт: &laquo;НЕ делай X, потому что Y&raquo;.
            </p>
          </div>

          {/* Rejection Analysis */}
          <div className="card p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="font-semibold text-lg text-slate-900">Анализ отклонений</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  {analysis ? `${analysis.total_rejected} отклонённых ответов, ${analysis.patterns.length} паттернов` : "Загрузка..."}
                </p>
              </div>
              <button
                type="button"
                onClick={generateRules}
                disabled={generating || !analysis || analysis.total_rejected < 2}
                className="bg-amber-600 hover:bg-amber-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
              >
                {generating ? "GPT-4o анализирует..." : "GPT-4o: создать правила"}
              </button>
            </div>

            {analysis && analysis.patterns.length === 0 && (
              <div className="text-center py-8 text-slate-400">
                Нет отклонённых ответов. Разметьте диалоги на вкладке &laquo;Разметка&raquo;, чтобы найти ошибки AI.
              </div>
            )}

            {analysis && analysis.patterns.length > 0 && (
              <div className="space-y-2">
                {analysis.patterns.map((p) => (
                  <div key={p.reason} className="border border-slate-200 rounded-xl overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setExpandedPattern(expandedPattern === p.reason ? null : p.reason)}
                      className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 text-left transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <span className="bg-rose-100 text-rose-700 text-xs font-bold px-2 py-0.5 rounded">
                          {p.count}x
                        </span>
                        <span className="text-sm font-medium text-slate-900">{p.reason}</span>
                      </div>
                      <span className="text-slate-400 text-xs">{expandedPattern === p.reason ? "^" : "v"}</span>
                    </button>
                    {expandedPattern === p.reason && (
                      <div className="border-t border-slate-200 bg-slate-50 px-4 py-3 space-y-3">
                        {p.examples.map((ex) => (
                          <div key={ex.id} className="text-xs space-y-1">
                            {ex.user_text && (
                              <div>
                                <span className="text-slate-500">Клиент:</span>{" "}
                                <span className="text-slate-700">{ex.user_text}</span>
                              </div>
                            )}
                            <div>
                              <span className="text-rose-500">AI:</span>{" "}
                              <span className="text-slate-700">{ex.ai_text}</span>
                            </div>
                            {ex.selected_text && (
                              <div className="bg-rose-50 text-rose-600 px-2 py-1 rounded inline-block">
                                Проблема: {ex.selected_text}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Active Rules */}
          <div className="card p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="font-semibold text-lg text-slate-900">Правила для промпта</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Активные правила автоматически добавляются в системный промпт AI
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">
                  {rules.filter((r) => r.active).length} активных / {rules.length} всего
                </span>
              </div>
            </div>

            {rules.length === 0 ? (
              <div className="text-center py-8 text-slate-400">
                Нет правил. Нажмите &laquo;GPT-4o: создать правила&raquo; или добавьте вручную.
              </div>
            ) : (
              <div className="space-y-2">
                {rules.map((r) => (
                  <div
                    key={r.id}
                    className={`border rounded-xl px-4 py-3 transition-all ${r.active ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50 opacity-60"}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm font-medium ${r.active ? "text-slate-900" : "text-slate-500"}`}>
                          {r.rule}
                        </p>
                        {r.reason && (
                          <p className="text-xs text-slate-500 mt-1">
                            Причина: {r.reason}
                          </p>
                        )}
                        <div className="flex items-center gap-2 mt-1.5">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                            r.source === "auto"
                              ? "bg-violet-100 text-violet-600"
                              : "bg-indigo-100 text-indigo-600"
                          }`}>
                            {r.source === "auto" ? "GPT-4o" : "Вручную"}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          type="button"
                          onClick={() => toggleRule(r.id, !r.active)}
                          className={`w-10 h-5 rounded-full transition-colors ${
                            r.active ? "bg-amber-500" : "bg-slate-300"
                          }`}
                        >
                          <div
                            className={`w-4 h-4 bg-white rounded-full shadow transform transition-transform ${
                              r.active ? "translate-x-5" : "translate-x-0.5"
                            }`}
                          />
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteRule(r.id)}
                          className="text-slate-400 hover:text-rose-500 text-xs transition-colors"
                          title="Удалить"
                        >
                          x
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Add manual rule */}
            <div className="mt-4 border-t border-slate-200 pt-4">
              <p className="text-xs font-medium text-slate-600 mb-2">Добавить правило вручную</p>
              <div className="space-y-2">
                <input
                  type="text"
                  placeholder="НИКОГДА не смешивай русские слова в узбекском ответе"
                  value={newRule}
                  onChange={(e) => setNewRule(e.target.value)}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Причина (необязательно)"
                    value={newReason}
                    onChange={(e) => setNewReason(e.target.value)}
                    className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  />
                  <button
                    type="button"
                    onClick={addManualRule}
                    disabled={!newRule.trim()}
                    className="bg-amber-600 hover:bg-amber-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
                  >
                    Добавить
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* How it works */}
          <div className="bg-slate-50 rounded-xl p-5 text-sm text-slate-600 border border-slate-200/60">
            <p className="font-semibold text-slate-700 mb-2">Как это работает</p>
            <ol className="list-decimal list-inside space-y-1.5">
              <li><b>Разметка</b> — отклоняете плохие ответы AI с указанием причины</li>
              <li><b>Анализ</b> — GPT-4o группирует ошибки и находит паттерны</li>
              <li><b>Правила</b> — из паттернов создаются правила: &laquo;НЕ делай X, потому что Y&raquo;</li>
              <li><b>Промпт</b> — активные правила автоматически добавляются в системный промпт</li>
              <li><b>Результат</b> — AI видит свои ошибки и не повторяет их</li>
            </ol>
          </div>
        </>
      )}

      {/* === FINETUNE TAB === */}
      {activeTab === "finetune" && (
        <>
          {/* Fine-tune workflow */}
          <div className="card p-6 mb-6">
            <h2 className="font-semibold text-lg text-slate-900 mb-4">Fine-tuning</h2>
            <p className="text-sm text-slate-600 mb-4">
              Создай свою модель на основе одобренных ответов. Модель будет дешевле и лучше следовать стилю магазина.
            </p>

            <div className="grid grid-cols-3 gap-4 mb-6 text-center">
              <div className="bg-emerald-50 rounded-xl p-4">
                <div className="text-3xl font-bold text-emerald-700">{stats?.labeled.approved ?? 0}</div>
                <div className="text-xs text-emerald-600 mt-1">одобренных примеров</div>
              </div>
              <div className="bg-indigo-50 rounded-xl p-4">
                <div className="text-3xl font-bold text-indigo-700">gpt-4o-mini</div>
                <div className="text-xs text-indigo-600 mt-1">базовая модель</div>
              </div>
              <div className="bg-violet-50 rounded-xl p-4">
                <div className="text-3xl font-bold text-violet-700">~3</div>
                <div className="text-xs text-violet-600 mt-1">эпохи обучения</div>
              </div>
            </div>

            {(stats?.labeled.approved ?? 0) < 10 ? (
              <div className="bg-amber-50 border border-amber-100 rounded-xl p-4 text-sm text-amber-700 mb-4">
                Нужно минимум 10 одобренных примеров для fine-tuning. Сейчас: {stats?.labeled.approved ?? 0}.
                Разметьте больше диалогов на вкладке &laquo;Разметка&raquo;.
              </div>
            ) : (
              <button
                type="button"
                onClick={startFineTune}
                disabled={fineTuning}
                className="w-full px-4 py-3 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-semibold transition-colors disabled:opacity-50"
              >
                {fineTuning ? "Запуск..." : `Запустить Fine-tuning (${stats?.labeled.approved ?? 0} примеров)`}
              </button>
            )}
          </div>

          {/* Jobs list */}
          <div className="card p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-slate-900">История fine-tuning</h3>
              <button
                type="button"
                onClick={() => api.get<FineTuneJob[]>("/training/fine-tune-status").then(setFtJobs).catch(() => {})}
                className="text-xs text-indigo-600 hover:text-indigo-700 transition-colors"
              >
                Обновить
              </button>
            </div>

            {ftJobs.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-6">Ещё не запускали fine-tuning</p>
            ) : (
              <div className="space-y-3">
                {ftJobs.map((j) => (
                  <div key={j.job_id} className="border border-slate-200 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-mono text-slate-500">{j.job_id}</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusColors[j.status] || "bg-slate-100 text-slate-600"}`}>
                        {j.status}
                      </span>
                    </div>
                    <div className="text-sm text-slate-600">
                      <span>Модель: {j.model}</span>
                      {j.trained_tokens && <span className="ml-4">Токены: {j.trained_tokens.toLocaleString()}</span>}
                    </div>
                    {j.fine_tuned_model && (
                      <div className="mt-2 bg-emerald-50 border border-emerald-100 rounded-xl p-3">
                        <p className="text-xs text-emerald-600 font-medium mb-1">Готовая модель:</p>
                        <code className="text-xs text-emerald-800 break-all">{j.fine_tuned_model}</code>
                        <p className="text-[10px] text-emerald-500 mt-1">
                          Добавь в .env: OPENAI_MODEL_MAIN={j.fine_tuned_model}
                        </p>
                      </div>
                    )}
                    {j.error && (
                      <div className="mt-2 bg-rose-50 rounded-xl p-2 text-xs text-rose-600">{j.error}</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* How it works */}
          <div className="bg-slate-50 rounded-xl p-5 mt-6 text-sm text-slate-600 border border-slate-200/60">
            <p className="font-semibold text-slate-700 mb-2">Как это работает</p>
            <ol className="list-decimal list-inside space-y-1.5">
              <li><b>Разметка</b> — GPT-4o проверяет каждый ответ AI на качество</li>
              <li><b>Экспорт</b> — одобренные пары (вопрос/ответ) сохраняются в JSONL</li>
              <li><b>Fine-tuning</b> — OpenAI обучает gpt-4o-mini на ваших данных (10-30 мин)</li>
              <li><b>Валидация</b> — проверка качества модели на тестовых диалогах <span className="text-[10px] bg-violet-100 text-violet-600 px-1.5 py-0.5 rounded-full ml-1">Coming Soon</span></li>
              <li><b>Деплой</b> — автоматическое переключение на обученную модель <span className="text-[10px] bg-violet-100 text-violet-600 px-1.5 py-0.5 rounded-full ml-1">Coming Soon</span></li>
            </ol>
          </div>
        </>
      )}
      <ConfirmDialog
        open={!!pendingConfirm}
        title={pendingConfirm?.title || ""}
        message={pendingConfirm?.message || ""}
        confirmText="Подтвердить"
        variant={pendingConfirm?.variant || "warning"}
        onConfirm={() => { pendingConfirm?.action(); setPendingConfirm(null); }}
        onCancel={() => setPendingConfirm(null)}
      />

      {/* Rejection reason modal */}
      {rejectingMsgId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setRejectingMsgId(null)}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 mx-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-slate-900 mb-3">Причина отклонения</h3>
            <div className="flex flex-wrap gap-1.5 mb-3">
              {["Неверный язык", "Галлюцинация", "Неверная цена/спеки", "Плохой тон", "Не по теме", "Лишний вопрос"].map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRejectReason(rejectReason === r ? "" : r)}
                  className={`px-2.5 py-1 rounded-full text-xs transition-colors ${rejectReason === r ? "bg-rose-100 text-rose-700 font-medium" : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}
                >
                  {r}
                </button>
              ))}
            </div>
            <input
              type="text"
              placeholder="Или свою причину..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm mb-3 outline-none focus:ring-2 focus:ring-rose-400 focus:border-rose-400 transition-all"
            />
            <textarea
              placeholder="Выделенный текст (необязательно)..."
              value={rejectSelected}
              onChange={(e) => setRejectSelected(e.target.value)}
              rows={2}
              className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm mb-4 outline-none focus:ring-2 focus:ring-rose-400 focus:border-rose-400 transition-all resize-none"
            />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setRejectingMsgId(null)} className="px-4 py-2 text-sm text-slate-500 rounded-lg hover:bg-slate-50 transition-colors">Отмена</button>
              <button type="button" onClick={submitReject} className="px-4 py-2 text-sm bg-rose-600 text-white rounded-lg hover:bg-rose-700 transition-colors">Отклонить</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color: "indigo" | "emerald" | "rose" | "amber";
}) {
  const colors = {
    indigo: "bg-indigo-50 text-indigo-700",
    emerald: "bg-emerald-50 text-emerald-700",
    rose: "bg-rose-50 text-rose-700",
    amber: "bg-amber-50 text-amber-700",
  };
  return (
    <div className={`rounded-xl p-4 ${colors[color]}`}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs mt-1 opacity-70">{label}</div>
    </div>
  );
}

function Step({ n, label, done }: { n: number; label: string; done: boolean }) {
  return (
    <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
      done ? "bg-emerald-100 text-emerald-700" : "bg-white text-slate-500 border border-slate-200"
    }`}>
      <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
        done ? "bg-emerald-500 text-white" : "bg-slate-200 text-slate-500"
      }`}>
        {done ? "+" : n}
      </span>
      {label}
    </div>
  );
}

function Arrow() {
  return <span className="text-slate-300 text-xs shrink-0">&rarr;</span>;
}

function LabelPie({ approved, rejected, unlabeled }: { approved: number; rejected: number; unlabeled: number }) {
  const total = approved + rejected + unlabeled;
  if (total === 0) return null;

  const r = 40;
  const cx = 50;
  const cy = 50;
  const slices = [
    { value: approved, color: "#10b981" },
    { value: rejected, color: "#fb7185" },
    { value: unlabeled, color: "#e2e8f0" },
  ].filter((s) => s.value > 0);

  let cumulative = 0;
  const paths = slices.map((slice) => {
    const start = cumulative;
    cumulative += slice.value / total;
    const startAngle = start * 2 * Math.PI - Math.PI / 2;
    const endAngle = cumulative * 2 * Math.PI - Math.PI / 2;
    const largeArc = slice.value / total > 0.5 ? 1 : 0;
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);

    if (slices.length === 1) {
      return <circle key={slice.color} cx={cx} cy={cy} r={r} fill={slice.color} />;
    }
    return (
      <path
        key={`${slice.color}-${start}`}
        d={`M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${largeArc},1 ${x2},${y2} Z`}
        fill={slice.color}
      />
    );
  });

  return (
    <svg viewBox="0 0 100 100" className="w-24 h-24">
      {paths}
      <circle cx={cx} cy={cy} r={22} fill="white" />
      <text x={cx} y={cy - 3} textAnchor="middle" className="text-[10px] font-bold fill-slate-700">
        {Math.round((approved / total) * 100)}%
      </text>
      <text x={cx} y={cy + 8} textAnchor="middle" className="text-[6px] fill-slate-400">
        одобр.
      </text>
    </svg>
  );
}
