import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DashboardShell } from "../components/DashboardShell";
import { StatusBadge } from "../components/StatusBadge";
import { LoadingState } from "../components/LoadingState";
import { EmptyState } from "../components/EmptyState";
import { apiFetch, getFriendlyError } from "../lib/api";
import type { PatentOut } from "../lib/types";

export default function AgentDashboard() {
  const [patents, setPatents] = useState<PatentOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const data = await apiFetch<PatentOut[]>("/api/patents");
      setPatents(data);
    } catch (err) {
      setError(
        getFriendlyError("AgentDashboard.loadPatents", err, "Failed to load applications")
      );
    }
  }

  useEffect(() => {
    load();
  }, []);

  const awaitingDecision = patents?.filter(
    (p) => p.application_status === "Awaiting Patent Agent Acceptance"
  );
  const rest = patents?.filter(
    (p) => p.application_status !== "Awaiting Patent Agent Acceptance"
  );

  return (
    <DashboardShell title="Patent Agent">
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {awaitingDecision && awaitingDecision.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">
            Awaiting your decision
          </h2>
          <div className="space-y-3">
            {awaitingDecision.map((p) => (
              <AssignmentCard key={p.id} patent={p} onChanged={load} />
            ))}
          </div>
        </div>
      )}

      <div>
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Your applications</h2>
        {rest === null && <LoadingState />}
        {rest?.length === 0 && (
          <EmptyState title="Nothing assigned to you yet." />
        )}
        <div className="space-y-2">
          {rest?.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-3"
            >
              <span className="text-sm font-medium text-slate-900">{p.invention_title}</span>
              <div className="flex items-center gap-3">
                <StatusBadge status={p.application_status} />
                <Link
                  to={`/agent/patents/${p.id}/draft`}
                  className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  AI Drafting
                </Link>
              </div>
            </div>
          ))}
        </div>
      </div>
    </DashboardShell>
  );
}

function AssignmentCard({ patent, onChanged }: { patent: PatentOut; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [reason, setReason] = useState("");

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patent.id}/assignment/accept`, { method: "POST" });
      onChanged();
    } catch (err) {
      setError(
        getFriendlyError("AgentDashboard.accept", err, "Failed to accept")
      );
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patent.id}/assignment/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() || undefined }),
      });
      onChanged();
    } catch (err) {
      setError(
        getFriendlyError("AgentDashboard.reject", err, "Failed to reject")
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-900">{patent.invention_title}</span>
        <StatusBadge status={patent.application_status} />
      </div>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}

      {!showReject ? (
        <div className="mt-3 flex gap-2">
          <button
            onClick={accept}
            disabled={busy}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Accept
          </button>
          <button
            onClick={() => setShowReject(true)}
            disabled={busy}
            className="rounded-md border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <input
            type="text"
            placeholder="Reason (optional)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
          />
          <div className="flex gap-2">
            <button
              onClick={reject}
              disabled={busy}
              className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              Confirm reject
            </button>
            <button
              onClick={() => setShowReject(false)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
