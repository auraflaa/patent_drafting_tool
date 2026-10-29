import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { DashboardShell } from "../components/DashboardShell";
import { StatusBadge } from "../components/StatusBadge";
import { LoadingState } from "../components/LoadingState";
import { EmptyState } from "../components/EmptyState";
import { apiFetch, getFriendlyError } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { ROLE_HOME, type PatentOut } from "../lib/types";

/** Admin's entry point into individual patents — closes open item #13.
 * GET /api/patents already returns every application for Admin/Super
 * Admin (visible_patents_query has no team/assignment restriction for
 * those roles), so this is purely a new frontend surface; no backend
 * change was needed.
 *
 * Shared with Super Admin as of open item #38 — same route
 * (/admin/patents), same component, no duplication. The only
 * role-specific bit is the "back" link below, since Super Admin's home
 * is /super-admin, not /admin, and that route requires the ADMIN role. */
export default function AdminPatentsPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.roles.includes("SUPER_ADMIN") ?? false;
  const backHref = isSuperAdmin ? ROLE_HOME.SUPER_ADMIN : ROLE_HOME.ADMIN;
  const backLabel = isSuperAdmin ? "Back to Super Admin dashboard" : "Back to Admin dashboard";

  const [patents, setPatents] = useState<PatentOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("All");

  useEffect(() => {
    apiFetch<PatentOut[]>("/api/patents")
      .then(setPatents)
      .catch((err) =>
        setError(
          getFriendlyError("AdminPatentsPage.loadPatents", err, "Failed to load applications")
        )
      );
  }, []);

  const statuses = useMemo(() => {
    if (!patents) return [];
    return Array.from(new Set(patents.map((p) => p.application_status))).sort();
  }, [patents]);

  const filtered = useMemo(() => {
    if (!patents) return null;
    if (statusFilter === "All") return patents;
    return patents.filter((p) => p.application_status === statusFilter);
  }, [patents, statusFilter]);

  return (
    <DashboardShell title="All Patents">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <Link to={backHref} className="text-xs text-slate-400 hover:underline">
            ← {backLabel}
          </Link>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">All Patents</h2>
          <p className="mt-1 text-xs text-slate-500">
            Every patent application in the system — read-only. Click into one to view its
            Basic Information, Questionnaire, and Files &amp; Comments.
          </p>
        </div>
        {statuses.length > 0 && (
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
          >
            <option value="All">All statuses</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {filtered === null && !error && <LoadingState />}
      {filtered?.length === 0 && (
        <EmptyState title="No patent applications match this filter." />
      )}

      <div className="space-y-2">
        {filtered?.map((p) => (
          <Link
            key={p.id}
            to={`/admin/patents/${p.id}`}
            className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-3 hover:border-slate-300"
          >
            <div>
              <span className="text-sm font-medium text-slate-900">{p.invention_title}</span>
              <span className="ml-2 text-xs text-slate-400">#{p.id}</span>
            </div>
            <StatusBadge status={p.application_status} />
          </Link>
        ))}
      </div>
    </DashboardShell>
  );
}
