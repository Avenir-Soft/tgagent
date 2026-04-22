"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";

export interface UserModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  editUser?: { id: string; email: string; full_name: string; role: string; is_active: boolean } | null;
  tenantId?: string;
  tenantName?: string;
  tenants?: { id: string; name: string }[];
}

export function UserModal({ open, onClose, onSuccess, editUser, tenantId, tenantName, tenants }: UserModalProps) {
  const isEdit = !!editUser;

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("store_owner");
  const [password, setPassword] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [selectedTenantId, setSelectedTenantId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Reset form when modal opens or editUser changes
  useEffect(() => {
    if (!open) return;
    setError("");
    setPassword("");
    setSaving(false);
    if (isEdit && editUser) {
      setEmail(editUser.email);
      setFullName(editUser.full_name);
      setRole(editUser.role);
      setIsActive(editUser.is_active);
      setSelectedTenantId(tenantId || "");
    } else {
      setEmail("");
      setFullName("");
      setRole("store_owner");
      setIsActive(true);
      setSelectedTenantId(tenantId || tenants?.[0]?.id || "");
    }
  }, [open, editUser, isEdit, tenantId, tenants]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError("");

    try {
      // Validation
      if (!isEdit && !email.trim()) {
        setError("Email обязателен");
        setSaving(false);
        return;
      }
      if (!fullName.trim()) {
        setError("Имя обязательно");
        setSaving(false);
        return;
      }
      if (!isEdit && !password) {
        setError("Пароль обязателен для нового пользователя");
        setSaving(false);
        return;
      }
      if (password && password.length < 8) {
        setError("Пароль должен быть минимум 8 символов");
        setSaving(false);
        return;
      }
      if (password && (!/[a-zA-Zа-яА-Я]/.test(password) || !/[0-9]/.test(password))) {
        setError("Пароль должен содержать буквы и цифры");
        setSaving(false);
        return;
      }
      if (!isEdit && !tenantId && !selectedTenantId) {
        setError("Выберите тенант");
        setSaving(false);
        return;
      }

      if (isEdit && editUser) {
        const body: Record<string, unknown> = {
          full_name: fullName.trim(),
          role,
          is_active: isActive,
        };
        if (password) body.new_password = password;
        await api.patch(`/platform/users/${editUser.id}`, body);
      } else {
        await api.post("/platform/users", {
          tenant_id: tenantId || selectedTenantId,
          email: email.trim(),
          full_name: fullName.trim(),
          password,
          role,
        });
      }

      onClose();
      onSuccess();
    } catch (err: any) {
      setError(err.message || "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  }, [isEdit, editUser, email, fullName, role, password, isActive, tenantId, selectedTenantId, onClose, onSuccess]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  if (!open) return null;

  const resolvedTenantName = tenantName || tenants?.find((t) => t.id === selectedTenantId)?.name || "";

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.45)", backdropFilter: "blur(2px)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-[500px] mx-4 rounded-[10px]"
        style={{
          background: "var(--panel)",
          border: "1px solid var(--line)",
          boxShadow: "0 20px 60px -20px rgba(0,0,0,0.4)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div
          className="flex items-start justify-between px-[18px] py-[16px]"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          <div>
            <div className="text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
              {isEdit ? "Редактирование пользователя" : "Новый пользователь"}
            </div>
            <div className="text-[11.5px] mt-[3px]" style={{ color: "var(--ink-3)" }}>
              {isEdit
                ? editUser?.email
                : tenantName
                  ? `Будет создан в тенанте ${tenantName}`
                  : "Новый пользователь для тенанта"}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-[18px] w-[28px] h-[28px] rounded-[6px] grid place-items-center transition-colors flex-shrink-0"
            style={{ color: "var(--ink-3)" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            &#215;
          </button>
        </div>

        {/* ── Error ── */}
        {error && (
          <div
            className="mx-[18px] mt-[14px] p-[10px] rounded-[6px] text-[12px]"
            style={{ background: "var(--bad-soft)", color: "var(--bad)" }}
          >
            {error}
          </div>
        )}

        {/* ── Section: Основные данные ── */}
        <div className="px-[18px] py-[14px]" style={{ borderBottom: "1px solid var(--line)" }}>
          <div className="label-mono mb-[10px]">ОСНОВНЫЕ ДАННЫЕ</div>

          {/* Email */}
          <div className="flex flex-col gap-[5px] mb-[10px]">
            <label className="label-mono" style={{ fontSize: "10px" }}>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isEdit}
              required
              placeholder="user@store.com"
              className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none transition-shadow disabled:opacity-60 disabled:cursor-not-allowed"
              style={{
                background: "var(--bg)",
                border: "1px solid var(--line)",
                color: "var(--ink)",
              }}
              onFocus={(e) => { if (!isEdit) { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; } }}
              onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
            />
          </div>

          {/* Имя */}
          <div className="flex flex-col gap-[5px] mb-[10px]">
            <label className="label-mono" style={{ fontSize: "10px" }}>Имя</label>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
              placeholder="Иван Петров"
              className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none transition-shadow"
              style={{
                background: "var(--bg)",
                border: "1px solid var(--line)",
                color: "var(--ink)",
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
              onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
            />
          </div>

          {/* Row: Роль + Тенант */}
          <div className="grid grid-cols-2 gap-[10px]">
            {/* Роль */}
            <div className="flex flex-col gap-[5px]">
              <label className="label-mono" style={{ fontSize: "10px" }}>Роль</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none cursor-pointer transition-shadow"
                style={{
                  background: "var(--bg)",
                  border: "1px solid var(--line)",
                  color: "var(--ink)",
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
                onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
              >
                <option value="store_owner">Владелец</option>
                <option value="operator">Оператор</option>
                <option value="super_admin">Super Admin</option>
              </select>
            </div>

            {/* Тенант */}
            <div className="flex flex-col gap-[5px]">
              <label className="label-mono" style={{ fontSize: "10px" }}>Тенант</label>
              {tenantId ? (
                <div
                  className="rounded-[6px] px-[10px] py-[8px] text-[12.5px]"
                  style={{
                    background: "var(--bg-2)",
                    border: "1px solid var(--line)",
                    color: "var(--ink-2)",
                  }}
                >
                  {resolvedTenantName || "..."}
                </div>
              ) : !isEdit ? (
                <select
                  value={selectedTenantId}
                  onChange={(e) => setSelectedTenantId(e.target.value)}
                  className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none cursor-pointer transition-shadow"
                  style={{
                    background: "var(--bg)",
                    border: "1px solid var(--line)",
                    color: "var(--ink)",
                  }}
                  onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
                  onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
                >
                  <option value="">Выберите тенант</option>
                  {tenants?.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              ) : (
                <div
                  className="rounded-[6px] px-[10px] py-[8px] text-[12.5px]"
                  style={{
                    background: "var(--bg-2)",
                    border: "1px solid var(--line)",
                    color: "var(--ink-2)",
                  }}
                >
                  {resolvedTenantName || "..."}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Section: Безопасность ── */}
        <div className="px-[18px] py-[14px]" style={{ borderBottom: "1px solid var(--line)" }}>
          <div className="label-mono mb-[10px]">БЕЗОПАСНОСТЬ</div>

          {/* Пароль */}
          <div className="flex flex-col gap-[5px]">
            <label className="label-mono" style={{ fontSize: "10px" }}>Пароль</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required={!isEdit}
              placeholder={isEdit ? "Оставьте пустым чтобы не менять" : "Минимум 8 символов, буквы и цифры"}
              className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none transition-shadow"
              style={{
                background: "var(--bg)",
                border: "1px solid var(--line)",
                color: "var(--ink)",
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
              onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
            />
          </div>

          {/* Статус toggle — edit only */}
          {isEdit && (
            <div className="grid grid-cols-2 gap-[10px] mt-[12px]">
              <div className="flex flex-col gap-[5px]">
                <label className="label-mono" style={{ fontSize: "10px" }}>Статус</label>
                <button
                  type="button"
                  onClick={() => setIsActive(!isActive)}
                  className="flex items-center gap-[8px] rounded-[6px] px-[10px] py-[7px] text-[12.5px] transition-colors text-left"
                  style={{
                    background: "var(--bg)",
                    border: "1px solid var(--line)",
                    color: "var(--ink)",
                  }}
                >
                  <span
                    className="relative w-[32px] h-[18px] rounded-full flex-shrink-0 transition-colors"
                    style={{
                      background: isActive ? "var(--accent)" : "var(--bg-2)",
                      border: `1px solid ${isActive ? "var(--accent)" : "var(--line)"}`,
                    }}
                  >
                    <span
                      className="absolute top-[1px] w-[14px] h-[14px] rounded-full bg-white transition-transform"
                      style={{
                        left: "1px",
                        transform: isActive ? "translateX(14px)" : "translateX(0)",
                      }}
                    />
                  </span>
                  <span style={{ color: isActive ? "var(--good)" : "var(--ink-3)" }}>
                    {isActive ? "Активен" : "Отключен"}
                  </span>
                </button>
              </div>
              <div>{/* empty — reserved */}</div>
            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="flex justify-end gap-[8px] px-[18px] py-[14px]">
          <button
            type="button"
            onClick={onClose}
            className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-medium transition-colors"
            style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink)" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-semibold text-white disabled:opacity-50 transition-colors"
            style={{ background: "var(--accent)", border: "1px solid var(--accent)" }}
          >
            {saving ? "Сохранение..." : isEdit ? "Сохранить" : "Создать"}
          </button>
        </div>
      </div>
    </div>
  );
}
