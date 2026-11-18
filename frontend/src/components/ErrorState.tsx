// Shared error state — a failed load must not leave a spinner on screen
// forever. Permanent "loading" guards render this instead once the request has
// failed, and the retry re-runs the same loader.

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  compact?: boolean;
}

export function ErrorState({ message, onRetry, compact = false }: ErrorStateProps) {
  if (compact) {
    return (
      <p role="alert" className="py-2 text-center text-xs text-red-600">
        {message}
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="ml-2 font-medium underline hover:no-underline"
          >
            Retry
          </button>
        )}
      </p>
    );
  }

  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-3 py-12 text-center"
    >
      <p className="max-w-sm text-sm font-medium text-red-700">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          Try again
        </button>
      )}
    </div>
  );
}
