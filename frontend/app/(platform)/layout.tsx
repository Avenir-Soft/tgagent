"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { isAuthenticated, getUser, logout } from "@/lib/auth";
import { resetSessionFlag } from "@/lib/api";
import PlatformSidebar from "@/components/platform-sidebar";

/* -- Breadcrumbs -- */

const routeLabels: Record<string, string> = {
  "platform-overview": "Обзор",
  "platform-tenants": "Тенанты",
  "platform-users": "Пользователи",
  "platform-ai-monitor": "AI Монитор",
  "platform-billing": "Биллинг",
  "platform-logs": "Логи",
  "platform-settings": "Настройки",
};

function Breadcrumbs() {
  const pathname = usePathname();
  if (!pathname) return null;

  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return null;

  const crumbs: { label: string; href?: string }[] = [{ label: "Платформа", href: "/platform-overview" }];

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const label = routeLabels[seg];
    if (label) {
      const href = "/" + segments.slice(0, i + 1).join("/");
      crumbs.push({ label, href });
    } else if (!routeLabels[seg] && i > 0) {
      crumbs.push({ label: seg.length > 8 ? seg.slice(0, 8) + "..." : seg });
    }
  }

  if (crumbs.length <= 1) return null;

  return (
    <nav className="flex items-center gap-[8px] text-[15px] mt-2">
      {crumbs.map((c, i) => (
        <span key={i} className="flex items-center gap-[8px]">
          {i > 0 && (
            <span style={{ color: "var(--ink-4)" }}>/</span>
          )}
          {c.href && i < crumbs.length - 1 ? (
            <a
              href={c.href}
              className="transition-colors"
              style={{ color: "var(--ink-3)" }}
              onMouseEnter={(e) => { e.currentTarget.style.color = "var(--accent)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = "var(--ink-3)"; }}
            >
              {c.label}
            </a>
          ) : (
            <span style={{ color: "var(--ink)", fontWeight: 500 }}>{c.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [impersonating, setImpersonating] = useState(false);
  const [impersonateTenant, setImpersonateTenant] = useState<string>("");

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login");
      return;
    }
    const user = getUser();
    if (!user || user.role !== "super_admin") {
      router.push("/dashboard");
      return;
    }
    setAuthChecked(true);
  }, [router]);

  // Check impersonation state
  useEffect(() => {
    if (typeof window === "undefined") return;
    const originalToken = sessionStorage.getItem("original_token");
    if (originalToken) {
      setImpersonating(true);
      setImpersonateTenant(sessionStorage.getItem("impersonate_tenant_name") || "Tenant");
    }
  }, []);

  // Listen for session expiry events from API client
  useEffect(() => {
    const handler = () => setSessionExpired(true);
    window.addEventListener("session-expired", handler);
    return () => window.removeEventListener("session-expired", handler);
  }, []);

  const handleSessionLogout = () => {
    resetSessionFlag();
    logout();
  };

  const handleExitImpersonate = () => {
    const originalToken = sessionStorage.getItem("original_token");
    const originalUser = sessionStorage.getItem("original_user");
    if (originalToken) {
      localStorage.setItem("token", originalToken);
      if (originalUser) localStorage.setItem("user", originalUser);
      sessionStorage.removeItem("original_token");
      sessionStorage.removeItem("original_user");
      sessionStorage.removeItem("impersonate_tenant_name");
      setImpersonating(false);
      router.push("/platform-tenants");
    }
  };

  // Don't render until auth is verified
  if (!authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center" style={{ background: "var(--bg)" }}>
        <div className="flex flex-col items-center gap-3">
          <div
            className="w-[30px] h-[30px] rounded-[7px] grid place-items-center text-[11px] font-bold text-white animate-pulse"
            style={{ background: "var(--accent)" }}
          >
            AC
          </div>
          <div className="text-[12px]" style={{ color: "var(--ink-3)" }}>Загрузка...</div>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Session expiry dialog */}
      {sessionExpired && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Сессия истекла">
          <div className="rounded-[10px] shadow-2xl w-full max-w-sm mx-4 p-6 text-center" style={{ background: "var(--panel)", border: "1px solid var(--line)" }}>
            <div className="w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-4" style={{ background: "var(--warn-soft)" }}>
              <svg className="w-6 h-6" style={{ color: "var(--warn)" }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" /></svg>
            </div>
            <h3 className="text-[15px] font-semibold mb-1" style={{ color: "var(--ink)" }}>Сессия истекла</h3>
            <p className="text-[12.5px] mb-6" style={{ color: "var(--ink-3)" }}>Ваша сессия завершена. Войдите снова для продолжения работы.</p>
            <button
              type="button"
              onClick={handleSessionLogout}
              className="w-full py-[9px] rounded-[6px] text-[13px] font-semibold text-white transition-all"
              style={{ background: "var(--accent)" }}
            >
              Войти снова
            </button>
          </div>
        </div>
      )}

      {/* Impersonate banner */}
      {impersonating && (
        <div className="fixed top-0 left-0 right-0 z-[60] text-[13px] font-medium py-2 px-4 flex items-center justify-center gap-3" style={{ background: "var(--warn)", color: "#1a1205" }}>
          <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <span>Просмотр от имени: <strong>{impersonateTenant}</strong></span>
          <button
            onClick={handleExitImpersonate}
            className="ml-2 text-white text-[11px] font-bold px-3 py-1 rounded-[6px] transition-colors"
            style={{ background: "rgba(0,0,0,0.2)" }}
          >
            Выйти
          </button>
        </div>
      )}

      <div className={`flex min-h-screen ${impersonating ? "pt-10" : ""}`} style={{ background: "var(--bg)" }}>
        <PlatformSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <div className="flex-1 flex flex-col min-w-0">
          {/* Mobile header */}
          <header className="md:hidden sticky top-0 z-30 backdrop-blur-lg px-4 py-3 flex items-center gap-3" style={{ background: "color-mix(in srgb, var(--panel) 85%, transparent)", borderBottom: "1px solid var(--line)" }}>
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="transition-colors"
              style={{ color: "var(--ink-2)" }}
              aria-label="Открыть меню"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            </button>
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-[5px] grid place-items-center text-[9px] font-bold text-white" style={{ background: "var(--accent)" }}>AC</div>
              <span className="font-semibold text-[13px]" style={{ color: "var(--ink)" }}>Platform</span>
            </div>
          </header>

          {/* Top bar with breadcrumbs — same height as sidebar brand row */}
          <div className="hidden md:flex items-center gap-3 px-[18px] py-[14px]" style={{ background: "var(--panel)", borderBottom: "1px solid var(--line)" }}>
            <Breadcrumbs />
          </div>

          <main className="flex-1 p-[20px] md:px-[18px] md:py-[20px] overflow-auto">
            <div className="md:hidden"><Breadcrumbs /></div>
            {children}
          </main>
        </div>
      </div>
    </>
  );
}
