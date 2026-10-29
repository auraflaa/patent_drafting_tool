// Shared empty state — every "nothing here yet" message in the app renders
// through here so empty UI is centred and consistent. Pairs a medium-weight
// title with an optional hint and an optional action (e.g. a create button
// passed in by the caller via composition).

import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  message?: string;
  action?: ReactNode;
  icon?: ReactNode;
}

export function EmptyState({ title, message, action, icon }: EmptyStateProps) {
  return (
    <div role="status" className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      {icon && (
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400" aria-hidden="true">
          {icon}
        </div>
      )}
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {message && <p className="max-w-sm text-sm text-slate-400">{message}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
