"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { TableSkeleton } from "@/components/ui/page-skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import Link from "next/link";
import { plural, formatPrice } from "@/lib/utils";
import SmartProductCreator from "@/components/smart-product-creator";

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

function fmtPrice(val: string | null): string {
  return formatPrice(val);
}

function priceRange(p: Product): string {
  if (!p.min_price) return "Нет вариантов";
  if (p.min_price === p.max_price) return `${fmtPrice(p.min_price)} сум`;
  return `${fmtPrice(p.min_price)} — ${fmtPrice(p.max_price)} сум`;
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
  const [showSmartCreate, setShowSmartCreate] = useState(false);
  const [wizardStep, setWizardStep] = useState(1);
  const [form, setForm] = useState({ name: "", brand: "", model: "", description: "", category_id: "" });
  const [wizardVariants, setWizardVariants] = useState<{ title: string; color: string; storage: string; ram: string; price: string }[]>([]);
  const [variantDraft, setVariantDraft] = useState({ title: "", color: "", storage: "", ram: "", price: "" });
  const [creating, setCreating] = useState(false);
  const [sortBy, setSortBy] = useState<"name" | "price" | "stock">("name");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

  const load = useCallback(() => {
    api.get<Product[]>("/products?limit=500").then((data) => { setProducts(data); setLoading(false); }).catch(() => { toast("Не удалось загрузить товары", "error"); setLoading(false); });
    api.get<Category[]>("/categories").then(setCategories).catch(() => toast("Не удалось загрузить категории", "error"));
  }, []);
  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

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
      const ids = [...selected];
      const BATCH = 5;
      for (let i = 0; i < ids.length; i += BATCH) {
        await Promise.all(ids.slice(i, i + BATCH).map((id) => api.patch(`/products/${id}`, { is_active: active })));
      }
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

  const openWizard = () => {
    setForm({ name: "", brand: "", model: "", description: "", category_id: "" });
    setWizardVariants([]);
    setVariantDraft({ title: "", color: "", storage: "", ram: "", price: "" });
    setWizardStep(1);
    setShowCreate(true);
  };

  const addVariantFromDraft = () => {
    if (!variantDraft.title.trim() || !variantDraft.price) return;
    setWizardVariants((prev) => [...prev, { ...variantDraft }]);
    setVariantDraft({ title: "", color: "", storage: "", ram: "", price: "" });
  };

  const removeWizardVariant = (i: number) => {
    setWizardVariants((prev) => prev.filter((_, idx) => idx !== i));
  };

  const createProduct = async () => {
    if (!form.name.trim()) return;
    setCreating(true);
    try {
      const variants = wizardVariants.length > 0 ? wizardVariants.map((v) => ({
        title: v.title.trim(),
        color: v.color.trim() || null,
        storage: v.storage.trim() || null,
        ram: v.ram.trim() || null,
        price: Number(v.price),
      })) : undefined;
      await api.post("/products", {
        name: form.name.trim(),
        brand: form.brand.trim() || null,
        model: form.model.trim() || null,
        description: form.description.trim() || null,
        category_id: form.category_id || null,
        variants,
      });
      setShowCreate(false);
      toast(`Товар создан${variants ? ` с ${variants.length} вариант${variants.length === 1 ? "ом" : "ами"}` : ""}`, "success");
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
            onClick={openWizard}
            className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 rounded-lg px-3 py-2 text-sm font-medium transition-colors"
          >
            + Вручную
          </button>
          <button
            type="button"
            onClick={() => setShowSmartCreate(true)}
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors flex items-center gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" /></svg>
            AI Создать
          </button>
        </div>
      </div>

      {/* Create wizard modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowCreate(false)}>
          <div
            onClick={(e) => e.stopPropagation()}
            className="bg-white rounded-2xl shadow-2xl w-full max-w-xl mx-4 overflow-hidden animate-scale-in max-h-[90vh] flex flex-col"
          >
            {/* Header with steps */}
            <div className="px-6 py-4 border-b border-slate-100">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-bold text-slate-900">Новый товар</h3>
                <button type="button" onClick={() => setShowCreate(false)} className="text-slate-400 hover:text-slate-600 transition-colors" aria-label="Закрыть">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
              <div className="flex items-center gap-2">
                {[
                  { n: 1, label: "Товар" },
                  { n: 2, label: "Варианты" },
                  { n: 3, label: "Обзор" },
                ].map((s, i) => (
                  <div key={s.n} className="flex items-center gap-2 flex-1">
                    <button
                      type="button"
                      onClick={() => { if (s.n === 1 || form.name.trim()) setWizardStep(s.n); }}
                      className={`w-7 h-7 rounded-full text-xs font-bold flex items-center justify-center shrink-0 transition-all ${
                        wizardStep === s.n ? "bg-indigo-600 text-white shadow-sm" :
                        wizardStep > s.n ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400"
                      }`}
                    >
                      {wizardStep > s.n ? "✓" : s.n}
                    </button>
                    <span className={`text-xs font-medium hidden sm:block ${wizardStep === s.n ? "text-slate-900" : "text-slate-400"}`}>{s.label}</span>
                    {i < 2 && <div className={`flex-1 h-px ${wizardStep > s.n ? "bg-emerald-200" : "bg-slate-200"}`} />}
                  </div>
                ))}
              </div>
            </div>

            {/* Body */}
            <div className="px-6 py-5 overflow-y-auto flex-1">
              {/* Step 1: Product info */}
              {wizardStep === 1 && (
                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-500 mb-1">Название *</label>
                    <input
                      type="text"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                      minLength={2} maxLength={200} placeholder="iPhone 17 Pro" autoFocus
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-500 mb-1">Категория</label>
                    <select value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}
                      className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all">
                      <option value="">Без категории</option>
                      {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-500 mb-1">Бренд</label>
                      <input type="text" value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all" placeholder="Apple" maxLength={100} />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-500 mb-1">Модель</label>
                      <input type="text" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all" placeholder="A3104" maxLength={100} />
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-500 mb-1">Описание</label>
                    <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2.5 text-sm h-20 resize-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all" placeholder="Краткое описание товара" maxLength={1000} />
                  </div>
                </div>
              )}

              {/* Step 2: Variants */}
              {wizardStep === 2 && (
                <div className="space-y-4">
                  <p className="text-sm text-slate-500">
                    Добавьте варианты товара — например, разные цвета, объёмы памяти или размеры. Можно пропустить и добавить позже.
                  </p>

                  {/* Added variants list */}
                  {wizardVariants.length > 0 && (
                    <div className="space-y-2">
                      {wizardVariants.map((v, i) => (
                        <div key={i} className="flex items-center gap-3 bg-slate-50 rounded-xl px-4 py-3 group">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-slate-900">{v.title}</p>
                            <div className="flex gap-1.5 mt-1 flex-wrap">
                              {v.color && <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600 text-[10px]">{v.color}</span>}
                              {v.storage && <span className="px-1.5 py-0.5 rounded bg-violet-50 text-violet-600 text-[10px]">{v.storage}</span>}
                              {v.ram && <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-600 text-[10px]">{v.ram}</span>}
                            </div>
                          </div>
                          <span className="text-sm font-medium text-slate-700 whitespace-nowrap">{formatPrice(v.price)} сум</span>
                          <button type="button" onClick={() => removeWizardVariant(i)}
                            className="w-6 h-6 rounded-full bg-white border border-slate-200 text-slate-400 hover:text-rose-500 hover:border-rose-200 flex items-center justify-center text-xs transition-colors opacity-0 group-hover:opacity-100">&times;</button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Add variant form */}
                  <div className="border border-dashed border-slate-200 rounded-xl p-4 space-y-3 bg-slate-50/50">
                    <p className="text-xs font-medium text-slate-600">Добавить вариант</p>
                    <div className="grid grid-cols-2 gap-2">
                      <input type="text" placeholder="Название *" value={variantDraft.title} onChange={(e) => setVariantDraft({ ...variantDraft, title: e.target.value })}
                        className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none col-span-2"
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addVariantFromDraft(); } }} />
                      <input type="text" placeholder="Цвет" value={variantDraft.color} onChange={(e) => setVariantDraft({ ...variantDraft, color: e.target.value })}
                        className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
                      <input type="text" placeholder="Память (256GB)" value={variantDraft.storage} onChange={(e) => setVariantDraft({ ...variantDraft, storage: e.target.value })}
                        className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
                      <input type="text" placeholder="RAM (8GB)" value={variantDraft.ram} onChange={(e) => setVariantDraft({ ...variantDraft, ram: e.target.value })}
                        className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
                      <input type="number" placeholder="Цена *" value={variantDraft.price} onChange={(e) => setVariantDraft({ ...variantDraft, price: e.target.value })}
                        className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" min={1} />
                    </div>
                    <button type="button" onClick={addVariantFromDraft} disabled={!variantDraft.title.trim() || !variantDraft.price}
                      className="w-full py-2 bg-white border border-slate-200 rounded-lg text-sm text-indigo-600 font-medium hover:bg-indigo-50 disabled:opacity-40 disabled:hover:bg-white transition-colors">
                      + Добавить вариант
                    </button>
                  </div>
                </div>
              )}

              {/* Step 3: Review */}
              {wizardStep === 3 && (
                <div className="space-y-4">
                  <div className="bg-gradient-to-br from-slate-50 to-indigo-50/30 rounded-xl p-5">
                    <h4 className="font-bold text-slate-900 text-lg">{form.name}</h4>
                    <div className="flex gap-2 mt-1 text-sm text-slate-500">
                      {form.brand && <span>{form.brand}</span>}
                      {form.model && <span className="text-slate-300">·</span>}
                      {form.model && <span>{form.model}</span>}
                      {form.category_id && <span className="text-slate-300">·</span>}
                      {form.category_id && <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600 text-xs">{categories.find((c) => c.id === form.category_id)?.name}</span>}
                    </div>
                    {form.description && <p className="text-sm text-slate-500 mt-2">{form.description}</p>}
                  </div>

                  {wizardVariants.length > 0 ? (
                    <div>
                      <p className="text-xs font-medium text-slate-500 mb-2">{wizardVariants.length} {plural(wizardVariants.length, "вариант", "варианта", "вариантов")}</p>
                      <div className="space-y-1.5">
                        {wizardVariants.map((v, i) => (
                          <div key={i} className="flex items-center justify-between bg-slate-50 rounded-lg px-4 py-2.5">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-slate-900">{v.title}</span>
                              <div className="flex gap-1">
                                {v.color && <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600 text-[10px]">{v.color}</span>}
                                {v.storage && <span className="px-1.5 py-0.5 rounded bg-violet-50 text-violet-600 text-[10px]">{v.storage}</span>}
                                {v.ram && <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-600 text-[10px]">{v.ram}</span>}
                              </div>
                            </div>
                            <span className="text-sm font-medium text-slate-700">{formatPrice(v.price)} сум</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-4 bg-amber-50/50 rounded-xl">
                      <p className="text-sm text-amber-600">Без вариантов — можно добавить позже на странице товара</p>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div>
                {wizardStep > 1 && (
                  <button type="button" onClick={() => setWizardStep((s) => s - 1)}
                    className="text-sm text-slate-500 hover:text-slate-700 font-medium transition-colors">
                    ← Назад
                  </button>
                )}
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => setShowCreate(false)}
                  className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors">
                  Отмена
                </button>
                {wizardStep < 3 ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (wizardStep === 1 && !form.name.trim()) return;
                      setWizardStep((s) => s + 1);
                    }}
                    disabled={wizardStep === 1 && !form.name.trim()}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-5 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 shadow-sm"
                  >
                    Далее →
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={createProduct}
                    disabled={creating}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-5 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 shadow-sm"
                  >
                    {creating ? "Создание..." : `Создать${wizardVariants.length > 0 ? ` (${wizardVariants.length} вар.)` : ""}`}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Smart Product Creator */}
      {showSmartCreate && (
        <SmartProductCreator
          onCreated={() => { setShowSmartCreate(false); load(); }}
          onClose={() => setShowSmartCreate(false)}
        />
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

      {/* Table (desktop) + Cards (mobile) */}
      {loading ? (
        <TableSkeleton rows={6} cols={7} />
      ) : paginated.length === 0 ? (
        <EmptyState
          message={search ? "Ничего не найдено" : "Нет товаров"}
          description={search ? undefined : "Добавьте товары чтобы AI мог предлагать их клиентам"}
          action={search ? undefined : { label: "AI Создать товар", onClick: () => setShowSmartCreate(true) }}
        />
      ) : (
      <>
        {/* Mobile cards */}
        <div className="md:hidden space-y-3">
          {paginated.map((p) => (
            <Link key={p.id} href={`/products/${p.id}`} className={`card p-4 block transition-colors hover:ring-1 hover:ring-indigo-200 ${!p.is_active ? "opacity-60" : ""}`}>
              <div className="flex items-start gap-3">
                <div className="w-12 h-12 rounded-lg bg-slate-100 flex items-center justify-center shrink-0 overflow-hidden">
                  {p.image_url ? (
                    <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" />
                  ) : (
                    <svg className="w-5 h-5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" /></svg>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-slate-900 truncate">{p.name}</p>
                  {p.brand && <p className="text-xs text-slate-400">{p.brand} {p.model || ""}</p>}
                  <div className="flex items-center gap-2 mt-2 flex-wrap">
                    <span className="text-sm font-medium text-slate-700">{priceRange(p)}</span>
                    {stockBadge(p.total_stock)}
                    <span className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-indigo-50 text-indigo-600">{p.category_name || "\u2014"}</span>
                  </div>
                </div>
                <span className={`px-2 py-0.5 rounded-md text-[10px] font-medium shrink-0 ${p.is_active ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-600"}`}>
                  {p.is_active ? "Активен" : "Скрыт"}
                </span>
              </div>
            </Link>
          ))}
        </div>

        {/* Desktop table */}
        <div className="hidden md:block card overflow-x-auto">
          <table className="w-full text-sm">
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
              {paginated.map((p) => (
                <tr key={p.id} className={`hover:bg-slate-50/50 transition-colors cursor-pointer ${!p.is_active ? "opacity-60" : ""} ${selected.has(p.id) ? "bg-indigo-50/50" : ""}`} onClick={() => window.location.href = `/products/${p.id}`}>
                  <td className="pl-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggleSelect(p.id)} className="rounded" />
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-3">
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
                        <div className="font-medium text-indigo-600">{p.name}</div>
                        {p.brand && <div className="text-xs text-slate-400">{p.brand} {p.model || ""}</div>}
                      </div>
                    </div>
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
                  <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <button type="button" onClick={() => toggleActive(p)}
                      className={`px-2 py-0.5 rounded-md text-xs font-medium cursor-pointer transition-colors ${p.is_active ? "bg-emerald-50 text-emerald-600 hover:bg-emerald-100" : "bg-rose-50 text-rose-600 hover:bg-rose-100"}`}>
                      {p.is_active ? "Активен" : "Скрыт"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
      )}

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
          Показано {Math.min(visibleCount, filtered.length)} из {filtered.length}{filtered.length !== products.length && ` (всего ${products.length})`}
        </div>
      )}
    </div>
  );
}
