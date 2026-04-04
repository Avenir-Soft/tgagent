interface LoadingSpinnerProps {
  message?: string;
}

export function LoadingSpinner({ message = "Загрузка..." }: LoadingSpinnerProps) {
  return (
    <div className="flex items-center justify-center gap-2 p-8 text-gray-400">
      <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span>{message}</span>
    </div>
  );
}
