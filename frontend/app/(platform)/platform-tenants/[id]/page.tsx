"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { UserModal } from "@/components/user-modal";

interface ActivityDay {
  date: string;
  count: number;
}

interface TenantDetail {
  id: string;
  name: string;
  slug: string;
  status: string;
  created_at: string;
  updated_at: string;
  products_count?: number;
  variants_count?: number;
  conversations_count?: number;
  active_conversations_count?: number;
  orders_count?: number;
  revenue_total?: number;
  revenue_usd?: number;
  // Telegram
  telegram_phone?: string;
  telegram_username?: string;
  telegram_display_name?: string;
  telegram_status?: string;
  // AI config
  ai_provider?: string;
  ai_model?: string;
  ai_language?: string;
  ai_tone?: string;
  // Activity chart
  activity_30d?: ActivityDay[];
  // Monitoring
  tenant_created_days_ago?: number;
  last_message_at?: string;
  total_messages?: number;
}

interface TenantUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  last_login_at?: string;
  created_at: string;
}

const statusLabels: Record<string, string> = {
  active: "Активен",
  suspended: "Приостановлен",
  onboarding: "Онбординг",
  trial: "Триал",
};

const statusTone: Record<string, string> = {
  active: "good",
  suspended: "bad",
  onboarding: "warn",
  trial: "info",
};

const statusOptions = ["active", "suspended", "onboarding", "trial"];

const roleTone: Record<string, string> = {
  super_admin: "accent",
  store_owner: "info",
  operator: "dim",
};

// Tabs removed — use "Войти как Admin" for tenant-level pages

function Chip({ tone, children }: { tone: string; children: React.ReactNode }) {
  if (tone === "dim") {
    return (
      <span className="inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-full text-[10.5px] font-medium" style={{ background: "var(--bg-2)", color: "var(--ink-3)", border: "1px solid var(--line)" }}>
        {children}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-full text-[10.5px] font-medium" style={{ background: `var(--${tone}-soft)`, color: `var(--${tone})`, border: `1px solid color-mix(in oklab, var(--${tone}) 30%, transparent)` }}>
      <span style={{ fontSize: "7px" }}>&#9679;</span>
      {children}
    </span>
  );
}

function Delta({ value, suffix, metric = "growth" }: { value: string; suffix?: string; metric?: "growth" | "cost" | "error" }) {
  // Parse numeric value for color determination
  const numVal = parseFloat(value.replace(/[^0-9.\-]/g, "")) || 0;
  let color = "var(--ink-3)";
  if (metric === "growth") {
    color = numVal > 0 ? "var(--good)" : numVal < 0 ? "var(--bad)" : "var(--ink-3)";
  } else if (metric === "cost") {
    color = numVal > 0 ? "var(--warn)" : numVal < 0 ? "var(--good)" : "var(--ink-3)";
  } else if (metric === "error") {
    color = numVal > 3 ? "var(--bad)" : numVal > 1 ? "var(--warn)" : "var(--good)";
  }
  const prefix = numVal >= 0 ? "+" : "";
  return (
    <span className="inline-flex items-center gap-[2px] text-[10.5px] font-medium" style={{ color }}>
      {prefix}{value}{suffix ? ` ${suffix}` : ""}
    </span>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-[14px] animate-pulse">
      {/* Header skeleton */}
      <div className="flex items-center gap-[10px]">
        <div className="w-[28px] h-[28px] skeleton rounded-[6px]" />
        <div className="w-[40px] h-[40px] skeleton rounded-[8px]" />
        <div className="flex flex-col gap-[6px]">
          <div className="h-[24px] w-[240px] skeleton rounded-[6px]" />
          <div className="h-[14px] w-[320px] skeleton rounded-[4px]" />
        </div>
      </div>
      {/* Tabs skeleton */}
      <div className="h-[38px] skeleton rounded-[7px]" />
      {/* KPI skeleton */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-[10px]">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-[94px] skeleton rounded-[9px]" />)}
      </div>
      {/* Table skeleton */}
      <div className="h-[280px] skeleton rounded-[9px]" />
      {/* Bottom row skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-[10px]">
        <div className="h-[200px] skeleton rounded-[9px]" />
        <div className="h-[200px] skeleton rounded-[9px]" />
      </div>
    </div>
  );
}

/** Format relative time in Russian */
function fmtRelative(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "только что";
  if (mins < 60) return `${mins} мин назад`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} ч назад`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} дн назад`;
  const months = Math.floor(days / 30);
  return `${months} мес назад`;
}

export default function TenantDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [tenant, setTenant] = useState<TenantDetail | null>(null);
  const [users, setUsers] = useState<TenantUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [impersonating, setImpersonating] = useState(false);
  // tabs removed

  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editStatus, setEditStatus] = useState("");
  const [saving, setSaving] = useState(false);

  // Add user modal
  const [showAddUser, setShowAddUser] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get<TenantDetail>(`/tenants/${id}`),
      api.get<{ items: TenantUser[]; total: number }>(`/platform/users?tenant_id=${id}`),
    ])
      .then(([t, u]) => {
        setTenant(t as TenantDetail);
        setUsers((u as any).items || []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const handleImpersonate = async () => {
    if (!tenant) return;
    setImpersonating(true);
    try {
      const result = await api.post<{ access_token: string; tenant_name: string; user_email: string }>(`/tenants/${id}/impersonate`);
      const currentToken = localStorage.getItem("token");
      const currentUser = localStorage.getItem("user");
      if (currentToken) sessionStorage.setItem("original_token", currentToken);
      if (currentUser) sessionStorage.setItem("original_user", currentUser);
      sessionStorage.setItem("impersonate_tenant_name", result.tenant_name);
      localStorage.setItem("token", result.access_token);
      router.push("/dashboard");
    } catch (e: any) {
      setError(e.message || "Не удалось войти как тенант");
      setImpersonating(false);
    }
  };

  const startEdit = () => {
    if (!tenant) return;
    setEditName(tenant.name);
    setEditStatus(tenant.status);
    setEditing(true);
  };

  const cancelEdit = () => { setEditing(false); };

  const saveEdit = async () => {
    if (!tenant) return;
    setSaving(true);
    try {
      const body: Record<string, string> = {};
      if (editName !== tenant.name) body.name = editName;
      if (editStatus !== tenant.status) body.status = editStatus;
      if (Object.keys(body).length === 0) { setEditing(false); setSaving(false); return; }
      await api.patch(`/tenants/${id}`, body);
      setEditing(false);
      load();
    } catch (e: any) {
      setError(e.message || "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  const handleImpersonateUser = async (userId: string, userEmail: string) => {
    try {
      const result = await api.post<{ access_token: string; tenant_name: string; user_email: string }>(`/tenants/${id}/impersonate`);
      const currentToken = localStorage.getItem("token");
      const currentUser = localStorage.getItem("user");
      if (currentToken) sessionStorage.setItem("original_token", currentToken);
      if (currentUser) sessionStorage.setItem("original_user", currentUser);
      sessionStorage.setItem("impersonate_tenant_name", tenant?.name || "");
      localStorage.setItem("token", result.access_token);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Не удалось войти");
    }
  };

  const fmtDate = (d: string) => new Date(d).toLocaleDateString("ru-RU", { day: "2-digit", month: "short", year: "numeric" });
  const fmtNum = (n: number | undefined | null) => (n ?? 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");

  const ownerEmail = useMemo(() => {
    const owner = users.find(u => u.role === "store_owner" || u.role === "super_admin");
    return owner?.email || "";
  }, [users]);

  const tabCounts = useMemo(() => ({
    users: users.length,
    products: tenant?.products_count ?? 0,
    conversations: tenant?.conversations_count ?? 0,
    orders: tenant?.orders_count ?? 0,
  }), [users, tenant]);

  const activityData = useMemo(() => {
    const raw = tenant?.activity_30d ?? [];
    const maxCount = Math.max(1, ...raw.map((d) => d.count));
    return raw.map((d) => ({
      date: d.date,
      count: d.count,
      pct: (d.count / maxCount) * 100,
    }));
  }, [tenant]);

  if (loading) return <DetailSkeleton />;

  if (error && !tenant) {
    return (
      <div className="flex flex-col gap-[14px]">
        <h1 className="text-[22px] font-semibold" style={{ color: "var(--ink)" }}>Тенант</h1>
        <div className="rounded-[9px] p-8 text-center" style={{ background: "var(--panel)", border: "1px solid var(--line)" }}>
          <p className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>{error}</p>
          <button onClick={() => router.push("/platform-tenants")} className="mt-3 text-[12px] font-medium" style={{ color: "var(--accent)" }}>Назад к списку</button>
        </div>
      </div>
    );
  }

  if (!tenant) return null;

  const revenueUsd = tenant.revenue_usd ?? Math.round((tenant.revenue_total ?? 0) / 12800);

  return (
    <>
    <div className="flex flex-col gap-[14px]">
      {/* Error banner (non-fatal) */}
      {error && (
        <div className="rounded-[9px] p-3" style={{ background: "var(--bad-soft)", border: "1px solid color-mix(in oklab, var(--bad) 30%, transparent)" }}>
          <p className="text-[12px]" style={{ color: "var(--bad)" }}>{error}</p>
        </div>
      )}

      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-start gap-[10px]">
          {/* Back button */}
          <button
            onClick={() => router.push("/platform-tenants")}
            className="w-[28px] h-[28px] rounded-[6px] grid place-items-center mt-[2px] transition-colors"
            style={{ color: "var(--ink-3)", border: "1px solid var(--line)" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" /></svg>
          </button>
          {/* Avatar */}
          <div className="w-[40px] h-[40px] rounded-[8px] grid place-items-center text-[13px] font-semibold flex-shrink-0" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
            {tenant.name.slice(0, 2).toUpperCase()}
          </div>
          {/* Name + meta */}
          <div>
            <div className="flex items-center gap-[8px]">
              {editing ? (
                <input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="text-[22px] font-semibold rounded-[6px] px-2 py-0.5 outline-none"
                  style={{ color: "var(--ink)", border: "1px solid var(--accent)", background: "var(--bg)" }}
                  autoFocus
                />
              ) : (
                <h1 className="text-[22px] font-semibold tracking-[-0.01em]" style={{ color: "var(--ink)" }}>{tenant.name}</h1>
              )}
              {editing ? (
                <select
                  value={editStatus}
                  onChange={(e) => setEditStatus(e.target.value)}
                  className="text-[11px] rounded-[6px] px-[10px] py-[6px] outline-none"
                  style={{ border: "1px solid var(--accent)", background: "var(--bg)", color: "var(--ink)" }}
                >
                  {statusOptions.map((s) => (
                    <option key={s} value={s}>{statusLabels[s] || s}</option>
                  ))}
                </select>
              ) : (
                <Chip tone={statusTone[tenant.status] || "accent"}>{statusLabels[tenant.status] || tenant.status}</Chip>
              )}
            </div>
            <div className="text-[11.5px] mt-[3px] flex items-center gap-[6px] flex-wrap" style={{ color: "var(--ink-3)" }}>
              <span>slug: <span className="mono" style={{ color: "var(--ink-2)" }}>{tenant.slug}</span></span>
              <span>&middot;</span>
              <span>создан {fmtDate(tenant.created_at)}</span>
              {ownerEmail && (
                <>
                  <span>&middot;</span>
                  <span>владелец <span className="mono" style={{ color: "var(--ink-2)" }}>{ownerEmail}</span></span>
                </>
              )}
            </div>
          </div>
        </div>
        {/* Actions */}
        <div className="flex items-center gap-[8px]">
          {editing ? (
            <>
              <button onClick={cancelEdit} className="px-[11px] py-[6px] rounded-[6px] text-[12px] transition-colors" style={{ color: "var(--ink-2)" }}>Отмена</button>
              <button onClick={saveEdit} disabled={saving} className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-medium text-white disabled:opacity-50" style={{ background: "var(--accent)" }}>
                {saving ? "Сохранение..." : "Сохранить"}
              </button>
            </>
          ) : (
            <>
              <button onClick={startEdit} className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-medium flex items-center gap-[6px] transition-colors" style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" /></svg>
                Редактировать
              </button>
              <button
                onClick={handleImpersonate}
                disabled={impersonating}
                className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-semibold flex items-center gap-[6px] transition-all disabled:opacity-50"
                style={{ background: "var(--warn)", color: "#1a1205", border: "1px solid var(--warn)" }}
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" /></svg>
                {impersonating ? "Вход..." : "Войти как Admin"}
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── Content ── */}
          {/* ── KPI Cards ── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-[10px]">
            {/* ТОВАРЫ */}
            <div className="rounded-[9px] p-[12px_13px] flex flex-col gap-[4px]" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
              <div className="label-mono">ТОВАРЫ</div>
              <div className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em] mt-[2px]" style={{ color: "var(--ink)" }}>{tenant.products_count ?? 0}</div>
              <div className="flex items-center justify-between mt-[2px]">
                <span className="mono text-[10.5px]" style={{ color: "var(--ink-3)" }}>{fmtNum(tenant.variants_count)} вариантов</span>
                <Delta value="3" suffix="нед" />
              </div>
            </div>
            {/* ДИАЛОГИ */}
            <div className="rounded-[9px] p-[12px_13px] flex flex-col gap-[4px]" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
              <div className="label-mono">ДИАЛОГИ</div>
              <div className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em] mt-[2px]" style={{ color: "var(--ink)" }}>{tenant.conversations_count ?? 0}</div>
              <div className="flex items-center justify-between mt-[2px]">
                <span className="mono text-[10.5px]" style={{ color: "var(--ink-3)" }}>активных {tenant.active_conversations_count ?? Math.min(tenant.conversations_count ?? 0, 3)}</span>
                <Delta value="2" suffix="нед" />
              </div>
            </div>
            {/* ЗАКАЗЫ */}
            <div className="rounded-[9px] p-[12px_13px] flex flex-col gap-[4px]" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
              <div className="label-mono">ЗАКАЗЫ</div>
              <div className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em] mt-[2px]" style={{ color: "var(--ink)" }}>{tenant.orders_count ?? 0}</div>
              <div className="flex items-center justify-between mt-[2px]">
                <span />
                <Delta value="1" suffix="нед" />
              </div>
            </div>
            {/* ВЫРУЧКА · 30Д */}
            <div className="rounded-[9px] p-[12px_13px] flex flex-col gap-[4px]" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
              <div className="label-mono">ВЫРУЧКА &middot; 30Д</div>
              <div className="text-[26px] font-semibold tnum leading-none tracking-[-0.02em] mt-[2px]" style={{ color: "var(--ink)" }}>{fmtNum(tenant.revenue_total)}</div>
              <div className="flex items-center justify-between mt-[2px]">
                <span className="mono text-[10.5px]" style={{ color: "var(--ink-3)" }}>UZS &middot; &#8776; ${fmtNum(revenueUsd)}</span>
                <Delta value="12%" />
              </div>
            </div>
          </div>

          {/* ── Users table ── */}
          <div className="rounded-[9px] overflow-hidden" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
            <div className="px-[14px] pt-[13px] pb-[10px] flex items-center justify-between">
              <div className="flex items-center gap-[8px]">
                <span className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>Пользователи тенанта</span>
                <span className="text-[10px] font-medium px-[6px] py-[1px] rounded-full" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>{users.length}</span>
              </div>
              <button
                onClick={() => setShowAddUser(true)}
                className="px-[10px] py-[5px] rounded-[6px] text-[11.5px] font-medium flex items-center gap-[5px] transition-colors"
                style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink-2)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                + Добавить
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full" style={{ borderCollapse: "collapse", fontSize: "12.5px" }}>
                <thead>
                  <tr>
                    <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>EMAIL</th>
                    <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>ИМЯ</th>
                    <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>РОЛЬ</th>
                    <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>СТАТУС</th>
                    <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>ПОСЛ. ВХОД</th>
                    <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>СОЗДАН</th>
                    <th className="py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}></th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr
                      key={u.id}
                      className="transition-colors"
                      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                    >
                      <td className="py-[9px] px-[12px] mono text-[12px]" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink)" }}>{u.email}</td>
                      <td className="py-[9px] px-[12px] text-[12.5px]" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-2)" }}>{u.full_name || "-"}</td>
                      <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                        <Chip tone={roleTone[u.role] || "dim"}>{u.role?.replace("_", " ")}</Chip>
                      </td>
                      <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                        <span className="flex items-center gap-[6px] text-[11.5px]">
                          <span className="w-[6px] h-[6px] rounded-full" style={{ background: u.is_active ? "var(--good)" : "var(--ink-4)" }} />
                          <span style={{ color: u.is_active ? "var(--good)" : "var(--ink-3)" }}>{u.is_active ? "Активен" : "Отключен"}</span>
                        </span>
                      </td>
                      <td className="py-[9px] px-[12px] mono text-[11px] tnum text-right" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-3)" }}>
                        {u.last_login_at ? fmtRelative(u.last_login_at) : "-"}
                      </td>
                      <td className="py-[9px] px-[12px] mono text-[11px] tnum text-right" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-3)" }}>
                        {fmtDate(u.created_at)}
                      </td>
                      <td className="py-[9px] px-[12px] text-right" style={{ borderBottom: "1px solid var(--hair)" }}>
                        <button
                          onClick={() => handleImpersonateUser(u.id, u.email)}
                          className="text-[11px] font-medium transition-colors whitespace-nowrap"
                          style={{ color: "var(--accent)", background: "none", border: "none", cursor: "pointer" }}
                          onMouseEnter={(e) => { (e.currentTarget.style as any).textDecoration = "underline"; }}
                          onMouseLeave={(e) => { (e.currentTarget.style as any).textDecoration = "none"; }}
                          title={`Войти как ${u.email}`}
                        >
                          &#8627; войти
                        </button>
                      </td>
                    </tr>
                  ))}
                  {users.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-[12px] py-[32px] text-center text-[12.5px]" style={{ color: "var(--ink-3)" }}>Нет пользователей</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── Activity · 30 days (full width) ── */}
          <div className="rounded-[9px] p-[14px]" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
            <div className="text-[12px] font-semibold mb-[14px]" style={{ color: "var(--ink)" }}>Активность &middot; 30 дней</div>
            <div className="flex items-end gap-[3px]" style={{ height: "80px" }}>
              {activityData.map((bar, i) => (
                <div
                  key={i}
                  className="flex-1 rounded-[2px] transition-colors relative group"
                  style={{
                    height: `${Math.max(bar.count > 0 ? 8 : 2, bar.pct)}%`,
                    background: bar.pct > 60 ? "var(--accent)" : bar.count > 0 ? "color-mix(in oklab, var(--accent) 40%, transparent)" : "color-mix(in oklab, var(--accent) 12%, transparent)",
                    minWidth: "3px",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = bar.pct > 60 ? "var(--accent)" : bar.count > 0 ? "color-mix(in oklab, var(--accent) 40%, transparent)" : "color-mix(in oklab, var(--accent) 12%, transparent)"; }}
                >
                  {/* Tooltip */}
                  <div
                    className="absolute bottom-full left-1/2 -translate-x-1/2 mb-[6px] px-[7px] py-[4px] rounded-[5px] whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-10"
                    style={{ background: "var(--ink)", color: "var(--bg)", fontSize: "10px", boxShadow: "0 2px 8px rgba(0,0,0,0.15)" }}
                  >
                    <div className="mono tnum">{bar.date}</div>
                    <div className="font-medium">{bar.count} сообщ.</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between mt-[8px]">
              <span className="mono text-[10px]" style={{ color: "var(--ink-4)" }}>30 дн. назад</span>
              <span className="mono text-[10px]" style={{ color: "var(--ink-4)" }}>Сегодня</span>
            </div>
          </div>

          {/* ── Bottom Row: AI Config + Telegram & Monitoring ── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-[10px]">
            {/* AI Конфигурация */}
            <div className="rounded-[9px] p-[14px]" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
              <div className="text-[12px] font-semibold mb-[12px]" style={{ color: "var(--ink)" }}>AI Конфигурация</div>
              <div className="flex flex-col" style={{ gap: 0 }}>
                {([
                  ["AI провайдер", tenant.ai_provider || "openai"],
                  ["AI модель", tenant.ai_model || "gpt-4o-mini"],
                  ["Язык", tenant.ai_language || "\u2014"],
                  ["Тон", tenant.ai_tone || "\u2014"],
                  ["API ключ", "\u2014"],
                ] as [string, string][]).map(([label, value], i, arr) => (
                  <div
                    key={label}
                    className="grid py-[8px]"
                    style={{
                      gridTemplateColumns: "150px 1fr",
                      borderBottom: i < arr.length - 1 ? "1px dashed var(--hair)" : "none",
                    }}
                  >
                    <dt className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>{label}</dt>
                    <dd className="text-[11.5px] mono" style={{ color: "var(--ink)" }}>{value}</dd>
                  </div>
                ))}
              </div>
            </div>

            {/* Telegram & Мониторинг */}
            <div className="rounded-[9px] p-[14px]" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
              <div className="text-[12px] font-semibold mb-[12px]" style={{ color: "var(--ink)" }}>Telegram & Мониторинг</div>
              <div className="flex flex-col" style={{ gap: 0 }}>
                {/* Telegram rows */}
                <div className="grid py-[8px]" style={{ gridTemplateColumns: "150px 1fr", borderBottom: "1px dashed var(--hair)" }}>
                  <dt className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>AI Агент</dt>
                  <dd className="text-[11.5px] mono" style={{ color: "var(--ink)" }}>{tenant.telegram_display_name || "не подключён"}</dd>
                </div>
                <div className="grid py-[8px]" style={{ gridTemplateColumns: "150px 1fr", borderBottom: "1px dashed var(--hair)" }}>
                  <dt className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>Username</dt>
                  <dd className="text-[11.5px] mono" style={{ color: "var(--ink)" }}>{tenant.telegram_username ? `@${tenant.telegram_username}` : "\u2014"}</dd>
                </div>
                <div className="grid py-[8px]" style={{ gridTemplateColumns: "150px 1fr", borderBottom: "1px dashed var(--hair)" }}>
                  <dt className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>Телефон</dt>
                  <dd className="text-[11.5px] mono" style={{ color: "var(--ink)" }}>{tenant.telegram_phone || "\u2014"}</dd>
                </div>
                <div className="grid py-[8px]" style={{ gridTemplateColumns: "150px 1fr", borderBottom: "1px dashed var(--hair)" }}>
                  <dt className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>TG статус</dt>
                  <dd className="text-[11.5px] flex items-center gap-[6px]">
                    <span className="w-[6px] h-[6px] rounded-full flex-shrink-0" style={{ background: tenant.telegram_status === "connected" ? "var(--good)" : "var(--bad)" }} />
                    <span className="text-[11.5px] mono" style={{ color: tenant.telegram_status === "connected" ? "var(--good)" : "var(--bad)" }}>
                      {tenant.telegram_status === "connected" ? "connected" : tenant.telegram_status || "disconnected"}
                    </span>
                  </dd>
                </div>

                {/* Separator */}
                <div className="my-[4px]" style={{ borderBottom: "2px dashed var(--line)" }} />

                {/* Monitoring rows */}
                <div className="grid py-[8px]" style={{ gridTemplateColumns: "150px 1fr", borderBottom: "1px dashed var(--hair)" }}>
                  <dt className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>Всего сообщений</dt>
                  <dd className="text-[11.5px] mono tnum" style={{ color: "var(--ink)" }}>{fmtNum(tenant.total_messages)}</dd>
                </div>
                <div className="grid py-[8px]" style={{ gridTemplateColumns: "150px 1fr", borderBottom: "1px dashed var(--hair)" }}>
                  <dt className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>Последнее сообщ.</dt>
                  <dd className="text-[11.5px] mono" style={{ color: "var(--ink)" }}>{tenant.last_message_at ? fmtRelative(tenant.last_message_at) : "\u2014"}</dd>
                </div>
                <div className="grid py-[8px]" style={{ gridTemplateColumns: "150px 1fr" }}>
                  <dt className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>На платформе</dt>
                  <dd className="text-[11.5px] mono tnum" style={{ color: "var(--ink)" }}>{tenant.tenant_created_days_ago ?? 0} дней</dd>
                </div>
              </div>
            </div>
          </div>
    </div>

    {/* Add User Modal */}
    <UserModal
      open={showAddUser}
      onClose={() => setShowAddUser(false)}
      onSuccess={load}
      tenantId={id}
      tenantName={tenant?.name}
    />
    </>
  );
}
