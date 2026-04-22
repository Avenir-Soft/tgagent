"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { api } from "@/lib/api";

interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: string;
  products_count: number;
  conversations_count: number;
  orders_count: number;
  users_count: number;
  created_at: string;
}

interface TenantListResponse {
  items: Tenant[];
  total: number;
}

const PAGE_SIZES = [25, 50, 100] as const;

const statusLabels: Record<string, string> = {
  active: "Активен",
  suspended: "Приостановлен",
  onboarding: "Онбординг",
  trial: "Trial",
};

const statusTone: Record<string, string> = {
  active: "good",
  suspended: "bad",
  onboarding: "warn",
  trial: "info",
};

type SortField = "name" | "created_at" | "products_count";

type StatusFilter = "all" | "active" | "trial" | "suspended";

function SortArrow({ field, sortBy, sortOrder }: { field: SortField; sortBy: SortField; sortOrder: string }) {
  if (sortBy !== field) return <span className="ml-1" style={{ color: "var(--ink-4)" }}>&#8597;</span>;
  return <span className="ml-1" style={{ color: "var(--accent)" }}>{sortOrder === "asc" ? "\u2191" : "\u2193"}</span>;
}

function TenantsSkeleton() {
  return (
    <div className="flex flex-col gap-[14px] animate-pulse">
      <div className="h-8 w-40 skeleton rounded-[9px]" />
      <div className="h-[36px] skeleton rounded-[7px]" />
      <div className="space-y-0 rounded-[9px] overflow-hidden" style={{ border: "1px solid var(--line)" }}>
        <div className="h-[38px] skeleton" />
        {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-[52px] skeleton" />)}
      </div>
    </div>
  );
}

function Chip({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-full text-[10.5px] font-medium whitespace-nowrap"
      style={{
        background: `var(--${tone}-soft)`,
        color: `var(--${tone})`,
        border: `1px solid color-mix(in oklab, var(--${tone}) 30%, transparent)`,
      }}
    >
      <span style={{ fontSize: "7px" }}>&#9679;</span>
      {children}
    </span>
  );
}

function exportTenantsCSV(tenants: Tenant[]) {
  const headers = ["Название", "Slug", "Статус", "Товары", "Диалоги", "Заказы", "Пользователи", "Создан"];
  const rows = tenants.map((t) => [
    t.name,
    t.slug,
    statusLabels[t.status] || t.status,
    t.products_count,
    t.conversations_count,
    t.orders_count ?? 0,
    t.users_count,
    new Date(t.created_at).toLocaleDateString("ru-RU"),
  ]);
  const csv = [headers.join(","), ...rows.map((r) => r.map((v) => `"${v}"`).join(","))].join("\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `tenants-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(25);
  const [sortBy, setSortBy] = useState<SortField>("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const [formName, setFormName] = useState("");
  const [formSlug, setFormSlug] = useState("");
  const [formEmail, setFormEmail] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formStatus, setFormStatus] = useState("trial");
  const [formModel, setFormModel] = useState("gpt-4o-mini");
  const [formInvite, setFormInvite] = useState(true);

  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    debounceRef.current = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(0);
    }, 300);
    return () => clearTimeout(debounceRef.current);
  }, [search]);

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({
      limit: String(pageSize),
      offset: String(page * pageSize),
      sort_by: sortBy === "products_count" ? "created_at" : sortBy,
      sort_order: sortOrder,
    });
    if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());

    api.get<TenantListResponse>(`/tenants?${params}`)
      .then((res) => {
        let items = res.items;
        if (sortBy === "products_count") {
          items = [...items].sort((a, b) =>
            sortOrder === "asc" ? a.products_count - b.products_count : b.products_count - a.products_count
          );
        }
        setTenants(items);
        setTotal(res.total);
        setSelected(new Set());
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [page, pageSize, debouncedSearch, sortBy, sortOrder]);

  useEffect(() => { load(); }, [load]);

  /* Status counts computed from loaded data */
  const statusCounts = useMemo(() => {
    const counts = { active: 0, trial: 0, suspended: 0 };
    tenants.forEach((t) => {
      if (t.status === "active") counts.active++;
      else if (t.status === "trial") counts.trial++;
      else if (t.status === "suspended") counts.suspended++;
    });
    return counts;
  }, [tenants]);

  /* Filtered tenants by status */
  const filteredTenants = useMemo(() => {
    if (statusFilter === "all") return tenants;
    return tenants.filter((t) => t.status === statusFilter);
  }, [tenants, statusFilter]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError("");
    if (!formName.trim() || !formSlug.trim() || !formEmail.trim() || !formPassword.trim()) {
      setCreateError("Все поля обязательны");
      return;
    }
    setCreating(true);
    try {
      const tenant = await api.post<{ id: string }>("/tenants", { name: formName, slug: formSlug, status: formStatus });
      await api.post(`/tenants/${tenant.id}/users`, { email: formEmail, password: formPassword, role: "store_owner", full_name: formName + " Admin" });
      setShowCreate(false);
      setFormName(""); setFormSlug(""); setFormEmail(""); setFormPassword("");
      setFormStatus("trial"); setFormModel("gpt-4o-mini"); setFormInvite(true);
      load();
    } catch (e: any) {
      setCreateError(e.message || "Ошибка создания тенанта");
    } finally {
      setCreating(false);
    }
  };

  const fmtDate = (d: string) => new Date(d).toLocaleDateString("ru-RU", { day: "2-digit", month: "short", year: "numeric" });

  const handleSort = (field: SortField) => {
    if (sortBy === field) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(field);
      setSortOrder("desc");
    }
    setPage(0);
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === filteredTenants.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filteredTenants.map((t) => t.id)));
    }
  };

  const handleBulkStatus = async (status: "active" | "suspended") => {
    if (selected.size === 0) return;
    setBulkLoading(true);
    try {
      await api.patch("/tenants/bulk-status", { tenant_ids: Array.from(selected), status });
      load();
    } catch (e: any) {
      setError(e.message || "Ошибка массового обновления");
    } finally {
      setBulkLoading(false);
    }
  };

  const totalPages = Math.ceil(total / pageSize);
  const showFrom = total > 0 ? page * pageSize + 1 : 0;
  const showTo = Math.min((page + 1) * pageSize, total);

  if (loading && tenants.length === 0) return <TenantsSkeleton />;

  return (
    <div className="flex flex-col gap-[14px]">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-[22px] font-semibold tracking-[-0.01em] flex items-center gap-[8px]" style={{ color: "var(--ink)" }}>
            Тенанты
            <span
              className="text-[11px] font-medium px-[7px] py-[2px] rounded-full"
              style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
            >
              {total}
            </span>
          </h1>
          <div className="text-[11.5px] mt-[3px]" style={{ color: "var(--ink-3)" }}>
            Активных {statusCounts.active} &middot; Trial {statusCounts.trial} &middot; Suspended {statusCounts.suspended} &middot; Всего {total}
          </div>
        </div>
        <div className="flex items-center gap-[8px]">
          <button
            onClick={() => exportTenantsCSV(tenants)}
            className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-medium transition-colors"
            style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink)" }}
          >
            Экспорт CSV
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-semibold text-white transition-all"
            style={{ background: "var(--accent)", border: "1px solid var(--accent)" }}
          >
            + Новый тенант
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-[9px] p-4" style={{ background: "var(--bad-soft)", border: "1px solid color-mix(in oklab, var(--bad) 30%, transparent)" }}>
          <p className="text-[12.5px]" style={{ color: "var(--bad)" }}>{error}</p>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center" style={{ background: "rgba(0,0,0,0.45)", backdropFilter: "blur(2px)" }}>
          <div className="w-full max-w-[480px] mx-4 rounded-[10px]" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "0 20px 60px -20px rgba(0,0,0,0.4)" }}>
            {/* Modal header */}
            <div className="flex items-start justify-between px-[18px] py-[16px]" style={{ borderBottom: "1px solid var(--line)" }}>
              <div>
                <div className="text-[15px] font-semibold" style={{ color: "var(--ink)" }}>Новый тенант</div>
                <div className="text-[11.5px] mt-[3px]" style={{ color: "var(--ink-3)" }}>Создаст организацию и первого владельца &middot; можно отредактировать позже</div>
              </div>
              <button onClick={() => setShowCreate(false)} className="text-[18px] w-[28px] h-[28px] rounded-[6px] grid place-items-center transition-colors" style={{ color: "var(--ink-3)" }}>&times;</button>
            </div>

            <form onSubmit={handleCreate}>
              {createError && (
                <div className="mx-[18px] mt-[12px] p-3 rounded-[6px] text-[12px]" style={{ background: "var(--bad-soft)", color: "var(--bad)" }}>{createError}</div>
              )}

              {/* Organization section */}
              <div className="px-[18px] py-[12px]" style={{ borderBottom: "1px solid var(--line)" }}>
                <div className="text-[10px] uppercase tracking-[0.16em] mb-[10px] mono" style={{ color: "var(--ink-3)" }}>Организация</div>
                <div className="flex flex-col gap-[10px]">
                  {/* Name */}
                  <div className="flex flex-col gap-[5px]">
                    <label className="label-mono">Название</label>
                    <input
                      type="text"
                      value={formName}
                      onChange={(e) => setFormName(e.target.value)}
                      placeholder="My Store"
                      className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none transition-shadow"
                      style={{ background: "var(--bg)", border: "1px solid var(--line)", color: "var(--ink)" }}
                      onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
                      onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
                    />
                  </div>
                  {/* Slug with prefix */}
                  <div className="flex flex-col gap-[5px]">
                    <label className="label-mono">
                      Slug
                      <span className="text-[10px] normal-case tracking-normal" style={{ color: "var(--ink-3)", letterSpacing: "0" }}>&middot; используется в URL, только латиница</span>
                    </label>
                    <div className="flex items-stretch rounded-[6px] overflow-hidden" style={{ border: "1px solid var(--line)", background: "var(--bg)" }}>
                      <span className="px-[10px] py-[8px] text-[11px] mono flex items-center flex-shrink-0" style={{ background: "var(--panel-2)", color: "var(--ink-3)", borderRight: "1px solid var(--line)" }}>
                        aicloser.app /
                      </span>
                      <input
                        type="text"
                        value={formSlug}
                        onChange={(e) => setFormSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
                        placeholder="my-store"
                        className="flex-1 px-[10px] py-[8px] text-[12.5px] outline-none bg-transparent"
                        style={{ color: "var(--ink)", border: "none" }}
                      />
                    </div>
                  </div>
                  {/* Status + AI Model row */}
                  <div className="grid grid-cols-2 gap-[10px]">
                    <div className="flex flex-col gap-[5px]">
                      <label className="label-mono">Статус</label>
                      <select
                        value={formStatus}
                        onChange={(e) => setFormStatus(e.target.value)}
                        className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none"
                        style={{ background: "var(--bg)", border: "1px solid var(--line)", color: "var(--ink)" }}
                      >
                        <option value="trial">Trial &middot; 14 дней</option>
                        <option value="active">Active</option>
                      </select>
                    </div>
                    <div className="flex flex-col gap-[5px]">
                      <label className="label-mono">AI модель</label>
                      <select
                        value={formModel}
                        onChange={(e) => setFormModel(e.target.value)}
                        className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none"
                        style={{ background: "var(--bg)", border: "1px solid var(--line)", color: "var(--ink)" }}
                      >
                        <option value="gpt-4o-mini">GPT-4o Mini (по умолчанию)</option>
                        <option value="gpt-4o">GPT-4o</option>
                      </select>
                    </div>
                  </div>
                </div>
              </div>

              {/* Admin section */}
              <div className="px-[18px] py-[12px]" style={{ borderBottom: "1px solid var(--line)" }}>
                <div className="text-[10px] uppercase tracking-[0.16em] mb-[10px] mono" style={{ color: "var(--ink-3)" }}>Первый администратор</div>
                <div className="grid grid-cols-2 gap-[10px]">
                  <div className="flex flex-col gap-[5px]">
                    <label className="label-mono">Email</label>
                    <input
                      type="email"
                      value={formEmail}
                      onChange={(e) => setFormEmail(e.target.value)}
                      placeholder="admin@store.com"
                      className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none transition-shadow"
                      style={{ background: "var(--bg)", border: "1px solid var(--line)", color: "var(--ink)" }}
                      onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
                      onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
                    />
                  </div>
                  <div className="flex flex-col gap-[5px]">
                    <label className="label-mono">Пароль &middot; мин. 8</label>
                    <input
                      type="password"
                      value={formPassword}
                      onChange={(e) => setFormPassword(e.target.value)}
                      placeholder="••••••••"
                      className="rounded-[6px] px-[10px] py-[8px] text-[12.5px] outline-none transition-shadow"
                      style={{ background: "var(--bg)", border: "1px solid var(--line)", color: "var(--ink)" }}
                      onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
                      onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
                    />
                  </div>
                </div>
                <label className="flex items-center gap-[8px] mt-[10px] text-[12px] cursor-pointer" style={{ color: "var(--ink-2)" }}>
                  <input type="checkbox" checked={formInvite} onChange={(e) => setFormInvite(e.target.checked)} style={{ accentColor: "var(--accent)" }} />
                  Отправить приглашение на email
                </label>
              </div>

              {/* Modal footer */}
              <div className="flex justify-end gap-[8px] px-[18px] py-[14px]">
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-medium transition-colors"
                  style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink)" }}
                >
                  Отмена
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-[11px] py-[6px] rounded-[6px] text-[12px] font-semibold text-white transition-all disabled:opacity-50"
                  style={{ background: "var(--accent)", border: "1px solid var(--accent)" }}
                >
                  {creating ? "Создание..." : "Создать тенант"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Toolbar: search + segmented filter + page size */}
      <div className="flex flex-wrap items-center gap-[8px]">
        {/* Search */}
        <div className="relative min-w-[280px]">
          <span className="absolute left-[10px] top-1/2 -translate-y-1/2 text-[12px]" style={{ color: "var(--ink-3)" }}>&#8981;</span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по названию или slug..."
            className="w-full rounded-[7px] pl-[30px] pr-[10px] py-[7px] text-[12px] outline-none transition-shadow"
            style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--ink)" }}
            onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
            onBlur={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.boxShadow = "none"; }}
          />
        </div>

        {/* Segmented control */}
        <div
          className="inline-flex p-[2px] rounded-[7px]"
          style={{ background: "var(--bg-2)", border: "1px solid var(--line)" }}
        >
          {([
            { key: "all" as StatusFilter, label: `Все \u00b7 ${total}` },
            { key: "active" as StatusFilter, label: `Active \u00b7 ${statusCounts.active}` },
            { key: "trial" as StatusFilter, label: `Trial \u00b7 ${statusCounts.trial}` },
            { key: "suspended" as StatusFilter, label: `Suspended \u00b7 ${statusCounts.suspended}` },
          ]).map((seg) => (
            <button
              key={seg.key}
              onClick={() => { setStatusFilter(seg.key); setPage(0); }}
              className="px-[10px] py-[4px] text-[11px] rounded-[5px] transition-all border-0 cursor-pointer"
              style={{
                background: statusFilter === seg.key ? "var(--panel)" : "transparent",
                color: statusFilter === seg.key ? "var(--ink)" : "var(--ink-3)",
                boxShadow: statusFilter === seg.key ? "0 1px 2px rgba(0,0,0,0.08)" : "none",
              }}
            >
              {seg.label}
            </button>
          ))}
        </div>

        {/* Bulk actions */}
        {selected.size > 0 && (
          <div className="flex items-center gap-[8px] ml-2">
            <span className="text-[11.5px] font-medium" style={{ color: "var(--accent)" }}>{selected.size} выбрано</span>
            <button onClick={() => handleBulkStatus("active")} disabled={bulkLoading} className="px-[9px] py-[4px] rounded-[5px] text-[11px] font-medium disabled:opacity-50 transition-colors" style={{ background: "var(--good-soft)", color: "var(--good)" }}>Активировать</button>
            <button onClick={() => handleBulkStatus("suspended")} disabled={bulkLoading} className="px-[9px] py-[4px] rounded-[5px] text-[11px] font-medium disabled:opacity-50 transition-colors" style={{ background: "var(--bad-soft)", color: "var(--bad)" }}>Деактивировать</button>
            <button onClick={() => setSelected(new Set())} className="text-[11px] transition-colors" style={{ color: "var(--ink-3)" }}>Сбросить</button>
          </div>
        )}

        {/* Page size */}
        <div className="ml-auto flex items-center gap-[6px]">
          <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>Строк:</span>
          <select
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }}
            className="rounded-[5px] px-[8px] py-[4px] text-[11px] outline-none"
            style={{ background: "var(--bg)", border: "1px solid var(--line)", color: "var(--ink)" }}
          >
            {PAGE_SIZES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-[9px] overflow-hidden" style={{ background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}>
        <div className="overflow-x-auto">
          <table className="w-full" style={{ borderCollapse: "collapse", fontSize: "12.5px" }}>
            <thead>
              <tr>
                <th className="w-[32px] py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>
                  <input type="checkbox" checked={filteredTenants.length > 0 && selected.size === filteredTenants.length} onChange={toggleSelectAll} style={{ accentColor: "var(--accent)" }} />
                </th>
                <th className="label-mono text-left py-[9px] px-[12px] cursor-pointer select-none" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }} onClick={() => handleSort("name")}>
                  Название &middot; Slug <SortArrow field="name" sortBy={sortBy} sortOrder={sortOrder} />
                </th>
                <th className="label-mono text-left py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>Статус</th>
                <th className="label-mono text-right py-[9px] px-[12px] cursor-pointer select-none" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }} onClick={() => handleSort("products_count")}>
                  Товары <SortArrow field="products_count" sortBy={sortBy} sortOrder={sortOrder} />
                </th>
                <th className="label-mono text-right py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>Диалоги</th>
                <th className="label-mono text-center py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>Заказы</th>
                <th className="label-mono text-center py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}>Польз.</th>
                <th className="label-mono text-left py-[9px] px-[12px] cursor-pointer select-none" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }} onClick={() => handleSort("created_at")}>
                  Создан <SortArrow field="created_at" sortBy={sortBy} sortOrder={sortOrder} />
                </th>
                <th className="py-[9px] px-[12px]" style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }}></th>
              </tr>
            </thead>
            <tbody>
              {filteredTenants.map((t) => (
                <tr
                  key={t.id}
                  className="transition-colors"
                  style={{ background: selected.has(t.id) ? "var(--accent-soft)" : "transparent" }}
                  onMouseEnter={(e) => { if (!selected.has(t.id)) e.currentTarget.style.background = "var(--bg-2)"; }}
                  onMouseLeave={(e) => { if (!selected.has(t.id)) e.currentTarget.style.background = "transparent"; }}
                >
                  <td className="py-[10px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                    <input type="checkbox" checked={selected.has(t.id)} onChange={() => toggleSelect(t.id)} style={{ accentColor: "var(--accent)" }} />
                  </td>
                  <td className="py-[10px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                    <div className="flex items-center gap-[10px]">
                      <div className="w-[28px] h-[28px] rounded-[6px] grid place-items-center text-[11px] font-semibold flex-shrink-0" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
                        {t.name.slice(0, 2).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <div className="text-[12.5px] truncate" style={{ color: "var(--ink)" }}>{t.name}</div>
                        <div className="mono text-[10.5px] mt-[1px]" style={{ color: "var(--ink-3)" }}>{t.slug}</div>
                      </div>
                    </div>
                  </td>
                  <td className="py-[10px] px-[12px]" style={{ borderBottom: "1px solid var(--hair)" }}>
                    <Chip tone={statusTone[t.status] || "accent"}>{statusLabels[t.status] || t.status}</Chip>
                  </td>
                  <td className="py-[10px] px-[12px] text-right tnum" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink)" }}>{t.products_count}</td>
                  <td className="py-[10px] px-[12px] text-right tnum" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink)" }}>{t.conversations_count}</td>
                  <td className="py-[10px] px-[12px] text-center tnum" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink)" }}>{t.orders_count ?? 0}</td>
                  <td className="py-[10px] px-[12px] text-center tnum" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink)" }}>{t.users_count}</td>
                  <td className="py-[10px] px-[12px] mono text-[11px] tnum" style={{ borderBottom: "1px solid var(--hair)", color: "var(--ink)" }}>{fmtDate(t.created_at)}</td>
                  <td className="py-[10px] px-[12px] text-right" style={{ borderBottom: "1px solid var(--hair)" }}>
                    <a href={`/platform-tenants/${t.id}`} className="text-[11.5px] transition-colors whitespace-nowrap" style={{ color: "var(--accent)" }}>
                      Открыть &#8594;
                    </a>
                  </td>
                </tr>
              ))}
              {filteredTenants.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-[12px] py-[40px] text-center text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                    {debouncedSearch ? "Ничего не найдено" : statusFilter !== "all" ? `Нет тенантов со статусом "${statusFilter}"` : "Нет тенантов. Создайте первый."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pager */}
        {total > 0 && (
          <div className="flex items-center justify-between px-[14px] py-[10px]" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)", fontSize: "11.5px" }}>
            <span style={{ color: "var(--ink-3)" }}>Показано {showFrom}&#8211;{showTo} из {total}</span>
            <div className="flex items-center gap-[4px]">
              <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className="w-[28px] h-[26px] rounded-[5px] grid place-items-center text-[11px] transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink-2)" }}>&lsaquo;</button>
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                let pageNum: number;
                if (totalPages <= 7) { pageNum = i; }
                else if (page < 3) { pageNum = i; }
                else if (page > totalPages - 4) { pageNum = totalPages - 7 + i; }
                else { pageNum = page - 3 + i; }
                return (
                  <button
                    key={pageNum}
                    onClick={() => setPage(pageNum)}
                    className="w-[28px] h-[26px] rounded-[5px] grid place-items-center text-[11px] transition-colors"
                    style={{
                      background: pageNum === page ? "var(--accent-soft)" : "transparent",
                      color: pageNum === page ? "var(--accent)" : "var(--ink-2)",
                      border: pageNum === page ? "1px solid var(--accent)" : "1px solid var(--line)",
                    }}
                  >
                    {pageNum + 1}
                  </button>
                );
              })}
              <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="w-[28px] h-[26px] rounded-[5px] grid place-items-center text-[11px] transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink-2)" }}>&rsaquo;</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
