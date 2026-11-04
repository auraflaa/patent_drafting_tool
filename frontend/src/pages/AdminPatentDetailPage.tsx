import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { DashboardShell } from "../components/DashboardShell";
import { StatusBadge } from "../components/StatusBadge";
import { CollaborationPanel } from "../components/CollaborationPanel";
import { LoadingState } from "../components/LoadingState";
import { BasicInfoTab, QuestionnaireTab } from "../components/PatentDetailTabs";
import { apiFetch, getFriendlyError } from "../lib/api";
import { type AvailableAgentOut, type PatentOut } from "../lib/types";

type Tab = "basic-info" | "questionnaire" | "collaboration";

// Mirrors PRE_ASSIGNMENT_STATUSES / TERMINAL_STATUSES on the backend
// (app/services/patent_service.py) — used here only to decide whether to
// show the Reassign panel at all. The backend is the actual source of
// truth and re-validates on every call; this is purely a UI hint so
// Admin isn't shown a button that would just 400.
const PRE_ASSIGNMENT_STATUSES = new Set([
  "Draft",
  "Submitted",
  "Awaiting Patent Agent Acceptance",
]);
const TERMINAL_STATUSES = new Set(["Granted", "Rejected", "Withdrawn", "Abandoned"]);

function ReassignAgentPanel({
  patent,
  onChanged,
}: {
  patent: PatentOut;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<AvailableAgentOut[] | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const eligible =
    !PRE_ASSIGNMENT_STATUSES.has(patent.application_status) &&
    !TERMINAL_STATUSES.has(patent.application_status);

  if (!eligible) return null;

  async function openPanel() {
    setOpen(true);
    setError(null);
    try {
      const data = await apiFetch<AvailableAgentOut[]>("/api/patents/available-agents");
      setAgents(data.filter((a) => a.id !== patent.assigned_patent_agent_id));
    } catch (err) {
      setError(
        getFriendlyError("AdminPatentDetailPage.availableAgents", err, "Failed to load agents")
      );
    }
  }

  async function submit() {
    if (!selectedAgentId || !reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patent.id}/reassign`, {
        method: "POST",
        body: JSON.stringify({ patent_agent_id: selectedAgentId, reason: reason.trim() }),
      });
      setOpen(false);
      setReason("");
      setSelectedAgentId(null);
      onChanged();
    } catch (err) {
      setError(
        getFriendlyError("AdminPatentDetailPage.reassign", err, "Failed to reassign")
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-4">
      {!open ? (
        <button
          onClick={openPanel}
          className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          Reassign Patent Agent
        </button>
      ) : (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
          <p className="mb-2 text-xs text-amber-800">
            This application already has an agent who accepted it. Reassigning pulls it away
            from them — the new agent will still have to accept it themselves before work
            continues, same as any other assignment.
          </p>
          {error && <p className="mb-2 text-xs text-red-600">{error}</p>}
          {agents === null && <LoadingState compact label="Loading agents…" />}
          <div className="mb-2 space-y-1">
            {agents?.map((a) => (
              <button
                key={a.id}
                onClick={() => setSelectedAgentId(a.id)}
                disabled={busy}
                className={`flex w-full items-center justify-between rounded-md border px-2.5 py-1.5 text-xs disabled:opacity-50 ${
                  selectedAgentId === a.id
                    ? "border-slate-900 bg-white"
                    : "border-slate-200 bg-white hover:bg-slate-100"
                }`}
              >
                <span>
                  {a.full_name} <span className="text-slate-400">({a.email})</span>
                </span>
                <span className="text-slate-400">{a.active_assignment_count} active</span>
              </button>
            ))}
          </div>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for reassigning (required, kept in the audit trail)"
            rows={2}
            className="mb-2 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs"
          />
          <div className="flex gap-2">
            <button
              onClick={submit}
              disabled={busy || !selectedAgentId || !reason.trim()}
              className="rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              Confirm reassignment
            </button>
            <button
              onClick={() => setOpen(false)}
              className="text-xs text-slate-400 hover:underline"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Read-only Basic Information / Questionnaire / Files & Comments view for
 * Admin — closes open item #13 (Admin previously had no way to view an
 * individual patent's content at all, only its Templates panel). Reuses
 * the exact same BasicInfoTab/QuestionnaireTab components the Innovator's
 * editable PatentWorkflowPage uses, with editable={false} throughout —
 * Admin can see everything visible_patents_query/can_view_patent already
 * grants them on the backend, but never edits an applicant's own data
 * from here. */
export default function AdminPatentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const patentId = id ?? "";

  const [patent, setPatent] = useState<PatentOut | null>(null);
  const [tab, setTab] = useState<Tab>("basic-info");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<PatentOut>(`/api/patents/${patentId}`)
      .then(setPatent)
      .catch((err) =>
        setError(
          getFriendlyError("AdminPatentDetailPage.loadPatent", err, "Failed to load patent application")
        )
      );
  }, [patentId]);

  if (!patent) {
    return (
      <DashboardShell title="Patent Application">
        {error ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : (
          <LoadingState />
        )}
      </DashboardShell>
    );
  }

  return (
    <DashboardShell title="Patent Application">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <Link to="/admin/patents" className="text-xs text-slate-400 hover:underline">
            ← Back to all patents
          </Link>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">
            {patent.invention_title}
          </h2>
        </div>
        <div className="flex items-center gap-3">
          <Link
            to={`/admin/patents/${patentId}/draft`}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Drafting workspace
          </Link>
          <StatusBadge status={patent.application_status} />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
        Admin view is read-only — Basic Information and the Questionnaire belong to the
        Innovator and Agent's own workflows.
      </p>

      <ReassignAgentPanel
        patent={patent}
        onChanged={() =>
          apiFetch<PatentOut>(`/api/patents/${patentId}`)
            .then(setPatent)
            .catch((err) =>
              setError(getFriendlyError("AdminPatentDetailPage.catch1", err, "Failed to reload patent application"))
            )
        }
      />

      <div className="mb-6 flex gap-1 border-b border-slate-200" role="tablist" aria-label="Patent sections">
        {(
          [
            ["basic-info", "Basic Information"],
            ["questionnaire", "Questionnaire"],
            ["collaboration", "Files & Comments"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
              tab === key
                ? "border-slate-900 text-slate-900"
                : "border-transparent text-slate-400 hover:text-slate-600"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "basic-info" ? (
        <BasicInfoTab patentId={patentId} editable={false} />
      ) : tab === "questionnaire" ? (
        <QuestionnaireTab patentId={patentId} editable={false} />
      ) : (
        // Calendar event management is server-gated to the assigned agent
        // and admins — see the calendar routes in backend/app/api/resources.py.
        <CollaborationPanel patentId={patentId} canManageCalendar={true} />
      )}
    </DashboardShell>
  );
}
