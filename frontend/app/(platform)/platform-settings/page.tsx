"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { api } from "@/lib/api";

interface PlatformSettings {
  default_ai_model: string;
  fallback_model: string;
  default_language: string;
  default_timezone: string;
  max_products_per_tenant: number;
  max_users_per_tenant: number;
  max_messages_per_day: number;
  trial_days: number;
  signup_enabled: boolean;
  maintenance_mode: boolean;
  read_only_mode: boolean;
}

const SECTIONS = [
  { id: "ai", label: "AI" },
  { id: "localization", label: "Локализация" },
  { id: "limits", label: "Лимиты" },
  { id: "registration", label: "Регистрация" },
  { id: "critical", label: "Критические" },
] as const;

const LIMIT_DEFAULTS: Partial<PlatformSettings> = {
  max_products_per_tenant: 500,
  max_users_per_tenant: 10,
  max_messages_per_day: 5000,
  trial_days: 14,
};

/* ── Skeleton ─────────────────────────────────────────────────────────────── */

function SettingsSkeleton() {
  return (
    <div className="flex flex-col gap-[14px] animate-pulse">
      <div className="h-8 w-60 skeleton rounded-[9px]" />
      <div className="h-4 w-80 skeleton rounded-[6px]" />
      <div className="grid gap-[14px] mt-2" style={{ gridTemplateColumns: "180px 1fr" }}>
        <div className="flex flex-col gap-[6px]">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-[32px] skeleton rounded-[6px]" />
          ))}
        </div>
        <div className="flex flex-col gap-[12px]">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-[100px] skeleton rounded-[9px]" />
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Toggle switch ────────────────────────────────────────────────────────── */

function ToggleSwitch({
  on,
  onClick,
  danger,
}: {
  on: boolean;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: 36,
        height: 20,
        borderRadius: 999,
        background: on ? (danger ? "var(--bad)" : "var(--accent)") : "var(--bg-2)",
        border: `1px solid ${on ? (danger ? "var(--bad)" : "var(--accent)") : "var(--line)"}`,
        position: "relative",
        cursor: "pointer",
        transition: "background 0.15s, border-color 0.15s",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 1,
          left: 1,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: on ? "#fff" : "var(--ink-3)",
          transform: on ? "translateX(16px)" : "translateX(0)",
          transition: "transform 0.15s, background 0.15s",
        }}
      />
    </button>
  );
}

/* ── Set-Row ──────────────────────────────────────────────────────────────── */

function SetRow({
  title,
  sub,
  children,
  first,
}: {
  title: string;
  sub?: string;
  children: React.ReactNode;
  first?: boolean;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 20,
        padding: "12px 0",
        borderTop: first ? "none" : "1px dashed var(--hair)",
        alignItems: "center",
        ...(first ? { paddingTop: 4 } : {}),
      }}
    >
      <div>
        <div style={{ fontSize: "12.5px", fontWeight: 500, color: "var(--ink)" }}>
          {title}
        </div>
        {sub && (
          <div style={{ fontSize: "10.5px", color: "var(--ink-3)", marginTop: 2, maxWidth: 380 }}>
            {sub}
          </div>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {children}
      </div>
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────────────────────── */

export default function PlatformSettingsPage() {
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [original, setOriginal] = useState<PlatformSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [activeSection, setActiveSection] = useState("ai");

  const sectionRefs = useRef<Record<string, HTMLElement | null>>({});

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<PlatformSettings>("/platform/settings")
      .then((data) => {
        setSettings(data);
        setOriginal(data);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  /* ── Dirty tracking ──────────────────────────────────────────────────── */

  const dirtyCount = useMemo(() => {
    if (!settings || !original) return 0;
    let count = 0;
    for (const key of Object.keys(original) as (keyof PlatformSettings)[]) {
      if (settings[key] !== original[key]) count++;
    }
    return count;
  }, [settings, original]);

  /* ── Intersection observer for active nav ────────────────────────────── */

  useEffect(() => {
    const els = Object.values(sectionRefs.current).filter(Boolean) as HTMLElement[];
    if (els.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveSection(entry.target.id);
          }
        }
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: 0 }
    );

    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [settings]);

  /* ── Handlers ────────────────────────────────────────────────────────── */

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const res = await api.put<PlatformSettings>("/platform/settings", settings);
      setOriginal(res);
      setSettings(res);
      setSuccess("Настройки сохранены");
      setTimeout(() => setSuccess(""), 3000);
    } catch (e: any) {
      setError(e.message || "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (original) {
      setSettings({ ...original });
    }
  };

  const updateField = <K extends keyof PlatformSettings>(
    key: K,
    value: PlatformSettings[K]
  ) => {
    if (!settings) return;
    setSettings({ ...settings, [key]: value });
  };

  const resetLimits = () => {
    if (!settings) return;
    setSettings({ ...settings, ...LIMIT_DEFAULTS });
  };

  const scrollToSection = (id: string) => {
    const el = sectionRefs.current[id];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveSection(id);
    }
  };

  /* ── Loading ─────────────────────────────────────────────────────────── */

  if (loading) return <SettingsSkeleton />;

  if (!settings) {
    return (
      <div className="flex flex-col gap-[14px]">
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "-0.01em",
            color: "var(--ink)",
            margin: 0,
          }}
        >
          Настройки платформы
        </h1>
        <div
          style={{
            background: "var(--panel)",
            border: "1px solid var(--line)",
            borderRadius: 9,
            padding: 32,
            textAlign: "center",
          }}
        >
          <p style={{ fontSize: "12.5px", color: "var(--ink-3)" }}>
            {error || "Не удалось загрузить настройки"}
          </p>
          <button
            onClick={load}
            style={{
              marginTop: 12,
              fontSize: 12,
              fontWeight: 500,
              color: "var(--accent)",
              background: "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            Повторить
          </button>
        </div>
      </div>
    );
  }

  /* ── Select style ────────────────────────────────────────────────────── */

  const selectStyle: React.CSSProperties = {
    background: "var(--panel)",
    border: "1px solid var(--line)",
    borderRadius: 6,
    padding: "6px 10px",
    fontSize: 12,
    color: "var(--ink)",
    cursor: "pointer",
    outline: "none",
  };

  const inputStyle: React.CSSProperties = {
    background: "var(--bg)",
    border: "1px solid var(--line)",
    borderRadius: 6,
    padding: "8px 10px",
    fontSize: "12.5px",
    color: "var(--ink)",
    outline: "none",
    width: 100,
    fontVariantNumeric: "tabular-nums",
  };

  /* ── Render ──────────────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col gap-[14px]">
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: "-0.01em",
              color: "var(--ink)",
              margin: 0,
            }}
          >
            Настройки платформы
          </h1>
          <div
            style={{
              fontSize: "11.5px",
              color: "var(--ink-3)",
              marginTop: 3,
            }}
          >
            Глобальные значения для новых тенантов &middot; изменения логируются
          </div>
        </div>
        <div
          style={{
            fontSize: "11.5px",
            color: "var(--ink-3)",
            whiteSpace: "nowrap",
            fontFamily: "'Geist Mono', ui-monospace, monospace",
          }}
        >
          {success ? (
            <span style={{ color: "var(--good)" }}>Сохранено</span>
          ) : null}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div
          style={{
            background: "var(--bad-soft)",
            border: "1px solid color-mix(in oklab, var(--bad) 30%, transparent)",
            borderRadius: 9,
            padding: 14,
          }}
        >
          <p style={{ fontSize: "12.5px", color: "var(--bad)", margin: 0 }}>
            {error}
          </p>
        </div>
      )}

      {/* 2-column layout: nav + body */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "180px 1fr",
          gap: 14,
        }}
      >
        {/* Sticky nav */}
        <nav
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 2,
            position: "sticky",
            top: 10,
            alignSelf: "start",
          }}
        >
          {SECTIONS.map((s) => {
            const isActive = activeSection === s.id;
            return (
              <a
                key={s.id}
                onClick={(e) => {
                  e.preventDefault();
                  scrollToSection(s.id);
                }}
                href={`#${s.id}`}
                style={{
                  padding: "7px 10px",
                  fontSize: 12,
                  borderRadius: 6,
                  cursor: "pointer",
                  borderLeft: `2px solid ${isActive ? "var(--accent)" : "transparent"}`,
                  color: isActive ? "var(--accent)" : "var(--ink-3)",
                  background: isActive ? "var(--accent-soft)" : "transparent",
                  textDecoration: "none",
                  transition: "color 0.12s, background 0.12s",
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.color = "var(--ink)";
                    e.currentTarget.style.background = "var(--bg-2)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.color = "var(--ink-3)";
                    e.currentTarget.style.background = "transparent";
                  }
                }}
              >
                {s.label}
              </a>
            );
          })}
        </nav>

        {/* Settings body */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* ── AI section ──────────────────────────────────────────────── */}
          <section
            id="ai"
            ref={(el) => { sectionRefs.current["ai"] = el; }}
            style={{
              background: "var(--panel)",
              border: "1px solid var(--line)",
              borderRadius: 9,
              padding: 14,
              boxShadow: "var(--shadow)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
                marginBottom: 10,
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>
                AI
              </div>
              <div style={{ fontSize: "11.5px", color: "var(--ink-3)" }}>
                применяется к новым тенантам
              </div>
            </div>
            <SetRow
              title="Модель по умолчанию"
              sub="Основная LLM для новых тенантов"
              first
            >
              <select
                value={settings.default_ai_model}
                onChange={(e) => updateField("default_ai_model", e.target.value)}
                style={selectStyle}
              >
                <option value="gpt-4o-mini">GPT-4o Mini</option>
                <option value="gpt-4o">GPT-4o</option>
                <option value="gpt-4-turbo">GPT-4 Turbo</option>
                <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
              </select>
            </SetRow>
            <SetRow
              title="Временный fallback"
              sub="При недоступности основной модели"
            >
              <select
                value={settings.fallback_model}
                onChange={(e) => updateField("fallback_model", e.target.value)}
                style={selectStyle}
              >
                <option value="gpt-4o-mini">GPT-4o Mini</option>
                <option value="gpt-4o">GPT-4o</option>
                <option value="gpt-4-turbo">GPT-4 Turbo</option>
                <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
              </select>
            </SetRow>
          </section>

          {/* ── Локализация ─────────────────────────────────────────────── */}
          <section
            id="localization"
            ref={(el) => { sectionRefs.current["localization"] = el; }}
            style={{
              background: "var(--panel)",
              border: "1px solid var(--line)",
              borderRadius: 9,
              padding: 14,
              boxShadow: "var(--shadow)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
                marginBottom: 10,
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>
                Локализация
              </div>
            </div>
            <SetRow
              title="Язык по умолчанию"
              sub="Язык AI для новых тенантов"
              first
            >
              <select
                value={settings.default_language}
                onChange={(e) => updateField("default_language", e.target.value)}
                style={selectStyle}
              >
                <option value="ru">Русский</option>
                <option value="uz_latin">O&apos;zbek</option>
                <option value="en">English</option>
              </select>
            </SetRow>
            <SetRow title="Часовой пояс">
              <select
                value={settings.default_timezone}
                onChange={(e) => updateField("default_timezone", e.target.value)}
                style={selectStyle}
              >
                <option value="Asia/Tashkent">Asia/Tashkent (UTC+5)</option>
                <option value="Asia/Almaty">Asia/Almaty (UTC+6)</option>
                <option value="Europe/Moscow">Europe/Moscow (UTC+3)</option>
                <option value="UTC">UTC</option>
              </select>
            </SetRow>
          </section>

          {/* ── Лимиты ─────────────────────────────────────────────────── */}
          <section
            id="limits"
            ref={(el) => { sectionRefs.current["limits"] = el; }}
            style={{
              background: "var(--panel)",
              border: "1px solid var(--line)",
              borderRadius: 9,
              padding: 14,
              boxShadow: "var(--shadow)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
                marginBottom: 10,
                flexWrap: "wrap",
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>
                Лимиты
              </div>
              <button
                onClick={resetLimits}
                style={{
                  fontSize: "11.5px",
                  color: "var(--accent)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  borderBottom: "1px dotted var(--accent-ring)",
                  padding: 0,
                  lineHeight: 1.3,
                }}
              >
                сбросить к умолчаниям
              </button>
            </div>
            <SetRow
              title="Макс. товаров на тенант"
              sub="Лимит товаров в каталоге"
              first
            >
              <input
                type="number"
                value={settings.max_products_per_tenant}
                onChange={(e) =>
                  updateField(
                    "max_products_per_tenant",
                    parseInt(e.target.value) || 0
                  )
                }
                style={inputStyle}
                min={0}
              />
              <span
                style={{
                  fontSize: "10.5px",
                  color: "var(--ink-3)",
                  fontFamily: "'Geist Mono', ui-monospace, monospace",
                }}
              >
                шт
              </span>
            </SetRow>
            <SetRow
              title="Макс. пользователей"
              sub="Лимит админов на тенант"
            >
              <input
                type="number"
                value={settings.max_users_per_tenant}
                onChange={(e) =>
                  updateField(
                    "max_users_per_tenant",
                    parseInt(e.target.value) || 0
                  )
                }
                style={inputStyle}
                min={0}
              />
              <span
                style={{
                  fontSize: "10.5px",
                  color: "var(--ink-3)",
                  fontFamily: "'Geist Mono', ui-monospace, monospace",
                }}
              >
                чел
              </span>
            </SetRow>
            <SetRow
              title="Макс. AI сообщений / день"
              sub="Защита от превышения биллинга"
            >
              <input
                type="number"
                value={settings.max_messages_per_day}
                onChange={(e) =>
                  updateField(
                    "max_messages_per_day",
                    parseInt(e.target.value) || 0
                  )
                }
                style={inputStyle}
                min={0}
              />
              <span
                style={{
                  fontSize: "10.5px",
                  color: "var(--ink-3)",
                  fontFamily: "'Geist Mono', ui-monospace, monospace",
                }}
              >
                /день
              </span>
            </SetRow>
            <SetRow title="Триал" sub="Дни бесплатного использования">
              <input
                type="number"
                value={settings.trial_days}
                onChange={(e) =>
                  updateField("trial_days", parseInt(e.target.value) || 0)
                }
                style={inputStyle}
                min={0}
              />
              <span
                style={{
                  fontSize: "10.5px",
                  color: "var(--ink-3)",
                  fontFamily: "'Geist Mono', ui-monospace, monospace",
                }}
              >
                дней
              </span>
            </SetRow>
          </section>

          {/* ── Регистрация ────────────────────────────────────────────── */}
          <section
            id="registration"
            ref={(el) => { sectionRefs.current["registration"] = el; }}
            style={{
              background: "var(--panel)",
              border: "1px solid var(--line)",
              borderRadius: 9,
              padding: 14,
              boxShadow: "var(--shadow)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
                marginBottom: 10,
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>
                Регистрация
              </div>
            </div>
            <SetRow
              title="Регистрация новых тенантов"
              sub="Разрешить самостоятельную регистрацию через landing"
              first
            >
              <ToggleSwitch
                on={settings.signup_enabled}
                onClick={() =>
                  updateField("signup_enabled", !settings.signup_enabled)
                }
              />
            </SetRow>
          </section>

          {/* ── Критические ────────────────────────────────────────────── */}
          <section
            id="critical"
            ref={(el) => { sectionRefs.current["critical"] = el; }}
            style={{
              background: "var(--panel)",
              border: "1px solid color-mix(in oklab, var(--bad) 50%, var(--line))",
              borderRadius: 9,
              padding: 14,
              boxShadow: "var(--shadow)",
            }}
          >
            <div style={{ marginBottom: 10 }}>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: "var(--bad)",
                }}
              >
                &#9888; Критические действия
              </div>
              <div
                style={{
                  fontSize: "11.5px",
                  color: "var(--ink-3)",
                  marginTop: 2,
                }}
              >
                эти настройки влияют на всех пользователей &middot; требуется
                подтверждение
              </div>
            </div>
            <SetRow
              title="Режим обслуживания"
              sub="Отключает AI обработку на всей платформе"
              first
            >
              <ToggleSwitch
                on={settings.maintenance_mode}
                onClick={() =>
                  updateField("maintenance_mode", !settings.maintenance_mode)
                }
                danger
              />
              {settings.maintenance_mode && (
                <span
                  style={{
                    fontSize: "10.5px",
                    fontWeight: 500,
                    color: "var(--bad)",
                  }}
                >
                  Активен
                </span>
              )}
            </SetRow>
            <SetRow
              title="Read-only режим"
              sub="Блокирует любые изменения данных"
            >
              <ToggleSwitch
                on={settings.read_only_mode}
                onClick={() =>
                  updateField("read_only_mode", !settings.read_only_mode)
                }
                danger
              />
              {settings.read_only_mode && (
                <span
                  style={{
                    fontSize: "10.5px",
                    fontWeight: 500,
                    color: "var(--bad)",
                  }}
                >
                  Активен
                </span>
              )}
            </SetRow>
          </section>

          {/* ── Footer ─────────────────────────────────────────────────── */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              paddingTop: 6,
            }}
          >
            <div style={{ fontSize: "11.5px", color: "var(--ink-3)" }}>
              {success
                ? "Сохранено"
                : dirtyCount > 0
                  ? `${dirtyCount} несохранённых ${dirtyCount === 1 ? "изменение" : dirtyCount < 5 ? "изменения" : "изменений"}`
                  : "Несохранённых изменений нет"}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button
                onClick={handleCancel}
                style={{
                  padding: "6px 11px",
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 500,
                  border: "1px solid var(--line)",
                  background: "transparent",
                  color: "var(--ink)",
                  cursor: "pointer",
                  transition: "background 0.12s",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--bg-2)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                }}
              >
                Отмена
              </button>
              <button
                onClick={handleSave}
                disabled={saving || dirtyCount === 0}
                style={{
                  padding: "6px 11px",
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 500,
                  border: "1px solid var(--accent)",
                  background: "var(--accent)",
                  color: "#fff",
                  cursor: saving || dirtyCount === 0 ? "default" : "pointer",
                  opacity: saving || dirtyCount === 0 ? 0.5 : 1,
                  transition: "opacity 0.12s, filter 0.12s",
                }}
                onMouseEnter={(e) => {
                  if (!saving && dirtyCount > 0) {
                    e.currentTarget.style.filter = "brightness(1.1)";
                  }
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.filter = "none";
                }}
              >
                {saving ? "Сохранение..." : "Сохранить настройки"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
