"use client";

import { useEffect, useState, useMemo } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import Link from "next/link";
import { plural } from "@/lib/utils";

interface Variant {
  id: string;
  title: string;
  color: string | null;
  storage: string | null;
  ram: string | null;
  size: string | null;
  price: string;
  currency: string;
  is_active: boolean;
}

interface Product {
  id: string;
  name: string;
  slug: string;
  brand: string | null;
  model: string | null;
  description: string | null;
  category_id: string | null;
  category_name: string | null;
  is_active: boolean;
  variants: Variant[];
  total_stock: number;
  min_price: string | null;
  max_price: string | null;
  image_url: string | null;
}

interface Category {
  id: string;
  name: string;
}

const PAGE_SIZE = 30;

function formatPrice(val: string | null): string {
  if (!val) return "\u2014";
  return Number(val).toLocaleString("ru-RU");
}

function priceRange(p: Product): string {
  if (!p.min_price) return "Нет вариантов";
  if (p.min_price === p.max_price) return `${formatPrice(p.min_price)} сум`;
  return `${formatPrice(p.min_price)} — ${formatPrice(p.max_price)} сум`;
}

function stockBadge(stock: number) {
  if (stock <= 0)
    return <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-rose-50 text-rose-600">Нет в наличии</span>;
  if (stock <= 3)
    return <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-amber-50 text-amber-600">{stock} шт</span>;
  return <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-50 text-emerald-600">{stock} шт</span>;
}

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", brand: "", model: "", description: "", category_id: "" });
  const [creating, setCreating] = useState(false);
  const [sortBy, setSortBy] = useState<"name" | "price" | "stock">("name");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const { toast } = useToast();

  const load = () => {
    api.get<Product[]>("/products").then(setProducts).catch(console.error);
    api.get<Category[]>("/categories").then(setCategories).catch(console.error);
  };
  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  const categoryNames = [...new Set(products.map((p) => p.category_name).filter(Boolean))] as string[];

  const filtered = useMemo(() => {
    const base = products.filter((p) => {
      const matchSearch = !search || p.name.toLowerCase().includes(search.toLowerCase()) || (p.brand || "").toLowerCase().includes(search.toLowerCase());
      const matchCat = !categoryFilter || p.category_name === categoryFilter;
      return matchSearch && matchCat;
    });
    const arr = [...base];
    if (sortBy === "price") arr.sort((a, b) => Number(a.min_price || 0) - Number(b.min_price || 0));
    else if (sortBy === "stock") arr.sort((a, b) => a.total_stock - b.total_stock);
    else arr.sort((a, b) => a.name.localeCompare(b.name, "ru"));
    return arr;
  }, [products, search, categoryFilter, sortBy]);

  const paginated = useMemo(() => filtered.slice(0, visibleCount), [filtered, visibleCount]);
  const hasMore = visibleCount < filtered.length;

  useEffect(() => { setVisibleCount(PAGE_SIZE); }, [search, categoryFilter, sortBy]);

  const toggleActive = async (p: Product) => {
    try {
      await api.patch(`/products/${p.id}`, { is_active: !p.is_active });
      setProducts((prev) => prev.map((x) => x.id === p.id ? { ...x, is_active: !x.is_active } : x));
      toast(p.is_active ? "Товар скрыт" : "Товар активирован", "success");
    } catch {
      toast("Ошибка при изменении статуса", "error");
    }
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === paginated.length) setSelected(new Set());
    else setSelected(new Set(paginated.map((p) => p.id)));
  };

  const bulkSetActive = async (active: boolean) => {
    if (selected.size === 0) return;
    try {
      await Promise.all([...selected].map((id) => api.patch(`/products/${id}`, { is_active: active })));
      setProducts((prev) => prev.map((p) => selected.has(p.id) ? { ...p, is_active: active } : p));
      toast(`${selected.size} ${plural(selected.size, "товар", "товара", "товаров")} ${active ? "активировано" : "скрыто"}`, "success");
      setSelected(new Set());
    } catch {
      toast("Ошибка массового обновления", "error");
    }
  };

  const exportCSV = () => {
    const header = "Название;Бренд;Модель;Категория;Мин. цена;Макс. цена;Остаток;Статус;Вариантов\n";
    const rows = filtered.map((p) =>
      `${p.name};${p.brand || ""};${p.model || ""};${p.category_name || ""};${p.min_price || ""};${p.max_price || ""};${p.total_stock};${p.is_active ? "Активен" : "Скрыт"};${p.variants.length}`
    ).join("\n");
    const blob = new Blob(["\uFEFF" + header + rows], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `products_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast("CSV скачан", "success");
  };

  const createProduct = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setCreating(true);
    try {
      await api.post("/products", {
        name: form.name.trim(),
        brand: form.brand.trim() || null,
        model: form.model.trim() || null,
        description: form.description.trim() || null,
        category_id: form.category_id || null,
      });
      setShowCreate(false);
      setForm({ name: "", brand: "", model: "", description: "", category_id: "" });
      toast("Товар создан", "success");
      load();
    } catch {
      toast("Ошибка при создании товара", "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Товары ({products.length})</h1>
          <p className="text-sm text-slate-400 mt-0.5">Управление каталогом товаров</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={exportCSV} className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 rounded-lg px-3 py-2 text-sm font-medium transition-colors">
            Экспорт CSV
          </button>
          <button
            type="button"
            onClick={() => setShowCreate(!showCreate)}
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            + Добавить
          </button>
        </div>
      </div>

      {/* Create form */}
      {showCreate && (
        <form onSubmit={createProduct} className="card p-5 mb-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Новый товар</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-500 mb-1">Название *</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                required minLength={2} maxLength={200} placeholder="iPhone 16 Pro"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Категория</label>
              <select value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all">
                <option value="">Без категории</option>
                {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Бренд</label>
              <input type="text" value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all" placeholder="Apple" maxLength={100} />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Модель</label>
              <input type="text" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all" placeholder="A3104" maxLength={100} />
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Описание</label>
            <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm h-16 resize-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all" placeholder="Краткое описание товара" maxLength={1000} />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowCreate(false)} className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium transition-colors">Отмена</button>
            <button type="submit" disabled={creating} className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50">{creating ? "..." : "Создать"}</button>
          </div>
        </form>
      )}

      {/* Filters */}
      <div className="flex flex-col md:flex-row gap-3 mb-3">
        <input type="text" placeholder="Поиск по названию или бренду..." value={search} onChange={(e) => setSearch(e.target.value)}
          className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all" />
        <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}
          className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all" aria-label="Фильтр по категории">
          <option value="">Все категории</option>
          {categoryNames.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {/* Sort + Bulk actions */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span>Сортировка:</span>
          {([["name", "по названию"], ["price", "по цене"], ["stock", "по наличию"]] as const).map(([key, label]) => (
            <button key={key} type="button" onClick={() => setSortBy(key)}
              className={`px-2 py-1 rounded transition-colors ${sortBy === key ? "bg-indigo-100 text-indigo-700 font-medium" : "hover:bg-slate-100"}`}>
              {label}
            </button>
          ))}
        </div>
        {selected.size > 0 && (
          <div className="flex items-center gap-2 bg-indigo-50 rounded-xl px-3 py-2">
            <span className="text-xs text-indigo-700 font-medium">{selected.size} выбрано</span>
            <button type="button" onClick={() => bulkSetActive(true)} className="px-2 py-1 rounded-md text-[10px] font-medium bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors">Активировать</button>
            <button type="button" onClick={() => bulkSetActive(false)} className="px-2 py-1 rounded-md text-[10px] font-medium bg-rose-50 text-rose-700 hover:bg-rose-100 transition-colors">Скрыть</button>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead>
            <tr className="border-b border-slate-100">
              <th className="pl-4 py-3 w-8">
                <input type="checkbox" checked={selected.size === paginated.length && paginated.length > 0} onChange={toggleSelectAll} className="rounded" />
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Товар</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Категория</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Цена</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Наличие</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Варианты</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Статус</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {paginated.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-400">Нет товаров</td></tr>
            ) : (
              paginated.map((p) => (
                <tr key={p.id} className={`hover:bg-slate-50/50 transition-colors ${!p.is_active ? "opacity-60" : ""} ${selected.has(p.id) ? "bg-indigo-50/50" : ""}`}>
                  <td className="pl-4 py-3">
                    <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggleSelect(p.id)} className="rounded" />
                  </td>
                  <td className="px-3 py-3">
                    <Link href={`/products/${p.id}`} className="flex items-center gap-3 group">
                      {/* Thumbnail */}
                      <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center shrink-0 overflow-hidden">
                        {p.image_url ? (
                          <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" />
                        ) : (
                          <svg className="w-5 h-5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                            <path d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
                          </svg>
                        )}
                      </div>
                      <div>
                        <div className="font-medium text-indigo-600 group-hover:text-indigo-700">{p.name}</div>
                        {p.brand && <div className="text-xs text-slate-400">{p.brand} {p.model || ""}</div>}
                      </div>
                    </Link>
                  </td>
                  <td className="px-3 py-3">
                    <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-indigo-50 text-indigo-600">{p.category_name || "\u2014"}</span>
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-slate-700">{priceRange(p)}</td>
                  <td className="px-3 py-3">{stockBadge(p.total_stock)}</td>
                  <td className="px-3 py-3 text-slate-500">
                    {p.variants.filter((v) => v.is_active).length}
                    {p.variants.some((v) => !v.is_active) && <span className="text-slate-300"> / {p.variants.length}</span>}
                  </td>
                  <td className="px-3 py-3">
                    <button type="button" onClick={() => toggleActive(p)}
                      className={`px-2 py-0.5 rounded-md text-xs font-medium cursor-pointer transition-colors ${p.is_active ? "bg-emerald-50 text-emerald-600 hover:bg-emerald-100" : "bg-rose-50 text-rose-600 hover:bg-rose-100"}`}>
                      {p.is_active ? "Активен" : "Скрыт"}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {hasMore && (
        <div className="text-center mt-4">
          <button type="button" onClick={() => setVisibleCount((p) => p + PAGE_SIZE)}
            className="bg-white border border-slate-200 hover:bg-slate-50 text-indigo-600 rounded-lg px-6 py-2 text-sm font-medium transition-colors shadow-sm">
            Загрузить ещё ({filtered.length - visibleCount} осталось)
          </button>
        </div>
      )}

      {filtered.length > 0 && (
        <div className="text-xs text-slate-400 mt-2 text-right">
          Показано {Math.min(visibleCount, filtered.length)} из {products.length}
        </div>
      )}
    </div>
  );
}
