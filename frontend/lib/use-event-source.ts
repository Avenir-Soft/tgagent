import { useEffect, useRef, useState } from "react";
import { API_BASE } from "./api";

export interface SSEEvent {
  event: string;
  conversation_id?: string;
  direction?: string;
  order_id?: string;
  reason?: string;
  data?: Record<string, unknown>;
}

/**
 * React hook for Server-Sent Events.
 *
 * First obtains a short-lived SSE token via POST /events/token (using Bearer JWT),
 * then connects to /events/stream with the short-lived token.
 * Auto-reconnects on error with fresh token (EventSource built-in + token refresh).
 * Cleans up on unmount.
 *
 * @param conversationId — optional: also subscribe to per-conversation channel
 * @param onEvent — callback fired for each SSE event
 * @returns { connected } — whether the SSE connection is open
 */
export type SSEStatus = "connecting" | "connected" | "disconnected";

async function fetchSseToken(): Promise<string | null> {
  const jwt = localStorage.getItem("token");
  if (!jwt) return null;
  try {
    const res = await fetch(`${API_BASE}/events/token`, {
      method: "POST",
      headers: { Authorization: `Bearer ${jwt}` },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.token || null;
  } catch {
    return null;
  }
}

export function useEventSource(
  conversationId?: string,
  onEvent?: (event: SSEEvent) => void,
) {
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<SSEStatus>("disconnected");
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const esRef = useRef<EventSource | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    let cancelled = false;

    async function connect() {
      const sseToken = await fetchSseToken();
      if (cancelled || !mountedRef.current) return;
      if (!sseToken) {
        setStatus("disconnected");
        return;
      }

      const params = new URLSearchParams({ token: sseToken });
      if (conversationId) params.set("conversation_id", conversationId);

      const url = `${API_BASE}/events/stream?${params.toString()}`;
      setStatus("connecting");
      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => { setConnected(true); setStatus("connected"); };

      // Generic message handler (events without explicit "event:" field)
      es.onmessage = (e) => {
        try {
          const data: SSEEvent = JSON.parse(e.data);
          onEventRef.current?.(data);
        } catch {
          // ignore non-JSON keepalives
        }
      };

      // Named event handlers — SSE routes events with "event: xxx" to addEventListener
      const eventTypes = [
        "new_message",
        "conversation_updated",
        "new_conversation",
        "order_status_changed",
        "telegram_status_changed",
        "auth_expired",
      ];
      for (const type of eventTypes) {
        es.addEventListener(type, ((e: MessageEvent) => {
          try {
            const data: SSEEvent = JSON.parse(e.data);
            if (type === "auth_expired") {
              // SSE token expired — close and reconnect with fresh token
              es.close();
              setConnected(false);
              if (!cancelled && mountedRef.current) {
                setTimeout(connect, 1000);
              }
              return;
            }
            onEventRef.current?.(data);
          } catch {
            // ignore parse errors
          }
        }) as EventListener);
      }

      es.onerror = () => {
        setConnected(false);
        setStatus("connecting");
        // If EventSource entered CLOSED state (e.g. 401 on expired token), reconnect with fresh token
        if (es.readyState === EventSource.CLOSED) {
          es.close();
          if (!cancelled && mountedRef.current) {
            setTimeout(() => connect(), 2000);
          }
        }
      };
    }

    connect();

    return () => {
      cancelled = true;
      mountedRef.current = false;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      setConnected(false);
      setStatus("disconnected");
    };
  }, [conversationId]);

  return { connected, status };
}
