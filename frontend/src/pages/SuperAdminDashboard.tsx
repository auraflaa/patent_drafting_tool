import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DashboardShell } from "../components/DashboardShell";
import { TemplatesPanel } from "../components/TemplatesPanel";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import { apiFetch, getFriendlyError } from "../lib/api";
import type {
  PendingUserOut,
  RbacMatrixResponse,
  ReportPermissionMatrixResponse,
  UserAdminOut,
} from "../lib/types";
import { ALL_ROLE_CODES } from "../lib/types";

type Tab = "pending" | "matrix" | "users" | "templates" | "report-permissions";

export default function SuperAdminDashboard() {
  const [tab, setTab] = useState<Tab>("pending");

  return (
    <DashboardShell title="Super Admin">
      <div className="mb-6 flex gap-1 border-b border-slate-200" role="tablist" aria-label="Super Admin sections">
        <TabButton active={tab === "pending"} onClick={() => setTab("pending")}>
          Pending Approvals
        </TabButton>
        <TabButton active={tab === "matrix"} onClick={() => setTab("matrix")}>
          Role &amp; Permission Matrix
        </TabButton>
        <TabButton active={tab === "users"} onClick={() => setTab("users")}>
          All Users
        </TabButton>
        <TabButton active={tab === "templates"} onClick={() => setTab("templates")}>
          Templates
        </TabButton>
        {/* Report types each role may download, independent of the ordinary
            Role & Permission Matrix's REPORTS_VIEW/REPORTS_DOWNLOAD codes. */}
        <TabButton
          active={tab === "report-permissions"}
          onClick={() => setTab("report-permissions")}
        >
          Report Download Permissions
        </TabButton>
        {/* Not a tab like the others: a real navigation into the shared
            /admin/patents route, styled like a tab but a Link. */}
        <Link
          to="/admin/patents"
          className="border-b-2 border-transparent px-4 py-2 text-sm font-medium text-slate-500 transition hover:text-slate-700"
        >
          All Patents
        </Link>
      </div>

      {tab === "pending" && <PendingApprovalsPanel />}
      {tab === "matrix" && <RbacMatrixPanel />}
      {tab === "users" && <AllUsersPanel />}
      {tab === "templates" && <TemplatesPanel />}
      {tab === "report-permissions" && <ReportPermissionsPanel />}
    </DashboardShell>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`border-b-2 px-4 py-2 text-sm font-medium transition ${
        active
          ? "border-slate-900 text-slate-900"
          : "border-transparent text-slate-500 hover:text-slate-700"
      }`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Pending approvals
// ---------------------------------------------------------------------------

function PendingApprovalsPanel() {
  const [pending, setPending] = useState<PendingUserOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedRoles, setSelectedRoles] = useState<Record<string, Set<string>>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    try {
      const data = await apiFetch<PendingUserOut[]>("/api/auth/pending-users");
      setPending(data);
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch1", err, "Failed to load pending users"));
    }
  }

  useEffect(() => {
    load();
  }, []);

  function toggleRole(userId: string, role: string) {
    setSelectedRoles((prev) => {
      const current = new Set(prev[userId] ?? []);
      if (current.has(role)) current.delete(role);
      else current.add(role);
      return { ...prev, [userId]: current };
    });
  }

  async function approve(userId: string) {
    const roles = Array.from(selectedRoles[userId] ?? []);
    if (roles.length === 0) {
      setError("Select at least one role before approving.");
      return;
    }
    setBusyId(userId);
    setError(null);
    try {
      await apiFetch(`/api/auth/users/${userId}/approve`, {
        method: "POST",
        body: JSON.stringify({ role_codes: roles }),
      });
      await load();
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch2", err, "Approval failed"));
    } finally {
      setBusyId(null);
    }
  }

  async function reject(userId: string) {
    setBusyId(userId);
    setError(null);
    try {
      await apiFetch(`/api/auth/users/${userId}/reject`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await load();
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch3", err, "Rejection failed"));
    } finally {
      setBusyId(null);
    }
  }

  if (pending === null)
    return error ? (
      <ErrorState message={error} onRetry={load} />
    ) : (
      <LoadingState />
    );

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-red-600">{error}</p>}
      {pending.length === 0 && (
        <EmptyState title="No accounts awaiting approval." />
      )}
      {pending.map((u) => {
        // Nameless rows (synthetic/test imports) still need an identifier.
        const title = u.full_name || u.email || u.id;
        return (
        <div key={u.id} className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm font-medium text-slate-900">{title}</p>
              {u.email && u.email !== title && (
                <p className="text-xs text-slate-500">{u.email}</p>
              )}
              {u.organization && (
                <p className="text-xs text-slate-400">{u.organization}</p>
              )}
            </div>
            <p className="text-xs text-slate-400">
              {new Date(u.created_at).toLocaleDateString()}
            </p>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {ALL_ROLE_CODES.map((role) => (
              <label
                key={role}
                className="flex items-center gap-1.5 rounded-md border border-slate-200 px-2 py-1 text-xs"
              >
                <input
                  type="checkbox"
                  checked={selectedRoles[u.id]?.has(role) ?? false}
                  onChange={() => toggleRole(u.id, role)}
                />
                {role}
              </label>
            ))}
          </div>

          <div className="mt-3 flex gap-2">
            <button
              onClick={() => approve(u.id)}
              disabled={busyId === u.id}
              className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Approve
            </button>
            <button
              onClick={() => reject(u.id)}
              disabled={busyId === u.id}
              className="rounded-md border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Role & Permission matrix
// ---------------------------------------------------------------------------

function RbacMatrixPanel() {
  const [matrix, setMatrix] = useState<RbacMatrixResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingCell, setPendingCell] = useState<string | null>(null);

  async function load() {
    try {
      const data = await apiFetch<RbacMatrixResponse>("/api/rbac/matrix");
      setMatrix(data);
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch4", err, "Failed to load matrix"));
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (!matrix)
    return error ? (
      <ErrorState message={error} onRetry={load} />
    ) : (
      <LoadingState />
    );

  const isGranted = (roleId: number, permId: number) =>
    matrix.grants.some((g) => g.role_id === roleId && g.permission_id === permId);

  async function toggle(roleId: number, permId: number, grant: boolean) {
    const key = `${roleId}-${permId}`;
    setPendingCell(key);
    setError(null);
    try {
      const updated = await apiFetch<RbacMatrixResponse>(
        `/api/rbac/toggle?grant=${grant}`,
        { method: "POST", body: JSON.stringify({ role_id: roleId, permission_id: permId }) }
      );
      setMatrix(updated);
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch5", err, "Toggle failed"));
    } finally {
      setPendingCell(null);
    }
  }

  // Group permissions by module for readability.
  const modules = Array.from(new Set(matrix.permissions.map((p) => p.module_name || "Other")));

  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50">
              <th className="px-3 py-2 text-left font-medium text-slate-600">Permission</th>
              {matrix.roles.map((r) => (
                <th key={r.id} className="px-3 py-2 text-center font-medium text-slate-600">
                  {r.role_code}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {modules.map((mod) => (
              <Fragment key={mod}>
                <tr key={`mod-${mod}`} className="bg-slate-100">
                  <td
                    colSpan={matrix.roles.length + 1}
                    className="px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-500"
                  >
                    {mod}
                  </td>
                </tr>
                {matrix.permissions
                  .filter((p) => (p.module_name || "Other") === mod)
                  .map((perm) => (
                    <tr key={perm.id} className="border-b border-slate-100">
                      <td className="px-3 py-2 text-slate-700">
                        {perm.permission_name}
                        <span className="ml-1 text-xs text-slate-400">
                          ({perm.action})
                        </span>
                      </td>
                      {matrix.roles.map((role) => {
                        const granted = isGranted(role.id, perm.id);
                        const key = `${role.id}-${perm.id}`;
                        const isSuperAdmin = role.role_code === "SUPER_ADMIN";
                        return (
                          <td key={role.id} className="px-3 py-2 text-center">
                            <input
                              type="checkbox"
                              checked={granted}
                              disabled={pendingCell === key || isSuperAdmin}
                              title={
                                isSuperAdmin
                                  ? "Super Admin always has full access"
                                  : undefined
                              }
                              onChange={(e) => toggle(role.id, perm.id, e.target.checked)}
                            />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Report download permissions — mirrors RbacMatrixPanel above, but against
// /api/reports/permissions/matrix (report_type x role, not permission x
// role). Admin/Super Admin already bypass this at the API layer (see
// app/services/reports_service.py's can_download() docstring), so those
// two columns are shown read-only/checked, same convention as
// RbacMatrixPanel disabling the SUPER_ADMIN column above.
// ---------------------------------------------------------------------------

function ReportPermissionsPanel() {
  const [matrix, setMatrix] = useState<ReportPermissionMatrixResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingCell, setPendingCell] = useState<string | null>(null);

  async function load() {
    try {
      const data = await apiFetch<ReportPermissionMatrixResponse>(
        "/api/reports/permissions/matrix"
      );
      setMatrix(data);
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch6", err, "Failed to load report permissions"));
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (!matrix)
    return error ? (
      <ErrorState message={error} onRetry={load} />
    ) : (
      <LoadingState />
    );

  const isGranted = (roleId: number, reportType: string) =>
    matrix.grants.some((g) => g.role_id === roleId && g.report_type === reportType);

  async function toggle(roleId: number, reportType: string, grant: boolean) {
    const key = `${roleId}-${reportType}`;
    setPendingCell(key);
    setError(null);
    try {
      const updated = await apiFetch<ReportPermissionMatrixResponse>(
        `/api/reports/permissions/toggle?grant=${grant}`,
        { method: "POST", body: JSON.stringify({ role_id: roleId, report_type: reportType }) }
      );
      setMatrix(updated);
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch7", err, "Toggle failed"));
    } finally {
      setPendingCell(null);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-400">
        Controls which report types each role may download as CSV. Admin and
        Super Admin always may — this only matters for Patent Agent and
        Innovator.
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50">
              <th className="px-3 py-2 text-left font-medium text-slate-600">Report</th>
              {matrix.roles.map((r) => (
                <th key={r.id} className="px-3 py-2 text-center font-medium text-slate-600">
                  {r.role_code}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.report_types.map((rt) => (
              <tr key={rt.report_type} className="border-b border-slate-100">
                <td className="px-3 py-2 text-slate-700">
                  {rt.label}
                  <span className="ml-1 text-xs text-slate-400">({rt.description})</span>
                </td>
                {matrix.roles.map((role) => {
                  const isAdminLike = role.role_code === "ADMIN" || role.role_code === "SUPER_ADMIN";
                  const granted = isAdminLike || isGranted(role.id, rt.report_type);
                  const key = `${role.id}-${rt.report_type}`;
                  return (
                    <td key={role.id} className="px-3 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={granted}
                        disabled={pendingCell === key || isAdminLike}
                        title={isAdminLike ? "Admin/Super Admin always may download" : undefined}
                        onChange={(e) => toggle(role.id, rt.report_type, e.target.checked)}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// All users — assign / revoke roles
// ---------------------------------------------------------------------------

function AllUsersPanel() {
  const [users, setUsers] = useState<UserAdminOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  async function load() {
    try {
      const data = await apiFetch<UserAdminOut[]>("/api/rbac/users");
      setUsers(data);
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch8", err, "Failed to load users"));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function assignRole(userId: string, role: string) {
    const key = `assign-${userId}-${role}`;
    setBusyKey(key);
    setError(null);
    try {
      await apiFetch(`/api/rbac/users/${userId}/roles`, {
        method: "POST",
        body: JSON.stringify({ role_code: role }),
      });
      await load();
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch9", err, "Assign failed"));
    } finally {
      setBusyKey(null);
    }
  }

  async function revokeRole(userId: string, role: string) {
    const key = `revoke-${userId}-${role}`;
    setBusyKey(key);
    setError(null);
    try {
      await apiFetch(`/api/rbac/users/${userId}/roles/${role}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(getFriendlyError("SuperAdminDashboard.catch10", err, "Revoke failed"));
    } finally {
      setBusyKey(null);
    }
  }

  if (!users)
    return error ? (
      <ErrorState message={error} onRetry={load} />
    ) : (
      <LoadingState />
    );

  return (
    <div className="space-y-3">
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-left">
              <th className="px-3 py-2 font-medium text-slate-600">User</th>
              <th className="px-3 py-2 font-medium text-slate-600">Status</th>
              <th className="px-3 py-2 font-medium text-slate-600">Roles</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-slate-100">
                <td className="px-3 py-2">
                  <div className="font-medium text-slate-900">{u.full_name}</div>
                  <div className="text-xs text-slate-500">{u.email}</div>
                </td>
                <td className="px-3 py-2 text-xs">
                  <span
                    className={`rounded-full px-2 py-0.5 ${
                      u.account_status === "Approved"
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {u.account_status}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1.5">
                    {ALL_ROLE_CODES.map((role) => {
                      const held = u.roles.includes(role);
                      const key = held ? `revoke-${u.id}-${role}` : `assign-${u.id}-${role}`;
                      return (
                        <button
                          key={role}
                          disabled={busyKey === key}
                          onClick={() =>
                            held ? revokeRole(u.id, role) : assignRole(u.id, role)
                          }
                          className={`rounded-full px-2 py-0.5 text-xs font-medium transition disabled:opacity-50 ${
                            held
                              ? "bg-slate-900 text-white hover:bg-slate-700"
                              : "border border-slate-300 text-slate-500 hover:bg-slate-50"
                          }`}
                          title={held ? `Click to revoke ${role}` : `Click to grant ${role}`}
                        >
                          {role}
                        </button>
                      );
                    })}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
