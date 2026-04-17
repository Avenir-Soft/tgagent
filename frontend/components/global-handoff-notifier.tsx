"use client";

import { useEffect, useRef, useCallback } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";

interface HandoffMinimal {
  id: string;
  status: string;
  reason: string;
  conversation_name: string | null;
}

/**
 * Global handoff notifier — runs in admin layout, polls for new pending handoffs
 * and plays sound + browser notification regardless of which page the user is on.
 * Skips sound when user is already on /handoffs (that page has its own notifier).
 */
export function GlobalHandoffNotifier() {
  const pathname = usePathname();
  const knownIds = useRef<Set<string>>(new Set());
  const initialLoadDone = useRef(false);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const audioBufferRef = useRef<AudioBuffer | null>(null);

  const initAudio = useCallback(async () => {
    if (audioCtxRef.current) return;
    const ctx = new AudioContext();
    audioCtxRef.current = ctx;
    try {
      const resp = await fetch("/sounds/notification.wav");
      const buf = await resp.arrayBuffer();
      audioBufferRef.current = await ctx.decodeAudioData(buf);
    } catch (e) {
      console.error("Failed to load notification sound", e);
    }
  }, []);

  const playSound = useCallback(() => {
    const ctx = audioCtxRef.current;
    const buffer = audioBufferRef.current;
    if (!ctx || !buffer) return;
    if (ctx.state === "suspended") ctx.resume();
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    const gain = ctx.createGain();
    gain.gain.value = 1.0;
    source.connect(gain);
    gain.connect(ctx.destination);
    source.start(0);
  }, []);

  // Init audio + request notification permission on first click
  useEffect(() => {
    const handler = () => {
      initAudio();
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        Notification.requestPermission();
      }
    };
    document.addEventListener("click", handler, { once: true });
    return () => document.removeEventListener("click", handler);
  }, [initAudio]);

  // Poll for pending handoffs every 10s
  useEffect(() => {
    const check = async () => {
      try {
        const data = await api.get<HandoffMinimal[]>("/handoffs?status=pending");
        const currentIds = new Set(data.map((h) => h.id));

        if (initialLoadDone.current) {
          const newOnes = data.filter((h) => !knownIds.current.has(h.id));
          // Skip if user is on /handoffs — that page has its own notifier
          const onHandoffsPage = pathname === "/handoffs";

          if (newOnes.length > 0 && !onHandoffsPage) {
            playSound();
            if (typeof Notification !== "undefined" && Notification.permission === "granted") {
              const h = newOnes[0];
              new Notification("Новый хендофф!", {
                body: `${h.conversation_name || "Клиент"}: ${h.reason}`,
                icon: "/favicon.ico",
              });
            }
          }
        }

        knownIds.current = currentIds;
        initialLoadDone.current = true;
      } catch {
        // silently ignore — don't spam errors
      }
    };

    check();
    const timer = setInterval(check, 10_000);
    return () => clearInterval(timer);
  }, [pathname, playSound]);

  return null; // invisible component
}
