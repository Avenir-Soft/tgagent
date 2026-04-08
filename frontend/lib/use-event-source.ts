import { useEffect, useRef, useState, useCallback } from "react";
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
 * Connects to /events/stream with JWT auth via query param.
 * Auto-reconnects on error (EventSource built-in behavior).
 * Cleans up on unmount.
 *
 * @param conversationId — optional: also subscribe to per-conversation channel
 * @param onEvent — callback fired for each SSE event
 * @returns { connected } — whether the SSE connection is open
 */
export function useEventSource(
  conversationId?: string,
  onEvent?: (event: SSEEvent) => void,
) {
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;

    const params = new URLSearchParams({ token });
    if (conversationId) params.set("conversation_id", conversationId);

    const url = `${API_BASE}/events/stream?${params.toString()}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => setConnected(true);

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
      "auth_expired",
    ];
    for (const type of eventTypes) {
      es.addEventListener(type, ((e: MessageEvent) => {
        try {
          const data: SSEEvent = JSON.parse(e.data);
          if (type === "auth_expired") {
            es.close();
            setConnected(false);
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
      // EventSource auto-reconnects — no manual retry needed
    };

    return () => {
      es.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [conversationId]);

  return { connected };
}
