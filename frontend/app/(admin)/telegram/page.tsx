"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { timeAgo } from "@/lib/time-ago";
import { PageHeader } from "@/components/ui/page-header";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

interface TgAccount {
  id: string;
  phone_number: string;
  display_name: string | null;
  username: string | null;
  status: string;
  is_primary: boolean;
}

interface TgChannel {
  id: string;
  telegram_channel_id: number;
  title: string;
  username: string | null;
  is_active: boolean;
}

interface TgGroup {
  id: string;
  telegram_group_id: number;
  title: string;
  is_active: boolean;
}

interface AccountStatus {
  account_id: string;
  status: "connected" | "disconnected" | "pending";
}

interface ActivityLog {
  id: string;
  created_at: string;
  customer_name: string | null;
  customer_username: string | null;
  sender_type: string;
  text_preview: string;
}

export default function TelegramPage() {
  const { toast } = useToast();

  const [accounts, setAccounts] = useState<TgAccount[]>([]);
  const [channels, setChannels] = useState<TgChannel[]>([]);
  const [groups, setGroups] = useState<TgGroup[]>([]);
  const [showChannelForm, setShowChannelForm] = useState(false);
  const [showGroupForm, setShowGroupForm] = useState(false);
  const [chForm, setChForm] = useState({ telegram_channel_id: "", title: "", username: "" });
  const [grForm, setGrForm] = useState({ telegram_group_id: "", title: "" });

  // Real-time status
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [reconnectingId, setReconnectingId] = useState<string | null>(null);

  // Activity logs
  const [logs, setLogs] = useState<ActivityLog[]>([]);

  // Disconnect confirm dialog
  const [disconnectTarget, setDisconnectTarget] = useState<TgAccount | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);

  // Auth flow state
  const [authStep, setAuthStep] = useState<"idle" | "phone" | "code" | "2fa" | "done">("idle");
  const [authPhone, setAuthPhone] = useState("");
  const [authName, setAuthName] = useState("");
  const [authCode, setAuthCode] = useState("");
  const [auth2fa, setAuth2fa] = useState("");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  const reload = useCallback(() => {
    api.get<TgAccount[]>("/telegram/accounts").then(setAccounts).catch(() => {});
    api.get<TgChannel[]>("/telegram/channels").then(setChannels).catch(() => {});
    api.get<TgGroup[]>("/telegram/discussion-groups").then(setGroups).catch(() => {});
  }, []);

  // Load activity logs
  const loadLogs = useCallback(() => {
    api.get<ActivityLog[]>("/telegram/activity-logs").then(setLogs).catch(() => {});
  }, []);

  // Poll connection status every 5s
  useEffect(() => {
    const fetchStatus = () => {
      api.get<AccountStatus[]>("/telegram/status").then((data) => {
        const map: Record<string, string> = {};
        data.forEach((s) => { map[s.account_id] = s.status; });
        setStatuses(map);
      }).catch(() => {});
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  // Poll activity logs every 10s
  useEffect(() => {
    loadLogs();
    const interval = setInterval(loadLogs, 10000);
    return () => clearInterval(interval);
  }, [loadLogs]);

  useEffect(() => { reload(); }, [reload]);

  // Get live status for account (prefer polled status, fall back to account.status)
  const getLiveStatus = (account: TgAccount): string => {
    return statuses[account.id] || account.status;
  };

  const statusDot = (status: string) => {
    if (status === "connected") {
      return <span className="relative flex h-2.5 w-2.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
      </span>;
    }
    if (status === "pending") {
      return <span className="inline-flex rounded-full h-2.5 w-2.5 bg-amber-500" />;
    }
    return <span className="inline-flex rounded-full h-2.5 w-2.5 bg-rose-500" />;
  };

  const statusLabel = (status: string) => {
    if (status === "connected") return "Подключен";
    if (status === "pending") return "Ожидание";
    return "Отключен";
  };

  const statusBadgeClass = (status: string) => {
    if (status === "connected") return "bg-emerald-100 text-emerald-700";
    if (status === "pending") return "bg-amber-100 text-amber-700";
    return "bg-rose-100 text-rose-700";
  };

  // Reconnect handler
  const handleReconnect = async (account: TgAccount) => {
    setReconnectingId(account.id);
    try {
      await api.post(`/telegram/accounts/${account.id}/reconnect`);
      toast("Переподключение выполнено", "success");
    } catch (err: any) {
      toast(err.message || "Ошибка переподключения", "error");
    } finally {
      setReconnectingId(null);
    }
  };

  // Disconnect handler
  const handleDisconnect = async () => {
    if (!disconnectTarget) return;
    setDisconnecting(true);
    try {
      await api.delete(`/telegram/accounts/${disconnectTarget.id}`);
      toast("Аккаунт отключен", "success");
      reload();
    } catch (err: any) {
      toast(err.message || "Ошибка отключения", "error");
    } finally {
      setDisconnecting(false);
      setDisconnectTarget(null);
    }
  };

  const sendCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError("");
    setAuthLoading(true);
    try {
      await api.post("/telegram/auth/send-code", {
        phone_number: authPhone,
        display_name: authName || null,
      });
      setAuthStep("code");
    } catch (err: any) {
      setAuthError(err.message || "Ошибка отправки кода");
    } finally {
      setAuthLoading(false);
    }
  };

  const verifyCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError("");
    setAuthLoading(true);
    try {
      const res = await api.post<{ status: string }>("/telegram/auth/verify-code", {
        phone_number: authPhone,
        code: authCode,
        password: auth2fa || null,
      });
      if (res.status === "2fa_required") {
        setAuthStep("2fa");
      } else {
        setAuthStep("done");
        toast("Аккаунт успешно подключен!", "success");
        reload();
        setTimeout(() => {
          setAuthStep("idle");
          setAuthPhone("");
          setAuthName("");
          setAuthCode("");
          setAuth2fa("");
        }, 3000);
      }
    } catch (err: any) {
      setAuthError(err.message || "Ошибка верификации");
    } finally {
      setAuthLoading(false);
    }
  };

  const senderLabel = (type: string) => {
    if (type === "ai") return { text: "AI", cls: "bg-violet-100 text-violet-700" };
    if (type === "human_admin") return { text: "Оператор", cls: "bg-indigo-100 text-indigo-700" };
    return { text: type, cls: "bg-slate-100 text-slate-600" };
  };

  return (
    <div className="space-y-8">
      {/* Disconnect confirm dialog */}
      <ConfirmDialog
        open={!!disconnectTarget}
        title="Отключить аккаунт?"
        message={`Аккаунт ${disconnectTarget?.phone_number} будет отключен. AI-агент перестанет обрабатывать сообщения.`}
        confirmText="Отключить"
        variant="danger"
        onConfirm={handleDisconnect}
        onCancel={() => setDisconnectTarget(null)}
        loading={disconnecting}
      />

      {/* Accounts Section */}
      <section>
        <PageHeader
          title="Telegram аккаунты"
          action={authStep === "idle" ? { label: "+ Подключить аккаунт", onClick: () => setAuthStep("phone") } : undefined}
        />

        {/* Auth Flow */}
        {authStep !== "idle" && authStep !== "done" && (
          <div className="card p-6 mb-4 max-w-lg">
            <h3 className="font-bold text-slate-900 mb-4">
              {authStep === "phone" && "Шаг 1: Введите номер телефона"}
              {authStep === "code" && "Шаг 2: Введите код из Telegram"}
              {authStep === "2fa" && "Шаг 3: Введите пароль 2FA"}
            </h3>

            {authError && (
              <div className="bg-rose-50 text-rose-600 text-sm p-3 rounded-lg mb-4">{authError}</div>
            )}

            {authStep === "phone" && (
              <form onSubmit={sendCode} className="space-y-3">
                <input
                  placeholder="+998901234567"
                  value={authPhone}
                  onChange={(e) => setAuthPhone(e.target.value)}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  required
                />
                <input
                  placeholder="Имя AI-админа (необязательно)"
                  value={authName}
                  onChange={(e) => setAuthName(e.target.value)}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setAuthStep("idle")}
                    className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    Отмена
                  </button>
                  <button
                    type="submit"
                    disabled={authLoading}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
                  >
                    {authLoading ? "Отправка..." : "Отправить код"}
                  </button>
                </div>
              </form>
            )}

            {authStep === "code" && (
              <form onSubmit={verifyCode} className="space-y-3">
                <p className="text-sm text-slate-500 mb-2">
                  Код отправлен на <strong>{authPhone}</strong> в Telegram
                </p>
                <input
                  placeholder="12345"
                  value={authCode}
                  onChange={(e) => setAuthCode(e.target.value)}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm text-center text-2xl tracking-widest focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  maxLength={6}
                  required
                  autoFocus
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => { setAuthStep("idle"); setAuthError(""); }}
                    className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    Отмена
                  </button>
                  <button
                    type="submit"
                    disabled={authLoading}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
                  >
                    {authLoading ? "Проверка..." : "Подтвердить"}
                  </button>
                </div>
              </form>
            )}

            {authStep === "2fa" && (
              <form onSubmit={verifyCode} className="space-y-3">
                <p className="text-sm text-slate-500 mb-2">
                  Аккаунт защищён двухфакторной аутентификацией. Введите пароль.
                </p>
                <input
                  type="password"
                  placeholder="Пароль 2FA"
                  value={auth2fa}
                  onChange={(e) => setAuth2fa(e.target.value)}
                  className="w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  required
                  autoFocus
                />
                <button
                  type="submit"
                  disabled={authLoading}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
                >
                  {authLoading ? "Проверка..." : "Войти"}
                </button>
              </form>
            )}
          </div>
        )}

        {authStep === "done" && (
          <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl p-4 mb-4 transition-all duration-200">
            Аккаунт успешно подключен! AI-агент начал слушать сообщения.
          </div>
        )}

        {/* Accounts Table */}
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Телефон</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Имя</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Username</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Статус</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {accounts.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                    Нет подключенных аккаунтов. Нажмите &quot;Подключить аккаунт&quot; чтобы начать.
                  </td>
                </tr>
              ) : (
                accounts.map((a) => {
                  const live = getLiveStatus(a);
                  return (
                    <tr key={a.id} className="hover:bg-slate-50/50 transition-colors">
                      <td className="px-4 py-3 font-mono text-slate-900">{a.phone_number}</td>
                      <td className="px-4 py-3 text-slate-700">{a.display_name || "\u2014"}</td>
                      <td className="px-4 py-3 text-slate-500">@{a.username || "\u2014"}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {statusDot(live)}
                          <span className={`px-2 py-0.5 rounded text-xs ${statusBadgeClass(live)}`}>
                            {statusLabel(live)}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleReconnect(a)}
                            disabled={reconnectingId === a.id}
                            className="px-3 py-1 bg-indigo-100 text-indigo-600 rounded text-xs hover:bg-indigo-200 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                          >
                            {reconnectingId === a.id ? (
                              <>
                                <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                </svg>
                                <span>Подключение...</span>
                              </>
                            ) : (
                              "Переподключить"
                            )}
                          </button>
                          <button
                            onClick={() => setDisconnectTarget(a)}
                            className="px-3 py-1 bg-rose-100 text-rose-600 rounded text-xs hover:bg-rose-200 transition-colors"
                          >
                            Отключить
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Channels */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-slate-900">Каналы</h2>
          <button onClick={() => setShowChannelForm(!showChannelForm)} className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-3 py-1.5 text-sm font-medium transition-colors">+ Канал</button>
        </div>
        {showChannelForm && (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api.post("/telegram/channels", { ...chForm, telegram_channel_id: parseInt(chForm.telegram_channel_id) });
                toast("Канал добавлен", "success");
                setShowChannelForm(false);
                setChForm({ telegram_channel_id: "", title: "", username: "" });
                reload();
              } catch (err: any) {
                toast(err.message || "Ошибка добавления канала", "error");
              }
            }}
            className="card p-4 mb-3 flex gap-3"
          >
            <input placeholder="Channel ID" value={chForm.telegram_channel_id} onChange={(e) => setChForm({ ...chForm, telegram_channel_id: e.target.value })} className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all flex-1" required />
            <input placeholder="Название" value={chForm.title} onChange={(e) => setChForm({ ...chForm, title: e.target.value })} className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all flex-1" required />
            <button type="submit" className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors">Добавить</button>
          </form>
        )}
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Название</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Статус</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {channels.length === 0 ? (
                <tr><td colSpan={3} className="px-4 py-6 text-center text-slate-400">Нет каналов</td></tr>
              ) : channels.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs text-slate-700">{c.telegram_channel_id}</td>
                  <td className="px-4 py-3 text-slate-900">{c.title}</td>
                  <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded text-xs ${c.is_active ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>{c.is_active ? "Активен" : "Выключен"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Discussion Groups */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-slate-900">Discussion группы</h2>
          <button onClick={() => setShowGroupForm(!showGroupForm)} className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-3 py-1.5 text-sm font-medium transition-colors">+ Группа</button>
        </div>
        {showGroupForm && (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api.post("/telegram/discussion-groups", { ...grForm, telegram_group_id: parseInt(grForm.telegram_group_id) });
                toast("Группа добавлена", "success");
                setShowGroupForm(false);
                setGrForm({ telegram_group_id: "", title: "" });
                reload();
              } catch (err: any) {
                toast(err.message || "Ошибка добавления группы", "error");
              }
            }}
            className="card p-4 mb-3 flex gap-3"
          >
            <input placeholder="Group ID" value={grForm.telegram_group_id} onChange={(e) => setGrForm({ ...grForm, telegram_group_id: e.target.value })} className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all flex-1" required />
            <input placeholder="Название" value={grForm.title} onChange={(e) => setGrForm({ ...grForm, title: e.target.value })} className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all flex-1" required />
            <button type="submit" className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors">Добавить</button>
          </form>
        )}
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Название</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Статус</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {groups.length === 0 ? (
                <tr><td colSpan={3} className="px-4 py-6 text-center text-slate-400">Нет групп</td></tr>
              ) : groups.map((g) => (
                <tr key={g.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs text-slate-700">{g.telegram_group_id}</td>
                  <td className="px-4 py-3 text-slate-900">{g.title}</td>
                  <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded text-xs ${g.is_active ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>{g.is_active ? "Активен" : "Выключен"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Activity Logs */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-slate-900">Лог активности</h2>
          <button
            onClick={loadLogs}
            className="text-sm text-slate-400 hover:text-indigo-600 transition-colors"
          >
            Обновить
          </button>
        </div>
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Время</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Клиент</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Отправитель</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500">Сообщение</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-slate-400">
                    Нет активности
                  </td>
                </tr>
              ) : (
                logs.map((log) => {
                  const sender = senderLabel(log.sender_type);
                  const displayName = log.customer_name || (log.customer_username ? `@${log.customer_username}` : "\u2014");
                  const rawText = log.text_preview || "";
                  const preview = rawText.length > 80 ? rawText.slice(0, 80) + "\u2026" : rawText;
                  return (
                    <tr key={log.id} className="hover:bg-slate-50/50 transition-colors">
                      <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">{timeAgo(log.created_at)}</td>
                      <td className="px-4 py-3 text-slate-700 text-sm">{displayName}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded text-xs ${sender.cls}`}>{sender.text}</span>
                      </td>
                      <td className="px-4 py-3 text-slate-600 text-sm max-w-xs truncate">{preview}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
