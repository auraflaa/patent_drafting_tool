import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { homePathFor } from "../lib/roles";

export default function PendingApprovalPage() {
  const { user, status, refreshMe, logout } = useAuth();
  const navigate = useNavigate();

  // Poll only while there is still something to wait for. Once the user is
  // approved, rejected, or signed out, the interval is torn down instead of
  // firing a request every 30s against a dead session.
  useEffect(() => {
    if (status !== "pending") return;
    const interval = setInterval(() => {
      void refreshMe();
    }, 30_000);
    return () => clearInterval(interval);
  }, [status, refreshMe]);

  useEffect(() => {
    if (status === "approved" && user) {
      navigate(homePathFor(user.roles), { replace: true });
    }
    if (status === "unauthenticated") {
      navigate("/login", { replace: true });
    }
  }, [status, user, navigate]);

  const statusLabel = user?.account_status ?? "Pending";
  const isRejectedOrSuspended = statusLabel === "Rejected" || statusLabel === "Suspended";

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <h1 className="text-lg font-semibold text-slate-900">
          {isRejectedOrSuspended ? "Account access restricted" : "Awaiting approval"}
        </h1>
        <p className="mt-3 text-sm text-slate-600">
          {isRejectedOrSuspended
            ? `Your account status is "${statusLabel}". Contact your Super Admin for details.`
            : "Your account has been created and is waiting for Super Admin approval. This page will update automatically once you're approved."}
        </p>
        <button
          onClick={logout}
          className="mt-6 rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
