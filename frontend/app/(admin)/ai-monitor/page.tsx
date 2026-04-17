"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/lib/api";

/* ── Types ───────────────────────────────────────────────── */

interface TraceStep {
  type: string;
  label: string;
  detail: string;
  duration_ms: number;
  timestamp: number;
}

interface AITrace {
  trace_id: string;
  conversation_id: string;
  user_message: string;
  detected_language: string;
  steps: TraceStep[];
  final_response: string;
  image_urls: string[];
  total_duration_ms: number;
  timestamp: number;
  tools_called: string[];
  model: string;
  state_before: string;
  state_after: string;
  prompt_tokens?: number;
  completion_tokens?: number;
}

/* ── Config ──────────────────────────────────────────────── */

const stepMeta: Record<string, { color: string; icon: string; label: string }> = {
  tool_call:   { color: "indigo",  icon: "\u25B6", label: "Call" },
  tool_result: { color: "emerald", icon: "\u25C0", label: "Result" },
  llm_call:    { color: "violet",  icon: "\u2726", label: "LLM" },
  photo:       { color: "amber",   icon: "\u25A3", label: "Photo" },
  guard:       { color: "rose",    icon: "\u25C6", label: "Guard" },
  state:       { color: "cyan",    icon: "\u25CB", label: "State" },
  info:        { color: "slate",   icon: "\u2022", label: "Info" },
};

const colorMap: Record<string, { bg: string; text: string; border: string; ring: string; dot: string }> = {
  indigo:  { bg: "bg-indigo-500/10",  text: "text-indigo-400",  border: "border-indigo-500/20",  ring: "ring-indigo-500/30",  dot: "bg-indigo-400" },
  emerald: { bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/20", ring: "ring-emerald-500/30", dot: "bg-emerald-400" },
  violet:  { bg: "bg-violet-500/10",  text: "text-violet-400",  border: "border-violet-500/20",  ring: "ring-violet-500/30",  dot: "bg-violet-400" },
  amber:   { bg: "bg-amber-500/10",   text: "text-amber-400",   border: "border-amber-500/20",   ring: "ring-amber-500/30",   dot: "bg-amber-400" },
  rose:    { bg: "bg-rose-500/10",    text: "text-rose-400",    border: "border-rose-500/20",    ring: "ring-rose-500/30",    dot: "bg-rose-400" },
  cyan:    { bg: "bg-cyan-500/10",    text: "text-cyan-400",    border: "border-cyan-500/20",    ring: "ring-cyan-500/30",    dot: "bg-cyan-400" },
  slate:   { bg: "bg-slate-500/10",   text: "text-slate-400",   border: "border-slate-500/20",   ring: "ring-slate-500/30",   dot: "bg-slate-500" },
};

function getStep(type: string) {
  const m = stepMeta[type] || stepMeta.info;
  return { ...m, ...colorMap[m.color] };
}

const PAGE_SIZE = 30;

/* ── Model Pricing (USD per 1M tokens) ──────────────────── */

const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  "gpt-4o-mini":     { input: 0.15,  output: 0.60 },
  "gpt-4o":          { input: 2.50,  output: 10.00 },
  "gpt-4-turbo":     { input: 10.00, output: 30.00 },
  "gpt-4":           { input: 30.00, output: 60.00 },
  "gpt-3.5-turbo":   { input: 0.50,  output: 1.50 },
};

function calcCost(model: string, promptTokens: number, completionTokens: number): number {
  const p = MODEL_PRICING[model] || MODEL_PRICING["gpt-4o-mini"];
  return (promptTokens * p.input + completionTokens * p.output) / 1_000_000;
}

function fmtCost(usd: number): string {
  if (usd < 0.001) return `$${(usd * 100).toFixed(4)}¢`;
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

/* ── Daily Stats Types ──────────────────────────────────── */

interface DailyStat {
  date: string;
  count: number;
  prompt_tokens: number;
  completion_tokens: number;
  avg_duration_ms: number;
}

/* ── Helpers ─────────────────────────────────────────────── */

function fmtDate(ts: number) {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" }) + " " +
         d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtMs(ms: number) {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtPrice(raw: string | number) {
  const n = typeof raw === "string" ? parseFloat(raw) : raw;
  if (isNaN(n)) return String(raw);
  return new Intl.NumberFormat("ru-RU").format(Math.round(n)) + " сум";
}

function fmtTokens(n: number) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function safeParse(text: string): unknown | null {
  const raw = text.startsWith("args: ") ? text.slice(6) : text;
  // Try direct parse
  try { return JSON.parse(raw); } catch {}
  // Try to repair truncated JSON — close open brackets/braces
  try {
    let fixed = raw;
    const opens = (fixed.match(/[\[{]/g) || []).length;
    const closes = (fixed.match(/[\]}]/g) || []).length;
    // Trim trailing partial value (after last comma or colon)
    fixed = fixed.replace(/,\s*"[^"]*$/, "").replace(/,\s*$/, "").replace(/:\s*"[^"]*$/, ': ""');
    for (let i = 0; i < opens - closes; i++) {
      const lastOpen = Math.max(fixed.lastIndexOf("["), fixed.lastIndexOf("{"));
      fixed += fixed[lastOpen] === "[" ? "]" : "}";
    }
    return JSON.parse(fixed);
  } catch {}
  return null;
}

/** Extract structured info from truncated/unparseable text via regex */
function extractFromText(text: string): { variants: AnyObj[]; products: AnyObj[]; found?: boolean } | null {
  const titles = [...text.matchAll(/"title":\s*"([^"]+)"/g)].map(m => m[1]);
  if (titles.length === 0) return null;
  const colors = [...text.matchAll(/"color":\s*"([^"]+)"/g)].map(m => m[1]);
  const prices = [...text.matchAll(/"price":\s*"([^"]+)"/g)].map(m => m[1]);
  const stocks = [...text.matchAll(/"in_stock":\s*(true|false)/g)].map(m => m[1] === "true");
  const storages = [...text.matchAll(/"storage":\s*"([^"]+)"/g)].map(m => m[1]);
  const found = text.includes('"found": true') || text.includes('"found":true');

  const variants = titles.map((t, i) => ({
    title: t,
    color: colors[i] || "",
    price: prices[i] || "",
    in_stock: stocks[i] ?? true,
    storage: storages[i] || "",
  }));
  return { variants, products: [], found };
}

/** Detect anomaly/error steps in trace */
function getTraceErrors(trace: AITrace): string[] {
  const errors: string[] = [];
  for (const s of trace.steps) {
    if (s.type === "guard" && s.label.includes("Anomaly")) errors.push(s.detail);
    if (s.type === "guard" && s.label.includes("Hallucination")) errors.push("Hallucination corrected");
    if (s.type === "guard" && s.label.includes("BLOCKED")) errors.push(s.label);
    if (s.type === "guard" && s.label.includes("Profanity")) errors.push("Profanity detected");
    if (s.type === "info" && s.detail.includes("ERROR")) errors.push(s.detail);
  }
  return errors;
}

const langLabels: Record<string, string> = {
  ru: "Русский", uz_cyrillic: "Узбекский (кир.)", uz_latin: "O'zbek (lot.)", en: "English",
};

/* ── Smart Renderers ─────────────────────────────────────── */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyObj = Record<string, any>;

function KV({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-2 min-w-0">
      <span className="text-[10px] uppercase tracking-wider text-slate-500 flex-shrink-0">{label}</span>
      <span className={`text-xs text-slate-300 truncate ${mono ? "font-mono" : ""}`}>{children}</span>
    </div>
  );
}

function Badge({ children, color = "slate" }: { children: React.ReactNode; color?: string }) {
  const c = colorMap[color] || colorMap.slate;
  return <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full ${c.bg} ${c.text} ${c.border} border`}>{children}</span>;
}

function VariantsView({ variants }: { variants: Array<AnyObj> }) {
  return (
    <div className="space-y-2">
      {variants.map((v, i) => (
        <div key={i} className="flex items-center gap-3 bg-slate-800/40 rounded-lg px-3 py-2 border border-slate-700/30">
          {/* Color dot */}
          <div className="flex-shrink-0">
            <div className="w-3 h-3 rounded-full border border-slate-600" style={{
              backgroundColor: String(v.color || "").toLowerCase().includes("black") ? "#1a1a2e" :
                String(v.color || "").toLowerCase().includes("natural") ? "#d4c5a9" :
                String(v.color || "").toLowerCase().includes("gold") ? "#ffd700" :
                String(v.color || "").toLowerCase().includes("silver") ? "#c0c0c0" :
                String(v.color || "").toLowerCase().includes("blue") ? "#4a90d9" :
                String(v.color || "").toLowerCase().includes("white") ? "#f5f5f5" :
                String(v.color || "").toLowerCase().includes("red") ? "#dc2626" :
                String(v.color || "").toLowerCase().includes("green") ? "#22c55e" :
                String(v.color || "").toLowerCase().includes("purple") ? "#7c3aed" :
                "#6b7280"
            }} />
          </div>
          {/* Info */}
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-slate-200 truncate">{String(v.title || v.name || "Variant")}</p>
            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
              {v.color && <span className="text-[10px] text-slate-400">{String(v.color)}</span>}
              {v.storage && <span className="text-[10px] text-slate-500">{String(v.storage)}</span>}
              {v.ram && <span className="text-[10px] text-slate-500">{String(v.ram)}</span>}
            </div>
          </div>
          {/* Price */}
          {v.price && (
            <span className="text-xs font-mono font-medium text-emerald-400 flex-shrink-0">
              {fmtPrice(v.price as string)}
            </span>
          )}
          {/* Stock */}
          {v.in_stock !== undefined && (
            <Badge color={v.in_stock ? "emerald" : "rose"}>
              {v.in_stock ? "В наличии" : "Нет"}
            </Badge>
          )}
          {/* Photos */}
          {(v.photo_count || (v.image_urls && Array.isArray(v.image_urls) && (v.image_urls as string[]).length > 0)) && (
            <span className="text-[10px] text-amber-400">
              {String(v.photo_count || (v.image_urls as string[])?.length || 0)} фото
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function ProductsView({ products }: { products: Array<AnyObj> }) {
  return (
    <div className="space-y-1.5">
      {products.map((p, i) => (
        <div key={i} className="flex items-center gap-3 bg-slate-800/40 rounded-lg px-3 py-2 border border-slate-700/30">
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-slate-200 truncate">{String(p.name || "Product")}</p>
            <div className="flex items-center gap-2 mt-0.5">
              {p.brand && <span className="text-[10px] text-slate-500">{String(p.brand)}</span>}
              {p.category && <span className="text-[10px] text-slate-500">{String(p.category)}</span>}
            </div>
          </div>
          {p.price_range && <span className="text-[10px] font-mono text-emerald-400">{String(p.price_range)}</span>}
          {p.total_variants !== undefined && <span className="text-[10px] text-slate-500">{String(p.total_variants)} вар.</span>}
          {p.photo_available && <span className="text-[10px] text-amber-400">Фото</span>}
        </div>
      ))}
    </div>
  );
}

function OrderView({ data }: { data: AnyObj }) {
  return (
    <div className="bg-slate-800/40 rounded-lg px-3 py-2 border border-slate-700/30 space-y-1">
      {data.order_number && <KV label="Заказ" mono>#{String(data.order_number)}</KV>}
      {data.status && <KV label="Статус"><Badge color={data.status === "draft" ? "amber" : data.status === "confirmed" ? "emerald" : "slate"}>{String(data.status)}</Badge></KV>}
      {data.total_price && <KV label="Сумма" mono>{fmtPrice(data.total_price as string)}</KV>}
      {data.customer_name && <KV label="Клиент">{String(data.customer_name)}</KV>}
    </div>
  );
}

function CartView({ data }: { data: AnyObj }) {
  return (
    <div className="bg-slate-800/40 rounded-lg px-3 py-2 border border-slate-700/30 space-y-1">
      {data.title && <KV label="Товар">{String(data.title)}</KV>}
      {data.variant && <KV label="Вариант">{String(data.variant)}</KV>}
      {data.price && <KV label="Цена" mono>{fmtPrice(data.price as string)}</KV>}
      {data.quantity && <KV label="Кол-во">{String(data.quantity)}</KV>}
      {data.success !== undefined && <Badge color={data.success ? "emerald" : "rose"}>{data.success ? "Добавлено" : "Ошибка"}</Badge>}
    </div>
  );
}

function PrettyJSON({ data }: { data: unknown }) {
  return (
    <pre className="p-3 bg-black/30 text-[11px] font-mono rounded-lg overflow-x-auto max-h-56 whitespace-pre-wrap break-words border border-slate-700/30 text-slate-300 leading-relaxed">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function SmartDetail({ step }: { step: TraceStep }) {
  const data = safeParse(step.detail);
  const toolName = step.label.replace("← ", "");

  // Tool call args
  if (step.type === "tool_call" && data && typeof data === "object") {
    const obj = data as AnyObj;
    return (
      <div className="mt-2 mb-3 flex flex-wrap gap-2">
        {Object.entries(obj).map(([k, v]) => (
          <div key={k} className="inline-flex items-center gap-1.5 bg-indigo-500/5 border border-indigo-500/15 rounded-lg px-2.5 py-1.5">
            <span className="text-[10px] text-indigo-400/70 uppercase">{k}</span>
            <span className="text-xs font-mono text-indigo-300">{typeof v === "string" ? (v.length > 24 ? v.slice(0, 8) + "..." + v.slice(-8) : v) : JSON.stringify(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  // Tool result — smart render based on content
  if (step.type === "tool_result" && data && typeof data === "object") {
    const obj = data as AnyObj;
    return (
      <div className="mt-2 mb-3 space-y-2">
        {/* Status header */}
        <div className="flex items-center gap-2 flex-wrap">
          {obj.found !== undefined && (
            <Badge color={obj.found ? "emerald" : "rose"}>{obj.found ? "Найдено" : "Не найдено"}</Badge>
          )}
          {obj.success !== undefined && (
            <Badge color={obj.success ? "emerald" : "rose"}>{obj.success ? "Успешно" : "Ошибка"}</Badge>
          )}
          {obj.error && <Badge color="rose">{String(obj.error).slice(0, 60)}</Badge>}
          {Array.isArray(obj.variants) && <span className="text-[10px] text-slate-500">{obj.variants.length} вариант(ов)</span>}
          {Array.isArray(obj.products) && <span className="text-[10px] text-slate-500">{obj.products.length} товар(ов)</span>}
          {obj.photos_attached !== undefined && <span className="text-[10px] text-amber-400">{String(obj.photos_attached)} фото прикреплено</span>}
        </div>

        {/* Variants */}
        {Array.isArray(obj.variants) && obj.variants.length > 0 && (
          <VariantsView variants={obj.variants as Array<AnyObj>} />
        )}

        {/* Products */}
        {Array.isArray(obj.products) && obj.products.length > 0 && (
          <ProductsView products={obj.products as Array<AnyObj>} />
        )}

        {/* Out of stock products */}
        {Array.isArray(obj.out_of_stock_products) && obj.out_of_stock_products.length > 0 && (
          <>
            <p className="text-[10px] text-rose-400 uppercase tracking-wider mt-2">Нет в наличии</p>
            <ProductsView products={obj.out_of_stock_products as Array<AnyObj>} />
          </>
        )}

        {/* Order-related */}
        {(obj.order_number || obj.order_id) && <OrderView data={obj} />}

        {/* Cart-related */}
        {obj.title && obj.variant && <CartView data={obj} />}

        {/* Delivery rules */}
        {Array.isArray(obj.rules) && (
          <div className="space-y-1">
            {(obj.rules as Array<AnyObj>).map((r, i) => (
              <div key={i} className="flex items-center gap-2 bg-slate-800/40 rounded-lg px-3 py-1.5 border border-slate-700/30 text-xs">
                <span className="text-slate-300">{String(r.city || r.region || "")}</span>
                <span className="text-emerald-400 font-mono ml-auto">{r.price ? fmtPrice(r.price as string) : "Бесплатно"}</span>
                {r.estimated_days && <span className="text-slate-500">{String(r.estimated_days)} дн.</span>}
              </div>
            ))}
          </div>
        )}

        {/* Fallback: if none of the smart renderers matched, show JSON */}
        {!obj.variants && !obj.products && !obj.out_of_stock_products && !obj.order_number && !obj.order_id && !(obj.title && obj.variant) && !obj.rules && (
          <PrettyJSON data={obj} />
        )}
      </div>
    );
  }

  // Photo steps — show key info
  if (step.type === "photo") {
    return (
      <div className="mt-1 mb-2">
        <span className="text-xs text-amber-400/80">{step.detail}</span>
      </div>
    );
  }

  // tool_result without parsed data — try regex extraction
  if (step.type === "tool_result" && !data) {
    const extracted = extractFromText(step.detail);
    if (extracted && extracted.variants.length > 0) {
      return (
        <div className="mt-2 mb-3 space-y-2">
          <div className="flex items-center gap-2">
            {extracted.found !== undefined && <Badge color={extracted.found ? "emerald" : "rose"}>{extracted.found ? "Найдено" : "Не найдено"}</Badge>}
            <span className="text-[10px] text-slate-600 italic">restored from truncated data</span>
          </div>
          <VariantsView variants={extracted.variants} />
        </div>
      );
    }
  }

  // Generic fallback
  if (!step.detail) return null;
  if (data) {
    return <div className="mt-2 mb-3"><PrettyJSON data={data} /></div>;
  }
  // Highlighted raw text for unparseable data
  return (
    <div className="mt-1 mb-2 text-[11px] font-mono text-slate-400 bg-black/20 rounded-lg px-3 py-2.5 border border-slate-700/20 whitespace-pre-wrap break-all max-h-48 overflow-y-auto leading-relaxed">
      <HighlightedText text={step.detail} />
    </div>
  );
}

function HighlightedText({ text }: { text: string }) {
  // Highlight JSON keys, values, prices, booleans
  const parts = text.split(/("(?:[^"\\]|\\.)*")/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('"') && part.endsWith('"')) {
          const inner = part.slice(1, -1);
          // Key (followed by colon in original) or known field
          if (inner.match(/^(title|color|price|in_stock|variant_id|product_id|name|found|storage|ram|brand|currency|status|order_number|image_urls|photo_count)$/)) {
            return <span key={i} className="text-cyan-400">{part}</span>;
          }
          // Price-like value
          if (inner.match(/^\d{5,}\.?\d*$/)) {
            return <span key={i} className="text-emerald-400">{part}</span>;
          }
          // URL
          if (inner.startsWith("http")) {
            return <span key={i} className="text-indigo-400/60">{`"${inner.slice(0, 40)}..."`}</span>;
          }
          // Regular string value
          return <span key={i} className="text-amber-300/80">{part}</span>;
        }
        // Booleans and nulls
        return <span key={i}>{part.replace(/\btrue\b/g, "\u2705true").replace(/\bfalse\b/g, "\u274Cfalse").replace(/\bnull\b/g, "\u2014")}</span>;
      })}
    </>
  );
}

/* ── Daily Cost Chart ───────────────────────────────────── */

function DailyCostChart({ data }: { data: DailyStat[] }) {
  const W = 700, H = 180, PX = 40, PY = 20;
  const chartW = W - PX * 2, chartH = H - PY * 2;

  const costs = data.map(d => calcCost("gpt-4o-mini", d.prompt_tokens, d.completion_tokens));
  const counts = data.map(d => d.count);
  const durations = data.map(d => d.avg_duration_ms);
  const maxCost = Math.max(...costs, 0.001);
  const maxCount = Math.max(...counts, 1);

  const barW = Math.min(chartW / data.length - 2, 32);
  const gap = (chartW - barW * data.length) / (data.length + 1);

  return (
    <div className="space-y-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 200 }}>
        {/* Y-axis labels */}
        {[0, 0.25, 0.5, 0.75, 1].map(p => {
          const y = PY + chartH * (1 - p);
          const val = maxCost * p;
          return (
            <g key={p}>
              <line x1={PX} y1={y} x2={W - PX} y2={y} stroke="rgba(148,163,184,0.1)" />
              <text x={PX - 4} y={y + 3} textAnchor="end" fill="rgba(148,163,184,0.5)" fontSize={9} fontFamily="monospace">
                {val < 0.01 ? `${(val * 100).toFixed(2)}¢` : `$${val.toFixed(2)}`}
              </text>
            </g>
          );
        })}

        {/* Bars + count dots */}
        {data.map((d, i) => {
          const x = PX + gap + i * (barW + gap);
          const costH = (costs[i] / maxCost) * chartH;
          const countY = PY + chartH * (1 - counts[i] / maxCount);
          const dayLabel = d.date.slice(5); // MM-DD
          return (
            <g key={d.date}>
              {/* Cost bar */}
              <rect
                x={x} y={PY + chartH - costH} width={barW} height={Math.max(costH, 1)}
                rx={3} fill="url(#costGrad)" opacity={0.85}
              />
              {/* Count dot */}
              <circle cx={x + barW / 2} cy={countY} r={3} fill="#818cf8" opacity={0.8} />
              {/* Day label */}
              <text x={x + barW / 2} y={H - 2} textAnchor="middle" fill="rgba(148,163,184,0.5)" fontSize={8} fontFamily="monospace">
                {dayLabel}
              </text>
              {/* Cost label on hover (always show for now) */}
              <text x={x + barW / 2} y={PY + chartH - costH - 4} textAnchor="middle" fill="#fbbf24" fontSize={8} fontFamily="monospace">
                {costs[i] > 0 ? fmtCost(costs[i]) : ""}
              </text>
            </g>
          );
        })}

        {/* Count line */}
        {data.length > 1 && (
          <polyline
            points={data.map((d, i) => {
              const x = PX + gap + i * (barW + gap) + barW / 2;
              const y = PY + chartH * (1 - counts[i] / maxCount);
              return `${x},${y}`;
            }).join(" ")}
            fill="none" stroke="#818cf8" strokeWidth={1.5} opacity={0.5}
          />
        )}

        <defs>
          <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" />
            <stop offset="100%" stopColor="#d97706" stopOpacity={0.6} />
          </linearGradient>
        </defs>
      </svg>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 text-[10px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-2 rounded-sm bg-amber-500 inline-block" /> Стоимость ($)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-indigo-400 inline-block" /> Запросы
        </span>
      </div>

      {/* Summary row */}
      <div className="flex items-center justify-center gap-6 text-[11px]">
        <span className="text-slate-500">
          Всего запросов: <span className="text-slate-300 font-mono">{counts.reduce((a, b) => a + b, 0)}</span>
        </span>
        <span className="text-slate-500">
          Ср. стоимость/день: <span className="text-amber-400 font-mono">{fmtCost(costs.reduce((a, b) => a + b, 0) / Math.max(data.length, 1))}</span>
        </span>
        <span className="text-slate-500">
          Ср. время: <span className="text-slate-300 font-mono">{fmtMs(Math.round(durations.reduce((a, b) => a + b, 0) / Math.max(data.length, 1)))}</span>
        </span>
      </div>
    </div>
  );
}

/* ── Timing Waterfall ────────────────────────────────────── */

function TimingWaterfall({ steps, totalMs }: { steps: TraceStep[]; totalMs: number }) {
  const timedSteps = steps.filter(s => s.duration_ms > 0);
  if (timedSteps.length === 0 || totalMs === 0) return null;

  return (
    <div className="space-y-1">
      {timedSteps.map((s, i) => {
        const pct = Math.max((s.duration_ms / totalMs) * 100, 2);
        const style = getStep(s.type);
        return (
          <div key={i} className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500 w-24 truncate text-right flex-shrink-0">{s.label}</span>
            <div className="flex-1 h-5 bg-slate-800/30 rounded overflow-hidden relative">
              <div
                className={`h-full rounded ${style.bg} border ${style.border} flex items-center px-1.5 transition-all`}
                style={{ width: `${Math.min(pct, 100)}%`, minWidth: "32px" }}
              >
                <span className={`text-[9px] font-mono ${style.text} whitespace-nowrap`}>{fmtMs(s.duration_ms)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Step Row ────────────────────────────────────────────── */

function StepRow({ step, index, total }: { step: TraceStep; index: number; total: number }) {
  const [expanded, setExpanded] = useState(false);
  const s = getStep(step.type);
  const hasDetail = step.detail && step.detail.length > 0;
  const isLast = index === total - 1;

  return (
    <div className="flex gap-3">
      {/* Timeline line */}
      <div className="flex flex-col items-center flex-shrink-0 w-6">
        <div className={`w-2.5 h-2.5 rounded-full ${s.dot} ring-4 ${s.ring} flex-shrink-0 mt-2 z-10`} />
        {!isLast && <div className="w-px flex-1 bg-slate-700/50 -mt-px" />}
      </div>

      {/* Content */}
      <div className={`flex-1 min-w-0 ${isLast ? "pb-0" : "pb-2"}`}>
        <button
          type="button"
          onClick={() => hasDetail && setExpanded(!expanded)}
          className={`w-full text-left flex items-center gap-2 py-1 rounded-lg transition-colors ${hasDetail ? "cursor-pointer hover:bg-white/[0.02]" : "cursor-default"}`}
        >
          <span className={`text-[9px] font-semibold uppercase tracking-wider ${s.text} w-12 flex-shrink-0`}>
            {stepMeta[step.type]?.label || step.type}
          </span>
          <span className="text-[13px] text-slate-200 truncate flex-1">{step.label}</span>
          {step.duration_ms > 0 && (
            <span className={`text-[11px] font-mono flex-shrink-0 tabular-nums ${
              step.duration_ms > 3000 ? "text-rose-400 font-semibold" :
              step.duration_ms > 1000 ? "text-amber-400" : "text-slate-500"
            }`}>
              {fmtMs(step.duration_ms)}
            </span>
          )}
          {hasDetail && (
            <svg className={`w-3 h-3 text-slate-600 transition-transform flex-shrink-0 ${expanded ? "rotate-90" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
              <path d="M9 5l7 7-7 7" />
            </svg>
          )}
        </button>

        {expanded && <SmartDetail step={step} />}
      </div>
    </div>
  );
}

/* ── Photo Thumbnails ────────────────────────────────────── */

function PhotoThumbnails({ urls }: { urls: string[] }) {
  const [broken, setBroken] = useState<Set<number>>(new Set());
  return (
    <div className="flex gap-2 overflow-x-auto py-1">
      {urls.map((url, i) => (
        <a key={i} href={url} target="_blank" rel="noopener" className="flex-shrink-0 group">
          {broken.has(i) ? (
            <div className="w-16 h-16 rounded-lg bg-slate-800 border border-slate-700/50 flex items-center justify-center">
              <span className="text-[9px] text-slate-500 text-center px-1 break-all">{url.split("/").pop()?.slice(0, 15)}</span>
            </div>
          ) : (
            <img
              src={url}
              alt=""
              className="w-16 h-16 rounded-lg object-cover border border-slate-700/50 group-hover:border-indigo-500/50 transition-colors"
              onError={() => setBroken(prev => new Set(prev).add(i))}
            />
          )}
        </a>
      ))}
    </div>
  );
}

/* ── Trace Card ──────────────────────────────────────────── */

function TraceCard({ trace }: { trace: AITrace }) {
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<"timeline" | "waterfall" | "response">("timeline");
  const toolCount = trace.tools_called.length;
  const hasPhotos = trace.image_urls.length > 0;
  const totalTokens = (trace.prompt_tokens || 0) + (trace.completion_tokens || 0);
  const traceCost = calcCost(trace.model || "gpt-4o-mini", trace.prompt_tokens || 0, trace.completion_tokens || 0);
  const llmRounds = trace.steps.filter(s => s.type === "llm_call").length;
  const errors = getTraceErrors(trace);

  return (
    <div className={`card overflow-hidden ${errors.length > 0 ? "ring-1 ring-rose-500/30" : ""}`}>
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-4 py-3.5 hover:bg-white/[0.015] transition-colors"
      >
        <div className="flex items-start gap-3">
          {/* Time */}
          <div className="flex-shrink-0 pt-0.5">
            <p className="text-[11px] font-mono text-slate-500 leading-tight">{fmtDate(trace.timestamp)}</p>
          </div>

          {/* Main content */}
          <div className="flex-1 min-w-0">
            <p className="text-[13px] font-medium text-slate-100 truncate leading-snug">
              {trace.user_message || "(empty)"}
            </p>
            <p className="text-xs text-slate-500 truncate mt-0.5 leading-snug">
              {trace.final_response?.slice(0, 150) || "(no response)"}
            </p>
          </div>

          {/* Badges */}
          <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap justify-end">
            {errors.length > 0 && <Badge color="rose">{errors.length} err</Badge>}
            {toolCount > 0 && <Badge color="indigo">{toolCount} tool{toolCount > 1 ? "s" : ""}</Badge>}
            {llmRounds > 1 && <Badge color="violet">{llmRounds} rounds</Badge>}
            {hasPhotos && <Badge color="amber">{trace.image_urls.length} foto</Badge>}
            {totalTokens > 0 && <Badge color="slate">{fmtCost(traceCost)}</Badge>}
            <span className={`text-[10px] font-mono font-medium px-2 py-0.5 rounded-full ${
              trace.total_duration_ms > 5000 ? "bg-rose-500/10 text-rose-400 border border-rose-500/20" :
              trace.total_duration_ms > 2000 ? "bg-amber-500/10 text-amber-400 border border-amber-500/20" :
              "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
            }`}>
              {fmtMs(trace.total_duration_ms)}
            </span>
            <svg className={`w-4 h-4 text-slate-600 transition-transform ${expanded ? "rotate-90" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M9 5l7 7-7 7" />
            </svg>
          </div>
        </div>

        {/* Collapsed tool pills */}
        {!expanded && toolCount > 0 && (
          <div className="flex items-center gap-1 mt-2 pl-[88px] flex-wrap">
            {trace.tools_called.map((t, i) => (
              <span key={i} className="text-[9px] font-mono px-1.5 py-0.5 bg-slate-800/60 text-slate-500 rounded border border-slate-700/40">
                {t}
              </span>
            ))}
          </div>
        )}
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-slate-700/30">
          {/* Meta bar */}
          <div className="px-4 py-2.5 bg-slate-800/20 grid grid-cols-2 sm:grid-cols-5 gap-x-4 gap-y-1.5 text-[11px]">
            <KV label="Trace" mono>{trace.trace_id}</KV>
            <KV label="Model" mono>{trace.model || "—"}</KV>
            <KV label="Язык">{langLabels[trace.detected_language] || trace.detected_language || "—"}</KV>
            <KV label="Состояние" mono>{trace.state_before} → {trace.state_after}</KV>
            <KV label="Conv" mono>{trace.conversation_id?.slice(0, 12) || "—"}</KV>
          </div>

          {/* Token/Cost bar */}
          {totalTokens > 0 && (
            <div className="px-4 py-2 border-t border-slate-700/20 flex items-center gap-4 text-[11px]">
              <span className="text-slate-500">Tokens:</span>
              <span className="font-mono text-violet-400">{(trace.prompt_tokens || 0).toLocaleString()} prompt</span>
              <span className="text-slate-600">+</span>
              <span className="font-mono text-emerald-400">{(trace.completion_tokens || 0).toLocaleString()} completion</span>
              <span className="text-slate-600">=</span>
              <span className="font-mono text-slate-300 font-medium">{totalTokens.toLocaleString()} total</span>
              <span className="text-slate-600">≈</span>
              <span className="font-mono text-amber-400 font-medium">{fmtCost(traceCost)}</span>
            </div>
          )}

          {/* Error banner */}
          {errors.length > 0 && (
            <div className="px-4 py-2 border-t border-rose-500/20 bg-rose-500/5">
              <p className="text-[10px] text-rose-400 font-semibold uppercase tracking-wider mb-1">Обнаружены проблемы ({errors.length})</p>
              <div className="space-y-1">
                {errors.map((err, i) => (
                  <p key={i} className="text-[11px] text-rose-300/80 flex items-start gap-1.5">
                    <span className="text-rose-400 mt-0.5 flex-shrink-0">!</span>
                    <span>{err.slice(0, 200)}</span>
                  </p>
                ))}
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className="px-4 pt-2 flex gap-1 border-t border-slate-700/20">
            {(["timeline", "waterfall", "response"] as const).map(t => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`px-3 py-1.5 rounded-t-lg text-[11px] font-medium transition-colors ${
                  tab === t ? "bg-slate-800/50 text-slate-200 border border-b-0 border-slate-700/30" : "text-slate-500 hover:text-slate-300"
                }`}
              >
                {t === "timeline" ? `Pipeline (${trace.steps.length})` : t === "waterfall" ? "Timing" : "Response"}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="px-4 py-3 border-t border-slate-700/20">
            {tab === "timeline" && (
              <div className="space-y-0">
                {trace.steps.map((s, i) => (
                  <StepRow key={i} step={s} index={i} total={trace.steps.length} />
                ))}
              </div>
            )}

            {tab === "waterfall" && (
              <div className="space-y-3">
                <TimingWaterfall steps={trace.steps} totalMs={trace.total_duration_ms} />
                <div className="flex items-center gap-3 pt-2 border-t border-slate-700/20 text-[10px] text-slate-500">
                  <span>Total: <span className="font-mono text-slate-300">{fmtMs(trace.total_duration_ms)}</span></span>
                  {llmRounds > 0 && (
                    <span>LLM: <span className="font-mono text-violet-400">{fmtMs(trace.steps.filter(s => s.type === "llm_call").reduce((a, s) => a + s.duration_ms, 0))}</span></span>
                  )}
                  {trace.steps.some(s => s.type === "tool_result") && (
                    <span>Tools: <span className="font-mono text-emerald-400">{fmtMs(trace.steps.filter(s => s.type === "tool_result").reduce((a, s) => a + s.duration_ms, 0))}</span></span>
                  )}
                </div>
              </div>
            )}

            {tab === "response" && (
              <div className="space-y-3">
                <div className="bg-black/20 rounded-lg p-3 border border-slate-700/30">
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">AI Response</p>
                  <p className="text-[13px] text-slate-200 whitespace-pre-wrap leading-relaxed">
                    {trace.final_response || "(empty)"}
                  </p>
                </div>
                {hasPhotos && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Photos ({trace.image_urls.length})</p>
                    <PhotoThumbnails urls={trace.image_urls} />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Main Page ───────────────────────────────────────────── */

export default function AIMonitorPage() {
  const [traces, setTraces] = useState<AITrace[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");

  const fetchTraces = useCallback(async (loadOffset = 0, append = false) => {
    if (append) setLoadingMore(true); else setLoading(true);
    try {
      const data = await api.get<{ traces: AITrace[]; total: number; count: number }>(
        `/ai-traces?limit=${PAGE_SIZE}&offset=${loadOffset}`
      );
      if (append) {
        setTraces(prev => [...prev, ...(data.traces || [])]);
      } else {
        setTraces(data.traces || []);
      }
      setTotal(data.total || 0);
      setOffset(loadOffset + (data.count || 0));
    } catch (e) {
      console.error("Failed to fetch traces:", e);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => { fetchTraces(0); }, [fetchTraces]);

  const handleRefresh = () => { setOffset(0); fetchTraces(0); };
  const handleLoadMore = () => fetchTraces(offset, true);
  const handleClear = async () => {
    try { await api.delete("/ai-traces"); setTraces([]); setTotal(0); setOffset(0); } catch {}
  };

  const filtered = useMemo(() => {
    if (!search.trim()) return traces;
    const q = search.toLowerCase();
    return traces.filter(t =>
      t.user_message.toLowerCase().includes(q) ||
      t.final_response.toLowerCase().includes(q) ||
      t.tools_called.some(tc => tc.toLowerCase().includes(q)) ||
      t.trace_id.includes(q)
    );
  }, [traces, search]);

  const totalTokensAll = traces.reduce((s, t) => s + (t.prompt_tokens || 0) + (t.completion_tokens || 0), 0);
  const totalCostAll = traces.reduce((s, t) => s + calcCost(t.model || "gpt-4o-mini", t.prompt_tokens || 0, t.completion_tokens || 0), 0);
  const totalTools = traces.reduce((s, t) => s + t.tools_called.length, 0);
  const avgMs = traces.length > 0 ? Math.round(traces.reduce((s, t) => s + t.total_duration_ms, 0) / traces.length) : 0;
  const withPhotos = traces.filter(t => t.image_urls.length > 0).length;
  const errTraces = traces.filter(t => getTraceErrors(t).length > 0).length;
  const hasMore = offset < total;

  // Daily stats for chart
  const [dailyStats, setDailyStats] = useState<DailyStat[]>([]);
  const [showChart, setShowChart] = useState(true);

  useEffect(() => {
    api.get<DailyStat[]>("/ai-traces/daily-stats?days=14").then(setDailyStats).catch(() => {});
  }, [traces.length]);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2.5">
            <span className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 12h6l3-9 6 18 3-9h4" />
              </svg>
            </span>
            AI Monitor
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">{total.toLocaleString()} трейсов в архиве</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <svg className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Поиск..."
              className="pl-8 pr-3 py-1.5 w-40 rounded-lg text-xs bg-white border border-slate-200 text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300"
            />
          </div>
          <button type="button" onClick={handleRefresh} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-200 hover:bg-indigo-100 transition-colors">
            Обновить
          </button>
          {traces.length > 0 && (
            <button type="button" onClick={handleClear} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200 hover:bg-rose-100 transition-colors">
              Очистить
            </button>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {[
          { label: "Всего", value: total.toLocaleString(), icon: "\u2261" },
          { label: "Стоимость", value: totalCostAll > 0 ? fmtCost(totalCostAll) : "—", icon: "$", color: "text-amber-600" },
          { label: "Avg time", value: fmtMs(avgMs), icon: "\u23F1", color: avgMs > 5000 ? "text-rose-600" : avgMs > 2000 ? "text-amber-600" : "text-emerald-600" },
          { label: "Tokens", value: totalTokensAll > 0 ? fmtTokens(totalTokensAll) : "—", icon: "\u2726", color: "text-violet-600" },
          { label: "Tool calls", value: totalTools, icon: "\u25B6", color: "text-indigo-600" },
          { label: "Ошибки", value: errTraces, icon: "\u25C6", color: errTraces > 0 ? "text-rose-600" : "text-slate-400" },
        ].map(st => (
          <div key={st.label} className="card p-3 flex items-center gap-2.5">
            <span className="text-lg opacity-40">{st.icon}</span>
            <div>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">{st.label}</p>
              <p className={`text-lg font-bold tabular-nums ${st.color || "text-slate-900"}`}>{st.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Daily Cost Chart */}
      {dailyStats.length > 1 && (
        <div className="card overflow-hidden">
          <button
            type="button"
            onClick={() => setShowChart(!showChart)}
            className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/[0.015] transition-colors"
          >
            <span className="text-sm font-semibold text-slate-200 flex items-center gap-2">
              <span className="text-amber-400">$</span> Расходы за {dailyStats.length} дней
              <span className="text-xs text-slate-500 font-normal">
                (итого: {fmtCost(dailyStats.reduce((s, d) => s + calcCost("gpt-4o-mini", d.prompt_tokens, d.completion_tokens), 0))})
              </span>
            </span>
            <svg className={`w-4 h-4 text-slate-500 transition-transform ${showChart ? "rotate-180" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M6 9l6 6 6-6"/></svg>
          </button>
          {showChart && (
            <div className="px-4 pb-4">
              <DailyCostChart data={dailyStats} />
            </div>
          )}
        </div>
      )}

      {/* Traces list */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="card p-4 animate-pulse">
              <div className="h-4 bg-slate-200/50 rounded w-3/4 mb-2" />
              <div className="h-3 bg-slate-200/30 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-12 text-center">
          <div className="w-14 h-14 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-3">
            <svg className="w-7 h-7 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
              <path d="M2 12h6l3-9 6 18 3-9h4" />
            </svg>
          </div>
          <p className="text-slate-600 font-medium">{search ? "Ничего не найдено" : "Нет трейсов"}</p>
          <p className="text-sm text-slate-400 mt-1">{search ? "Попробуйте другой запрос" : "Напишите боту в Telegram"}</p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {filtered.map(trace => (
            <TraceCard key={trace.trace_id} trace={trace} />
          ))}

          {hasMore && !search && (
            <div className="flex justify-center pt-2 pb-1">
              <button
                type="button"
                onClick={handleLoadMore}
                disabled={loadingMore}
                className="px-6 py-2 rounded-xl text-sm font-medium bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700 transition-colors disabled:opacity-50"
              >
                {loadingMore ? "Загрузка..." : `Ещё ${total - offset} записей`}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Legend */}
      <div className="card p-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="text-[9px] text-slate-500 uppercase tracking-widest mr-1">Legend</span>
        {Object.entries(stepMeta).map(([type, m]) => {
          const c = colorMap[m.color];
          return (
            <div key={type} className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${c.dot}`} />
              <span className="text-[10px] text-slate-500">{m.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
