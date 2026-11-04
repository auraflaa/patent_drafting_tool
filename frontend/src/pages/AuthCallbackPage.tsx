import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { LoadingState } from "../components/LoadingState";
import { homePathFor } from "../lib/roles";

/**
 * Landing point after `signInWithRedirect` (the popup fallback).
 *
 * Firebase resolves the redirect itself, so this page only waits for
 * AuthContext to finish loading the profile and then forwards the user to the
 * landing page for their role.
 */
export default function AuthCallbackPage() {
  const { status, user } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (status === "loading") return;
    if (status === "pending") {
      navigate("/pending-approval", { replace: true });
      return;
    }
    if (status === "unauthenticated" || !user) {
      navigate("/login", { replace: true });
      return;
    }
    const home = homePathFor(user.roles);
    navigate(home === "/login" ? "/not-authorized" : home, { replace: true });
  }, [status, user, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <LoadingState label="Finishing sign-in…" />
    </div>
  );
}
