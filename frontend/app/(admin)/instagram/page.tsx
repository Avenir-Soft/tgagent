"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page-header";

interface IgAccount {
  id: string;
  instagram_user_id: string;
  instagram_username: string | null;
  display_name: string | null;
  facebook_page_id: string | null;
  status: string;
  is_primary: boolean;
  token_expires_at: string | null;
  created_at: string;
  updated_at: string;
}

interface IgStatus {
  connected: boolean;
  status: string;
  username?: string;
  display_name?: string;
  token_expires_at?: string;
}

export default function InstagramPage() {
  const { toast } = useToast();

  const [accounts, setAccounts] = useState<IgAccount[]>([]);
  const [status, setStatus] = useState<IgStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [showConnectForm, setShowConnectForm] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [accs, st] = await Promise.all([
        api.get<IgAccount[]>("/instagram/accounts"),
        api.get<IgStatus>("/instagram/status"),
      ]);
      setAccounts(accs);
      setStatus(st);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleConnect = async () => {
    if (!tokenInput.trim()) {
      toast("Вставьте access token", "error");
      return;
    }
    setConnecting(true);
    try {
      await api.post("/instagram/auth/connect", {
        access_token: tokenInput.trim(),
      });
      toast("Instagram аккаунт подключен!", "success");
      setTokenInput("");
      setShowConnectForm(false);
      fetchData();
    } catch (err: any) {
      toast(err?.message || "Ошибка подключения", "error");
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async (accountId: string) => {
    try {
      await api.delete(`/instagram/accounts/${accountId}`);
      toast("Аккаунт отключен", "success");
      fetchData();
    } catch (err: any) {
      toast(err?.message || "Ошибка", "error");
    }
  };

  const handleRefreshToken = async (accountId: string) => {
    try {
      await api.post(`/instagram/accounts/${accountId}/refresh-token`);
      toast("Токен обновлен", "success");
      fetchData();
    } catch (err: any) {
      toast(err?.message || "Ошибка обновления токена", "error");
    }
  };

  const daysUntilExpiry = (expiresAt: string | null) => {
    if (!expiresAt) return null;
    const diff = new Date(expiresAt).getTime() - Date.now();
    return Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)));
  };

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <PageHeader title="Instagram" />
        <div className="card p-8 animate-pulse">
          <div className="h-6 bg-slate-200 rounded w-1/3 mb-4" />
          <div className="h-4 bg-slate-200 rounded w-2/3" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Instagram"
        subtitle="Подключение Instagram Business аккаунта для автоответов на DM и комментарии"
      />

      {/* Status Card */}
      <div className="card p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
              status?.connected
                ? "bg-gradient-to-br from-purple-500 to-pink-500"
                : "bg-slate-200"
            }`}>
              <svg className="w-6 h-6 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="2" width="20" height="20" rx="5" />
                <circle cx="12" cy="12" r="5" />
                <circle cx="17.5" cy="6.5" r="1.5" />
              </svg>
            </div>
            <div>
              <h3 className="text-lg font-semibold text-slate-800">
                {status?.connected ? `@${status.username}` : "Не подключен"}
              </h3>
              <p className="text-sm text-slate-500">
                {status?.connected
                  ? status.display_name || "Instagram Business Account"
                  : "Подключите аккаунт для автоматических ответов"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${
              status?.connected
                ? "bg-emerald-50 text-emerald-700"
                : status?.status === "token_expired"
                ? "bg-amber-50 text-amber-700"
                : "bg-slate-100 text-slate-600"
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${
                status?.connected ? "bg-emerald-500" : status?.status === "token_expired" ? "bg-amber-500" : "bg-slate-400"
              }`} />
              {status?.connected ? "Подключен" : status?.status === "token_expired" ? "Токен истек" : "Отключен"}
            </span>
          </div>
        </div>
      </div>

      {/* Connected Accounts */}
      {accounts.length > 0 && (
        <div className="card p-6 space-y-4">
          <h3 className="text-base font-semibold text-slate-800">Подключенные аккаунты</h3>
          {accounts.map((acc) => {
            const days = daysUntilExpiry(acc.token_expires_at);
            return (
              <div key={acc.id} className="flex items-center justify-between p-4 bg-slate-50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center text-white font-bold text-sm">
                    {(acc.instagram_username || "?")[0].toUpperCase()}
                  </div>
                  <div>
                    <p className="font-medium text-slate-800">
                      @{acc.instagram_username || acc.instagram_user_id}
                    </p>
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                      <span className={`inline-flex items-center gap-1 ${
                        acc.status === "connected" ? "text-emerald-600" : acc.status === "token_expired" ? "text-amber-600" : "text-slate-500"
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${
                          acc.status === "connected" ? "bg-emerald-500" : acc.status === "token_expired" ? "bg-amber-500" : "bg-slate-400"
                        }`} />
                        {acc.status}
                      </span>
                      {days !== null && (
                        <span className={days < 7 ? "text-amber-600 font-medium" : ""}>
                          Токен: {days} дн.
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleRefreshToken(acc.id)}
                    className="px-3 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                  >
                    Обновить токен
                  </button>
                  <button
                    onClick={() => handleDisconnect(acc.id)}
                    className="px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
                  >
                    Отключить
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Connect Form */}
      {!status?.connected && (
        <div className="card p-6 space-y-4">
          <h3 className="text-base font-semibold text-slate-800">Подключить Instagram</h3>

          {!showConnectForm ? (
            <div className="space-y-4">
              <div className="bg-indigo-50 border border-indigo-100 rounded-lg p-4">
                <h4 className="font-medium text-indigo-800 mb-2">Как подключить:</h4>
                <ol className="text-sm text-indigo-700 space-y-1.5 list-decimal list-inside">
                  <li>Конвертируйте Instagram в Business/Creator аккаунт</li>
                  <li>Привяжите Instagram к Facebook Page</li>
                  <li>Создайте Facebook Developer App на developers.facebook.com</li>
                  <li>Добавьте Instagram product в App</li>
                  <li>Получите Access Token через Graph API Explorer</li>
                  <li>Вставьте токен ниже</li>
                </ol>
              </div>
              <button
                onClick={() => setShowConnectForm(true)}
                className="w-full px-4 py-3 bg-gradient-to-r from-purple-600 to-pink-600 text-white rounded-lg font-medium hover:from-purple-700 hover:to-pink-700 transition-all"
              >
                Подключить аккаунт
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Access Token
                </label>
                <textarea
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Вставьте access token из Graph API Explorer..."
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm resize-none h-24 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                />
                <p className="mt-1 text-xs text-slate-500">
                  Получите токен на developers.facebook.com {"->"} Graph API Explorer с permissions: instagram_business_basic, instagram_manage_messages, instagram_manage_comments
                </p>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={handleConnect}
                  disabled={connecting || !tokenInput.trim()}
                  className="px-6 py-2.5 bg-gradient-to-r from-purple-600 to-pink-600 text-white rounded-lg font-medium hover:from-purple-700 hover:to-pink-700 transition-all disabled:opacity-50"
                >
                  {connecting ? "Подключение..." : "Подключить"}
                </button>
                <button
                  onClick={() => { setShowConnectForm(false); setTokenInput(""); }}
                  className="px-4 py-2.5 text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  Отмена
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Webhook Info */}
      <div className="card p-6 space-y-3">
        <h3 className="text-base font-semibold text-slate-800">Webhook настройки</h3>
        <p className="text-sm text-slate-600">
          Укажите эти URL в Facebook Developer App {"->"} Instagram {"->"} Webhooks:
        </p>
        <div className="space-y-2">
          <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-lg">
            <span className="text-xs font-medium text-slate-500 w-24">Callback URL:</span>
            <code className="text-sm text-slate-800 font-mono flex-1">
              https://your-domain.com/instagram/webhook
            </code>
          </div>
          <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-lg">
            <span className="text-xs font-medium text-slate-500 w-24">Verify Token:</span>
            <code className="text-sm text-slate-800 font-mono flex-1">
              easy-tour-ig-verify-2026
            </code>
          </div>
          <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-lg">
            <span className="text-xs font-medium text-slate-500 w-24">Subscriptions:</span>
            <span className="text-sm text-slate-800">messages, messaging_postbacks, comments</span>
          </div>
        </div>
      </div>

      {/* Features */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card p-5">
          <div className="w-10 h-10 rounded-lg bg-indigo-100 flex items-center justify-center mb-3">
            <svg className="w-5 h-5 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
          </div>
          <h4 className="font-medium text-slate-800 mb-1">Авто-ответ на DM</h4>
          <p className="text-xs text-slate-500">AI автоматически отвечает на Direct Messages, как в Telegram</p>
        </div>
        <div className="card p-5">
          <div className="w-10 h-10 rounded-lg bg-violet-100 flex items-center justify-center mb-3">
            <svg className="w-5 h-5 text-violet-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
              <path d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443h.001c2.456-.205 4.886-.64 7.136-1.291V6.75a2.25 2.25 0 00-2.25-2.25H5.25a2.25 2.25 0 00-2.25 2.25v6.51z" />
            </svg>
          </div>
          <h4 className="font-medium text-slate-800 mb-1">Ответы на комменты</h4>
          <p className="text-xs text-slate-500">Автоматические ответы с информацией о туре под постами</p>
        </div>
        <div className="card p-5">
          <div className="w-10 h-10 rounded-lg bg-emerald-100 flex items-center justify-center mb-3">
            <svg className="w-5 h-5 text-emerald-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" />
            </svg>
          </div>
          <h4 className="font-medium text-slate-800 mb-1">Захват лидов</h4>
          <p className="text-xs text-slate-500">Каждый DM автоматически создает лид в системе</p>
        </div>
      </div>
    </div>
  );
}
