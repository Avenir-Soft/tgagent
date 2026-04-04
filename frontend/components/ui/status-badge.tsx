"use client";

interface StatusBadgeProps {
  status: string;
  colorMap?: Record<string, string>;
  labels?: Record<string, string>;
}

const defaultColors: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700",
  connected: "bg-emerald-100 text-emerald-700",
  pending: "bg-amber-100 text-amber-700",
  handoff: "bg-amber-100 text-amber-700",
  closed: "bg-slate-100 text-slate-500",
  error: "bg-rose-100 text-rose-700",
  disconnected: "bg-rose-100 text-rose-700",
};

export function StatusBadge({ status, colorMap, labels }: StatusBadgeProps) {
  const colors = colorMap || defaultColors;
  const cls = colors[status] || "bg-slate-100 text-slate-600";
  const label = labels?.[status] || status;

  return (
    <span className={`inline-flex px-2 py-0.5 rounded-lg text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}
