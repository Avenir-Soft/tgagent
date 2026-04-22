"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated, logout } from "@/lib/auth";
import { resetSessionFlag } from "@/lib/api";
import Sidebar from "@/components/sidebar";
import { ToastProvider } from "@/components/ui/toast";
import { GlobalHandoffNotifier } from "@/components/global-handoff-notifier";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [impersonating, setImpersonating] = useState(false);
  const [impersonateTenant, setImpersonateTenant] = useState("");

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login");
    } else {
      setAuthChecked(true);
    }
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

  // Don't render admin content until auth is verified
  if (!authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center animate-pulse">
            <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
            </svg>
          </div>
          <div className="text-sm text-slate-400">Загрузка...</div>
        </div>
      </div>
    );
  }

  return (
    <ToastProvider>
      <GlobalHandoffNotifier />
      {/* Session expiry dialog */}
      {sessionExpired && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Сессия истекла">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6 text-center">
            <div className="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" /></svg>
            </div>
            <h3 className="text-lg font-semibold text-slate-900 mb-1">Сессия истекла</h3>
            <p className="text-sm text-slate-500 mb-6">Ваша сессия завершена. Войдите снова для продолжения работы.</p>
            <button type="button" onClick={handleSessionLogout} className="w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white py-2.5 rounded-xl font-semibold text-sm hover:from-indigo-500 hover:to-violet-500 transition-all shadow-lg shadow-indigo-500/25">
              Войти снова
            </button>
          </div>
        </div>
      )}
      {/* Impersonate banner */}
      {impersonating && (
        <div className="fixed top-0 left-0 right-0 z-[60] bg-amber-500 text-amber-950 text-sm font-medium py-2 px-4 flex items-center justify-center gap-3">
          <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <span>Просмотр от имени: <strong>{impersonateTenant}</strong></span>
          <button
            onClick={handleExitImpersonate}
            className="ml-2 bg-amber-700 hover:bg-amber-800 text-white text-xs font-bold px-3 py-1 rounded-lg transition-colors"
          >
            Выйти в платформу
          </button>
        </div>
      )}
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[9999] focus:px-4 focus:py-2 focus:bg-indigo-600 focus:text-white focus:rounded-lg focus:text-sm focus:font-medium">
        Перейти к контенту
      </a>
      <div className={`flex min-h-screen bg-slate-50 ${impersonating ? "pt-10" : ""}`}>
        <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <div className="flex-1 flex flex-col min-w-0">
          {/* Mobile header */}
          <header className="md:hidden sticky top-0 z-30 bg-white/80 backdrop-blur-lg border-b border-slate-200/60 px-4 py-3 flex items-center gap-3">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="text-slate-600 hover:text-slate-900 transition-colors"
              aria-label="Открыть меню"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            </button>
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-md bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center">
                <svg className="w-3.5 h-3.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                  <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                </svg>
              </div>
              <span className="font-bold text-sm text-slate-900">AI Closer</span>
            </div>
          </header>
          <main id="main-content" className="flex-1 p-4 md:p-8 overflow-auto">{children}</main>
        </div>
      </div>
    </ToastProvider>
  );
}
