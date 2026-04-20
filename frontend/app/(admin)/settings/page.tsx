"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { getUser } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

const SECTIONS = [
  { id: "profile", label: "Профиль" },
  { id: "ai-agent", label: "AI Агент" },
  { id: "order-policies", label: "Бронирования" },
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
}

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
          {/* Presets */}
          <div className="card p-5 max-w-2xl mt-6">
            <h2 className="text-sm font-bold text-slate-900 mb-3">Быстрые пресеты</h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {([
                {
                  name: "Агрессивный консультант",
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
                  name: "Осторожный консультант",
                  desc: "Минимум риска: всё через оператора, AI только информирует о турах",
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
                tooltip="AI отвечает на вопросы о цене и наличии мест под постами канала, направляя клиентов в ЛС для бронирования."
              />
              <Toggle
                label="Handoff при неизвестном туре"
                description="Передать оператору если тур не найден в каталоге"
                checked={settings.require_handoff_for_unknown_product}
                onChange={(v) => save({ require_handoff_for_unknown_product: v })}
                tooltip="Если клиент спрашивает тур, которого нет в каталоге — AI сразу подключит оператора вместо ответа 'тур не найден'."
              />
              <div className="py-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-900">Макс. вариантов в ответе</p>
                    <p className="text-xs text-slate-500">Сколько дат тура показывать за раз</p>
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
                    <option value="friendly_sales">Дружелюбный консультант</option>
                    <option value="formal">Формальный</option>
                    <option value="casual">Неформальный</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          {/* Order Policies */}
          <div id="order-policies" className="card p-6 max-w-2xl mt-6 scroll-mt-24">
            <h2 className="text-lg font-bold text-slate-900 mb-4">Политики бронирований</h2>
            <div className="divide-y divide-slate-100">
              <Toggle label="AI может отменять черновые брони" description="Без участия оператора — только брони в статусе 'Ожидает оплаты'" checked={settings.allow_ai_cancel_draft} onChange={(v) => save({ allow_ai_cancel_draft: v })}
                tooltip="Если клиент передумал — AI сам отменит черновую бронь. Подтверждённые брони AI отменить не может." />
              <Toggle label="Оператор для изменений" description="Всегда подключать оператора для редактирования бронирования" checked={settings.require_operator_for_edit} onChange={(v) => save({ require_operator_for_edit: v })}
                tooltip="Когда вкл — любая просьба изменить бронь создаёт handoff. Когда выкл — AI сам меняет черновые брони." />
              <Toggle label="Оператор для отмен" description="Всегда подключать оператора для отмены бронирований" checked={settings.require_operator_for_returns} onChange={(v) => save({ require_operator_for_returns: v })}
                tooltip="Отмены бронирований — чувствительная тема. Рекомендуем оставить включённым для контроля." />
              <Toggle label="Подтверждение перед бронированием" description="AI запрашивает подтверждение перед созданием брони" checked={settings.confirm_before_order} onChange={(v) => save({ confirm_before_order: v })}
                tooltip="AI перечислит тур, дату, кол-во участников и сумму, и спросит 'Всё верно?' перед созданием брони. Снижает ошибки." />
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
                    placeholder="osonturizm_admin"
                    value={settings.operator_telegram_username || ""}
                    onChange={(e) => setSettings({ ...settings, operator_telegram_username: e.target.value.replace(/[^a-zA-Z0-9_]/g, "") || null })}
                    onBlur={() => save({ operator_telegram_username: settings.operator_telegram_username })}
                    className="flex-1 bg-white border border-slate-200 rounded-r-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                    pattern="[a-zA-Z0-9_]{3,32}"
                    maxLength={32}
                  />
                </div>
                <p className="text-xs text-slate-400 mt-1">Без @. Убедитесь что оператор начал диалог с Telegram-аккаунтом Easy Tour.</p>
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
            <p className="text-xs text-slate-500 mb-4">AI автоматически отвечает на вопросы о цене и наличии мест в комментариях Telegram-канала.</p>
            <div className="divide-y divide-slate-100">
              <Toggle label="Умные ответы на вопросы" description="AI распознаёт вопросы о цене/наличии мест и отвечает с призывом написать в ЛС" checked={settings.channel_ai_replies_enabled} onChange={(v) => save({ channel_ai_replies_enabled: v })}
                tooltip="AI мониторит комментарии под постами канала. Распознаёт вопросы о туре и отвечает с CTA написать в ЛС." />
              <Toggle label="Показывать цену в ответе" description="Если пост о конкретном туре — AI укажет цену из каталога" checked={settings.channel_show_price} onChange={(v) => save({ channel_show_price: v })}
                tooltip="Если вкл — AI покажет диапазон цен прямо в комментарии. Если выкл — только предложит написать в ЛС для деталей." />
              <div className="py-3 space-y-3">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">CTA — аккаунт для бронирований</label>
                  <input
                    type="text"
                    placeholder="@osonturizm"
                    value={settings.channel_cta_handle || ""}
                    onChange={(e) => setSettings({ ...settings, channel_cta_handle: e.target.value || null })}
                    onBlur={() => save({ channel_cta_handle: settings.channel_cta_handle })}
                    className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                    maxLength={64}
                  />
                  <p className="text-xs text-slate-400 mt-1">Аккаунт или ссылка, куда отправлять клиентов. Например: @osonturizm</p>
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
