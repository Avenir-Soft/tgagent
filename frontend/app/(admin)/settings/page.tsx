"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { getUser } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

const SECTIONS = [
  { id: "profile", label: "Профиль" },
  { id: "ai-provider", label: "AI Провайдер" },
  { id: "ai-agent", label: "AI Агент" },
  { id: "order-policies", label: "Заказы" },
  { id: "conflicts", label: "Конфликты" },
  { id: "operator", label: "Оператор" },
  { id: "channel", label: "Канал" },
] as const;

interface AiSettings {
  id: string;
  tenant_id: string;
  tone: string;
  language: string;
  fallback_mode: string;
  allow_auto_comment_reply: boolean;
  allow_auto_dm_reply: boolean;
  require_handoff_for_unknown_product: boolean;
  allow_ai_cancel_draft: boolean;
  require_operator_for_edit: boolean;
  require_operator_for_returns: boolean;
  max_variants_in_reply: number;
  confirm_before_order: boolean;
  auto_handoff_on_profanity: boolean;
  operator_telegram_username: string | null;
  channel_cta_handle: string | null;
  channel_ai_replies_enabled: boolean;
  channel_show_price: boolean;
  timezone: string;
  currency: string;
  ai_provider: string;
  has_api_key: boolean;
  ai_model_override: string | null;
}

interface ApiKeyStatus {
  has_key: boolean;
  provider: string;
  model: string | null;
}

const OPENAI_MODELS = [
  { value: "gpt-4o-mini", label: "GPT-4o Mini" },
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
];

const ANTHROPIC_MODELS = [
  { value: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
  { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
  { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
];

function Toggle({
  label,
  description,
  checked,
  onChange,
  tooltip,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  tooltip?: string;
}) {
  return (
    <div className="flex items-center justify-between py-3">
      <div>
        <div className="flex items-center gap-1.5">
          <p className="text-sm font-medium text-slate-900">{label}</p>
          {tooltip && (
            <span className="group relative">
              <span className="w-4 h-4 rounded-full bg-slate-100 text-slate-400 text-[10px] font-bold flex items-center justify-center cursor-help hover:bg-indigo-50 hover:text-indigo-500 transition-colors">?</span>
              <span className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 px-3 py-2 bg-slate-900 text-white text-xs rounded-lg shadow-lg w-56 text-left opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-20 pointer-events-none">
                {tooltip}
                <span className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-x-4 border-x-transparent border-t-4 border-t-slate-900" />
              </span>
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500">{description}</p>
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`w-11 h-6 rounded-full transition-colors shrink-0 ${
          checked ? "bg-indigo-600" : "bg-slate-300"
        }`}
      >
        <div
          className={`w-5 h-5 bg-white rounded-full shadow-sm transform transition-transform ${
            checked ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

const TIMEZONES = [
  "Asia/Tashkent",
  "Asia/Samarkand",
  "Asia/Almaty",
  "Asia/Dubai",
  "Europe/Moscow",
  "Europe/Istanbul",
  "Asia/Seoul",
  "UTC",
];

const CURRENCIES = ["UZS", "USD", "RUB", "EUR", "KZT"];

export default function SettingsPage() {
  const user = getUser();
  const { toast } = useToast();
  const [settings, setSettings] = useState<AiSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [activeSection, setActiveSection] = useState<string>("profile");
  const pendingRef = useRef<Partial<AiSettings>>({});
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Password change
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [changingPw, setChangingPw] = useState(false);

  // Test notification
  const [testingNotif, setTestingNotif] = useState(false);

  // API Key management
  const [keyStatus, setKeyStatus] = useState<ApiKeyStatus | null>(null);
  const [keyProvider, setKeyProvider] = useState("openai");
  const [keyInput, setKeyInput] = useState("");
  const [keyModel, setKeyModel] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [testingKey, setTestingKey] = useState(false);
  const [deletingKey, setDeletingKey] = useState(false);
  const [confirmDeleteKey, setConfirmDeleteKey] = useState(false);

  // Confirm reset dialog
  const [confirmReset, setConfirmReset] = useState(false);

  // Preset confirm dialog
  const [pendingPreset, setPendingPreset] = useState<{ name: string; values: Partial<AiSettings> } | null>(null);

  // Track which section is in view
  useEffect(() => {
    const observers: IntersectionObserver[] = [];
    const visibleSections = new Map<string, number>();

    SECTIONS.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (!el) return;
      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) {
            visibleSections.set(id, entry.intersectionRatio);
          } else {
            visibleSections.delete(id);
          }
          for (const { id: sId } of SECTIONS) {
            if (visibleSections.has(sId)) {
              setActiveSection(sId);
              break;
            }
          }
        },
        { rootMargin: "-80px 0px -60% 0px", threshold: 0 }
      );
      observer.observe(el);
      observers.push(observer);
    });

    return () => observers.forEach((o) => o.disconnect());
  }, [settings]);

  useEffect(() => {
    api.get<AiSettings>("/ai-settings").then(setSettings).catch(() => toast("Не удалось загрузить настройки", "error"));
    api.get<ApiKeyStatus>("/ai-settings/api-key-status").then((status) => {
      setKeyStatus(status);
      if (status.provider) setKeyProvider(status.provider);
      if (status.model) setKeyModel(status.model);
    }).catch(() => {});
  }, []);

  const flushSave = useCallback(async (merged: AiSettings) => {
    setSaving(true);
    setSaved(false);
    try {
      const result = await api.put<AiSettings>("/ai-settings", merged);
      setSettings(result);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      toast("Ошибка сохранения", "error");
    } finally {
      setSaving(false);
      pendingRef.current = {};
    }
  }, [toast]);

  const save = useCallback((updated: Partial<AiSettings>) => {
    if (!settings) return;
    Object.assign(pendingRef.current, updated);
    const merged = { ...settings, ...pendingRef.current };
    setSettings(merged);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => flushSave(merged), 600);
  }, [settings, flushSave]);

  const scrollTo = (id: string) => {
    const el = document.getElementById(id);
    if (el) {
      const offset = 80;
      const top = el.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top, behavior: "smooth" });
    }
  };

  const handlePasswordChange = async () => {
    if (newPw !== confirmPw) { toast("Пароли не совпадают", "error"); return; }
    if (newPw.length < 8 || !/[a-zA-Zа-яА-Я]/.test(newPw) || !/\d/.test(newPw)) { toast("Пароль минимум 8 символов, обязательно буквы и цифры", "error"); return; }
    setChangingPw(true);
    try {
      await api.post("/auth/change-password", { current_password: currentPw, new_password: newPw });
      toast("Пароль изменён", "success");
      setCurrentPw(""); setNewPw(""); setConfirmPw("");
    } catch (e: any) {
      toast(e?.detail || "Ошибка смены пароля", "error");
    }
    setChangingPw(false);
  };

  const handleTestNotification = async () => {
    setTestingNotif(true);
    try {
      await api.post("/ai-settings/test-notification");
      toast("Тестовое уведомление отправлено", "success");
    } catch (e: any) {
      toast(e?.detail || "Ошибка отправки", "error");
    }
    setTestingNotif(false);
  };

  // API Key handlers
  const handleSaveKey = async () => {
    if (!keyInput.trim()) { toast("Введите API ключ", "error"); return; }
    setSavingKey(true);
    try {
      await api.put("/ai-settings/api-key", {
        provider: keyProvider,
        api_key: keyInput.trim(),
        model: keyModel || null,
      });
      toast("API ключ сохранён и проверен", "success");
      setKeyInput("");
      // Refresh status
      const status = await api.get<ApiKeyStatus>("/ai-settings/api-key-status");
      setKeyStatus(status);
      // Refresh settings to update has_api_key
      const updated = await api.get<AiSettings>("/ai-settings");
      setSettings(updated);
    } catch (e: any) {
      toast(e?.message || "Ошибка сохранения ключа", "error");
    }
    setSavingKey(false);
  };

  const handleTestKey = async () => {
    if (!keyInput.trim()) { toast("Введите API ключ для проверки", "error"); return; }
    setTestingKey(true);
    try {
      await api.post("/ai-settings/test-api-key", {
        provider: keyProvider,
        api_key: keyInput.trim(),
        model: keyModel || null,
      });
      toast("Ключ валиден", "success");
    } catch (e: any) {
      toast(e?.message || "Ключ невалиден", "error");
    }
    setTestingKey(false);
  };

  const handleDeleteKey = async () => {
    setDeletingKey(true);
    try {
      await api.delete("/ai-settings/api-key");
      toast("API ключ удалён", "success");
      setKeyInput("");
      setKeyProvider("openai");
      setKeyModel("");
      const status = await api.get<ApiKeyStatus>("/ai-settings/api-key-status");
      setKeyStatus(status);
      const updated = await api.get<AiSettings>("/ai-settings");
      setSettings(updated);
    } catch (e: any) {
      toast(e?.message || "Ошибка удаления", "error");
    }
    setDeletingKey(false);
    setConfirmDeleteKey(false);
  };

  const resetSettings = async () => {
    try {
      const result = await api.post<AiSettings>("/ai-settings/reset");
      setSettings(result);
      toast("Настройки сброшены", "success");
    } catch {
      toast("Ошибка сброса", "error");
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-900 mb-4">Настройки</h1>

      {/* Section navigation */}
      <nav className="sticky top-0 z-10 -mx-1 mb-6 bg-white/80 backdrop-blur-sm border-b border-slate-200/60 rounded-lg">
        <div className="flex gap-1 px-1 py-1.5 overflow-x-auto no-scrollbar">
          {SECTIONS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => scrollTo(id)}
              className={`px-3 py-1.5 text-sm font-medium rounded-md whitespace-nowrap transition-all ${
                activeSection === id
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-slate-500 hover:text-slate-700 hover:bg-slate-50"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>

      {/* Profile + password */}
      <div id="profile" className="card p-6 max-w-2xl space-y-5 scroll-mt-24">
        <h2 className="text-lg font-bold text-slate-900 mb-2">Профиль</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-500">Имя</label>
            <p className="text-sm text-slate-900">{user?.full_name}</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Email</label>
            <p className="text-sm text-slate-900">{user?.email}</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Роль</label>
            <p className="text-sm text-slate-900">{user?.role}</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Tenant ID</label>
            <p className="text-xs font-mono text-slate-400">{user?.tenant_id}</p>
          </div>
        </div>

        {/* Password change */}
        <div className="border-t border-slate-100 pt-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Смена пароля</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <input
              type="password"
              placeholder="Текущий пароль"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
            />
            <input
              type="password"
              placeholder="Новый пароль"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
            />
            <input
              type="password"
              placeholder="Подтвердите"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handlePasswordChange()}
              className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
            />
          </div>
          <button
            type="button"
            onClick={handlePasswordChange}
            disabled={changingPw || !currentPw || !newPw}
            className="mt-2 px-4 py-2 bg-slate-900 text-white rounded-lg text-sm font-medium hover:bg-slate-800 disabled:opacity-50 transition-colors"
          >
            {changingPw ? "..." : "Сменить пароль"}
          </button>
        </div>

        {/* Timezone + Currency */}
        {settings && (
          <div className="border-t border-slate-100 pt-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Часовой пояс</label>
                <select
                  value={settings.timezone}
                  onChange={(e) => save({ timezone: e.target.value })}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                >
                  {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Валюта</label>
                <select
                  value={settings.currency}
                  onChange={(e) => save({ currency: e.target.value })}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                >
                  {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* AI Settings */}
      {settings && (
        <>
          {/* AI Provider & API Key */}
          <div id="ai-provider" className="card p-6 max-w-2xl mt-6 scroll-mt-24">
            <h2 className="text-lg font-bold text-slate-900 mb-1">AI Провайдер и API Ключ</h2>
            <p className="text-xs text-slate-500 mb-4">Используйте свой API ключ для AI запросов. Без ключа используется платформенный ключ.</p>

            {/* Status indicator */}
            <div className="mb-4">
              {keyStatus?.has_key ? (
                <div className="flex items-center gap-2 px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-lg">
                  <svg className="w-4 h-4 text-emerald-600 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                  <span className="text-sm text-emerald-700 font-medium">Ключ настроен</span>
                  <span className="text-xs text-emerald-600 ml-1">({keyStatus.provider}{keyStatus.model ? ` / ${keyStatus.model}` : ""})</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg">
                  <svg className="w-4 h-4 text-amber-600 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" /></svg>
                  <span className="text-sm text-amber-700 font-medium">Используется платформенный ключ</span>
                </div>
              )}
            </div>

            {/* Provider selector */}
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Провайдер</label>
                <div className="flex gap-2">
                  {(["openai", "anthropic"] as const).map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => { setKeyProvider(p); setKeyModel(""); }}
                      className={`flex-1 px-4 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                        keyProvider === p
                          ? "bg-indigo-50 border-indigo-300 text-indigo-700 ring-1 ring-indigo-200"
                          : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {p === "openai" ? "OpenAI" : "Anthropic"}
                    </button>
                  ))}
                </div>
              </div>

              {/* Model selector */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Модель</label>
                <select
                  value={keyModel}
                  onChange={(e) => setKeyModel(e.target.value)}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                >
                  <option value="">По умолчанию</option>
                  {(keyProvider === "openai" ? OPENAI_MODELS : ANTHROPIC_MODELS).map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
                <p className="text-xs text-slate-400 mt-1">Если не выбрано, используется модель платформы по умолчанию.</p>
              </div>

              {/* API Key input */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">API Ключ</label>
                <input
                  type="password"
                  placeholder={keyStatus?.has_key ? "••••••••••••••••••••" : keyProvider === "openai" ? "sk-..." : "sk-ant-..."}
                  value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  autoComplete="off"
                />
                <p className="text-xs text-slate-400 mt-1">Ключ шифруется и никогда не отображается. Получить ключ: {keyProvider === "openai" ? "platform.openai.com" : "console.anthropic.com"}</p>
              </div>

              {/* Action buttons */}
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleSaveKey}
                  disabled={savingKey || !keyInput.trim()}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                >
                  {savingKey ? "Проверка и сохранение..." : "Сохранить ключ"}
                </button>
                <button
                  type="button"
                  onClick={handleTestKey}
                  disabled={testingKey || !keyInput.trim()}
                  className="px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 disabled:opacity-50 transition-colors"
                >
                  {testingKey ? "Проверка..." : "Проверить ключ"}
                </button>
                {keyStatus?.has_key && (
                  <button
                    type="button"
                    onClick={() => setConfirmDeleteKey(true)}
                    disabled={deletingKey}
                    className="px-4 py-2 bg-white border border-rose-200 text-rose-600 rounded-lg text-sm font-medium hover:bg-rose-50 disabled:opacity-50 transition-colors ml-auto"
                  >
                    {deletingKey ? "Удаление..." : "Удалить ключ"}
                  </button>
                )}
              </div>
            </div>
          </div>

          <ConfirmDialog
            open={confirmDeleteKey}
            title="Удалить API ключ"
            message="API ключ будет удалён. AI запросы будут использовать платформенный ключ по умолчанию."
            confirmText="Удалить"
            variant="danger"
            onConfirm={handleDeleteKey}
            onCancel={() => setConfirmDeleteKey(false)}
          />

          {/* Presets */}
          <div className="card p-5 max-w-2xl mt-6">
            <h2 className="text-sm font-bold text-slate-900 mb-3">Быстрые пресеты</h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {([
                {
                  name: "Агрессивный продавец",
                  desc: "Максимум автономии: AI сам отменяет, не ждёт оператора",
                  icon: "🔥",
                  color: "border-rose-200 hover:bg-rose-50",
                  values: {
                    tone: "aggressive_sales",
                    allow_auto_dm_reply: true,
                    allow_auto_comment_reply: true,
                    allow_ai_cancel_draft: true,
                    require_operator_for_edit: false,
                    require_operator_for_returns: false,
                    require_handoff_for_unknown_product: false,
                    confirm_before_order: false,
                    auto_handoff_on_profanity: false,
                    max_variants_in_reply: 8,
                  },
                },
                {
                  name: "Сбалансированный",
                  desc: "Золотая середина: AI помогает, оператор контролирует",
                  icon: "⚖️",
                  color: "border-indigo-200 hover:bg-indigo-50",
                  values: {
                    tone: "friendly_sales",
                    allow_auto_dm_reply: true,
                    allow_auto_comment_reply: true,
                    allow_ai_cancel_draft: true,
                    require_operator_for_edit: true,
                    require_operator_for_returns: true,
                    require_handoff_for_unknown_product: true,
                    confirm_before_order: true,
                    auto_handoff_on_profanity: true,
                    max_variants_in_reply: 5,
                  },
                },
                {
                  name: "Осторожный помощник",
                  desc: "Минимум риска: всё через оператора, AI только консультирует",
                  icon: "🛡️",
                  color: "border-emerald-200 hover:bg-emerald-50",
                  values: {
                    tone: "support_only",
                    allow_auto_dm_reply: true,
                    allow_auto_comment_reply: false,
                    allow_ai_cancel_draft: false,
                    require_operator_for_edit: true,
                    require_operator_for_returns: true,
                    require_handoff_for_unknown_product: true,
                    confirm_before_order: true,
                    auto_handoff_on_profanity: true,
                    max_variants_in_reply: 3,
                  },
                },
              ] as const).map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  onClick={() => setPendingPreset({ name: preset.name, values: preset.values as Partial<AiSettings> })}
                  className={`text-left p-3 rounded-xl border transition-all ${preset.color}`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-base">{preset.icon}</span>
                    <span className="text-sm font-semibold text-slate-900">{preset.name}</span>
                  </div>
                  <p className="text-[11px] text-slate-500 leading-snug">{preset.desc}</p>
                </button>
              ))}
            </div>
          </div>

          {/* General AI */}
          <div id="ai-agent" className="card p-6 max-w-2xl mt-6 scroll-mt-24">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-slate-900">AI Агент</h2>
              <div className="flex items-center gap-2">
                {saving && <span className="text-xs text-slate-400">Сохранение...</span>}
                {saved && <span className="text-xs text-emerald-600">Сохранено</span>}
              </div>
            </div>
            <div className="divide-y divide-slate-100">
              <Toggle
                label="Авто-ответ в личных сообщениях"
                description="AI отвечает на входящие DM автоматически"
                checked={settings.allow_auto_dm_reply}
                onChange={(v) => save({ allow_auto_dm_reply: v })}
                tooltip="Главный выключатель AI. Если выкл — бот молчит, но продолжает получать сообщения. Включите когда каталог и настройки готовы."
              />
              <Toggle
                label="Авто-ответ в комментариях"
                description="AI отвечает на триггеры в комментариях канала"
                checked={settings.allow_auto_comment_reply}
                onChange={(v) => save({ allow_auto_comment_reply: v })}
                tooltip="AI отвечает на вопросы о цене и наличии под постами канала, направляя покупателей в ЛС для заказа."
              />
              <Toggle
                label="Handoff при неизвестном товаре"
                description="Передать оператору если товар не найден в каталоге"
                checked={settings.require_handoff_for_unknown_product}
                onChange={(v) => save({ require_handoff_for_unknown_product: v })}
                tooltip="Если клиент спрашивает товар, которого нет в каталоге — AI сразу подключит оператора вместо ответа 'товар не найден'."
              />
              <div className="py-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-900">Макс. вариантов в ответе</p>
                    <p className="text-xs text-slate-500">Сколько вариантов товара показывать за раз</p>
                  </div>
                  <select
                    value={settings.max_variants_in_reply}
                    onChange={(e) => save({ max_variants_in_reply: Number(e.target.value) })}
                    className="bg-white border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  >
                    {[3, 5, 8, 10].map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="py-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-900">Тон общения</p>
                    <p className="text-xs text-slate-500">Стиль ответов AI агента</p>
                  </div>
                  <select
                    value={settings.tone}
                    onChange={(e) => save({ tone: e.target.value })}
                    className="bg-white border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  >
                    <option value="friendly_sales">Дружелюбный продавец</option>
                    <option value="formal">Формальный</option>
                    <option value="casual">Неформальный</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          {/* Order Policies */}
          <div id="order-policies" className="card p-6 max-w-2xl mt-6 scroll-mt-24">
            <h2 className="text-lg font-bold text-slate-900 mb-4">Политики заказов</h2>
            <div className="divide-y divide-slate-100">
              <Toggle label="AI может отменять черновые заказы" description="Без участия оператора — только заказы в статусе 'Ожидает подтверждения'" checked={settings.allow_ai_cancel_draft} onChange={(v) => save({ allow_ai_cancel_draft: v })}
                tooltip="Если клиент передумал — AI сам отменит заказ-черновик. Подтверждённые и обработанные заказы AI отменить не может." />
              <Toggle label="Оператор для изменений" description="Всегда подключать оператора для редактирования заказа" checked={settings.require_operator_for_edit} onChange={(v) => save({ require_operator_for_edit: v })}
                tooltip="Когда вкл — любая просьба изменить заказ создаёт handoff. Когда выкл — AI сам меняет черновые и подтверждённые заказы." />
              <Toggle label="Оператор для возвратов" description="Всегда подключать оператора для возвратов и обменов" checked={settings.require_operator_for_returns} onChange={(v) => save({ require_operator_for_returns: v })}
                tooltip="Возвраты — чувствительная тема. Рекомендуем оставить включённым, пока не наладите автоматический процесс." />
              <Toggle label="Подтверждение перед заказом" description="AI запрашивает подтверждение перед созданием заказа" checked={settings.confirm_before_order} onChange={(v) => save({ confirm_before_order: v })}
                tooltip="AI перечислит товары, цены и сумму, и спросит 'Всё верно?' перед созданием заказа. Снижает ошибки." />
            </div>
          </div>

          {/* Conflict Policies */}
          <div id="conflicts" className="card p-6 max-w-2xl mt-6 scroll-mt-24">
            <h2 className="text-lg font-bold text-slate-900 mb-4">Обработка конфликтов</h2>
            <div className="divide-y divide-slate-100">
              <Toggle label="Мгновенный handoff при мате" description="Сразу передавать оператору при нецензурной лексике (иначе — 1 попытка разрешить)" checked={settings.auto_handoff_on_profanity} onChange={(v) => save({ auto_handoff_on_profanity: v })}
                tooltip="Если выкл — AI попробует разрядить ситуацию 1 раз. Если вкл — сразу передаёт оператору без попытки." />
              <div className="py-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-900">Fallback режим</p>
                    <p className="text-xs text-slate-500">Что делать когда AI не может ответить</p>
                  </div>
                  <select value={settings.fallback_mode} onChange={(e) => save({ fallback_mode: e.target.value })} className="bg-white border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all">
                    <option value="handoff">Передать оператору</option>
                    <option value="fallback_model">Использовать запасную модель</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          {/* Operator Notifications */}
          <div id="operator" className="card p-6 max-w-2xl mt-6 scroll-mt-24">
            <h2 className="text-lg font-bold text-slate-900 mb-1">Уведомления оператора</h2>
            <p className="text-xs text-slate-500 mb-4">Когда AI создаёт handoff, оператор получает Telegram-сообщение с деталями диалога.</p>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Telegram оператора</label>
                <div className="flex gap-2">
                  <span className="flex items-center px-3 bg-slate-100 border border-slate-200 border-r-0 rounded-l-lg text-slate-500 text-sm">@</span>
                  <input
                    type="text"
                    placeholder="oybeff"
                    value={settings.operator_telegram_username || ""}
                    onChange={(e) => setSettings({ ...settings, operator_telegram_username: e.target.value.replace(/[^a-zA-Z0-9_]/g, "") || null })}
                    onBlur={() => save({ operator_telegram_username: settings.operator_telegram_username })}
                    className="flex-1 bg-white border border-slate-200 rounded-r-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                    pattern="[a-zA-Z0-9_]{3,32}"
                    maxLength={32}
                  />
                </div>
                <p className="text-xs text-slate-400 mt-1">Без @. Убедитесь что оператор начал диалог с Telegram-аккаунтом магазина.</p>
              </div>

              {settings.operator_telegram_username && (
                <button
                  type="button"
                  onClick={handleTestNotification}
                  disabled={testingNotif}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                >
                  {testingNotif ? "Отправка..." : "Тест уведомления"}
                </button>
              )}
            </div>
          </div>

          {/* Channel Auto-Responses */}
          <div id="channel" className="card p-6 max-w-2xl mt-6 scroll-mt-24">
            <h2 className="text-lg font-bold text-slate-900 mb-1">Ответы в комментариях канала</h2>
            <p className="text-xs text-slate-500 mb-4">AI автоматически отвечает на вопросы о цене, доставке и наличии в комментариях Telegram-канала.</p>
            <div className="divide-y divide-slate-100">
              <Toggle label="Умные ответы на вопросы" description="AI распознаёт вопросы о цене/доставке/наличии и отвечает с призывом написать в ЛС" checked={settings.channel_ai_replies_enabled} onChange={(v) => save({ channel_ai_replies_enabled: v })}
                tooltip="AI мониторит комментарии под постами канала. Распознаёт вопросы о товаре и отвечает с CTA написать в ЛС." />
              <Toggle label="Показывать цену в ответе" description="Если пост о конкретном товаре — AI укажет цену из каталога" checked={settings.channel_show_price} onChange={(v) => save({ channel_show_price: v })}
                tooltip="Если вкл — AI покажет диапазон цен прямо в комментарии. Если выкл — только предложит написать в ЛС для деталей." />
              <div className="py-3 space-y-3">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">CTA — аккаунт для заказов</label>
                  <input
                    type="text"
                    placeholder="@myshop"
                    value={settings.channel_cta_handle || ""}
                    onChange={(e) => setSettings({ ...settings, channel_cta_handle: e.target.value || null })}
                    onBlur={() => save({ channel_cta_handle: settings.channel_cta_handle })}
                    className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                    maxLength={64}
                  />
                  <p className="text-xs text-slate-400 mt-1">Аккаунт или ссылка, куда отправлять покупателей. Например: @myshop или @myshop_bot</p>
                </div>
              </div>
            </div>
          </div>

          {/* Reset to defaults */}
          <div className="max-w-2xl mt-6 flex justify-end">
            <button
              type="button"
              onClick={() => setConfirmReset(true)}
              className="px-4 py-2 bg-white border border-rose-200 text-rose-600 rounded-lg text-sm font-medium hover:bg-rose-50 transition-colors"
            >
              Сбросить к настройкам по умолчанию
            </button>
          </div>

          <ConfirmDialog
            open={confirmReset}
            title="Сбросить настройки"
            message="Сбросить все настройки AI к значениям по умолчанию? Правила промптов сохранятся."
            confirmText="Сбросить"
            variant="warning"
            onConfirm={() => { setConfirmReset(false); resetSettings(); }}
            onCancel={() => setConfirmReset(false)}
          />

          <ConfirmDialog
            open={!!pendingPreset}
            title={`Применить пресет «${pendingPreset?.name}»?`}
            message="Текущие настройки AI будут заменены значениями из пресета. Это действие можно отменить вручную."
            confirmText="Применить"
            variant="warning"
            onConfirm={() => { if (pendingPreset) save(pendingPreset.values); setPendingPreset(null); }}
            onCancel={() => setPendingPreset(null)}
          />
        </>
      )}
    </div>
  );
}
