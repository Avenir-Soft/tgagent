"use client";

import { useState, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { formatPrice } from "@/lib/utils";

interface SpecAxes {
  color: string[];
  storage: string[] | null;
  ram: string[] | null;
  size: string[] | null;
}

interface AiResult {
  category: string;
  brand: string;
  model: string;
  description: string;
  spec_axes: SpecAxes;
  aliases: string[];
  base_title_template?: string;
  possible_duplicates?: { id: string; name: string }[];
}

interface VariantRow {
  id: string; // local temp ID
  color: string;
  storage: string;
  ram: string;
  size: string;
  price: string;
  quantity: string;
  enabled: boolean;
}

interface PhotoSlot {
  key: string; // "main" or color name
  label: string;
  file: File | null;
  preview: string | null;
}

interface SmartProductCreatorProps {
  onCreated: () => void;
  onClose: () => void;
}

let _rowId = 0;
function nextId() {
  return `row_${++_rowId}`;
}

export default function SmartProductCreator({ onCreated, onClose }: SmartProductCreatorProps) {
  const { toast } = useToast();

  // Step tracking
  const [step, setStep] = useState<"name" | "specs" | "variants" | "review">("name");

  // Step 1: Name
  const [productName, setProductName] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<AiResult | null>(null);

  // Step 2: Specs (editable AI result)
  const [category, setCategory] = useState("");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [description, setDescription] = useState("");

  // Spec axes with selection
  const [specAxes, setSpecAxes] = useState<SpecAxes>({ color: [], storage: null, ram: null, size: null });
  const [selectedSpecs, setSelectedSpecs] = useState<Record<string, Set<string>>>({});
  const [customSpecInput, setCustomSpecInput] = useState<Record<string, string>>({});

  // Step 3: Variants table
  const [variants, setVariants] = useState<VariantRow[]>([]);

  // Photos
  const [photos, setPhotos] = useState<PhotoSlot[]>([]);
  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  // Aliases
  const [aliases, setAliases] = useState<string[]>([]);
  const [newAlias, setNewAlias] = useState("");

  // Creating
  const [creating, setCreating] = useState(false);

  // ─── Step 1: AI Generate ───
  const handleAiGenerate = useCallback(async () => {
    if (!productName.trim()) return;
    setAiLoading(true);
    try {
      const result = await api.post<AiResult>("/products/ai-generate", { name: productName.trim() });

      setAiResult(result);
      setCategory(result.category || "");
      setBrand(result.brand || "");
      setModel(result.model || "");
      setDescription(result.description || "");
      setAliases(result.aliases || []);

      // Set spec axes and pre-select all
      setSpecAxes(result.spec_axes || { color: [], storage: null, ram: null, size: null });
      const sel: Record<string, Set<string>> = {};
      for (const [axis, values] of Object.entries(result.spec_axes || {})) {
        if (values && Array.isArray(values)) {
          sel[axis] = new Set(values);
        }
      }
      setSelectedSpecs(sel);

      if (result.possible_duplicates?.length) {
        toast(`Возможный дубль: ${result.possible_duplicates[0].name}`, "info");
      }

      setStep("specs");
    } catch (e: any) {
      toast(e?.message || "AI ошибка — попробуйте снова", "error");
    } finally {
      setAiLoading(false);
    }
  }, [productName, toast]);

  // ─── Step 2 → Step 3: Generate variants from specs ───
  const generateVariants = useCallback(() => {
    const colors = [...(selectedSpecs.color || [])];
    const storages = specAxes.storage ? [...(selectedSpecs.storage || [])] : [""];
    const rams = specAxes.ram ? [...(selectedSpecs.ram || [])] : [""];
    const sizes = specAxes.size ? [...(selectedSpecs.size || [])] : [""];

    if (colors.length === 0) colors.push("");

    const rows: VariantRow[] = [];
    for (const color of colors) {
      for (const storage of storages) {
        for (const ram of rams) {
          for (const size of sizes) {
            rows.push({
              id: nextId(),
              color,
              storage,
              ram,
              size,
              price: "",
              quantity: "",
              enabled: true,
            });
          }
        }
      }
    }
    setVariants(rows);

    // Build photo slots
    const slots: PhotoSlot[] = [{ key: "main", label: "Главное фото", file: null, preview: null }];
    const uniqueColors = [...new Set(colors.filter(Boolean))];
    for (const c of uniqueColors) {
      slots.push({ key: c, label: c, file: null, preview: null });
    }
    setPhotos(slots);

    setStep("variants");
  }, [selectedSpecs, specAxes]);

  // ─── Spec toggle ───
  const toggleSpec = (axis: string, value: string) => {
    setSelectedSpecs(prev => {
      const set = new Set(prev[axis] || []);
      if (set.has(value)) set.delete(value);
      else set.add(value);
      return { ...prev, [axis]: set };
    });
  };

  const addCustomSpec = (axis: string) => {
    const val = (customSpecInput[axis] || "").trim();
    if (!val) return;
    setSpecAxes(prev => {
      const existing = (prev as any)[axis] || [];
      if (existing.includes(val)) return prev;
      return { ...prev, [axis]: [...existing, val] };
    });
    setSelectedSpecs(prev => {
      const set = new Set(prev[axis] || []);
      set.add(val);
      return { ...prev, [axis]: set };
    });
    setCustomSpecInput(prev => ({ ...prev, [axis]: "" }));
  };

  // ─── Variant operations ───
  const updateVariant = (id: string, field: keyof VariantRow, value: string | boolean) => {
    setVariants(prev => prev.map(v => v.id === id ? { ...v, [field]: value } : v));
  };

  const duplicateVariant = (id: string) => {
    setVariants(prev => {
      const idx = prev.findIndex(v => v.id === id);
      if (idx === -1) return prev;
      const copy = { ...prev[idx], id: nextId() };
      const next = [...prev];
      next.splice(idx + 1, 0, copy);
      return next;
    });
  };

  const removeVariant = (id: string) => {
    setVariants(prev => prev.filter(v => v.id !== id));
  };

  const addVariantRow = () => {
    setVariants(prev => [...prev, {
      id: nextId(), color: "", storage: "", ram: "", size: "",
      price: "", quantity: "", enabled: true,
    }]);
  };

  // Quick fill — 3 independent filter axes
  const [quickField, setQuickField] = useState<"price" | "quantity">("price");
  const [qfColor, setQfColor] = useState("all");
  const [qfStorage, setQfStorage] = useState("all");
  const [qfRam, setQfRam] = useState("all");
  const [quickValue, setQuickValue] = useState("");

  const applyQuickFill = () => {
    if (!quickValue) return;
    setVariants(prev => prev.map(v => {
      if (!v.enabled) return v;
      if (qfColor !== "all" && v.color !== qfColor) return v;
      if (qfStorage !== "all" && v.storage !== qfStorage) return v;
      if (qfRam !== "all" && v.ram !== qfRam) return v;
      return { ...v, [quickField]: quickValue };
    }));
    setQuickValue("");
  };

  // ─── Photo handling ───
  const handlePhotoSelect = (key: string, file: File) => {
    const preview = URL.createObjectURL(file);
    setPhotos(prev => prev.map(p => p.key === key ? { ...p, file, preview } : p));
  };

  const removePhoto = (key: string) => {
    setPhotos(prev => prev.map(p => {
      if (p.key === key) {
        if (p.preview) URL.revokeObjectURL(p.preview);
        return { ...p, file: null, preview: null };
      }
      return p;
    }));
  };

  // ─── Alias management ───
  const addAlias = () => {
    const clean = newAlias.trim().toLowerCase();
    if (clean && !aliases.includes(clean)) {
      setAliases(prev => [...prev, clean]);
      setNewAlias("");
    }
  };

  const removeAlias = (a: string) => setAliases(prev => prev.filter(x => x !== a));

  // ─── Create product ───
  const handleCreate = useCallback(async () => {
    const enabledVariants = variants.filter(v => v.enabled);
    if (enabledVariants.length === 0) {
      toast("Добавьте хотя бы один вариант", "error");
      return;
    }

    const missingPrices = enabledVariants.filter(v => !v.price || Number(v.price) <= 0);
    if (missingPrices.length > 0) {
      toast(`Заполните цену для ${missingPrices.length} вариантов`, "error");
      return;
    }

    setCreating(true);
    try {
      // Build photo mapping
      const photoMapping: Record<string, any> = {};
      const photoFiles: File[] = [];
      let photoIdx = 0;

      for (const slot of photos) {
        if (slot.file) {
          const key = `photo_${photoIdx}`;
          if (slot.key === "main") {
            photoMapping.main = key;
          } else {
            if (!photoMapping.colors) photoMapping.colors = {};
            photoMapping.colors[slot.key] = key;
          }
          photoFiles.push(slot.file);
          photoIdx++;
        }
      }

      const payload = {
        name: productName.trim(),
        brand: brand.trim() || null,
        model: model.trim() || null,
        description: description.trim() || null,
        category_name: category.trim() || null,
        variants: enabledVariants.map(v => ({
          color: v.color || null,
          storage: v.storage || null,
          ram: v.ram || null,
          size: v.size || null,
          price: Number(v.price),
          quantity: Number(v.quantity) || 0,
        })),
        aliases,
        photo_mapping: photoMapping,
      };

      const formData = new FormData();
      formData.append("payload", JSON.stringify(payload));
      for (const f of photoFiles) {
        formData.append("photos", f);
      }

      const resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001"}/products/smart-create`, {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
        body: formData,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Error ${resp.status}`);
      }

      toast(`${productName} создан!`, "success");
      onCreated();
    } catch (e: any) {
      toast(e?.message || "Ошибка создания", "error");
    } finally {
      setCreating(false);
    }
  }, [variants, photos, productName, brand, model, description, category, aliases, toast, onCreated]);

  // ─── Count helpers ───
  const enabledCount = variants.filter(v => v.enabled).length;
  const photosCount = photos.filter(p => p.file).length;
  const hasAllPrices = variants.filter(v => v.enabled).every(v => v.price && Number(v.price) > 0);

  // ════════════════════ RENDER ════════════════════

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm overflow-y-auto py-8" onClick={onClose}>
      <div className="w-full max-w-4xl mx-4 card p-0 animate-slide-up" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200/60">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Умное создание товара</h2>
            <p className="text-xs text-slate-400 mt-0.5">AI заполнит всё автоматически</p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600 transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 px-6 py-3 bg-slate-50/50 border-b border-slate-100">
          {[
            { key: "name", label: "Название" },
            { key: "specs", label: "Спеки" },
            { key: "variants", label: "Варианты и фото" },
          ].map((s, i) => {
            const steps = ["name", "specs", "variants"];
            const current = steps.indexOf(step);
            const thisIdx = steps.indexOf(s.key);
            const isDone = thisIdx < current;
            const isCurrent = thisIdx === current;
            return (
              <div key={s.key} className="flex items-center gap-2 flex-1">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                  isDone ? "bg-emerald-100 text-emerald-700" :
                  isCurrent ? "bg-indigo-600 text-white" : "bg-slate-200 text-slate-400"
                }`}>
                  {isDone ? "✓" : i + 1}
                </div>
                <span className={`text-xs font-medium ${isCurrent ? "text-slate-900" : "text-slate-400"}`}>{s.label}</span>
                {i < 2 && <div className={`flex-1 h-px ${isDone ? "bg-emerald-200" : "bg-slate-200"}`} />}
              </div>
            );
          })}
        </div>

        <div className="p-6 max-h-[calc(100vh-200px)] overflow-y-auto">
          {/* ════ STEP 1: Name Input ════ */}
          {step === "name" && (
            <div className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Что продаёте?</label>
                <div className="flex gap-3">
                  <input
                    type="text"
                    value={productName}
                    onChange={e => setProductName(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && handleAiGenerate()}
                    placeholder="Например: iPhone 15 Pro, Samsung Galaxy S24, AirPods Pro 2..."
                    className="flex-1 bg-white border border-slate-200 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                    autoFocus
                  />
                  <button
                    type="button"
                    onClick={handleAiGenerate}
                    disabled={!productName.trim() || aiLoading}
                    className="px-6 py-3 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2 shrink-0"
                  >
                    {aiLoading ? (
                      <>
                        <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" /><path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" className="opacity-75" /></svg>
                        AI думает...
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" /></svg>
                        AI заполнит
                      </>
                    )}
                  </button>
                </div>
                <p className="text-xs text-slate-400 mt-2">Введите название — AI определит категорию, бренд, варианты и алиасы</p>
              </div>

              {/* Manual fallback */}
              <div className="border-t border-slate-100 pt-4">
                <button
                  type="button"
                  onClick={() => {
                    setStep("specs");
                    setSpecAxes({ color: [], storage: null, ram: null, size: null });
                    setSelectedSpecs({});
                  }}
                  className="text-sm text-slate-500 hover:text-indigo-600 transition-colors"
                >
                  или заполнить вручную без AI →
                </button>
              </div>
            </div>
          )}

          {/* ════ STEP 2: Specs Selection ════ */}
          {step === "specs" && (
            <div className="space-y-6">
              {/* Editable product info */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">Категория</label>
                  <input type="text" value={category} onChange={e => setCategory(e.target.value)}
                    className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">Бренд</label>
                  <input type="text" value={brand} onChange={e => setBrand(e.target.value)}
                    className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">Модель</label>
                  <input type="text" value={model} onChange={e => setModel(e.target.value)}
                    className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Описание</label>
                <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none resize-none" />
              </div>

              {/* Spec axes selection */}
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-800">Что есть в наличии?</h3>

                {(["color", "storage", "ram", "size"] as const).map(axis => {
                  const values = specAxes[axis];
                  if (!values || values.length === 0) return null;
                  const labels: Record<string, string> = { color: "Цвета", storage: "Память", ram: "RAM", size: "Размер" };
                  return (
                    <div key={axis}>
                      <label className="block text-xs font-medium text-slate-500 mb-2">{labels[axis]}</label>
                      <div className="flex flex-wrap gap-2">
                        {values.map(v => {
                          const isSelected = selectedSpecs[axis]?.has(v);
                          return (
                            <button
                              key={v}
                              type="button"
                              onClick={() => toggleSpec(axis, v)}
                              className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                                isSelected
                                  ? "bg-indigo-50 border-indigo-300 text-indigo-700 shadow-sm"
                                  : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"
                              }`}
                            >
                              {isSelected && <span className="mr-1">✓</span>}
                              {v}
                            </button>
                          );
                        })}
                        {/* Add custom */}
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            value={customSpecInput[axis] || ""}
                            onChange={e => setCustomSpecInput(p => ({ ...p, [axis]: e.target.value }))}
                            onKeyDown={e => e.key === "Enter" && addCustomSpec(axis)}
                            placeholder="+"
                            className="w-20 px-2 py-1.5 border border-dashed border-slate-300 rounded-lg text-sm text-center focus:ring-1 focus:ring-indigo-500 outline-none"
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}

                {/* Add new spec axis */}
                {!specAxes.storage && (
                  <button type="button" onClick={() => setSpecAxes(p => ({ ...p, storage: [] }))}
                    className="text-xs text-indigo-600 hover:text-indigo-700">+ Добавить Память</button>
                )}
                {!specAxes.ram && (
                  <button type="button" onClick={() => setSpecAxes(p => ({ ...p, ram: [] }))}
                    className="text-xs text-indigo-600 hover:text-indigo-700 ml-3">+ Добавить RAM</button>
                )}
                {!specAxes.size && (
                  <button type="button" onClick={() => setSpecAxes(p => ({ ...p, size: [] }))}
                    className="text-xs text-indigo-600 hover:text-indigo-700 ml-3">+ Добавить Размер</button>
                )}
              </div>

              {/* Navigation */}
              <div className="flex items-center justify-between pt-4 border-t border-slate-100">
                <button type="button" onClick={() => setStep("name")}
                  className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 transition-colors">← Назад</button>
                <button
                  type="button"
                  onClick={generateVariants}
                  className="px-6 py-2.5 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 transition-colors"
                >
                  Сгенерировать варианты →
                </button>
              </div>
            </div>
          )}

          {/* ════ STEP 3: Variants + Photos + Aliases ════ */}
          {step === "variants" && (
            <div className="space-y-6">
              {/* Variants table */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-slate-800">
                    Варианты <span className="text-slate-400 font-normal">({enabledCount} шт)</span>
                  </h3>
                  <button type="button" onClick={addVariantRow}
                    className="text-xs text-indigo-600 hover:text-indigo-700 font-medium">+ Добавить строку</button>
                </div>

                {/* Quick fill bar */}
                <div className="flex flex-wrap items-center gap-2 mb-3 p-3 bg-slate-50 rounded-xl">
                  <span className="text-xs text-slate-500 shrink-0">Быстро:</span>
                  <select value={quickField} onChange={e => setQuickField(e.target.value as any)}
                    className="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white">
                    <option value="price">Цена</option>
                    <option value="quantity">Кол-во</option>
                  </select>
                  <span className="text-xs text-slate-400">для</span>
                  {/* Color filter */}
                  {specAxes.color && specAxes.color.length > 1 && (
                    <select value={qfColor} onChange={e => setQfColor(e.target.value)}
                      className="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white">
                      <option value="all">Все цвета</option>
                      {[...new Set(variants.map(v => v.color).filter(Boolean))].map(c =>
                        <option key={c} value={c}>{c}</option>
                      )}
                    </select>
                  )}
                  {/* Storage filter */}
                  {specAxes.storage && specAxes.storage.length > 1 && (
                    <select value={qfStorage} onChange={e => setQfStorage(e.target.value)}
                      className="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white">
                      <option value="all">Вся память</option>
                      {[...new Set(variants.map(v => v.storage).filter(Boolean))].map(s =>
                        <option key={s} value={s}>{s}</option>
                      )}
                    </select>
                  )}
                  {/* RAM filter */}
                  {specAxes.ram && specAxes.ram.length > 1 && (
                    <select value={qfRam} onChange={e => setQfRam(e.target.value)}
                      className="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white">
                      <option value="all">Весь RAM</option>
                      {[...new Set(variants.map(v => v.ram).filter(Boolean))].map(r =>
                        <option key={r} value={r}>{r}</option>
                      )}
                    </select>
                  )}
                  <span className="text-xs text-slate-400">=</span>
                  <input type="text" value={quickValue ? formatPrice(quickValue) : ""} onChange={e => setQuickValue(e.target.value.replace(/[^0-9]/g, ""))}
                    onKeyDown={e => e.key === "Enter" && applyQuickFill()}
                    placeholder={quickField === "price" ? "15.200.000" : "5"}
                    className="w-32 text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white outline-none focus:ring-1 focus:ring-indigo-500" />
                  <button type="button" onClick={applyQuickFill}
                    className="text-xs bg-indigo-100 text-indigo-700 px-3 py-1 rounded-lg hover:bg-indigo-200 font-medium">Применить</button>
                </div>

                {/* Desktop table */}
                <div className="hidden md:block overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-slate-500 border-b border-slate-100">
                        <th className="py-2 px-2 text-left w-8">✓</th>
                        {specAxes.color?.length ? <th className="py-2 px-2 text-left">Цвет</th> : null}
                        {specAxes.storage ? <th className="py-2 px-2 text-left">Память</th> : null}
                        {specAxes.ram ? <th className="py-2 px-2 text-left">RAM</th> : null}
                        {specAxes.size ? <th className="py-2 px-2 text-left">Размер</th> : null}
                        <th className="py-2 px-2 text-left">Цена (сум)</th>
                        <th className="py-2 px-2 text-left">Кол-во</th>
                        <th className="py-2 px-2 text-center w-20"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {variants.map(v => (
                        <tr key={v.id} className={`border-b border-slate-50 ${!v.enabled ? "opacity-40" : ""}`}>
                          <td className="py-1.5 px-2">
                            <input type="checkbox" checked={v.enabled} onChange={() => updateVariant(v.id, "enabled", !v.enabled)}
                              className="w-4 h-4 rounded border-slate-300 text-indigo-600" />
                          </td>
                          {specAxes.color?.length ? (
                            <td className="py-1.5 px-2">
                              <input type="text" value={v.color} onChange={e => updateVariant(v.id, "color", e.target.value)}
                                className="w-full bg-transparent border-b border-transparent hover:border-slate-200 focus:border-indigo-400 py-0.5 text-sm outline-none" />
                            </td>
                          ) : null}
                          {specAxes.storage ? (
                            <td className="py-1.5 px-2">
                              <input type="text" value={v.storage} onChange={e => updateVariant(v.id, "storage", e.target.value)}
                                className="w-full bg-transparent border-b border-transparent hover:border-slate-200 focus:border-indigo-400 py-0.5 text-sm outline-none" />
                            </td>
                          ) : null}
                          {specAxes.ram ? (
                            <td className="py-1.5 px-2">
                              <input type="text" value={v.ram} onChange={e => updateVariant(v.id, "ram", e.target.value)}
                                className="w-full bg-transparent border-b border-transparent hover:border-slate-200 focus:border-indigo-400 py-0.5 text-sm outline-none" />
                            </td>
                          ) : null}
                          {specAxes.size ? (
                            <td className="py-1.5 px-2">
                              <input type="text" value={v.size} onChange={e => updateVariant(v.id, "size", e.target.value)}
                                className="w-full bg-transparent border-b border-transparent hover:border-slate-200 focus:border-indigo-400 py-0.5 text-sm outline-none" />
                            </td>
                          ) : null}
                          <td className="py-1.5 px-2">
                            <input type="text" value={v.price ? formatPrice(v.price) : ""} onChange={e => updateVariant(v.id, "price", e.target.value.replace(/[^0-9]/g, ""))}
                              placeholder="0"
                              className="w-full bg-transparent border-b border-slate-200 focus:border-indigo-400 py-0.5 text-sm outline-none font-mono" />
                          </td>
                          <td className="py-1.5 px-2">
                            <input type="text" value={v.quantity} onChange={e => updateVariant(v.id, "quantity", e.target.value.replace(/[^0-9]/g, ""))}
                              placeholder="0"
                              className="w-16 bg-transparent border-b border-slate-200 focus:border-indigo-400 py-0.5 text-sm outline-none font-mono" />
                          </td>
                          <td className="py-1.5 px-2 text-center">
                            <button type="button" onClick={() => duplicateVariant(v.id)} title="Дублировать"
                              className="text-slate-400 hover:text-indigo-600 transition-colors p-1">
                              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75" />
                              </svg>
                            </button>
                            <button type="button" onClick={() => removeVariant(v.id)} title="Удалить"
                              className="text-slate-400 hover:text-rose-500 transition-colors p-1">
                              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Mobile cards */}
                <div className="md:hidden space-y-3">
                  {variants.map(v => (
                    <div key={v.id} className={`rounded-xl border border-slate-200 p-3 space-y-2 ${!v.enabled ? "opacity-40" : ""}`}>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <input type="checkbox" checked={v.enabled} onChange={() => updateVariant(v.id, "enabled", !v.enabled)}
                            className="w-4 h-4 rounded border-slate-300 text-indigo-600" />
                          <span className="text-sm font-medium text-slate-700">
                            {[v.color, v.storage, v.ram, v.size].filter(Boolean).join(" · ") || "Стандарт"}
                          </span>
                        </div>
                        <div className="flex gap-1">
                          <button type="button" onClick={() => duplicateVariant(v.id)} className="text-slate-400 hover:text-indigo-600 p-1">
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75" /></svg>
                          </button>
                          <button type="button" onClick={() => removeVariant(v.id)} className="text-slate-400 hover:text-rose-500 p-1">
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path d="M6 18L18 6M6 6l12 12" /></svg>
                          </button>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="text-[10px] text-slate-400 uppercase">Цена</label>
                          <input type="text" value={v.price ? formatPrice(v.price) : ""} onChange={e => updateVariant(v.id, "price", e.target.value.replace(/[^0-9]/g, ""))}
                            placeholder="0" className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm font-mono outline-none focus:ring-1 focus:ring-indigo-500" />
                        </div>
                        <div>
                          <label className="text-[10px] text-slate-400 uppercase">Кол-во</label>
                          <input type="text" value={v.quantity} onChange={e => updateVariant(v.id, "quantity", e.target.value.replace(/[^0-9]/g, ""))}
                            placeholder="0" className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm font-mono outline-none focus:ring-1 focus:ring-indigo-500" />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Photos */}
              <div>
                <h3 className="text-sm font-semibold text-slate-800 mb-3">
                  Фото <span className="text-slate-400 font-normal">({photosCount} загружено)</span>
                </h3>
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                  {photos.map(slot => (
                    <div key={slot.key} className="space-y-1">
                      <label className="text-xs text-slate-500 font-medium">{slot.label}</label>
                      {slot.preview ? (
                        <div className="relative group">
                          <img src={slot.preview} alt={slot.label} className="w-full aspect-square object-cover rounded-xl border border-slate-200" />
                          <button
                            type="button"
                            onClick={() => removePhoto(slot.key)}
                            className="absolute top-1 right-1 w-6 h-6 bg-rose-500 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity text-xs"
                          >✕</button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => fileInputRefs.current[slot.key]?.click()}
                          className="w-full aspect-square border-2 border-dashed border-slate-300 rounded-xl flex flex-col items-center justify-center text-slate-400 hover:border-indigo-400 hover:text-indigo-500 transition-colors"
                        >
                          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                            <path d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
                          </svg>
                          <span className="text-[10px] mt-1">Загрузить</span>
                        </button>
                      )}
                      <input
                        ref={el => { fileInputRefs.current[slot.key] = el; }}
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={e => {
                          const f = e.target.files?.[0];
                          if (f) handlePhotoSelect(slot.key, f);
                          e.target.value = "";
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>

              {/* Aliases */}
              <div>
                <h3 className="text-sm font-semibold text-slate-800 mb-2">
                  Алиасы для поиска <span className="text-slate-400 font-normal">({aliases.length})</span>
                </h3>
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {aliases.map(a => (
                    <span key={a} className="inline-flex items-center gap-1 px-2 py-1 bg-slate-100 text-slate-600 rounded-lg text-xs">
                      {a}
                      <button type="button" onClick={() => removeAlias(a)} className="text-slate-400 hover:text-rose-500 ml-0.5">✕</button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newAlias}
                    onChange={e => setNewAlias(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && (e.preventDefault(), addAlias())}
                    placeholder="Добавить алиас..."
                    className="flex-1 border border-slate-200 rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                  <button type="button" onClick={addAlias} className="text-xs text-indigo-600 hover:text-indigo-700 font-medium px-3">+ Добавить</button>
                </div>
              </div>

              {/* Summary + Create */}
              <div className="bg-gradient-to-br from-indigo-50 to-violet-50 rounded-xl p-4 border border-indigo-100">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center mb-4">
                  <div>
                    <div className="text-lg font-bold text-indigo-700">{enabledCount}</div>
                    <div className="text-[10px] text-slate-500 uppercase">Вариантов</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold text-indigo-700">{photosCount}</div>
                    <div className="text-[10px] text-slate-500 uppercase">Фото</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold text-indigo-700">{aliases.length}</div>
                    <div className="text-[10px] text-slate-500 uppercase">Алиасов</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold text-indigo-700">
                      {variants.filter(v => v.enabled).reduce((s, v) => s + (Number(v.quantity) || 0), 0)}
                    </div>
                    <div className="text-[10px] text-slate-500 uppercase">Общий склад</div>
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <button type="button" onClick={() => setStep("specs")}
                    className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 transition-colors">← Назад</button>
                  <button
                    type="button"
                    onClick={handleCreate}
                    disabled={creating || enabledCount === 0 || !hasAllPrices}
                    className="px-8 py-3 bg-indigo-600 text-white rounded-xl text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm flex items-center gap-2"
                  >
                    {creating ? (
                      <>
                        <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" /><path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" className="opacity-75" /></svg>
                        Создаю...
                      </>
                    ) : (
                      <>Создать товар</>
                    )}
                  </button>
                </div>
                {!hasAllPrices && enabledCount > 0 && (
                  <p className="text-xs text-amber-600 text-center mt-2">Заполните цену для всех вариантов</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
