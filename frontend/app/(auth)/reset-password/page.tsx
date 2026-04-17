"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900"><div className="text-white">Загрузка...</div></div>}>
      <ResetPasswordForm />
    </Suspense>
  );
}

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!token) { setError("Отсутствует токен сброса. Запросите новую ссылку."); return; }
    if (password.length < 8) { setError("Пароль минимум 8 символов"); return; }
    if (password !== confirm) { setError("Пароли не совпадают"); return; }
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: password });
      setSuccess(true);
    } catch (err: any) {
      setError(err.message || "Ссылка устарела. Запросите новую.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 relative overflow-hidden">
      <div className="absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 -right-40 w-80 h-80 rounded-full bg-indigo-500/10 blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 rounded-full bg-violet-500/10 blur-3xl" />
      </div>

      <div className="relative w-full max-w-sm mx-4">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-xl shadow-indigo-500/25 mx-auto mb-4">
            <svg className="w-7 h-7 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-white">Новый пароль</h1>
          <p className="text-slate-400 text-sm mt-1">Установите новый пароль для вашего аккаунта</p>
        </div>

        <div className="bg-white/[0.07] backdrop-blur-xl rounded-2xl border border-white/10 p-8 space-y-5">
          {success ? (
            <div className="text-center space-y-4">
              <div className="w-12 h-12 rounded-full bg-emerald-500/20 flex items-center justify-center mx-auto">
                <svg className="w-6 h-6 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              </div>
              <p className="text-slate-300 text-sm">Пароль успешно изменён!</p>
              <button onClick={() => router.push("/login")} className="w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white py-2.5 rounded-xl font-semibold text-sm hover:from-indigo-500 hover:to-violet-500 transition-all shadow-lg shadow-indigo-500/25">
                Войти
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              {error && (
                <div className="bg-rose-500/10 border border-rose-500/20 text-rose-300 text-sm p-3 rounded-xl text-center">{error}</div>
              )}
              {!token && (
                <div className="bg-amber-500/10 border border-amber-500/20 text-amber-300 text-sm p-3 rounded-xl text-center">
                  Нет токена. <button type="button" onClick={() => router.push("/login")} className="underline hover:no-underline">Запросить сброс</button>
                </div>
              )}
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">Новый пароль</label>
                <div className="relative">
                  <input type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} className="w-full bg-white/[0.06] border border-white/10 rounded-xl px-4 py-2.5 pr-10 text-sm text-white placeholder-slate-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition-all" placeholder="Минимум 8 символов" required />
                  <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-300 transition-colors" tabIndex={-1}>
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">Подтвердите пароль</label>
                <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className="w-full bg-white/[0.06] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition-all" placeholder="Повторите пароль" required />
              </div>
              <button type="submit" disabled={loading || !token} className="w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white py-2.5 rounded-xl font-semibold text-sm hover:from-indigo-500 hover:to-violet-500 disabled:opacity-50 transition-all shadow-lg shadow-indigo-500/25">
                {loading ? "Сохранение..." : "Установить пароль"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
