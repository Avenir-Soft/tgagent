/**
 * Reusable skeleton loaders for list/table pages.
 * Uses the existing `skeleton` CSS class (shimmer animation from globals.css).
 */

export function CardSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card p-5">
          <div className="flex items-center gap-4">
            <div className="h-10 w-10 rounded-full skeleton" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-1/3 skeleton rounded" />
              <div className="h-3 w-1/2 skeleton rounded" />
            </div>
            <div className="h-6 w-20 skeleton rounded-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 6, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="card overflow-hidden">
      {/* Header row */}
      <div className="flex items-center gap-4 px-5 py-3 border-b border-slate-200/60 dark:border-slate-700/60">
        {Array.from({ length: cols }, (_, j) => (
          <div key={j} className={`h-3 skeleton rounded ${j === 0 ? "w-1/4" : "w-1/6"}`} />
        ))}
      </div>
      {/* Data rows */}
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 px-5 py-4 border-b border-slate-100 dark:border-slate-800 last:border-0">
          {Array.from({ length: cols }, (_, j) => (
            <div key={j} className={`h-4 skeleton rounded ${j === 0 ? "w-1/4" : j === cols - 1 ? "w-16" : "w-1/6"}`} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function StatsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card p-5">
          <div className="space-y-3">
            <div className="h-3 w-20 skeleton rounded" />
            <div className="h-7 w-16 skeleton rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}
