"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { LoadingSpinner } from "@/components/ui/loading-spinner";

interface Variant {
  id: string;
  title: string;
  sku: string | null;
  color: string | null;
  storage: string | null;
  ram: string | null;
  size: string | null;
  price: string;
  currency: string;
  is_active: boolean;
  stock: number;
  reserved: number;
}

interface Alias {
  id: string;
  alias_text: string;
  priority: number;
}

interface Media {
  id: string;
  url: string;
  media_type: string;
  sort_order: number;
}

interface Product {
  id: string;
  name: string;
  slug: string;
  brand: string | null;
  model: string | null;
  description: string | null;
  category_name: string | null;
  is_active: boolean;
  variants: Variant[];
  aliases: Alias[];
  total_stock: number;
  min_price: string | null;
  max_price: string | null;
  image_url: string | null;
}

interface SaleOrder {
  order_number: string;
  customer: string;
  status: string;
  variant: string | null;
  qty: number;
  price: number;
  total: number;
  date: string | null;
}

interface SalesData {
  total_sold: number;
  total_revenue: number;
  orders: SaleOrder[];
}

function fmt(val: string | number): string {
  return Number(val).toLocaleString("ru-RU");
}

const statusLabels: Record<string, string> = {
  draft: "Черновик", confirmed: "Подтверждён", processing: "В обработке",
  shipped: "Отправлен", delivered: "Доставлен", cancelled: "Отменён",
};

const statusColors: Record<string, string> = {
  delivered: "bg-emerald-100 text-emerald-700", cancelled: "bg-rose-100 text-rose-600",
  shipped: "bg-indigo-100 text-indigo-600",
};

export default function ProductDetailPage() {
  const { id } = useParams();
  const router = useRouter();
  const { toast } = useToast();
  const [product, setProduct] = useState<Product | null>(null);
  const [loading, setLoading] = useState(true);
  // Inline inventory editing
  const [editing, setEditing] = useState<Record<string, { quantity: number; reserved: number }>>({});
  const [saving, setSaving] = useState<Set<string>>(new Set());
  // Product edit mode
  const [editProduct, setEditProduct] = useState(false);
  const [productForm, setProductForm] = useState({ name: "", brand: "", model: "", description: "" });
  const [savingProduct, setSavingProduct] = useState(false);
  // Alias management
  const [newAlias, setNewAlias] = useState("");
  // Variant editing
  const [editingVariant, setEditingVariant] = useState<string | null>(null);
  const [variantPrice, setVariantPrice] = useState("");
  // New variant form
  const [showAddVariant, setShowAddVariant] = useState(false);
  const [variantForm, setVariantForm] = useState({ title: "", color: "", storage: "", ram: "", price: "" });
  // Media
  const [mediaList, setMediaList] = useState<Media[]>([]);
  const [newMediaUrl, setNewMediaUrl] = useState("");
  // Sales
  const [sales, setSales] = useState<SalesData | null>(null);
  const [showSales, setShowSales] = useState(false);

  const load = useCallback(() => {
    if (!id) return;
    api.get<Product>(`/products/${id}`).then(setProduct).catch(console.error).finally(() => setLoading(false));
    api.get<Media[]>(`/products/${id}/media`).then(setMediaList).catch(() => {});
  }, [id]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);

  const loadSales = () => {
    if (!id) return;
    api.get<SalesData>(`/products/${id}/sales`).then(setSales).catch(() => {});
    setShowSales(true);
  };

  // Inventory editing
  const startEdit = (v: Variant) => {
    setEditing((prev) => ({ ...prev, [v.id]: { quantity: v.stock + v.reserved, reserved: v.reserved } }));
  };
  const cancelEdit = (vid: string) => {
    setEditing((prev) => { const next = { ...prev }; delete next[vid]; return next; });
  };
  const saveInventory = async (vid: string) => {
    const edit = editing[vid];
    if (!edit) return;
    setSaving((prev) => new Set(prev).add(vid));
    try {
      await api.put(`/inventory/${vid}`, { quantity: edit.quantity, reserved_quantity: edit.reserved });
      toast("Остаток обновлён", "success");
      cancelEdit(vid);
      load();
    } catch { toast("Ошибка сохранения", "error"); }
    finally { setSaving((prev) => { const n = new Set(prev); n.delete(vid); return n; }); }
  };
  const updateEditField = (vid: string, field: "quantity" | "reserved", value: number) => {
    setEditing((prev) => ({ ...prev, [vid]: { ...prev[vid], [field]: Math.max(0, value) } }));
  };

  // Product info editing
  const startProductEdit = () => {
    if (!product) return;
    setProductForm({ name: product.name, brand: product.brand || "", model: product.model || "", description: product.description || "" });
    setEditProduct(true);
  };
  const saveProductInfo = async () => {
    setSavingProduct(true);
    try {
      await api.patch(`/products/${id}`, { name: productForm.name.trim(), brand: productForm.brand.trim() || null, model: productForm.model.trim() || null, description: productForm.description.trim() || null });
      toast("Товар обновлён", "success");
      setEditProduct(false);
      load();
    } catch { toast("Ошибка сохранения", "error"); }
    finally { setSavingProduct(false); }
  };

  // Aliases
  const addAlias = async () => {
    if (!newAlias.trim()) return;
    try {
      await api.post(`/products/${id}/aliases`, { alias_text: newAlias.trim(), priority: 0 });
      setNewAlias("");
      toast("Алиас добавлен", "success");
      load();
    } catch { toast("Ошибка добавления", "error"); }
  };
  const deleteAlias = async (aliasId: string) => {
    try { await api.delete(`/aliases/${aliasId}`); load(); }
    catch { toast("Ошибка удаления", "error"); }
  };

  // Variant price editing
  const startVariantPriceEdit = (v: Variant) => {
    setEditingVariant(v.id);
    setVariantPrice(v.price);
  };
  const saveVariantPrice = async (vid: string) => {
    if (!variantPrice || Number(variantPrice) <= 0) return;
    try {
      await api.patch(`/variants/${vid}`, { price: Number(variantPrice) });
      toast("Цена обновлена", "success");
      setEditingVariant(null);
      load();
    } catch { toast("Ошибка обновления цены", "error"); }
  };

  // Add variant
  const addVariant = async () => {
    if (!variantForm.title.trim() || !variantForm.price) return;
    try {
      await api.post(`/products/${id}/variants`, {
        title: variantForm.title.trim(),
        color: variantForm.color.trim() || null,
        storage: variantForm.storage.trim() || null,
        ram: variantForm.ram.trim() || null,
        price: Number(variantForm.price),
      });
      toast("Вариант добавлен", "success");
      setShowAddVariant(false);
      setVariantForm({ title: "", color: "", storage: "", ram: "", price: "" });
      load();
    } catch { toast("Ошибка добавления варианта", "error"); }
  };

  // Delete variant
  const deleteVariant = async (vid: string) => {
    if (!confirm("Удалить вариант?")) return;
    try {
      await api.delete(`/variants/${vid}`);
      toast("Вариант удалён", "success");
      load();
    } catch { toast("Ошибка удаления", "error"); }
  };

  // Media
  const addMedia = async () => {
    if (!newMediaUrl.trim()) return;
    try {
      await api.post(`/products/${id}/media`, { url: newMediaUrl.trim(), media_type: "photo" });
      setNewMediaUrl("");
      toast("Фото добавлено", "success");
      load();
    } catch { toast("Ошибка добавления", "error"); }
  };
  const deleteMedia = async (mediaId: string) => {
    try {
      await api.delete(`/media/${mediaId}`);
      load();
    } catch { toast("Ошибка удаления", "error"); }
  };

  if (loading) return <LoadingSpinner />;
  if (!product) return <div className="p-8 text-center text-rose-500">Товар не найден</div>;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <button onClick={() => router.push("/products")} className="text-sm text-indigo-600 hover:text-indigo-700 hover:underline mb-2 block transition-colors">&larr; Назад к товарам</button>
          {editProduct ? (
            <div className="space-y-3 max-w-lg">
              <input type="text" value={productForm.name} onChange={(e) => setProductForm({ ...productForm, name: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-lg font-bold focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Название" required />
              <div className="flex gap-2">
                <input type="text" value={productForm.brand} onChange={(e) => setProductForm({ ...productForm, brand: e.target.value })}
                  className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Бренд" />
                <input type="text" value={productForm.model} onChange={(e) => setProductForm({ ...productForm, model: e.target.value })}
                  className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Модель" />
              </div>
              <textarea value={productForm.description} onChange={(e) => setProductForm({ ...productForm, description: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm h-20 resize-none focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Описание" />
              <div className="flex gap-2">
                <button type="button" onClick={saveProductInfo} disabled={savingProduct || !productForm.name.trim()}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">{savingProduct ? "..." : "Сохранить"}</button>
                <button type="button" onClick={() => setEditProduct(false)} className="px-4 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors">Отмена</button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-slate-900">{product.name}</h1>
                <button type="button" onClick={startProductEdit} className="text-slate-400 hover:text-indigo-600 transition-colors" title="Редактировать">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                </button>
              </div>
              <div className="flex gap-3 mt-1 text-sm text-slate-500">
                {product.brand && <span>{product.brand}</span>}
                {product.model && <span>{product.model}</span>}
                {product.category_name && <span className="px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 text-xs">{product.category_name}</span>}
                <span className={`px-2 py-0.5 rounded text-xs ${product.is_active ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
                  {product.is_active ? "Активен" : "Скрыт"}
                </span>
              </div>
            </>
          )}
        </div>
        <div className="text-right">
          <div className="text-sm text-slate-500">Доступно к продаже</div>
          <div className="text-2xl font-bold text-slate-900">{product.total_stock} шт</div>
          {product.variants.reduce((s, v) => s + v.reserved, 0) > 0 && (
            <div className="text-xs text-amber-600 mt-0.5">+ {product.variants.reduce((s, v) => s + v.reserved, 0)} в резерве</div>
          )}
        </div>
      </div>

      {/* Photos */}
      <div className="card p-4">
        <h2 className="font-semibold text-slate-900 mb-3">Фото ({mediaList.length})</h2>
        <div className="flex gap-3 flex-wrap mb-3">
          {mediaList.map((m) => (
            <div key={m.id} className="relative group w-20 h-20 rounded-lg overflow-hidden bg-slate-100 border border-slate-200">
              <img src={m.url} alt="" className="w-full h-full object-cover" />
              <button type="button" onClick={() => deleteMedia(m.id)}
                className="absolute top-0.5 right-0.5 w-5 h-5 bg-rose-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">&times;</button>
            </div>
          ))}
          {mediaList.length === 0 && <p className="text-xs text-slate-400">Нет фото</p>}
        </div>
        <div className="flex gap-2">
          <input type="url" value={newMediaUrl} onChange={(e) => setNewMediaUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addMedia(); } }}
            placeholder="URL фото (https://...)" className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
          <button type="button" onClick={addMedia} disabled={!newMediaUrl.trim()}
            className="px-3 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">+ Фото</button>
        </div>
      </div>

      {/* Description */}
      {product.description && !editProduct && (
        <div className="card p-4">
          <h2 className="font-semibold text-slate-900 mb-2">Описание</h2>
          <p className="text-sm text-slate-500">{product.description}</p>
        </div>
      )}

      {/* Variants */}
      <div className="card overflow-x-auto">
        <div className="px-4 py-3 border-b border-slate-200/60 bg-slate-50/50 flex items-center justify-between">
          <h2 className="font-semibold text-slate-900">Варианты ({product.variants.length})</h2>
          <button type="button" onClick={() => setShowAddVariant(!showAddVariant)}
            className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 transition-colors">
            + Вариант
          </button>
        </div>

        {/* Add variant form */}
        {showAddVariant && (
          <div className="px-4 py-3 bg-indigo-50/50 border-b border-slate-200/60">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-2">
              <input type="text" placeholder="Название *" value={variantForm.title} onChange={(e) => setVariantForm({ ...variantForm, title: e.target.value })}
                className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" required />
              <input type="text" placeholder="Цвет" value={variantForm.color} onChange={(e) => setVariantForm({ ...variantForm, color: e.target.value })}
                className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
              <input type="text" placeholder="Память" value={variantForm.storage} onChange={(e) => setVariantForm({ ...variantForm, storage: e.target.value })}
                className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
              <input type="text" placeholder="RAM" value={variantForm.ram} onChange={(e) => setVariantForm({ ...variantForm, ram: e.target.value })}
                className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
              <input type="number" placeholder="Цена *" value={variantForm.price} onChange={(e) => setVariantForm({ ...variantForm, price: e.target.value })}
                className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" required min={1} />
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={addVariant} disabled={!variantForm.title.trim() || !variantForm.price}
                className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">Добавить</button>
              <button type="button" onClick={() => setShowAddVariant(false)}
                className="px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-600 hover:bg-slate-50 transition-colors">Отмена</button>
            </div>
          </div>
        )}

        {product.variants.length === 0 ? (
          <div className="px-4 py-8 text-center text-slate-400">Нет вариантов</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/50 text-left">
                <tr>
                  <th className="px-4 py-2 text-slate-500 font-medium">Название</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">Цвет</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">Память</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">RAM</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">Цена</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">Остаток</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">Статус</th>
                  <th className="px-4 py-2 w-28"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {product.variants.map((v) => {
                  const isEditing = !!editing[v.id];
                  const edit = editing[v.id];
                  const isSaving = saving.has(v.id);
                  const isPriceEditing = editingVariant === v.id;
                  return (
                    <tr key={v.id} className={`hover:bg-slate-50/50 transition-colors ${isEditing ? "bg-indigo-50/40" : ""}`}>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-900">{v.title}</div>
                        {v.sku && <div className="text-xs text-slate-400">SKU: {v.sku}</div>}
                      </td>
                      <td className="px-4 py-3">
                        {v.color ? <span className="px-2 py-0.5 rounded bg-slate-100 text-xs text-slate-700">{v.color}</span> : <span className="text-slate-300">&mdash;</span>}
                      </td>
                      <td className="px-4 py-3 text-slate-700">{v.storage || "\u2014"}</td>
                      <td className="px-4 py-3 text-slate-700">{v.ram || "\u2014"}</td>
                      <td className="px-4 py-3 font-medium whitespace-nowrap text-slate-900">
                        {isPriceEditing ? (
                          <div className="flex items-center gap-1">
                            <input type="number" value={variantPrice} onChange={(e) => setVariantPrice(e.target.value)}
                              className="w-24 bg-white border border-indigo-300 rounded px-2 py-1 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" min={1}
                              onKeyDown={(e) => { if (e.key === "Enter") saveVariantPrice(v.id); if (e.key === "Escape") setEditingVariant(null); }} autoFocus />
                            <button type="button" onClick={() => saveVariantPrice(v.id)} className="text-indigo-600 hover:text-indigo-700 text-xs">✓</button>
                            <button type="button" onClick={() => setEditingVariant(null)} className="text-slate-400 hover:text-slate-600 text-xs">✗</button>
                          </div>
                        ) : (
                          <button type="button" onClick={() => startVariantPriceEdit(v)} className="hover:text-indigo-600 transition-colors" title="Нажмите, чтобы изменить цену">
                            {fmt(v.price)} сум
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {isEditing ? (
                          <div className="flex items-center gap-2">
                            <div>
                              <label className="text-[10px] text-slate-400 block">Всего</label>
                              <input type="number" min={0} value={edit.quantity} onChange={(e) => updateEditField(v.id, "quantity", parseInt(e.target.value) || 0)}
                                className="w-16 bg-white border border-slate-200 rounded-lg px-2 py-1 text-sm text-center focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
                            </div>
                            <div>
                              <label className="text-[10px] text-slate-400 block">Резерв</label>
                              <input type="number" min={0} max={edit.quantity} value={edit.reserved} onChange={(e) => updateEditField(v.id, "reserved", parseInt(e.target.value) || 0)}
                                className="w-16 bg-white border border-slate-200 rounded-lg px-2 py-1 text-sm text-center focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
                            </div>
                            <div className="text-[10px] text-slate-400">= {Math.max(0, edit.quantity - edit.reserved)} своб</div>
                          </div>
                        ) : (
                          <div>
                            <span className={`font-medium ${v.stock > 0 ? "text-emerald-600" : "text-rose-600"}`}>{v.stock} своб</span>
                            {v.reserved > 0 && <span className="text-xs text-amber-600 ml-1">+ {v.reserved} резерв</span>}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded text-xs ${v.is_active ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
                          {v.is_active ? "Актив" : "Скрыт"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {isEditing ? (
                          <div className="flex gap-1">
                            <button type="button" disabled={isSaving} onClick={() => saveInventory(v.id)}
                              className="px-2.5 py-1 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">{isSaving ? "..." : "OK"}</button>
                            <button type="button" onClick={() => cancelEdit(v.id)}
                              className="px-2 py-1 bg-white border border-slate-200 rounded-lg text-xs text-slate-500 hover:bg-slate-50 transition-colors">X</button>
                          </div>
                        ) : (
                          <div className="flex gap-1">
                            <button type="button" onClick={() => startEdit(v)}
                              className="px-2 py-1 bg-white border border-slate-200 rounded-lg text-xs text-indigo-600 hover:bg-indigo-50 transition-colors">Склад</button>
                            <button type="button" onClick={() => deleteVariant(v.id)}
                              className="px-2 py-1 bg-white border border-slate-200 rounded-lg text-xs text-rose-500 hover:bg-rose-50 transition-colors" title="Удалить вариант">&times;</button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Sales history */}
      <div className="card">
        <div className="px-4 py-3 border-b border-slate-200/60 bg-slate-50/50 flex items-center justify-between">
          <h2 className="font-semibold text-slate-900">История продаж</h2>
          {!showSales && <button type="button" onClick={loadSales} className="text-xs text-indigo-600 hover:text-indigo-700 font-medium">Загрузить →</button>}
        </div>
        {showSales && sales && (
          <div className="p-4">
            <div className="flex gap-4 mb-4">
              <div className="bg-indigo-50 rounded-xl px-4 py-3 text-center">
                <p className="text-xl font-bold text-indigo-700">{sales.total_sold}</p>
                <p className="text-[10px] text-indigo-500">продано шт</p>
              </div>
              <div className="bg-emerald-50 rounded-xl px-4 py-3 text-center">
                <p className="text-xl font-bold text-emerald-700">{fmt(sales.total_revenue)}</p>
                <p className="text-[10px] text-emerald-500">выручка (сум)</p>
              </div>
            </div>
            {sales.orders.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-4">Нет продаж</p>
            ) : (
              <div className="space-y-2">
                {sales.orders.slice(0, 20).map((o, i) => (
                  <div key={i} className="flex items-center justify-between text-sm bg-slate-50 rounded-lg px-3 py-2">
                    <div>
                      <span className="font-mono text-xs font-medium text-slate-700">{o.order_number}</span>
                      <span className="text-slate-400 ml-2">{o.customer}</span>
                      {o.variant && <span className="text-xs text-slate-400 ml-2">({o.variant})</span>}
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      <span className={`px-1.5 py-0.5 rounded ${statusColors[o.status] || "bg-amber-50 text-amber-700"}`}>
                        {statusLabels[o.status] || o.status}
                      </span>
                      <span className="text-slate-500">{o.qty} шт</span>
                      <span className="font-medium text-slate-900">{fmt(o.total)} сум</span>
                      {o.date && <span className="text-slate-400">{new Date(o.date).toLocaleDateString("ru")}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Aliases */}
      <div className="card overflow-x-auto">
        <div className="px-4 py-3 border-b border-slate-200/60 bg-slate-50/50">
          <h2 className="font-semibold text-slate-900">Алиасы / Синонимы ({product.aliases.length})</h2>
          <p className="text-xs text-slate-400 mt-0.5">По этим словам ИИ находит этот товар</p>
        </div>
        <div className="p-4">
          <div className="flex gap-2 mb-3">
            <input type="text" value={newAlias} onChange={(e) => setNewAlias(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addAlias(); } }}
              placeholder="Добавить алиас (Enter)" className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
            <button type="button" onClick={addAlias} disabled={!newAlias.trim()}
              className="px-3 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">+</button>
          </div>
          {product.aliases.length === 0 ? (
            <p className="text-center text-slate-400 py-4">Нет алиасов</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {product.aliases.sort((a, b) => b.priority - a.priority).map((a) => (
                <span key={a.id} className="group inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm bg-indigo-50 text-indigo-700 border border-indigo-200">
                  {a.alias_text}
                  {a.priority > 0 && <span className="text-xs text-indigo-400">({a.priority})</span>}
                  <button type="button" onClick={() => deleteAlias(a.id)}
                    className="text-indigo-300 hover:text-rose-500 transition-colors opacity-0 group-hover:opacity-100 ml-0.5" title="Удалить">&times;</button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
