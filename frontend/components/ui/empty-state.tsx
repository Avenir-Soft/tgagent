"use client";

import Link from "next/link";

interface EmptyStateProps {
  message?: string;
  description?: string;
  icon?: React.ReactNode;
  action?: { label: string; href?: string; onClick?: () => void };
}

export function EmptyState({ message = "Ничего не найдено", description, icon, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      {icon || (
        <svg className="w-12 h-12 text-slate-300 mb-3" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5m6 4.125l2.25 2.25m0 0l2.25 2.25M12 11.625l2.25-2.25M12 11.625l-2.25 2.25M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
        </svg>
      )}
      <p className="text-sm text-slate-400">{message}</p>
      {description && <p className="text-xs text-slate-400/70 mt-1 max-w-sm">{description}</p>}
      {action && (
        action.href ? (
          <Link href={action.href} className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors">
            {action.label}
          </Link>
        ) : (
          <button type="button" onClick={action.onClick} className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors">
            {action.label}
          </button>
        )
      )}
    </div>
  );
}
