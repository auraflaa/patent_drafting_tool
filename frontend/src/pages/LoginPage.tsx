import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { homePathFor } from "../lib/roles";
import { LoadingState } from "../components/LoadingState";
import { getFriendlyError } from "../lib/api";

const SIGN_IN_ERROR_MESSAGES: Record<string, string> = {
  "auth/popup-blocked":
    "Your browser blocked the sign-in window. Allow pop-ups for this site and try again.",
  "auth/unauthorized-domain":
    "This domain is not authorised for sign-in. Add it under Firebase Authentication → Settings → Authorized domains.",
  "auth/operation-not-allowed":
    "Google sign-in is not enabled for this Firebase project. Enable it under Authentication → Sign-in method.",
  "auth/configuration-not-found":
    "Firebase Authentication is not fully configured. Confirm Google sign-in is enabled and this host is an authorised domain.",
  "auth/network-request-failed":
    "Could not reach Firebase. Check your connection and try again. A browser that blocks accounts.google.com cannot complete sign-in.",
};

export default function LoginPage() {
  const { status, user, configError, sessionError, signInWithGoogle } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // If a session already exists, go straight to the role's landing page.
  // Pending accounts (awaiting admin approval) go to the pending-approval page.
  useEffect(() => {
    if (status === "approved" && user) {
      navigate(homePathFor(user.roles), { replace: true });
    } else if (status === "pending") {
      navigate("/pending-approval", { replace: true });
    }
  }, [status, user, navigate]);

  // While Firebase restores the session after a redirect sign-in, show a
  // loading indicator so the user isn't left on a blank page.
  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center">
            <h1 className="text-2xl font-semibold text-slate-900">
              Patent Filing &amp; Lifecycle Platform
            </h1>
            <p className="mt-2 text-sm text-slate-500">Sign in to continue</p>
          </div>
          <LoadingState label="Signing in…" />
        </div>
      </div>
    );
  }

  async function handleGoogleSignIn() {
    setError(null);
    setSubmitting(true);
    try {
      await signInWithGoogle();
      // onAuthStateChanged in AuthContext takes over from here.
    } catch (err) {
      const code = (err as { code?: string } | null)?.code ?? "";
      const message =
        SIGN_IN_ERROR_MESSAGES[code] ||
        getFriendlyError("LoginPage.signIn", err, "Google sign-in failed. Please try again.");
      // Keep the raw code visible for codes we do not map, so a support report
      // names the actual failure instead of a generic message.
      setError(code && !SIGN_IN_ERROR_MESSAGES[code] ? `${message} (${code})` : message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-slate-900">
            Patent Filing &amp; Lifecycle Platform
          </h1>
          <p className="mt-2 text-sm text-slate-500">Sign in to continue</p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <button
            type="button"
            onClick={handleGoogleSignIn}
            disabled={submitting || Boolean(configError)}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
            {submitting ? "Signing in…" : "Sign in with Google"}
          </button>
          <p className="mt-3 text-center text-xs text-slate-400">
            New accounts require Super Admin approval before access is granted.
          </p>
        </div>

        {configError && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-amber-700">
              Firebase not configured
            </p>
            <p className="mt-2 text-xs text-amber-800">{configError}</p>
          </div>
        )}

        {error && (
          <p role="alert" className="text-center text-sm text-red-600">
            {error}
          </p>
        )}

        {!error && sessionError && (
          <p role="alert" className="text-center text-sm text-red-600">
            {sessionError}
          </p>
        )}
      </div>
    </div>
  );
}
