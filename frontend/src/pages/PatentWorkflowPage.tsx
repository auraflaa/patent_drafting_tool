import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { DashboardShell } from "../components/DashboardShell";
import { StatusBadge } from "../components/StatusBadge";
import { CollaborationPanel } from "../components/CollaborationPanel";
import { LoadingState } from "../components/LoadingState";
import { BasicInfoTab, QuestionnaireTab } from "../components/PatentDetailTabs";
import { apiFetch, getFriendlyError } from "../lib/api";
import { type PatentOut } from "../lib/types";

type Tab = "basic-info" | "questionnaire" | "collaboration";

export default function PatentWorkflowPage() {
  const { id } = useParams<{ id: string }>();
  const patentId = id ?? "";

  const [patent, setPatent] = useState<PatentOut | null>(null);
  const [tab, setTab] = useState<Tab>("basic-info");
  const [error, setError] = useState<string | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);

  async function loadPatent() {
    try {
      const data = await apiFetch<PatentOut>(`/api/patents/${patentId}`);
      setPatent(data);
    } catch (err) {
      setError(getFriendlyError("PatentWorkflowPage.loadPatent", err, "Failed to load patent application"));
    }
  }

  useEffect(() => {
    loadPatent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  const isDraft = patent?.application_status === "Draft";

  async function submitApplication() {
    setSubmitBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/submit`, { method: "POST" });
      await loadPatent();
    } catch (err) {
      setError(getFriendlyError("PatentWorkflowPage.catch1", err, "Failed to submit"));
    } finally {
      setSubmitBusy(false);
    }
  }

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
          <Link
            to="/innovator"
            className="text-xs text-slate-400 hover:underline"
          >
            ← Back to dashboard
          </Link>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">
            {patent.invention_title}
          </h2>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={patent.application_status} />
          {isDraft && (
            <button
              onClick={submitApplication}
              disabled={submitBusy}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              Submit application
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {!isDraft && (
        <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
          This application is past Draft — Basic Information and the
          Questionnaire are read-only.
        </p>
      )}

      <div className="mb-6 flex gap-1 border-b border-slate-200">
        {(
          [
            ["basic-info", "Basic Information"],
            ["questionnaire", "Questionnaire"],
            ["collaboration", "Files & Comments"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
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
        <BasicInfoTab patentId={patentId} editable={isDraft} />
      ) : tab === "questionnaire" ? (
        <QuestionnaireTab patentId={patentId} editable={isDraft} />
      ) : (
        <CollaborationPanel patentId={patentId} canManageCalendar={false} />
      )}
    </DashboardShell>
  );
}
