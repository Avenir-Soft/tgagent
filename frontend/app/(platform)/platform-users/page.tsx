"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { api } from "@/lib/api";
import { UserModal } from "@/components/user-modal";

interface PlatformUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  tenant_id: string;
  tenant_name: string;
  created_at: string;
  last_login_at?: string;
}

interface UserListResponse {
  items: PlatformUser[];
  total: number;
}

interface TenantOption {
  id: string;
  name: string;
}

const PAGE_SIZE = 20;

const roleLabels: Record<string, string> = {
  super_admin: "Super Admin",
  store_owner: "Store Owner",
  operator: "Operator",
};

const roleTone: Record<string, string> = {
  super_admin: "accent",
  store_owner: "info",
  operator: "dim",
};

type SortField = "email" | "full_name" | "role" | "created_at";
type StatusFilter = "all" | "active" | "disabled";

function SortArrow({ field, sortBy, sortOrder }: { field: SortField; sortBy: SortField; sortOrder: string }) {
  if (sortBy !== field) return <span className="ml-1" style={{ color: "var(--ink-4)" }}>&#8597;</span>;
  return <span className="ml-1" style={{ color: "var(--accent)" }}>{sortOrder === "asc" ? "\u2191" : "\u2193"}</span>;
}

function Chip({ tone, children }: { tone: string; children: React.ReactNode }) {
  if (tone === "dim") {
    return (
      <span className="inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-full text-[10.5px] font-medium whitespace-nowrap" style={{ background: "var(--bg-2)", color: "var(--ink-3)", border: "1px solid var(--line)" }}>
        {children}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-full text-[10.5px] font-medium whitespace-nowrap" style={{ background: `var(--${tone}-soft)`, color: `var(--${tone})`, border: `1px solid color-mix(in oklab, var(--${tone}) 30%, transparent)` }}>
      {children}
    </span>
  );
}

function UsersSkeleton() {
  return (
    <div className="flex flex-col gap-[14px] animate-pulse">
      <div className="h-8 w-48 skeleton rounded-[9px]" />
      <div className="h-[40px] skeleton rounded-[9px]" />
      <div className="space-y-0 rounded-[9px] overflow-hidden" style={{ border: "1px solid var(--line)" }}>
        <div className="h-[38px] skeleton" />
        {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-[52px] skeleton" />)}
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

function getInitials(name: string, email: string): string {
  if (name && name.trim()) {
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return parts[0].slice(0, 2).toUpperCase();
  }
  return email.slice(0, 2).toUpperCase();
}

export default function PlatformUsersPage() {
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [total, setTotal] = useState(0);
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterTenant, setFilterTenant] = useState("all");
  const [filterRole, setFilterRole] = useState("all");
  const [filterStatus, setFilterStatus] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(0);
  const [sortBy, setSortBy] = useState<SortField>("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const [tenantsLoaded, setTenantsLoaded] = useState(false);

  const [modalOpen, setModalOpen] = useState(false);
  const [editUser, setEditUser] = useState<{ id: string; email: string; full_name: string; role: string; is_active: boolean } | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    debounceRef.current = setTimeout(() => { setDebouncedSearch(search); setPage(0); }, 300);
    return () => clearTimeout(debounceRef.current);
  }, [search]);

  useEffect(() => {
    api.get<{ items: TenantOption[]; total: number }>("/tenants?limit=100&offset=0")
      .then((res) => setTenants(res.items))
      .catch(() => {})
      .finally(() => setTenantsLoaded(true));
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE), sort_by: sortBy, sort_order: sortOrder });
    if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());
    if (filterTenant !== "all") params.set("tenant_id", filterTenant);
    if (filterRole !== "all") params.set("role", filterRole);

    api.get<UserListResponse>(`/platform/users?${params}`)
      .then((res) => { setUsers(res.items); setTotal(res.total); setSelected(new Set()); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [page, debouncedSearch, sortBy, sortOrder, filterTenant, filterRole]);

  useEffect(() => { load(); }, [load]);

  /* Computed role/status counts from loaded data */
  const roleCounts = useMemo(() => {
    const counts: Record<string, number> = { super_admin: 0, store_owner: 0, operator: 0 };
    users.forEach((u) => { if (counts[u.role] !== undefined) counts[u.role]++; });
    return counts;
  }, [users]);

  const disabledCount = useMemo(() => users.filter((u) => !u.is_active).length, [users]);

  /* Client-side status filter */
  const filteredUsers = useMemo(() => {
    if (filterStatus === "all") return users;
    if (filterStatus === "active") return users.filter((u) => u.is_active);
    return users.filter((u) => !u.is_active);
  }, [users, filterStatus]);

  const fmtDate = (d: string) => new Date(d).toLocaleDateString("ru-RU", { day: "2-digit", month: "short", year: "numeric" });

  const handleSort = (field: SortField) => {
    if (sortBy === field) { setSortOrder((prev) => (prev === "asc" ? "desc" : "asc")); }
    else { setSortBy(field); setSortOrder("desc"); }
    setPage(0);
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  };
  const toggleSelectAll = () => {
    if (selected.size === filteredUsers.length) { setSelected(new Set()); }
    else { setSelected(new Set(filteredUsers.map((u) => u.id))); }
  };

  const handleBulkStatus = async (isActive: boolean) => {
    if (selected.size === 0) return;
    setBulkLoading(true);
    try { await api.patch("/platform/users/bulk-status", { user_ids: Array.from(selected), is_active: isActive }); load(); }
    catch (e: any) { setError(e.message || "Ошибка массового обновления"); }
    finally { setBulkLoading(false); }
  };

  const openCreateModal = () => {
    setEditUser(null);
    setModalOpen(true);
  };
  const openEditModal = (u: PlatformUser) => {
    setEditUser({ id: u.id, email: u.email, full_name: u.full_name, role: u.role, is_active: u.is_active });
    setModalOpen(true);
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const showFrom = total > 0 ? page * PAGE_SIZE + 1 : 0;
  const showTo = Math.min((page + 1) * PAGE_SIZE, total);

  if (loading && users.length === 0 && !tenantsLoaded) return <UsersSkeleton />;

  return (
    <div className="flex flex-col gap-[14px]">
      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-[22px] font-semibold tracking-[-0.01em] flex items-center gap-[8px]" style={{ color: "var(--ink)" }}>
            Пользователи
            <span className="text-[11px] font-medium px-[7px] py-[2px] rounded-full" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>{total}</span>
          </h1>
          <div className="text-[11.5px] mt-[3px]" style={{ color: "var(--ink-3)" }}>
            Super Admin &middot; {roleCounts.super_admin} &middot; Store Owner &middot; {roleCounts.store_owner} &middot; деактивированных {disabledCount}
          </div>
        </div>
        <button
          onClick={openCreateModal}
          className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-semibold text-white flex items-center gap-[6px] transition-all"
          style={{ background: "var(--accent)", border: "1px solid var(--accent)" }}
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
          Создать пользователя
        </button>
      </div>

      {error && (
        <div className="rounded-[9px] p-4" style={{ background: "var(--bad-soft)", border: "1px solid color-mix(in oklab, var(--bad) 30%, transparent)" }}>
          <p className="text-[12.5px]" style={{ color: "var(--bad)" }}>{error}</p>
        </div>
      )}

      {/* ── Toolbar ── */}
      <div className="flex flex-wrap items-center gap-[8px]">
        {/* Search */}
        <div className="relative" style={{ width: 280 }}>
          <span className="absolute left-[10px] top-1/2 -translate-y-1/2 text-[12px]" style={{ color: "var(--ink-3)" }}>&#8981;</span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по email или имени\u2026"
            className="w-full rounded-[7px] pl-[30px] pr-[10px] py-[7px] text-[12px] outline-none transition-shadow"
            style={{ background: "var(--bg)", border: "1px solid var(--line)", color: "var(--ink)" }}
            onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
            onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
          />
        </div>

        {/* Tenant filter */}
        <select
          value={filterTenant}
          onChange={(e) => { setFilterTenant(e.target.value); setPage(0); }}
          className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none cursor-pointer"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
        >
          <option value="all">Все тенанты</option>
          {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>

        {/* Role filter */}
        <select
          value={filterRole}
          onChange={(e) => { setFilterRole(e.target.value); setPage(0); }}
          className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none cursor-pointer"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
        >
          <option value="all">Все роли</option>
          <option value="super_admin">Super Admin</option>
          <option value="store_owner">Store Owner</option>
          <option value="operator">Operator</option>
        </select>

        {/* Status filter */}
        <select
          value={filterStatus}
          onChange={(e) => { setFilterStatus(e.target.value as StatusFilter); setPage(0); }}
          className="rounded-[6px] px-[10px] py-[6px] text-[12px] outline-none cursor-pointer"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
        >
          <option value="all">Все статусы</option>
          <option value="active">Активные</option>
          <option value="disabled">Отключенные</option>
        </select>

        {/* Bulk actions — always visible */}
        <div className="flex items-center gap-[8px] ml-auto">
          <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>Выбрано {selected.size}</span>
          <span style={{ color: "var(--ink-4)" }}>&middot;</span>
          <button
            onClick={() => handleBulkStatus(true)}
            disabled={selected.size === 0 || bulkLoading}
            className="px-[9px] py-[4px] rounded-[6px] text-[11px] font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink-2)" }}
          >
            Активировать
          </button>
          <button
            onClick={() => handleBulkStatus(false)}
            disabled={selected.size === 0 || bulkLoading}
            className="px-[9px] py-[4px] rounded-[6px] text-[11px] font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink-2)" }}
          >
            Деактивировать
          </button>
        </div>
      </div>

      {/* ── Table ── */}
      <div className="rounded-[9px] overflow-hidden" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
        <div className="overflow-x-auto" style={{ padding: 0 }}>
          <table className="w-full" style={{ borderCollapse: "collapse", fontSize: "12.5px" }}>
            <thead>
              <tr>
                <th className="w-[32px] py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>
                  <input type="checkbox" checked={filteredUsers.length > 0 && selected.size === filteredUsers.length} onChange={toggleSelectAll} style={{ accentColor: "var(--accent)" }} />
                </th>
                <th className="label-mono text-left py-[9px] px-[12px] cursor-pointer select-none" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }} onClick={() => handleSort("email")}>
                  Email &middot; Имя <SortArrow field="email" sortBy={sortBy} sortOrder={sortOrder} />
                </th>
                <th className="label-mono text-left py-[9px] px-[12px] cursor-pointer select-none" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }} onClick={() => handleSort("role")}>
                  Роль <SortArrow field="role" sortBy={sortBy} sortOrder={sortOrder} />
                </th>
                <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>Тенант</th>
                <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>Статус</th>
                <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>Последний вход</th>
                <th className="label-mono text-right py-[9px] px-[12px] cursor-pointer select-none" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }} onClick={() => handleSort("created_at")}>
                  Создан <SortArrow field="created_at" sortBy={sortBy} sortOrder={sortOrder} />
                </th>
                <th className="py-[9px] px-[12px] w-[40px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}></th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((u) => (
                <tr
                  key={u.id}
                  className="transition-colors"
                  style={{ background: selected.has(u.id) ? "var(--accent-soft)" : "transparent" }}
                  onMouseEnter={(e) => { if (!selected.has(u.id)) e.currentTarget.style.background = "var(--bg-2)"; }}
                  onMouseLeave={(e) => { if (!selected.has(u.id)) e.currentTarget.style.background = "transparent"; }}
                >
                  {/* Checkbox */}
                  <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                    <input type="checkbox" checked={selected.has(u.id)} onChange={() => toggleSelect(u.id)} style={{ accentColor: "var(--accent)" }} />
                  </td>

                  {/* Identity: avatar + email + name */}
                  <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                    <div className="flex items-center gap-[10px]">
                      <div
                        className="w-[28px] h-[28px] rounded-[6px] grid place-items-center text-[10px] font-semibold flex-shrink-0"
                        style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
                      >
                        {getInitials(u.full_name, u.email)}
                      </div>
                      <div className="min-w-0">
                        <div className="mono text-[12px] truncate" style={{ color: "var(--ink)" }}>{u.email}</div>
                        <div className="text-[10.5px] mt-[1px] truncate" style={{ color: "var(--ink-3)" }}>{u.full_name || "\u2014"}</div>
                      </div>
                    </div>
                  </td>

                  {/* Role chip */}
                  <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                    <Chip tone={roleTone[u.role] || "dim"}>{roleLabels[u.role] || u.role}</Chip>
                  </td>

                  {/* Tenant */}
                  <td className="py-[9px] px-[12px] text-[11.5px]" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-2)" }}>
                    {u.tenant_name || "\u2014"}
                  </td>

                  {/* Status dot */}
                  <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                    <span className="flex items-center gap-[6px] text-[11.5px]">
                      <span className="w-[6px] h-[6px] rounded-full flex-shrink-0" style={{ background: u.is_active ? "var(--good)" : "var(--bad)" }} />
                      <span style={{ color: u.is_active ? "var(--good)" : "var(--ink-3)" }}>{u.is_active ? "active" : "disabled"}</span>
                    </span>
                  </td>

                  {/* Last login */}
                  <td className="py-[9px] px-[12px] mono text-[11px] tnum text-right" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-3)" }}>
                    {u.last_login_at ? fmtRelative(u.last_login_at) : "\u2014"}
                  </td>

                  {/* Created */}
                  <td className="py-[9px] px-[12px] mono text-[11px] tnum text-right" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink-3)" }}>
                    {fmtDate(u.created_at)}
                  </td>

                  {/* Edit */}
                  <td className="py-[9px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                    <button
                      onClick={() => openEditModal(u)}
                      className="w-[28px] h-[28px] rounded-[6px] grid place-items-center transition-colors"
                      style={{ color: "var(--ink-3)" }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; e.currentTarget.style.color = "var(--accent)"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--ink-3)"; }}
                    >
                      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" /></svg>
                    </button>
                  </td>
                </tr>
              ))}
              {filteredUsers.length === 0 && (
                <tr><td colSpan={8} className="px-[12px] py-[40px] text-center text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                  {debouncedSearch || filterTenant !== "all" || filterRole !== "all" || filterStatus !== "all" ? "Ничего не найдено" : "Нет пользователей"}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* ── Pager ── */}
        {total > 0 && (
          <div className="flex items-center justify-between px-[14px] py-[10px]" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)", fontSize: "11.5px" }}>
            <span style={{ color: "var(--ink-3)" }}>Показано {showFrom}&#8211;{showTo} из {total}</span>
            <div className="flex items-center gap-[4px]">
              <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className="w-[28px] h-[26px] rounded-[5px] grid place-items-center text-[11px] transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink-2)" }}>&lsaquo;</button>
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                let pageNum: number;
                if (totalPages <= 7) { pageNum = i; } else if (page < 3) { pageNum = i; } else if (page > totalPages - 4) { pageNum = totalPages - 7 + i; } else { pageNum = page - 3 + i; }
                return (
                  <button key={pageNum} onClick={() => setPage(pageNum)} className="w-[28px] h-[26px] rounded-[5px] grid place-items-center text-[11px] transition-colors"
                    style={{ background: pageNum === page ? "var(--accent-soft)" : "transparent", color: pageNum === page ? "var(--accent)" : "var(--ink-2)", border: pageNum === page ? "1px solid var(--accent)" : "1px solid var(--line)" }}>
                    {pageNum + 1}
                  </button>
                );
              })}
              <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="w-[28px] h-[26px] rounded-[5px] grid place-items-center text-[11px] transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink-2)" }}>&rsaquo;</button>
            </div>
          </div>
        )}
      </div>

      {/* Create/Edit User Modal */}
      <UserModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSuccess={load}
        editUser={editUser}
        tenants={tenants}
      />
    </div>
  );
}
