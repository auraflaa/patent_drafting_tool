import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { homePathFor } from "../lib/roles";

export default function NotAuthorizedPage() {
  const { user, logout } = useAuth();
  const home = homePathFor(user?.roles);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <h1 className="text-lg font-semibold text-slate-900">Not authorized</h1>
        <p className="mt-3 text-sm text-slate-600">
          Your account doesn't have permission to view this page.
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Link
            to={home}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            Go to my dashboard
          </Link>
          <button
            onClick={logout}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
