"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { LoadingSpinner } from "@/components/ui/loading-spinner";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { formatPrice } from "@/lib/utils";

interface VariantAttributes {
  meeting_point?: string;
  included?: string;
  what_to_bring?: string;
}

interface Variant {
  id: string;
  title: string;
  sku: string | null;
  color: string | null;
  storage: string | null;
  ram: string | null;
  size: string | null;
  attributes_json: VariantAttributes | null;
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
  variant_id: string | null;
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
  return formatPrice(val);
}

const statusLabels: Record<string, string> = {
  draft: "Черновик", pending_payment: "Ожидает оплаты", confirmed: "Подтверждён",
  completed: "Завершён", cancelled: "Отменён",
};

const statusColors: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-700", cancelled: "bg-rose-100 text-rose-600",
  confirmed: "bg-blue-100 text-blue-600", pending_payment: "bg-amber-100 text-amber-600",
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
  // Attributes editing
  const [editingAttr, setEditingAttr] = useState<string | null>(null); // variant id being edited
  const [attrForm, setAttrForm] = useState<VariantAttributes>({});
  const [savingAttr, setSavingAttr] = useState(false);
  // New variant form
  const [showAddVariant, setShowAddVariant] = useState(false);
  const [variantForm, setVariantForm] = useState({ title: "", color: "", storage: "", price: "" });
  // Media
  const [mediaList, setMediaList] = useState<Media[]>([]);
  const [newMediaUrl, setNewMediaUrl] = useState("");
  const [variantMediaInput, setVariantMediaInput] = useState<Record<string, string>>({});
  const [expandedVariantMedia, setExpandedVariantMedia] = useState<Set<string>>(new Set());
  // Sales
  const [sales, setSales] = useState<SalesData | null>(null);
  const [showSales, setShowSales] = useState(false);
  // Delete variant confirmation
  const [deleteVariantId, setDeleteVariantId] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!id) return;
    api.get<Product>(`/products/${id}`).then(setProduct).catch(() => toast("Не удалось загрузить тур", "error")).finally(() => setLoading(false));
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
      toast("Места обновлены", "success");
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
      toast("Тур обновлён", "success");
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

  // Attributes editing
  const startAttrEdit = (v: Variant) => {
    setEditingAttr(v.id);
    setAttrForm({
      meeting_point: v.attributes_json?.meeting_point || "",
      included: v.attributes_json?.included || "",
      what_to_bring: v.attributes_json?.what_to_bring || "",
    });
  };
  const saveAttributes = async (vid: string) => {
    setSavingAttr(true);
    try {
      const cleaned: VariantAttributes = {};
      if (attrForm.meeting_point?.trim()) cleaned.meeting_point = attrForm.meeting_point.trim();
      if (attrForm.included?.trim()) cleaned.included = attrForm.included.trim();
      if (attrForm.what_to_bring?.trim()) cleaned.what_to_bring = attrForm.what_to_bring.trim();
      await api.patch(`/variants/${vid}`, { attributes_json: Object.keys(cleaned).length > 0 ? cleaned : null });
      toast("Tafsilotlar saqlandi", "success");
      setEditingAttr(null);
      load();
    } catch { toast("Xatolik saqlashda", "error"); }
    finally { setSavingAttr(false); }
  };

  // Add variant
  const addVariant = async () => {
    if (!variantForm.title.trim() || !variantForm.price) return;
    try {
      await api.post(`/products/${id}/variants`, {
        title: variantForm.title.trim(),
        color: variantForm.color.trim() || null,
        storage: variantForm.storage.trim() || null,
        price: Number(variantForm.price),
      });
      toast("Дата добавлена", "success");
      setShowAddVariant(false);
      setVariantForm({ title: "", color: "", storage: "", price: "" });
      load();
    } catch { toast("Ошибка добавления даты", "error"); }
  };

  // Delete variant
  const deleteVariant = async (vid: string) => {
    try {
      await api.delete(`/variants/${vid}`);
      toast("Дата удалена", "success");
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

  // Variant media
  const addVariantMedia = async (variantId: string) => {
    const url = (variantMediaInput[variantId] || "").trim();
    if (!url) return;
    try {
      await api.post(`/products/${id}/media`, { url, media_type: "photo", variant_id: variantId });
      setVariantMediaInput((prev) => ({ ...prev, [variantId]: "" }));
      toast("Фото даты добавлено", "success");
      load();
    } catch { toast("Ошибка добавления", "error"); }
  };

  const toggleVariantMedia = (vid: string) => {
    setExpandedVariantMedia((prev) => {
      const next = new Set(prev);
      next.has(vid) ? next.delete(vid) : next.add(vid);
      return next;
    });
  };

  const getVariantMedia = (vid: string) => mediaList.filter((m) => m.variant_id === vid);
  const productLevelMedia = mediaList.filter((m) => !m.variant_id);

  if (loading) return (
    <div className="space-y-6 animate-pulse">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2">
        <div className="h-4 w-16 bg-slate-200 rounded" />
        <div className="h-4 w-3 bg-slate-200 rounded" />
        <div className="h-4 w-32 bg-slate-200 rounded" />
      </div>
      {/* Title + badges */}
      <div className="flex items-center gap-3">
        <div className="h-8 w-56 bg-slate-200 rounded-lg" />
        <div className="h-6 w-20 bg-indigo-100 rounded-full" />
        <div className="h-6 w-16 bg-slate-200 rounded-full" />
      </div>
      {/* Stock summary */}
      <div className="flex gap-4">
        <div className="h-5 w-28 bg-slate-200 rounded" />
        <div className="h-5 w-24 bg-slate-200 rounded" />
      </div>
      {/* Photos section */}
      <div className="card p-6 space-y-4">
        <div className="h-5 w-28 bg-slate-200 rounded" />
        <div className="flex gap-3">
          {[1,2,3].map(i => <div key={i} className="w-24 h-24 bg-slate-100 rounded-xl" />)}
        </div>
      </div>
      {/* Variants section */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="h-5 w-40 bg-slate-200 rounded" />
          <div className="h-8 w-32 bg-indigo-100 rounded-lg" />
        </div>
        {/* Mobile variant skeletons */}
        <div className="md:hidden space-y-3">
          {[1,2,3].map(i => (
            <div key={i} className="rounded-xl border border-slate-200 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="space-y-1.5">
                  <div className="h-5 w-36 bg-slate-200 rounded" />
                  <div className="h-3 w-20 bg-slate-100 rounded" />
                </div>
                <div className="h-6 w-14 bg-emerald-100 rounded-full" />
              </div>
              <div className="flex gap-2">
                <div className="h-6 w-16 bg-slate-100 rounded" />
                <div className="h-6 w-14 bg-slate-100 rounded" />
                <div className="h-6 w-12 bg-slate-100 rounded" />
              </div>
              <div className="flex items-center justify-between">
                <div className="h-6 w-32 bg-slate-200 rounded" />
                <div className="h-5 w-20 bg-emerald-50 rounded" />
              </div>
              <div className="flex gap-2">
                <div className="h-8 w-16 bg-slate-100 rounded-lg" />
                <div className="h-8 w-14 bg-slate-100 rounded-lg" />
                <div className="h-8 w-8 bg-slate-100 rounded-lg" />
              </div>
            </div>
          ))}
        </div>
        {/* Desktop variant skeletons */}
        <div className="hidden md:block space-y-2">
          {[1,2,3,4].map(i => <div key={i} className="h-14 bg-slate-50 rounded-lg" />)}
        </div>
      </div>
      {/* Aliases */}
      <div className="card p-6 space-y-3">
        <div className="h-5 w-24 bg-slate-200 rounded" />
        <div className="flex gap-2 flex-wrap">
          {[1,2,3,4,5].map(i => <div key={i} className="h-7 w-20 bg-slate-100 rounded-full" />)}
        </div>
      </div>
    </div>
  );
  if (!product) return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-16 h-16 rounded-2xl bg-rose-50 flex items-center justify-center mb-4">
        <svg className="w-8 h-8 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5m8.25 3v6.75m0 0l-3-3m3 3l3-3M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
        </svg>
      </div>
      <h2 className="text-lg font-semibold text-slate-900 mb-1">Тур не найден</h2>
      <p className="text-sm text-slate-400 mb-4">Возможно, он был удалён или ссылка неверна</p>
      <button type="button" onClick={() => router.push("/products")} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors">
        Назад к турам
      </button>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Breadcrumb items={[
            { label: "Туры", href: "/products" },
            { label: product?.name || "..." },
          ]} />
          {editProduct ? (
            <div className="space-y-3 max-w-lg">
              <input type="text" value={productForm.name} onChange={(e) => setProductForm({ ...productForm, name: e.target.value })}
                className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-lg font-bold focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Название" required />
              <div className="flex gap-2">
                <input type="text" value={productForm.brand} onChange={(e) => setProductForm({ ...productForm, brand: e.target.value })}
                  className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Сложность" />
                <input type="text" value={productForm.model} onChange={(e) => setProductForm({ ...productForm, model: e.target.value })}
                  className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Длительность" />
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
                <button type="button" onClick={startProductEdit} className="text-slate-400 hover:text-indigo-600 transition-colors" title="Редактировать" aria-label="Редактировать тур">
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
          <div className="text-sm text-slate-500">Свободно</div>
          <div className="text-2xl font-bold text-slate-900">{product.total_stock} мест</div>
          {product.variants.reduce((s, v) => s + v.reserved, 0) > 0 && (
            <div className="text-xs text-amber-600 mt-0.5">+ {product.variants.reduce((s, v) => s + v.reserved, 0)} в резерве</div>
          )}
        </div>
      </div>

      {/* Photos (product-level) */}
      <div className="card p-4">
        <h2 className="font-semibold text-slate-900 mb-1">Фото тура ({productLevelMedia.length})</h2>
        <p className="text-xs text-slate-400 mb-3">Общие фото тура. Фото дат добавляются в таблице ниже.</p>
        <div className="flex gap-3 flex-wrap mb-3">
          {productLevelMedia.map((m) => (
            <div key={m.id} className="relative group w-20 h-20 rounded-lg overflow-hidden bg-slate-100 border border-slate-200">
              <img src={m.url} alt="" className="w-full h-full object-cover" />
              <button type="button" onClick={() => deleteMedia(m.id)}
                className="absolute top-0.5 right-0.5 w-5 h-5 bg-rose-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">&times;</button>
            </div>
          ))}
          {productLevelMedia.length === 0 && <p className="text-xs text-slate-400">Нет фото</p>}
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
          <h2 className="font-semibold text-slate-900">Даты отправления ({product.variants.length})</h2>
          <button type="button" onClick={() => setShowAddVariant(!showAddVariant)}
            className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 transition-colors">
            + Дата
          </button>
        </div>

        {/* Add variant form */}
        {showAddVariant && (
          <div className="px-4 py-3 bg-indigo-50/50 border-b border-slate-200/60">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2">
              <input type="text" placeholder="Название *" value={variantForm.title} onChange={(e) => setVariantForm({ ...variantForm, title: e.target.value })}
                className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" required />
              <input type="text" placeholder="Дата (2026-04-19)" value={variantForm.color} onChange={(e) => setVariantForm({ ...variantForm, color: e.target.value })}
                className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
              <input type="text" placeholder="Время (08:00)" value={variantForm.storage} onChange={(e) => setVariantForm({ ...variantForm, storage: e.target.value })}
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
          <div className="px-4 py-8 text-center text-slate-400">Нет дат отправления</div>
        ) : (
          <>
            {/* Mobile variant cards */}
            <div className="md:hidden space-y-3 px-1">
              {product.variants.map((v) => {
                const isEditing = !!editing[v.id];
                const edit = editing[v.id];
                const isSaving = saving.has(v.id);
                const isPriceEditing = editingVariant === v.id;
                const vMedia = getVariantMedia(v.id);
                const isMediaExpanded = expandedVariantMedia.has(v.id);
                return (
                  <div key={v.id} className={`rounded-xl border transition-all ${isEditing ? "border-indigo-300 bg-indigo-50/30 shadow-sm" : "border-slate-200 bg-white"} p-4`}>
                    {/* Header: title + status */}
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <p className="font-semibold text-slate-900 text-[15px]">{v.title}</p>
                        {v.sku && <p className="text-[11px] text-slate-400 mt-0.5">SKU: {v.sku}</p>}
                      </div>
                      <span className={`px-2.5 py-1 rounded-full text-xs font-medium shrink-0 ${v.is_active ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-rose-50 text-rose-700 border border-rose-200"}`}>
                        {v.is_active ? "Актив" : "Скрыт"}
                      </span>
                    </div>
                    {/* Specs tags */}
                    {(v.color || v.storage) && (
                      <div className="flex flex-wrap gap-1.5 mb-3">
                        {v.color && <span className="px-2.5 py-1 rounded-lg bg-slate-50 text-slate-700 text-xs font-medium border border-slate-100">{v.color}</span>}
                        {v.storage && <span className="px-2.5 py-1 rounded-lg bg-indigo-50 text-indigo-700 text-xs font-medium border border-indigo-100">{v.storage}</span>}
                      </div>
                    )}
                    {/* Attributes (Tafsilotlar) */}
                    {editingAttr === v.id ? (
                      <div className="mb-3 bg-white rounded-lg p-3 border border-slate-200 space-y-2">
                        <div>
                          <label className="text-[10px] text-slate-400 block mb-0.5">Yig&apos;ilish joyi</label>
                          <input type="text" value={attrForm.meeting_point || ""} onChange={(e) => setAttrForm({ ...attrForm, meeting_point: e.target.value })}
                            placeholder="Masalan: Chorsu metro"
                            className="w-full bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-indigo-500 outline-none" />
                        </div>
                        <div>
                          <label className="text-[10px] text-slate-400 block mb-0.5">Kiradi</label>
                          <input type="text" value={attrForm.included || ""} onChange={(e) => setAttrForm({ ...attrForm, included: e.target.value })}
                            placeholder="Masalan: Transport, gid, tushlik"
                            className="w-full bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-indigo-500 outline-none" />
                        </div>
                        <div>
                          <label className="text-[10px] text-slate-400 block mb-0.5">Olib kelish</label>
                          <input type="text" value={attrForm.what_to_bring || ""} onChange={(e) => setAttrForm({ ...attrForm, what_to_bring: e.target.value })}
                            placeholder="Masalan: Qulay kiyim, suv"
                            className="w-full bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-indigo-500 outline-none" />
                        </div>
                        <div className="flex gap-1.5">
                          <button type="button" disabled={savingAttr} onClick={() => saveAttributes(v.id)}
                            className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">{savingAttr ? "..." : "Saqlash"}</button>
                          <button type="button" onClick={() => setEditingAttr(null)}
                            className="px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-500 hover:bg-slate-50 transition-colors">Bekor</button>
                        </div>
                      </div>
                    ) : v.attributes_json && (v.attributes_json.meeting_point || v.attributes_json.included || v.attributes_json.what_to_bring) ? (
                      <button type="button" onClick={() => startAttrEdit(v)} className="mb-3 w-full text-left group">
                        <div className="rounded-lg bg-indigo-50/50 border border-indigo-100 px-3 py-2 space-y-0.5 text-xs">
                          {v.attributes_json.meeting_point && (
                            <div className="text-slate-600"><span className="text-indigo-400 font-medium">Joyi:</span> {v.attributes_json.meeting_point}</div>
                          )}
                          {v.attributes_json.included && (
                            <div className="text-slate-600"><span className="text-indigo-400 font-medium">Kiradi:</span> {v.attributes_json.included}</div>
                          )}
                          {v.attributes_json.what_to_bring && (
                            <div className="text-slate-600"><span className="text-indigo-400 font-medium">Olib kelish:</span> {v.attributes_json.what_to_bring}</div>
                          )}
                          <svg className="w-3 h-3 text-slate-300 group-hover:text-indigo-500 transition-colors inline" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                        </div>
                      </button>
                    ) : (
                      <button type="button" onClick={() => startAttrEdit(v)} className="mb-3 text-xs text-slate-300 hover:text-indigo-500 transition-colors inline-flex items-center gap-1">
                        + Tafsilot qo&apos;shish
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                      </button>
                    )}
                    {/* Price + stock row */}
                    <div className="flex items-center justify-between mb-3 py-2 px-3 rounded-lg bg-slate-50/80">
                      <div className="font-semibold text-slate-900">
                        {isPriceEditing ? (
                          <div className="flex items-center gap-1">
                            <input type="number" value={variantPrice} onChange={(e) => setVariantPrice(e.target.value)}
                              className="w-28 bg-white border border-indigo-300 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" min={1}
                              onKeyDown={(e) => { if (e.key === "Enter") saveVariantPrice(v.id); if (e.key === "Escape") setEditingVariant(null); }} autoFocus />
                            <button type="button" onClick={() => saveVariantPrice(v.id)} className="text-indigo-600 text-sm px-1.5 font-bold">✓</button>
                            <button type="button" onClick={() => setEditingVariant(null)} className="text-slate-400 text-sm px-1.5">✗</button>
                          </div>
                        ) : (
                          <button type="button" onClick={() => startVariantPriceEdit(v)} className="text-left inline-flex items-center gap-1.5 group">
                            <span>{fmt(v.price)} сум</span>
                            <svg className="w-3.5 h-3.5 text-slate-300 group-hover:text-indigo-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                          </button>
                        )}
                      </div>
                      <div className="text-right">
                        <span className={`font-semibold text-sm ${v.stock > 0 ? "text-emerald-600" : "text-rose-600"}`}>{v.stock} мест</span>
                        {v.reserved > 0 && <span className="text-xs text-amber-600 ml-1.5 font-medium">+{v.reserved} рез</span>}
                      </div>
                    </div>
                    {isEditing && (
                      <div className="flex items-center gap-3 mb-3 bg-white rounded-lg p-3 border border-slate-200">
                        <div className="flex-1">
                          <label className="text-[10px] text-slate-400 block mb-1">Всего</label>
                          <input type="number" min={0} value={edit.quantity} onChange={(e) => updateEditField(v.id, "quantity", parseInt(e.target.value) || 0)}
                            className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm text-center focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
                        </div>
                        <div className="flex-1">
                          <label className="text-[10px] text-slate-400 block mb-1">Резерв</label>
                          <input type="number" min={0} max={edit.quantity} value={edit.reserved} onChange={(e) => updateEditField(v.id, "reserved", parseInt(e.target.value) || 0)}
                            className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm text-center focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
                        </div>
                        <div className="text-xs text-slate-400 pt-4">= {Math.max(0, edit.quantity - edit.reserved)}</div>
                      </div>
                    )}
                    <div className="flex gap-1.5 flex-wrap">
                      {isEditing ? (
                        <>
                          <button type="button" disabled={isSaving} onClick={() => saveInventory(v.id)}
                            className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">{isSaving ? "..." : "Сохранить"}</button>
                          <button type="button" onClick={() => cancelEdit(v.id)}
                            className="px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-500 hover:bg-slate-50 transition-colors">Отмена</button>
                        </>
                      ) : (
                        <>
                          <button type="button" onClick={() => toggleVariantMedia(v.id)}
                            className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${vMedia.length > 0 ? "bg-violet-50 text-violet-600 border border-violet-200" : "bg-white border border-slate-200 text-slate-400"}`}>
                            {vMedia.length > 0 ? `${vMedia.length} фото` : "Фото"}
                          </button>
                          <button type="button" onClick={() => startEdit(v)}
                            className="px-2.5 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-indigo-600">Места</button>
                          <button type="button" onClick={() => setDeleteVariantId(v.id)}
                            className="px-2.5 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-rose-500">&times;</button>
                        </>
                      )}
                    </div>
                    {isMediaExpanded && (
                      <div className="mt-3 flex items-center gap-2 flex-wrap">
                        {vMedia.map((m) => (
                          <div key={m.id} className="relative group w-16 h-16 rounded-lg overflow-hidden bg-slate-100 border border-slate-200">
                            <img src={m.url} alt="" className="w-full h-full object-cover" />
                            <button type="button" onClick={() => deleteMedia(m.id)}
                              className="absolute top-0.5 right-0.5 w-4 h-4 bg-rose-500 text-white rounded-full text-[10px] flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">&times;</button>
                          </div>
                        ))}
                        <div className="flex gap-1.5 flex-1 min-w-[160px]">
                          <input type="url" value={variantMediaInput[v.id] || ""} onChange={(e) => setVariantMediaInput((prev) => ({ ...prev, [v.id]: e.target.value }))}
                            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addVariantMedia(v.id); } }}
                            placeholder="URL фото..." className="flex-1 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-violet-500 outline-none" />
                          <button type="button" onClick={() => addVariantMedia(v.id)} disabled={!(variantMediaInput[v.id] || "").trim()}
                            className="px-2.5 py-1.5 bg-violet-600 text-white rounded-lg text-xs font-medium disabled:opacity-50">+</button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Desktop variant table */}
            <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/50 text-left">
                <tr>
                  <th className="px-4 py-2 text-slate-500 font-medium">Название</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">Tafsilotlar</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">Цена</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">Места</th>
                  <th className="px-4 py-2 text-slate-500 font-medium">Статус</th>
                  <th className="px-4 py-2 w-20"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {product.variants.map((v) => {
                  const isEditing = !!editing[v.id];
                  const edit = editing[v.id];
                  const isSaving = saving.has(v.id);
                  const isPriceEditing = editingVariant === v.id;
                  const vMedia = getVariantMedia(v.id);
                  const isMediaExpanded = expandedVariantMedia.has(v.id);
                  return (
                    <React.Fragment key={v.id}>
                    <tr className={`hover:bg-slate-50/50 transition-colors ${isEditing ? "bg-indigo-50/40" : ""}`}>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-900">{v.title}</div>
                        {(v.color || v.storage) && (
                          <div className="flex gap-1.5 mt-0.5">
                            {v.color && <span className="px-1.5 py-0.5 rounded bg-slate-100 text-[11px] text-slate-500">{v.color}</span>}
                            {v.storage && <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-[11px] text-indigo-500">{v.storage}</span>}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {editingAttr === v.id ? (
                          <div className="space-y-1.5 min-w-[220px]">
                            <div>
                              <label className="text-[10px] text-slate-400 block">Yig&apos;ilish joyi</label>
                              <input type="text" value={attrForm.meeting_point || ""} onChange={(e) => setAttrForm({ ...attrForm, meeting_point: e.target.value })}
                                placeholder="Masalan: Chorsu metro"
                                className="w-full bg-white border border-slate-200 rounded px-2 py-1 text-xs focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
                            </div>
                            <div>
                              <label className="text-[10px] text-slate-400 block">Kiradi</label>
                              <input type="text" value={attrForm.included || ""} onChange={(e) => setAttrForm({ ...attrForm, included: e.target.value })}
                                placeholder="Masalan: Transport, gid, tushlik"
                                className="w-full bg-white border border-slate-200 rounded px-2 py-1 text-xs focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
                            </div>
                            <div>
                              <label className="text-[10px] text-slate-400 block">Olib kelish</label>
                              <input type="text" value={attrForm.what_to_bring || ""} onChange={(e) => setAttrForm({ ...attrForm, what_to_bring: e.target.value })}
                                placeholder="Masalan: Qulay kiyim, suv"
                                className="w-full bg-white border border-slate-200 rounded px-2 py-1 text-xs focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
                            </div>
                            <div className="flex gap-1 pt-0.5">
                              <button type="button" disabled={savingAttr} onClick={() => saveAttributes(v.id)}
                                className="px-2 py-1 bg-indigo-600 text-white rounded text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">{savingAttr ? "..." : "Saqlash"}</button>
                              <button type="button" onClick={() => setEditingAttr(null)}
                                className="px-2 py-1 bg-white border border-slate-200 rounded text-xs text-slate-500 hover:bg-slate-50 transition-colors">Bekor</button>
                            </div>
                          </div>
                        ) : (
                          <button type="button" onClick={() => startAttrEdit(v)} className="group text-left w-full" title="Bosing — tahrirlash">
                            {v.attributes_json && (v.attributes_json.meeting_point || v.attributes_json.included || v.attributes_json.what_to_bring) ? (
                              <div className="space-y-0.5 text-xs">
                                {v.attributes_json.meeting_point && (
                                  <div className="text-slate-600"><span className="text-slate-400">Joyi:</span> {v.attributes_json.meeting_point}</div>
                                )}
                                {v.attributes_json.included && (
                                  <div className="text-slate-600"><span className="text-slate-400">Kiradi:</span> {v.attributes_json.included}</div>
                                )}
                                {v.attributes_json.what_to_bring && (
                                  <div className="text-slate-600"><span className="text-slate-400">Olib kelish:</span> {v.attributes_json.what_to_bring}</div>
                                )}
                                <svg className="w-3 h-3 text-slate-300 group-hover:text-indigo-500 transition-colors inline mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                              </div>
                            ) : (
                              <span className="text-slate-300 group-hover:text-indigo-500 transition-colors inline-flex items-center gap-1 text-xs">
                                + Tafsilot
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                              </span>
                            )}
                          </button>
                        )}
                      </td>
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
                          <button type="button" onClick={() => startVariantPriceEdit(v)} className="group hover:text-indigo-600 transition-colors inline-flex items-center gap-1" title="Нажмите, чтобы изменить цену">
                            {fmt(v.price)} сум
                            <svg className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {isEditing ? (
                          <div className="flex items-center gap-2">
                            <div>
                              <label className="text-[10px] text-slate-400 block">Всего</label>
                              <input type="number" min={0} value={edit.quantity} onChange={(e) => updateEditField(v.id, "quantity", parseInt(e.target.value) || 0)}
                                className="w-20 bg-white border border-slate-200 rounded-lg px-2 py-1 text-sm text-center focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
                            </div>
                            <div>
                              <label className="text-[10px] text-slate-400 block">Резерв</label>
                              <input type="number" min={0} max={edit.quantity} value={edit.reserved} onChange={(e) => updateEditField(v.id, "reserved", parseInt(e.target.value) || 0)}
                                className="w-20 bg-white border border-slate-200 rounded-lg px-2 py-1 text-sm text-center focus:ring-2 focus:ring-indigo-500 outline-none transition-all" />
                            </div>
                            <div className="text-[10px] text-slate-400">= {Math.max(0, edit.quantity - edit.reserved)} мест</div>
                          </div>
                        ) : (
                          <div>
                            <span className={`font-medium ${v.stock > 0 ? "text-emerald-600" : "text-rose-600"}`}>{v.stock} мест</span>
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
                        <div className="flex flex-col gap-1">
                          {isEditing ? (
                            <>
                              <button type="button" disabled={isSaving} onClick={() => saveInventory(v.id)}
                                className="px-2.5 py-1 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">{isSaving ? "..." : "OK"}</button>
                              <button type="button" onClick={() => cancelEdit(v.id)}
                                className="px-2 py-1 bg-white border border-slate-200 rounded-lg text-xs text-slate-500 hover:bg-slate-50 transition-colors">Bekor</button>
                            </>
                          ) : (
                            <>
                              <button type="button" onClick={() => toggleVariantMedia(v.id)}
                                className={`px-2 py-1 rounded-lg text-xs font-medium transition-colors ${vMedia.length > 0 ? "bg-violet-50 text-violet-600 border border-violet-200 hover:bg-violet-100" : "bg-white border border-slate-200 text-slate-400 hover:bg-slate-50"}`}
                                title="Фото даты">
                                {vMedia.length > 0 ? `${vMedia.length} фото` : "Фото"}
                              </button>
                              <button type="button" onClick={() => startEdit(v)}
                                className="px-2 py-1 bg-white border border-slate-200 rounded-lg text-xs text-indigo-600 hover:bg-indigo-50 transition-colors">Места</button>
                              <button type="button" onClick={() => setDeleteVariantId(v.id)}
                                className="px-2 py-1 bg-white border border-slate-200 rounded-lg text-xs text-rose-500 hover:bg-rose-50 transition-colors" title="Удалить дату">Удалить</button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                    {/* Variant photos row */}
                    {isMediaExpanded && (
                      <tr className="bg-violet-50/30">
                        <td colSpan={6} className="px-4 py-3">
                          <div className="flex items-center gap-3 flex-wrap">
                            {vMedia.map((m) => (
                              <div key={m.id} className="relative group w-16 h-16 rounded-lg overflow-hidden bg-slate-100 border border-slate-200">
                                <img src={m.url} alt="" className="w-full h-full object-cover" />
                                <button type="button" onClick={() => deleteMedia(m.id)}
                                  className="absolute top-0.5 right-0.5 w-4 h-4 bg-rose-500 text-white rounded-full text-[10px] flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">&times;</button>
                              </div>
                            ))}
                            <div className="flex gap-1.5 flex-1 min-w-[200px]">
                              <input type="url" value={variantMediaInput[v.id] || ""} onChange={(e) => setVariantMediaInput((prev) => ({ ...prev, [v.id]: e.target.value }))}
                                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addVariantMedia(v.id); } }}
                                placeholder="URL фото варианта..." className="flex-1 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-violet-500 outline-none transition-all" />
                              <button type="button" onClick={() => addVariantMedia(v.id)} disabled={!(variantMediaInput[v.id] || "").trim()}
                                className="px-2.5 py-1.5 bg-violet-600 text-white rounded-lg text-xs font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors">+</button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
            </div>
          </>
        )}
      </div>

      {/* Sales history */}
      <div className="card">
        <div className="px-4 py-3 border-b border-slate-200/60 bg-slate-50/50 flex items-center justify-between">
          <h2 className="font-semibold text-slate-900">История бронирований</h2>
          {!showSales && <button type="button" onClick={loadSales} className="text-xs text-indigo-600 hover:text-indigo-700 font-medium">Загрузить →</button>}
        </div>
        {showSales && sales && (
          <div className="p-4">
            <div className="flex gap-4 mb-4">
              <div className="bg-indigo-50 rounded-xl px-4 py-3 text-center">
                <p className="text-xl font-bold text-indigo-700">{sales.total_sold}</p>
                <p className="text-[10px] text-indigo-500">забронировано</p>
              </div>
              <div className="bg-emerald-50 rounded-xl px-4 py-3 text-center">
                <p className="text-xl font-bold text-emerald-700">{fmt(sales.total_revenue)}</p>
                <p className="text-[10px] text-emerald-500">выручка (сум)</p>
              </div>
            </div>
            {sales.orders.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-4">Нет бронирований</p>
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
                      <span className="text-slate-500">{o.qty} чел</span>
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
          <p className="text-xs text-slate-400 mt-0.5">По этим словам ИИ находит этот тур</p>
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
      <ConfirmDialog
        open={!!deleteVariantId}
        title="Удалить дату"
        message="Удалить эту дату отправления? Это действие нельзя отменить."
        confirmText="Удалить"
        variant="danger"
        onConfirm={() => { if (deleteVariantId) { deleteVariant(deleteVariantId); } setDeleteVariantId(null); }}
        onCancel={() => setDeleteVariantId(null)}
      />
    </div>
  );
}
