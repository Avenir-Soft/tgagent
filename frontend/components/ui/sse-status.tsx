import { SSEStatus } from "@/lib/use-event-source";

const config: Record<SSEStatus, { dot: string; label: string; text: string; animate?: boolean }> = {
  connected:    { dot: "bg-emerald-500", label: "Онлайн",              text: "text-emerald-600" },
  connecting:   { dot: "bg-amber-500",   label: "Переподключение...",  text: "text-amber-600", animate: true },
  disconnected: { dot: "bg-slate-400",   label: "Отключено",           text: "text-slate-500" },
};

export function SSEStatusBadge({ status }: { status: SSEStatus }) {
  const c = config[status];
  return (
    <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium ${c.text} bg-white/80 backdrop-blur-sm border border-slate-200/60`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot} ${c.animate ? "animate-pulse" : ""}`} />
      {c.label}
    </div>
  );
}
