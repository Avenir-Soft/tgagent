/**
 * Reusable page header with title, optional count badge, and optional action button.
 */

import { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  badge?: number;
  action?: { label: string; onClick: () => void };
  /** Slot for additional content on the right side (e.g., filter bar) */
  children?: ReactNode;
}

export function PageHeader({ title, badge, action, children }: PageHeaderProps) {
  return (
    <div className="flex items-center justify-between mb-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold">{title}</h1>
        {badge !== undefined && badge > 0 && (
          <span className="bg-rose-500 text-white text-xs font-bold px-2 py-0.5 rounded-full">
            {badge}
          </span>
        )}
      </div>
      <div className="flex items-center gap-3">
        {children}
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  );
}
