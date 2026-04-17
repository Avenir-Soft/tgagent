"use client";

import { useEffect, useState, useMemo, useRef } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page-header";
import { TableSkeleton } from "@/components/ui/page-skeleton";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { formatPrice } from "@/lib/utils";

interface DeliveryRule {
  id: string;
  city: string | null;
  zone: string | null;
  delivery_type: string;
  price: string;
  eta_min_days: number;
  eta_max_days: number;
  cod_available: boolean;
  is_active: boolean;
}

const typeLabels: Record<string, string> = {
  courier: "Курьер",
  post: "Почта",
  pickup: "Самовывоз",
};

const typeIcons: Record<string, string> = {
  courier: "C",
  post: "P",
  pickup: "S",
};

const typeColors: Record<string, string> = {
  courier: "bg-indigo-100 text-indigo-600",
  post: "bg-amber-100 text-amber-600",
  pickup: "bg-emerald-100 text-emerald-600",
};

const allTypes = ["all", "courier", "post", "pickup"] as const;
const typePillLabels: Record<string, string> = {
  all: "Все",
  courier: "Курьер",
  post: "Почта",
  pickup: "Самовывоз",
};

function fmt(val: string | number): string {
  return formatPrice(val);
}

export default function DeliveryPage() {
  const { toast } = useToast();

  const [rules, setRules] = useState<DeliveryRule[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({
    city: "", zone: "", delivery_type: "courier", price: "",
    eta_min_days: 1, eta_max_days: 3, cod_available: false,
  });

  // Filters
  const [filterCity, setFilterCity] = useState<string>("all");
  const [filterType, setFilterType] = useState<string>("all");

  // Delete confirm
  const [deleteTarget, setDeleteTarget] = useState<DeliveryRule | null>(null);
  const [deleting, setDeleting] = useState(false);

  // CSV import
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = () => api.get<DeliveryRule[]>("/delivery-rules").then((data) => { setRules(data); setLoading(false); }).catch(() => { setLoading(false); });
  useEffect(() => { load(); }, []);

  // Unique cities for dropdown
  const uniqueCities = useMemo(() => {
    const cities = new Set<string>();
    rules.forEach((r) => {
      if (r.city) cities.add(r.city);
    });
    return Array.from(cities).sort((a, b) => a.localeCompare(b, "ru"));
  }, [rules]);

  // Filtered rules
  const filteredRules = useMemo(() => {
    return rules.filter((r) => {
      if (filterCity !== "all") {
        if (filterCity === "__null__") {
          if (r.city !== null && r.city !== "") return false;
        } else {
          if (r.city !== filterCity) return false;
        }
      }
      if (filterType !== "all" && r.delivery_type !== filterType) return false;
      return true;
    });
  }, [rules, filterCity, filterType]);

  // City name mapping: English DB names → Russian display names
  const cityDisplayName: Record<string, string> = {
    "Tashkent": "Ташкент", "Samarkand": "Самарканд", "Bukhara": "Бухара",
    "Fergana": "Фергана", "Namangan": "Наманган", "Andijan": "Андижан",
    "Nukus": "Нукус", "Karshi": "Карши", "Navoi": "Навои",
    "Jizzakh": "Джизак", "Urgench": "Ургенч", "Termez": "Термез",
    "Gulistan": "Гулистан", "Kokand": "Коканд", "Margilan": "Маргилан",
    "Chirchik": "Чирчик", "Almalyk": "Алмалык", "Angren": "Ангрен",
  };
  const getCityLabel = (city: string) => cityDisplayName[city] || city;

  // ETA display
  const formatEta = (min: number, max: number) => {
    if (min === 0 && max === 0) return "В тот же день";
    if (min === max) return `${min} дн.`;
    return `${min}-${max} дн.`;
  };

  // Group filtered rules by city
  const groupedRules = useMemo(() => {
    const groups: { city: string; displayName: string; rules: DeliveryRule[] }[] = [];
    const cityMap = new Map<string, DeliveryRule[]>();

    filteredRules.forEach((r) => {
      const key = r.city || "__null__";
      if (!cityMap.has(key)) cityMap.set(key, []);
      cityMap.get(key)!.push(r);
    });

    // "Все города" (null) first
    if (cityMap.has("__null__")) {
      groups.push({ city: "__null__", displayName: "Все города (без привязки к городу — применяются везде)", rules: cityMap.get("__null__")! });
      cityMap.delete("__null__");
    }

    // Remaining cities sorted alphabetically (by Russian display name)
    const sortedKeys = Array.from(cityMap.keys()).sort((a, b) => getCityLabel(a).localeCompare(getCityLabel(b), "ru"));
    sortedKeys.forEach((key) => {
      groups.push({ city: key, displayName: getCityLabel(key), rules: cityMap.get(key)! });
    });

    return groups;
  }, [filteredRules]);

  const resetForm = () => {
    setForm({ city: "", zone: "", delivery_type: "courier", price: "", eta_min_days: 1, eta_max_days: 3, cod_available: false });
    setEditingId(null);
    setShowForm(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const price = parseFloat(form.price);
    if (isNaN(price) || price < 0) {
      toast("Цена должна быть числом >= 0", "error");
      return;
    }
    if (form.eta_min_days > form.eta_max_days) {
      toast("Минимальный срок не может превышать максимальный", "error");
      return;
    }
    const data = {
      ...form,
      city: form.city || null,
      zone: form.zone || null,
      price,
    };
    try {
      if (editingId) {
        await api.patch(`/delivery-rules/${editingId}`, data);
        toast("Правило обновлено", "success");
      } else {
        await api.post("/delivery-rules", data);
        toast("Правило создано", "success");
      }
      resetForm();
      load();
    } catch (err: any) {
      toast(err.message || "Ошибка сохранения", "error");
    }
  };

  const startEdit = (r: DeliveryRule) => {
    setForm({
      city: r.city || "",
      zone: r.zone || "",
      delivery_type: r.delivery_type,
      price: String(Number(r.price)),
      eta_min_days: r.eta_min_days,
      eta_max_days: r.eta_max_days,
      cod_available: r.cod_available,
    });
    setEditingId(r.id);
    setShowForm(true);
  };

  const toggleActive = async (r: DeliveryRule) => {
    try {
      await api.patch(`/delivery-rules/${r.id}`, { is_active: !r.is_active });
      load();
    } catch (err: any) {
      toast(err.message || "Ошибка обновления", "error");
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/delivery-rules/${deleteTarget.id}`);
      toast("Правило удалено", "success");
      load();
    } catch (err: any) {
      toast(err.message || "Ошибка удаления", "error");
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  const handleCsvImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const token = localStorage.getItem("token");
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8001"}/delivery-rules/import-csv`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || res.statusText);
      }
      const result = await res.json();
      toast(`Создано ${result.created ?? result.count ?? 0} правил`, "success");
      load();
    } catch (err: any) {
      toast(err.message || "Ошибка импорта CSV", "error");
    } finally {
      setImporting(false);
      // Reset file input so same file can be re-selected
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div>
      {/* Delete confirm dialog */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Удалить правило?"
        message={`Правило доставки для "${deleteTarget?.city || "Все города"}" (${typeLabels[deleteTarget?.delivery_type || ""] || deleteTarget?.delivery_type}) будет удалено.`}
        confirmText="Удалить"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        loading={deleting}
      />

      {/* Hidden CSV file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv"
        className="hidden"
        onChange={handleCsvImport}
      />

      <PageHeader
        title="Доставка"
        badge={rules.length}
        action={{ label: showForm ? "Отмена" : "+ Добавить", onClick: () => { resetForm(); setShowForm(!showForm); } }}
      >
        <button
          type="button"
          onClick={() => {
            const csv = "city,zone,delivery_type,price,eta_min_days,eta_max_days,cod_available\nТашкент,Центр,standard,25000,1,2,true\nТашкент,Окраина,express,50000,0,1,false";
            const blob = new Blob([csv], { type: "text/csv" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a"); a.href = url; a.download = "delivery_template.csv"; a.click();
            URL.revokeObjectURL(url);
          }}
          className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-3 py-2 text-sm font-medium transition-colors flex items-center gap-1.5"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
          </svg>
          Шаблон
        </button>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={importing}
          className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
        >
          {importing ? (
            <>
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Импорт...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
              </svg>
              Импорт CSV
            </>
          )}
        </button>
        <div className="relative group">
          <svg className="w-4 h-4 text-slate-400 cursor-help" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
          </svg>
          <div className="absolute right-0 top-6 hidden group-hover:block bg-slate-800 text-white text-xs rounded-lg px-3 py-2 w-56 z-10 shadow-lg">
            CSV: city, zone, delivery_type, price, eta_min_days, eta_max_days, cod_available
          </div>
        </div>
      </PageHeader>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <select
          value={filterCity}
          onChange={(e) => setFilterCity(e.target.value)}
          title="Фильтр по городу"
          className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
        >
          <option value="all">Все города</option>
          <option value="__null__">Без города</option>
          {uniqueCities.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>

        <div className="flex items-center gap-1">
          {allTypes.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setFilterType(t)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filterType === t
                  ? "bg-indigo-600 text-white"
                  : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {typePillLabels[t]}
            </button>
          ))}
        </div>

        {(filterCity !== "all" || filterType !== "all") && (
          <button
            type="button"
            onClick={() => { setFilterCity("all"); setFilterType("all"); }}
            className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
          >
            Сбросить
          </button>
        )}

        <span className="text-xs text-slate-400 ml-auto">
          Показано: {filteredRules.length} из {rules.length}
        </span>
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="card p-5 mb-4">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">
            {editingId ? "Редактировать правило" : "Новое правило доставки"}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-500 mb-1">Город</label>
              <input
                placeholder="Например: Tashkent"
                value={form.city}
                onChange={(e) => setForm({ ...form, city: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                maxLength={100}
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Зона / Район</label>
              <input
                placeholder="Опционально"
                value={form.zone}
                onChange={(e) => setForm({ ...form, zone: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Тип доставки</label>
              <select
                value={form.delivery_type}
                onChange={(e) => setForm({ ...form, delivery_type: e.target.value })}
                title="Тип доставки"
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              >
                <option value="courier">Курьер</option>
                <option value="post">Почта</option>
                <option value="pickup">Самовывоз</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Цена (сум)</label>
              <input
                placeholder="35000"
                type="number"
                value={form.price}
                onChange={(e) => setForm({ ...form, price: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                required
                min={0}
                step="any"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Мин. дней</label>
              <input
                type="number"
                title="Минимальное количество дней"
                placeholder="1"
                value={form.eta_min_days}
                onChange={(e) => setForm({ ...form, eta_min_days: +e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                required
                min={0}
                max={90}
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Макс. дней</label>
              <input
                type="number"
                title="Максимальное количество дней"
                placeholder="3"
                value={form.eta_max_days}
                onChange={(e) => setForm({ ...form, eta_max_days: +e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                required
                min={0}
                max={90}
              />
            </div>
          </div>
          <div className="flex items-center justify-between mt-4">
            <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
              <input
                type="checkbox"
                checked={form.cod_available}
                onChange={(e) => setForm({ ...form, cod_available: e.target.checked })}
                className="rounded"
              />
              Наложенный платёж (оплата при получении)
            </label>
            <div className="flex items-center gap-2">
              {editingId && (
                <button
                  type="button"
                  onClick={resetForm}
                  className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  Отмена
                </button>
              )}
              <button type="submit" className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-5 py-2 text-sm font-medium transition-colors">
                {editingId ? "Сохранить" : "Создать"}
              </button>
            </div>
          </div>
        </form>
      )}

      {/* Rules grouped by city */}
      {loading ? (
        <TableSkeleton rows={6} cols={5} />
      ) : (
      <div className="space-y-6">
        {filteredRules.length === 0 ? (
          <div className="card p-8 text-center text-slate-400">
            {rules.length === 0
              ? 'Нет правил доставки. Нажмите "+ Добавить" чтобы создать.'
              : "Нет правил, соответствующих фильтрам."}
          </div>
        ) : (
          groupedRules.map((group) => (
            <div key={group.city}>
              {/* City group header */}
              <div className="flex items-center gap-2 mb-2">
                <h3 className="text-sm font-semibold text-slate-700">{group.displayName}</h3>
                <span className="text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
                  {group.rules.length}
                </span>
              </div>

              <div className="space-y-2">
                {group.rules.map((r) => (
                  <div
                    key={r.id}
                    className={`card px-5 py-4 flex items-center gap-4 ${!r.is_active ? "opacity-50" : ""}`}
                  >
                    {/* Type icon */}
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold shrink-0 ${typeColors[r.delivery_type] || "bg-slate-100"}`}>
                      {typeIcons[r.delivery_type] || "?"}
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm text-slate-900">{r.city ? getCityLabel(r.city) : "Все города"}</span>
                        {r.zone && <span className="text-xs text-slate-400">({r.zone})</span>}
                        <span className={`px-2 py-0.5 rounded-lg text-xs ${typeColors[r.delivery_type] || "bg-slate-100"}`}>
                          {typeLabels[r.delivery_type] || r.delivery_type}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400 mt-0.5">
                        {formatEta(r.eta_min_days, r.eta_max_days)}
                        {r.cod_available && <span className="ml-2 text-emerald-600">Наложенный платёж</span>}
                      </div>
                    </div>

                    {/* Price */}
                    <div className="text-right shrink-0">
                      <div className="font-bold text-sm text-slate-900">
                        {Number(r.price) === 0 ? "Бесплатно" : `${fmt(r.price)} сум`}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        title="Редактировать"
                        onClick={() => startEdit(r)}
                        className="text-slate-400 hover:text-indigo-600 text-sm transition-colors"
                      >
                        &#9998;
                      </button>
                      <button
                        type="button"
                        title="Удалить"
                        onClick={() => setDeleteTarget(r)}
                        className="text-slate-400 hover:text-rose-600 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                        </svg>
                      </button>
                      <button
                        type="button"
                        title={r.is_active ? "Деактивировать" : "Активировать"}
                        onClick={() => toggleActive(r)}
                        className={`w-8 h-4 rounded-full transition-colors ${r.is_active ? "bg-indigo-600" : "bg-slate-300"}`}
                      >
                        <div className={`w-3 h-3 bg-white rounded-full shadow-sm transform transition-transform ${r.is_active ? "translate-x-4" : "translate-x-0.5"}`} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
      )}
    </div>
  );
}
