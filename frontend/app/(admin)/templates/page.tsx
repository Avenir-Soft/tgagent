"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Link from "next/link";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";

interface Template {
  id: string;
  trigger_type: string;
  trigger_patterns: string[];
  language: string;
  template_text: string;
  is_active: boolean;
  usage_count: number;
  platform: string;
}

interface AiSettings {
  channel_cta_handle: string | null;
  channel_ai_replies_enabled: boolean;
  channel_show_price: boolean;
}

interface CommentLog {
  id: string;
  action: string;
  platform: string;
  trigger_text: string;
  reply_text: string;
  sender_name: string | null;
  sender_username: string | null;
  chat_title: string | null;
  product_name: string | null;
  created_at: string | null;
}

interface TriggerMatch {
  id: string;
  trigger_type: string;
  trigger_patterns: string[];
  template_text: string;
  language: string;
}

const langLabels: Record<string, string> = { ru: "Русский", uz: "Узбекский", en: "English" };

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [channelSettings, setChannelSettings] = useState<AiSettings | null>(null);
  const { toast } = useToast();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [tagHistory, setTagHistory] = useState<string[][]>([]);
  const [form, setForm] = useState({
    trigger_type: "keyword",
    language: "ru",
    template_text: "",
    platform: "all",
  });

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  // Preview toggle
  const [previewId, setPreviewId] = useState<string | null>(null);

  // Trigger test
  const [testText, setTestText] = useState("");
  const [testResults, setTestResults] = useState<TriggerMatch[] | null>(null);
  const [testLoading, setTestLoading] = useState(false);

  // Comment log
  const [commentLogs, setCommentLogs] = useState<CommentLog[]>([]);
  const [logPlatform, setLogPlatform] = useState<"all" | "telegram" | "instagram">("all");
  const [showLogs, setShowLogs] = useState(false);

  const load = () => api.get<Template[]>("/templates").then(setTemplates).catch(() => toast("Не удалось загрузить шаблоны", "error"));
  const loadLogs = () => api.get<CommentLog[]>("/conversations/comments?limit=50").then(setCommentLogs).catch(() => {});
  useEffect(() => {
    load();
    loadLogs();
    api.get<AiSettings>("/ai-settings").then(setChannelSettings).catch(() => {});
  }, []);

  const addTag = (val: string) => {
    const v = val.trim();
    if (v && !tags.includes(v)) {
      setTagHistory((h) => [...h, tags].slice(-20));
      setTags([...tags, v]);
    }
    setTagInput("");
  };

  const removeTag = (idx: number) => {
    setTagHistory((h) => [...h, tags].slice(-20));
    setTags(tags.filter((_, i) => i !== idx));
  };

  // Cmd+Z / Ctrl+Z undo for tags
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "z" && tagHistory.length > 0) {
        e.preventDefault();
        const prev = tagHistory[tagHistory.length - 1];
        setTagHistory((h) => h.slice(0, -1));
        setTags(prev);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tagHistory]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (tags.length === 0) return;
    await api.post("/templates", { ...form, trigger_patterns: tags });
    resetForm();
    load();
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingId || tags.length === 0) return;
    await api.patch(`/templates/${editingId}`, { ...form, trigger_patterns: tags });
    resetForm();
    load();
  };

  const toggleActive = async (t: Template) => {
    await api.patch(`/templates/${t.id}`, { is_active: !t.is_active });
    load();
  };

  const deleteTemplate = async (id: string) => {
    await api.delete(`/templates/${id}`);
    load();
  };

  const startEdit = (t: Template) => {
    setEditingId(t.id);
    setShowForm(true);
    setTags(Array.isArray(t.trigger_patterns) ? [...t.trigger_patterns] : []);
    setForm({
      trigger_type: t.trigger_type,
      language: t.language,
      template_text: t.template_text,
      platform: t.platform || "all",
    });
  };

  const resetForm = () => {
    setShowForm(false);
    setEditingId(null);
    setTags([]);
    setTagInput("");
    setForm({ trigger_type: "keyword", language: "ru", template_text: "", platform: "all" });
  };

  const runTriggerTest = async () => {
    if (!testText.trim()) return;
    setTestLoading(true);
    try {
      const data = await api.post<{ matches: TriggerMatch[] }>("/templates/test-trigger", { text: testText });
      setTestResults(data.matches || []);
    } catch {
      setTestResults([]);
    } finally {
      setTestLoading(false);
    }
  };

  const totalUsage = templates.reduce((sum, t) => sum + (t.usage_count || 0), 0);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Шаблоны комментариев (TG + IG)</h1>
        <button
          onClick={() => { resetForm(); setShowForm(!showForm); }}
          className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
        >
          + Добавить
        </button>
      </div>

      {/* Smart replies status */}
      <div className={`rounded-xl p-4 mb-4 border transition-all duration-200 ${channelSettings?.channel_ai_replies_enabled ? "bg-emerald-50 border-emerald-200" : "bg-slate-50 border-slate-200"}`}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-800">
              {channelSettings?.channel_ai_replies_enabled ? "Умные ответы включены" : "Умные ответы выключены"}
            </p>
            <p className="text-xs text-slate-500 mt-0.5">
              {channelSettings?.channel_cta_handle
                ? `CTA: ${channelSettings.channel_cta_handle} · Цены: ${channelSettings.channel_show_price ? "да" : "нет"}`
                : "CTA не настроен — настройте в Настройках"}
            </p>
          </div>
          <Link href="/settings" className="text-xs text-indigo-600 hover:text-indigo-700 transition-colors">Настроить</Link>
        </div>
        <div className="mt-2 text-xs text-slate-500">
          Приоритет: <strong>Умные ответы</strong> (с ценой из БД) → <strong>Шаблоны</strong> (фоллбэк) → Молчание.
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="card px-4 py-3 text-center">
          <p className="text-2xl font-bold text-slate-900">{templates.length}</p>
          <p className="text-xs text-slate-500">Всего шаблонов</p>
        </div>
        <div className="card px-4 py-3 text-center">
          <p className="text-2xl font-bold text-emerald-600">{templates.filter((t) => t.is_active).length}</p>
          <p className="text-xs text-slate-500">Активных</p>
        </div>
        <div className="card px-4 py-3 text-center">
          <p className="text-2xl font-bold text-indigo-600">{totalUsage}</p>
          <p className="text-xs text-slate-500">Всего срабатываний</p>
        </div>
      </div>

      {/* Trigger test panel */}
      <div className="card p-4 mb-4">
        <h3 className="text-sm font-semibold text-slate-900 mb-2">Тест триггеров</h3>
        <p className="text-xs text-slate-500 mb-3">Введите текст комментария чтобы проверить какие шаблоны сработают</p>
        <div className="flex gap-2">
          <input
            value={testText}
            onChange={(e) => setTestText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") runTriggerTest(); }}
            placeholder="Например: сколько стоит?"
            className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
          />
          <button
            onClick={runTriggerTest}
            disabled={testLoading || !testText.trim()}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
          >
            {testLoading ? "..." : "Тест"}
          </button>
        </div>
        {testResults !== null && (
          <div className="mt-3">
            {testResults.length === 0 ? (
              <p className="text-xs text-slate-400 py-2">Ни один шаблон не сработал</p>
            ) : (
              <div className="space-y-2">
                {testResults.map((r, i) => (
                  <div key={i} className="bg-emerald-50 rounded-lg px-3 py-2">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 text-xs font-medium">{r.trigger_type}</span>
                      <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-xs">{r.language}</span>
                      <div className="flex gap-1">
                        {r.trigger_patterns.map((p, j) => (
                          <span key={j} className="text-xs text-emerald-600 font-mono">{p}</span>
                        ))}
                      </div>
                    </div>
                    <p className="text-sm text-slate-700">{r.template_text}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Create / Edit form */}
      {showForm && (
        <form onSubmit={editingId ? handleUpdate : handleCreate} className="card p-5 mb-4 space-y-4">
          <h3 className="text-sm font-semibold text-slate-900">{editingId ? "Редактировать шаблон" : "Новый шаблон"}</h3>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <label className="block text-xs text-slate-500 mb-1">Платформа</label>
              <select
                value={form.platform}
                onChange={(e) => setForm({ ...form, platform: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              >
                <option value="all">TG + IG (обе)</option>
                <option value="telegram">Только Telegram</option>
                <option value="instagram">Только Instagram</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Тип триггера</label>
              <select
                value={form.trigger_type}
                onChange={(e) => setForm({ ...form, trigger_type: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              >
                <option value="keyword">Ключевое слово</option>
                <option value="emoji">Эмодзи</option>
                <option value="regex">Regex</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Триггеры (Enter для добавления)</label>
              <div className="bg-white border border-slate-200 rounded-lg px-2 py-1.5 flex flex-wrap gap-1.5 min-h-[38px] items-center focus-within:ring-2 focus-within:ring-indigo-500 focus-within:border-indigo-500 transition-all">
                {tags.map((tag, i) => (
                  <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 text-xs">
                    {tag}
                    <button type="button" onClick={() => removeTag(i)} className="text-indigo-400 hover:text-indigo-700 transition-colors">&times;</button>
                  </span>
                ))}
                <input
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") {
                      e.preventDefault();
                      addTag(tagInput);
                    }
                    if (e.key === "Backspace" && !tagInput && tags.length > 0) {
                      removeTag(tags.length - 1);
                    }
                  }}
                  onBlur={() => { if (tagInput.trim()) addTag(tagInput); }}
                  placeholder={tags.length === 0 ? "цена, сколько, +" : ""}
                  className="flex-1 min-w-[80px] outline-none text-sm py-0.5"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Язык</label>
              <select
                value={form.language}
                onChange={(e) => setForm({ ...form, language: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              >
                <option value="ru">Русский</option>
                <option value="uz">Узбекский</option>
                <option value="en">English</option>
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Текст ответа</label>
            <textarea
              placeholder="Здравствуйте! Напишите нам @avenir_uz для заказа"
              value={form.template_text}
              onChange={(e) => setForm({ ...form, template_text: e.target.value })}
              className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm h-20 resize-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              required
              minLength={5}
              maxLength={1000}
            />
          </div>

          {/* Live preview */}
          {form.template_text.length > 0 && (
            <div>
              <label className="block text-xs text-slate-500 mb-1">Превью в Telegram</label>
              <div className="bg-[#0e1621] rounded-xl p-4 max-w-sm">
                <div className="flex items-start gap-2">
                  <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                    AI
                  </div>
                  <div>
                    <p className="text-xs text-indigo-400 font-medium mb-0.5">AI Closer</p>
                    <div className="bg-[#182533] text-[#e4ecf2] text-sm rounded-xl rounded-tl-sm px-3 py-2 max-w-xs whitespace-pre-wrap break-words">
                      {form.template_text}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={resetForm} className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium transition-colors">
              Отмена
            </button>
            <button type="submit" className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors">
              {editingId ? "Сохранить" : "Создать"}
            </button>
          </div>
        </form>
      )}

      {/* Template list */}
      <div className="space-y-3">
        {templates.length === 0 ? (
          <div className="card p-8 text-center text-slate-400">
            Нет шаблонов. Шаблоны — фоллбэк когда умный ответ не сработал.
          </div>
        ) : (
          templates.map((t) => (
            <div
              key={t.id}
              className={`card p-4 ${!t.is_active ? "opacity-50" : ""}`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    t.platform === "instagram"
                      ? "bg-gradient-to-r from-purple-100 to-pink-100 text-purple-700"
                      : t.platform === "telegram"
                      ? "bg-sky-100 text-sky-700"
                      : "bg-emerald-100 text-emerald-700"
                  }`}>
                    {t.platform === "instagram" ? "IG" : t.platform === "telegram" ? "TG" : "TG+IG"}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-indigo-100 text-indigo-700 text-xs font-medium">
                    {t.trigger_type}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-600 text-xs">
                    {langLabels[t.language] || t.language}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-violet-50 text-violet-600 text-xs">
                    {t.usage_count || 0} срабат.
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPreviewId(previewId === t.id ? null : t.id)}
                    className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors"
                  >
                    {previewId === t.id ? "Скрыть" : "Превью"}
                  </button>
                  <button
                    onClick={() => toggleActive(t)}
                    className={`px-2 py-0.5 rounded text-xs transition-colors ${
                      t.is_active ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"
                    }`}
                  >
                    {t.is_active ? "Активен" : "Выключен"}
                  </button>
                  <button
                    onClick={() => startEdit(t)}
                    className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors"
                  >
                    Изменить
                  </button>
                  <button
                    onClick={() => setDeleteTarget(t.id)}
                    className="px-2 py-0.5 rounded text-xs bg-rose-50 text-rose-500 hover:bg-rose-100 transition-colors"
                  >
                    Удалить
                  </button>
                </div>
              </div>

              {/* Triggers */}
              <div className="flex flex-wrap gap-1.5 mb-2">
                {(Array.isArray(t.trigger_patterns) ? t.trigger_patterns : []).map((p, i) => (
                  <span key={i} className="px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 text-xs font-mono">
                    {p}
                  </span>
                ))}
              </div>

              {/* Response text */}
              <p className="text-sm bg-slate-50 rounded-lg px-3 py-2 text-slate-700">{t.template_text}</p>

              {/* Telegram preview */}
              {previewId === t.id && (
                <div className="mt-3 bg-[#0e1621] rounded-xl p-4 max-w-sm">
                  <div className="flex items-start gap-2">
                    <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                      AI
                    </div>
                    <div>
                      <p className="text-xs text-indigo-400 font-medium mb-0.5">AI Closer</p>
                      <div className="bg-[#182533] text-[#e4ecf2] text-sm rounded-xl rounded-tl-sm px-3 py-2 max-w-xs whitespace-pre-wrap break-words">
                        {t.template_text}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Comment Interaction Log */}
      <div className="mt-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-slate-900">Лог ответов на комментарии</h2>
          <button
            onClick={() => { setShowLogs(!showLogs); if (!showLogs) loadLogs(); }}
            className="text-sm text-indigo-600 hover:text-indigo-700 transition-colors"
          >
            {showLogs ? "Скрыть" : "Показать"}
          </button>
        </div>
        {showLogs && (
          <>
            <div className="flex gap-2 mb-3">
              {(["all", "telegram", "instagram"] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setLogPlatform(p)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    logPlatform === p
                      ? "bg-indigo-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  {p === "all" ? "Все" : p === "telegram" ? "Telegram" : "Instagram"}
                </button>
              ))}
            </div>
            <div className="space-y-2">
              {commentLogs
                .filter((l) => logPlatform === "all" || l.platform === logPlatform)
                .map((l) => (
                  <div key={l.id} className="card p-3">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                        l.platform === "instagram"
                          ? "bg-gradient-to-r from-purple-100 to-pink-100 text-purple-700"
                          : "bg-sky-100 text-sky-700"
                      }`}>
                        {l.platform === "instagram" ? "IG" : "TG"}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-xs ${
                        l.action.includes("smart") ? "bg-emerald-100 text-emerald-700"
                          : l.action.includes("template") ? "bg-indigo-100 text-indigo-700"
                          : "bg-slate-100 text-slate-600"
                      }`}>
                        {l.action.includes("smart") ? "AI" : l.action.includes("template") ? "Шаблон" : "Фоллбэк"}
                      </span>
                      {l.product_name && (
                        <span className="text-xs text-violet-600">{l.product_name}</span>
                      )}
                      {l.sender_username && (
                        <span className="text-xs text-slate-400">@{l.sender_username}</span>
                      )}
                      {l.created_at && (
                        <span className="text-xs text-slate-400 ml-auto">
                          {new Date(l.created_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                        </span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div className="bg-slate-50 rounded px-2 py-1.5">
                        <p className="text-xs text-slate-400 mb-0.5">Комментарий</p>
                        <p className="text-slate-700 line-clamp-2">{l.trigger_text}</p>
                      </div>
                      <div className="bg-indigo-50 rounded px-2 py-1.5">
                        <p className="text-xs text-indigo-400 mb-0.5">Ответ</p>
                        <p className="text-slate-700 line-clamp-2">{l.reply_text}</p>
                      </div>
                    </div>
                  </div>
                ))}
              {commentLogs.filter((l) => logPlatform === "all" || l.platform === logPlatform).length === 0 && (
                <div className="card p-6 text-center text-slate-400 text-sm">
                  Нет записей{logPlatform !== "all" ? ` для ${logPlatform === "telegram" ? "Telegram" : "Instagram"}` : ""}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      <ConfirmDialog
        open={!!deleteTarget}
        title="Удалить шаблон"
        message="Удалить этот шаблон? Это действие нельзя отменить."
        confirmText="Удалить"
        variant="danger"
        onConfirm={() => {
          if (deleteTarget) deleteTemplate(deleteTarget);
          setDeleteTarget(null);
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
