"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { logout, getUser } from "@/lib/auth";
import { getTheme, toggleTheme, applyTheme } from "@/lib/theme";
import { ReactNode, useState, useEffect } from "react";
import { getInitial } from "@/lib/utils";

/* ── SVG Icons (24x24, stroke-based) ─────────────────────────── */

function Icon({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <svg className={className || "w-5 h-5"} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}

const icons: Record<string, ReactNode> = {
  dashboard: <Icon><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></Icon>,
  analytics: <Icon><path d="M3 3v18h18" /><path d="M7 16l4-6 4 4 5-8" /></Icon>,
  conversations: <Icon><path d="M8 12h.01M12 12h.01M16 12h.01" /><path d="M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" /></Icon>,
  leads: <Icon><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></Icon>,
  orders: <Icon><path d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z" /></Icon>,
  products: <Icon><path d="M7.875 1.5L3.75 5.25v13.5A1.5 1.5 0 005.25 20.25h13.5a1.5 1.5 0 001.5-1.5V5.25L16.125 1.5H7.875z" /><path d="M3.75 5.25h16.5" /><path d="M16 9a4 4 0 01-8 0" /></Icon>,
  delivery: <Icon><path d="M1 3h15v13H1z" /><path d="M16 8h4l3 3v5h-7V8z" /><circle cx="5.5" cy="18.5" r="2.5" /><circle cx="18.5" cy="18.5" r="2.5" /></Icon>,
  handoff: <Icon><path d="M7 11l5-5m0 0l5 5m-5-5v12" /><path d="M3 20h18" /></Icon>,
  broadcast: <Icon><path d="M10.34 15.84c-.688-.06-1.386-.09-2.09-.09H7.5a4.5 4.5 0 110-9h.75c.704 0 1.402-.03 2.09-.09m0 9.18c.253.962.584 1.892.985 2.783.247.55.06 1.21-.463 1.511l-.657.38a.954.954 0 01-1.233-.355 19.833 19.833 0 01-1.492-3.09m2.86-6.53c2.28-.273 4.478-.822 6.557-1.617A18.128 18.128 0 0019.5 12a18.13 18.13 0 00-1.753-7.769c-2.079-.795-4.277-1.344-6.557-1.617" /></Icon>,
  training: <Icon><path d="M12 18v-5.25m0 0a6.01 6.01 0 001.5-.189m-1.5.189a6.01 6.01 0 01-1.5-.189m3.75 7.478a12.06 12.06 0 01-4.5 0m3.75 2.383a14.406 14.406 0 01-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 10-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" /></Icon>,
  templates: <Icon><path d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" /></Icon>,
  telegram: <Icon><path d="M6 12L3 20l18-8L3 4l3 8zm0 0l6 0" /></Icon>,
  settings: <Icon><path d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" /><circle cx="12" cy="12" r="3" /></Icon>,
  monitor: <Icon><path d="M2 12h6l3-9 6 18 3-9h4" /></Icon>,
};

/* ── Navigation structure ────────────────────────────────────── */

interface NavItem {
  href: string;
  label: string;
  icon: string;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    title: "Обзор",
    items: [
      { href: "/dashboard", label: "Дашборд", icon: "dashboard" },
      { href: "/analytics", label: "Аналитика", icon: "analytics" },
    ],
  },
  {
    title: "Продажи",
    items: [
      { href: "/conversations", label: "Диалоги", icon: "conversations" },
      { href: "/leads", label: "Лиды", icon: "leads" },
      { href: "/orders", label: "Заказы", icon: "orders" },
      { href: "/products", label: "Товары", icon: "products" },
    ],
  },
  {
    title: "Операции",
    items: [
      { href: "/delivery", label: "Доставка", icon: "delivery" },
      { href: "/handoffs", label: "Передачи", icon: "handoff" },
      { href: "/broadcast", label: "Рассылки", icon: "broadcast" },
    ],
  },
  {
    title: "AI & Обучение",
    items: [
      { href: "/training", label: "Обучение AI", icon: "training" },
      { href: "/templates", label: "Шаблоны", icon: "templates" },
      { href: "/ai-monitor", label: "AI Monitor", icon: "monitor" },
    ],
  },
  {
    title: "Система",
    items: [
      { href: "/telegram", label: "Telegram", icon: "telegram" },
      { href: "/settings", label: "Настройки", icon: "settings" },
    ],
  },
];

/* ── Sidebar Component ───────────────────────────────────────── */

export default function Sidebar({ open, onClose }: { open?: boolean; onClose?: () => void }) {
  const pathname = usePathname();
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    setUser(getUser());
    setIsDark(getTheme() === "dark" || (getTheme() === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches));
    applyTheme();
  }, []);
  const initials = user?.full_name
    ? user.full_name.split(" ").map((w: string) => getInitial(w)).join("").slice(0, 2)
    : getInitial(user?.email);

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40 md:hidden animate-fade-in"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed md:sticky top-0 left-0 z-50 w-[260px] bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 text-white min-h-screen h-screen flex flex-col transition-transform duration-300 ease-out ${
          open ? "translate-x-0" : "-translate-x-full"
        } md:translate-x-0`}
      >
        {/* ── Brand ── */}
        <div className="px-5 pt-6 pb-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/25">
              <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
            <div>
              <h1 className="text-[15px] font-bold tracking-tight">AI Closer</h1>
              <p className="text-[10px] text-slate-400 font-medium tracking-wider uppercase">Панель управления</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="md:hidden text-slate-400 hover:text-white transition-colors"
            aria-label="Закрыть меню"
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* ── Navigation ── */}
        <nav className="flex-1 px-3 pb-4 overflow-y-auto space-y-5">
          {navGroups.map((group) => (
            <div key={group.title}>
              <p className="px-3 mb-1.5 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                {group.title}
              </p>
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const active = pathname === item.href || pathname?.startsWith(item.href + "/");
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={onClose}
                      className={`group flex items-center gap-3 px-3 py-2 rounded-lg text-[13px] font-medium transition-all duration-150 ${
                        active
                          ? "bg-white/10 text-white shadow-sm"
                          : "text-slate-400 hover:text-white hover:bg-white/[0.06]"
                      }`}
                    >
                      <span className={`flex-shrink-0 transition-colors ${active ? "text-indigo-400" : "text-slate-500 group-hover:text-slate-300"}`}>
                        {icons[item.icon]}
                      </span>
                      <span>{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* ── User section ── */}
        <div className="px-3 pb-4">
          <div className="border-t border-white/[0.08] pt-4 px-2">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center text-[11px] font-bold shadow-sm flex-shrink-0">
                {initials}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-medium text-slate-200 truncate">{user?.email}</p>
                <p className="text-[10px] text-slate-500 capitalize">{user?.role?.replace("_", " ")}</p>
              </div>
              <button
                onClick={() => { const next = toggleTheme(); setIsDark(next === "dark" || (next === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)); }}
                className="text-slate-500 hover:text-amber-400 transition-colors flex-shrink-0"
                title={isDark ? "Светлая тема" : "Тёмная тема"}
              >
                {isDark ? (
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="4" />
                    <path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41m12.73-12.73l1.41-1.41" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                  </svg>
                )}
              </button>
              <button
                onClick={logout}
                className="text-slate-500 hover:text-rose-400 transition-colors flex-shrink-0"
                title="Выйти"
              >
                <svg className="w-4.5 h-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
