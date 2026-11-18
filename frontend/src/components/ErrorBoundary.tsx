import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Last line of defence: a render crash (a malformed cache entry, a bad
 * response shape) should show a way out instead of a blank page.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[render]", error, info.componentStack);
  }

  private reset = () => {
    try {
      for (const key of Object.keys(localStorage)) {
        if (key.startsWith("patent-platform:")) localStorage.removeItem(key);
      }
    } catch {
      // localStorage unavailable — nothing cached to clear.
    }
    window.location.assign("/login");
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <div role="alert" className="w-full max-w-md space-y-3 rounded-lg border border-slate-200 bg-white p-6 text-center">
          <h1 className="text-lg font-semibold text-slate-900">Something went wrong</h1>
          <p className="text-sm text-slate-500">
            The page could not be displayed. Reloading usually fixes it.
          </p>
          <button
            type="button"
            onClick={this.reset}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Return to sign in
          </button>
        </div>
      </div>
    );
  }
}
