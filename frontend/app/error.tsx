"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log only in development — no stack traces in production console
    if (process.env.NODE_ENV === "development") {
      console.error("App error:", error);
    }
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
      <div className="max-w-md w-full bg-white rounded-2xl border border-slate-200 shadow-sm p-8 text-center">
        <div className="w-14 h-14 rounded-2xl bg-rose-100 flex items-center justify-center mx-auto mb-4">
          <svg className="w-7 h-7 text-rose-500" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-slate-900 mb-2">Ошибка</h2>
        <p className="text-sm text-slate-500 mb-6">
          Произошла непредвиденная ошибка.
        </p>
        <button
          onClick={reset}
          className="px-5 py-2.5 text-sm font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
        >
          Попробовать снова
        </button>
      </div>
    </div>
  );
}
