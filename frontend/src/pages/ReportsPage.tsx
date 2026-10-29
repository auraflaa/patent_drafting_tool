import { useEffect, useState } from "react";
import { DashboardShell } from "../components/DashboardShell";
import { StatusBadge } from "../components/StatusBadge";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import { useAuth } from "../context/AuthContext";
import { apiDownload, apiFetch, ApiError, getFriendlyError } from "../lib/api";
import type { DashboardSummary, ReportOut, ReportTypeOut } from "../lib/types";

export default function ReportsPage() {
  const { hasRole, hasPermission } = useAuth();
  // Mirrors the backend's _require_reports_access() bypass exactly (see
  // app/api/reports.py's module docstring): Admin/Super Admin always see
  // the report catalog, everyone else needs an explicit REPORTS_VIEW grant.
  const canViewReports =
    hasRole("ADMIN") || hasRole("SUPER_ADMIN") || hasPermission("REPORTS_VIEW");

  return (
    <DashboardShell title="Reports">
      <div className="space-y-8">
        <DashboardSummaryCards />
        {canViewReports ? (
          <ReportBrowser />
        ) : (
          <div className="rounded-lg border border-slate-200 bg-white p-6 text-center">
            <p className="text-sm text-slate-600">
              Your role doesn't have access to the Reports catalog yet.
            </p>
            <p className="mt-1 text-xs text-slate-400">
              Ask a Super Admin to grant "View Reports" for your role in the
              Role &amp; Permission Matrix.
            </p>
          </div>
        )}
      </div>
    </DashboardShell>
  );
}

// ---------------------------------------------------------------------------
// Personal dashboard summary — always visible, no permission gate.
// ---------------------------------------------------------------------------

function DashboardSummaryCards() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<DashboardSummary>("/api/reports/dashboard")
      .then(setSummary)
      .catch((err) =>
        setError(
          getFriendlyError("ReportsPage.dashboardSummary", err, "Failed to load dashboard")
        )
      );
  }, []);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!summary) return <LoadingState />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard label="Visible applications" value={summary.total_visible_patents} />
        <SummaryCard
          label={summary.action_required_label}
          value={summary.action_required_count}
          highlight={summary.action_required_count > 0}
        />
        <SummaryCard label="Unread notifications" value={summary.unread_notifications} />
        <SummaryCard label="Events in next 7 days" value={summary.upcoming_events_count} />
      </div>

      {summary.status_counts.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Status Breakdown</h2>
          <div className="flex flex-wrap gap-2">
            {summary.status_counts.map((sc) => (
              <div
                key={sc.status}
                className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-1.5"
              >
                <StatusBadge status={sc.status} />
                <span className="text-sm font-medium text-slate-700">{sc.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {summary.recent_activity !== null && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Recent Activity</h2>
          {summary.recent_activity.length === 0 ? (
            <p className="text-xs text-slate-400">No recent activity.</p>
          ) : (
            <ul className="space-y-1.5">
              {summary.recent_activity.map((item) => (
                <li
                  key={item.id}
                  className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-1.5 text-xs"
                >
                  <span className="text-slate-700">
                    {item.event_type || "Event"}
                    {item.entity_type ? ` · ${item.entity_type}` : ""}
                  </span>
                  <span className="text-slate-400">
                    {new Date(item.created_at).toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: number;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        highlight ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"
      }`}
    >
      <div className="text-2xl font-semibold text-slate-900">{value}</div>
      <div className="mt-1 text-xs text-slate-500">{label}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Report catalog — REPORTS_VIEW gated (Admin/Super Admin bypass).
// ---------------------------------------------------------------------------

function ReportBrowser() {
  const [types, setTypes] = useState<ReportTypeOut[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<ReportOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  async function loadTypes() {
    try {
      const data = await apiFetch<ReportTypeOut[]>("/api/reports");
      setTypes(data);
      if (data.length > 0) setSelected((prev) => prev ?? data[0].report_type);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load report types");
    }
  }

  useEffect(() => {
    loadTypes();
  }, []);

  useEffect(() => {
    if (!selected) return;
    setReport(null);
    setError(null);
    apiFetch<ReportOut>(`/api/reports/${selected}`)
      .then(setReport)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load report"));
  }, [selected]);

  async function download() {
    if (!selected) return;
    setDownloading(true);
    setError(null);
    try {
      await apiDownload(`/api/reports/${selected}/export`, `${selected.toLowerCase()}.csv`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("Your role isn't permitted to download this report — ask a Super Admin to grant it.");
      } else {
        setError(
          getFriendlyError("ReportsPage.downloadReport", err, "Download failed")
        );
      }
    } finally {
      setDownloading(false);
    }
  }

  if (!types)
    return error ? (
      <ErrorState message={error} onRetry={loadTypes} />
    ) : (
      <LoadingState label="Loading report catalog…" />
    );

  const selectedMeta = types.find((t) => t.report_type === selected);
  const columns = report && report.rows.length > 0 ? Object.keys(report.rows[0]) : [];

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {types.map((t) => (
            <button
              key={t.report_type}
              onClick={() => setSelected(t.report_type)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                selected === t.report_type
                  ? "bg-slate-900 text-white"
                  : "border border-slate-300 text-slate-700 hover:bg-slate-50"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <button
          onClick={download}
          disabled={!selectedMeta?.can_download || downloading}
          title={
            selectedMeta && !selectedMeta.can_download
              ? "Your role isn't permitted to download this report"
              : undefined
          }
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {downloading ? "Downloading…" : "Download CSV"}
        </button>
      </div>

      {selectedMeta && (
        <p className="mb-3 text-xs text-slate-400">{selectedMeta.description}</p>
      )}
      {error && report && (
        <p className="mb-3 text-xs text-red-600">{error}</p>
      )}

      {!report ? (
        error ? <ErrorState message={error} /> : <LoadingState />
      ) : report.rows.length === 0 ? (
        <EmptyState title="No data yet." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                {columns.map((col) => (
                  <th
                    key={col}
                    className="px-3 py-2 text-left font-medium text-slate-600"
                  >
                    {col.replace(/_/g, " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row, i) => (
                <tr key={i} className="border-b border-slate-100">
                  {columns.map((col) => (
                    <td key={col} className="px-3 py-2 text-slate-700">
                      {row[col] === null || row[col] === "" ? (
                        <span className="text-slate-300">—</span>
                      ) : (
                        String(row[col])
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
