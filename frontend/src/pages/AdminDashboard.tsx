// Admin route tree: user approvals are Super Admin-only; templates
// management and the read-only All Patents view are Admin-scoped.

import { Link } from "react-router-dom";
import { DashboardShell } from "../components/DashboardShell";
import { TemplatesPanel } from "../components/TemplatesPanel";

export default function AdminDashboard() {
  return (
    <DashboardShell title="Admin">
      <div className="mb-8 flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">All Patents</h2>
          <p className="text-xs text-slate-500">
            Browse every patent application in the system (read-only).
          </p>
        </div>
        <Link
          to="/admin/patents"
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          View all patents
        </Link>
      </div>

      <div className="mb-6 border-b border-slate-200 pb-2">
        <h2 className="text-sm font-semibold text-slate-900">Document Templates</h2>
        <p className="text-xs text-slate-500">
          Upload and manage the Word or PDF templates used when generating patent
          documents. Until one is uploaded, generation uses the bundled Form 1 layout.
        </p>
      </div>
      <TemplatesPanel />
    </DashboardShell>
  );
}
