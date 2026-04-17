import { refreshAccessToken } from "./auth";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8001";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Session expiry: emit custom event instead of hard redirect
let _sessionExpired = false;
function handleSessionExpiry() {
  if (_sessionExpired) return; // prevent multiple dialogs
  _sessionExpired = true;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("session-expired"));
  }
}
export function resetSessionFlag() { _sessionExpired = false; }

async function request<T>(path: string, options: RequestInit = {}, _retried = false): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      // Try silent refresh before giving up
      if (!_retried) {
        const newToken = await refreshAccessToken();
        if (newToken) {
          return request<T>(path, options, true);
        }
      }
      handleSessionExpiry();
      throw new ApiError(401, "Сессия истекла");
    }
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || res.statusText);
  }

  if (res.status === 204) return null as T;
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: async <T>(path: string, file: File, fieldName = "file") => {
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    const formData = new FormData();
    formData.append(fieldName, file);
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}${path}`, { method: "POST", headers, body: formData });
    if (!res.ok) {
      if (res.status === 401 && typeof window !== "undefined") {
        const newToken = await refreshAccessToken();
        if (newToken) {
          headers["Authorization"] = `Bearer ${newToken}`;
          const retry = await fetch(`${API_BASE}${path}`, { method: "POST", headers, body: formData });
          if (retry.ok) {
            if (retry.status === 204) return null as T;
            return retry.json() as Promise<T>;
          }
        }
        handleSessionExpiry();
        throw new ApiError(401, "Сессия истекла");
      }
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail || res.statusText);
    }
    if (res.status === 204) return null as T;
    return res.json() as Promise<T>;
  },
};
