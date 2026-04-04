/**
 * Reusable filter button bar.
 * Renders a row of toggle buttons with the selected one highlighted.
 */

interface FilterBarProps {
  filters: { value: string; label: string }[];
  selected: string;
  onChange: (value: string) => void;
  /** Use the smaller text-xs size (like orders page). Default is text-sm. */
  size?: "sm" | "xs";
}

export function FilterBar({ filters, selected, onChange, size = "sm" }: FilterBarProps) {
  const textSize = size === "xs" ? "text-xs" : "text-sm";
  const padding = size === "xs" ? "px-3 py-1" : "px-3 py-1.5";

  return (
    <div className="flex gap-2">
      {filters.map((f) => (
        <button
          type="button"
          key={f.value}
          onClick={() => onChange(f.value)}
          className={`${padding} rounded-lg ${textSize} font-medium transition-colors ${
            selected === f.value
              ? "bg-indigo-600 text-white"
              : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
          }`}
        >
          {f.label}
        </button>
      ))}
    </div>
  );
}
