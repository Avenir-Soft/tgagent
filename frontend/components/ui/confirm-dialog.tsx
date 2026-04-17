"use client";

import { useEffect, useRef, useCallback } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "danger" | "warning" | "info";
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const variantStyles = {
  danger: "bg-rose-600 hover:bg-rose-700 text-white",
  warning: "bg-amber-500 hover:bg-amber-600 text-white",
  info: "bg-indigo-600 hover:bg-indigo-700 text-white",
};

export function ConfirmDialog({
  open,
  title,
  message,
  confirmText = "Подтвердить",
  cancelText = "Отмена",
  variant = "danger",
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Focus trap + Escape handler
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === "Escape") { onCancel(); return; }
    if (e.key !== "Tab" || !panelRef.current) return;
    const focusable = panelRef.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  }, [onCancel]);

  useEffect(() => {
    if (!open) return;
    document.addEventListener("keydown", handleKeyDown);
    // Auto-focus cancel button
    const timer = setTimeout(() => {
      const cancel = panelRef.current?.querySelector<HTMLElement>("button");
      cancel?.focus();
    }, 50);
    return () => { document.removeEventListener("keydown", handleKeyDown); clearTimeout(timer); };
  }, [open, handleKeyDown]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-label={title}>
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in"
        onClick={onCancel}
      />
      {/* Panel */}
      <div ref={panelRef} className="relative bg-white rounded-xl shadow-xl border border-slate-200/60 p-6 w-full max-w-sm mx-4 animate-scale-in">
        <h3 className="text-lg font-bold text-slate-900 mb-2">{title}</h3>
        <p className="text-sm text-slate-600 mb-5">{message}</p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 text-sm text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
          >
            {cancelText}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className={`px-4 py-2 text-sm rounded-lg transition-colors disabled:opacity-50 ${variantStyles[variant]}`}
          >
            {loading ? "..." : confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
