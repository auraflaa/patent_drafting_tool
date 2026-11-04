import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { DashboardShell } from "../components/DashboardShell";
import { DocumentGenerationPanel } from "../components/DocumentGenerationPanel";
import { CollaborationPanel } from "../components/CollaborationPanel";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { StatusBadge } from "../components/StatusBadge";
import { BasicInfoTab, QuestionnaireTab } from "../components/PatentDetailTabs";
import { RefinePanel } from "../components/RefinePanel";
import { FormsPanel } from "../components/FormsPanel";
import { apiFetch, getFriendlyError, LONG_REQUEST_TIMEOUT_MS } from "../lib/api";
import { homePathFor } from "../lib/roles";
import { useAuth } from "../context/AuthContext";
import {
  SECTION_LABELS,
  SECTION_TYPES,
  type AIOutputOut,
  type DraftSectionSlot,
  type PatentOut,
  type SectionType,
} from "../lib/types";

type Tab = "drafting" | "basic-info" | "questionnaire" | "collaboration";

// Pre-filing statuses where AI drafting is allowed; mirrors backend
// DRAFTABLE_STATUSES in app/services/projections.py (the backend stays the
// guard — this only avoids rendering dead buttons).
const DRAFTABLE_STATUSES: ReadonlySet<string> = new Set([
  "Draft",
  "Submitted",
  "Awaiting Patent Agent Acceptance",
  "Under Review",
  "Changes Requested",
  "Ready for Draft Generation",
  "Draft Generated",
]);

export default function DraftWorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const patentId = id ?? "";
  const { user } = useAuth();

  const [patent, setPatent] = useState<PatentOut | null>(null);
  const [slots, setSlots] = useState<DraftSectionSlot[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generatingAll, setGeneratingAll] = useState(false);
  const [generatingSection, setGeneratingSection] =
    useState<SectionType | null>(null);
  const [expanded, setExpanded] = useState<SectionType | null>(null);
  const [versions, setVersions] = useState<Record<string, AIOutputOut[]>>({});
  const [tab, setTab] = useState<Tab>("drafting");

  async function loadPatent() {
    try {
      setPatent(await apiFetch<PatentOut>(`/api/patents/${patentId}`));
    } catch (err) {
      setError(getFriendlyError("DraftWorkspacePage.catch1", err, "Failed to load patent"));
    }
  }

  async function loadDraft() {
    try {
      setSlots(
        await apiFetch<DraftSectionSlot[]>(`/api/patents/${patentId}/draft`),
      );
    } catch (err) {
      setError(
        getFriendlyError("DraftWorkspacePage.loadDraft", err, "Failed to load draft sections"),
      );
    }
  }

  useEffect(() => {
    loadPatent();
    loadDraft();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  async function generateAll() {
    setGeneratingAll(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/draft/generate`, {
        method: "POST",
        body: JSON.stringify({}),
        timeoutMs: LONG_REQUEST_TIMEOUT_MS,
      });
      // New versions invalidate the cached history, and the batch updates
      // ai_status on the patent.
      setVersions({});
      await Promise.all([loadDraft(), loadPatent()]);
    } catch (err) {
      setError(getFriendlyError("DraftWorkspacePage.catch2", err, "Failed to generate draft"));
    } finally {
      setGeneratingAll(false);
    }
  }

  async function regenerate(section: SectionType) {
    setGeneratingSection(section);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/draft/generate`, {
        method: "POST",
        body: JSON.stringify({ section_types: [section] }),
        timeoutMs: LONG_REQUEST_TIMEOUT_MS,
      });
      setVersions({});
      await Promise.all([loadDraft(), loadPatent()]);
    } catch (err) {
      setError(
        getFriendlyError("DraftWorkspacePage.regenerateSection", err, "Failed to regenerate section"),
      );
    } finally {
      setGeneratingSection(null);
    }
  }

  async function toggleVersions(section: SectionType) {
    if (expanded === section) {
      setExpanded(null);
      return;
    }
    setExpanded(section);
    if (!versions[section]) {
      try {
        const data = await apiFetch<AIOutputOut[]>(
          `/api/patents/${patentId}/draft/${section}/versions`,
        );
        setVersions((v) => ({ ...v, [section]: data }));
      } catch (err) {
        setError(
          getFriendlyError("DraftWorkspacePage.loadVersions", err, "Failed to load version history"),
        );
      }
    }
  }

  if (!patent || !slots) {
    return (
      <DashboardShell title="AI Drafting">
        {error ? (
          <ErrorState
            message={error}
            onRetry={() => {
              loadPatent();
              loadDraft();
            }}
          />
        ) : (
          <LoadingState />
        )}
      </DashboardShell>
    );
  }

  // Mirrors backend DRAFTABLE_STATUSES (services/projections.py): drafting is
  // pre-filing work. The backend remains the guard; this only avoids
  // rendering dead buttons.
  const canGenerate = DRAFTABLE_STATUSES.has(patent.application_status);
  const anySectionGenerated = slots.some((s) => s.latest !== null);

  return (
    <DashboardShell title="AI Drafting">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <Link
            to={homePathFor(user?.roles)}
            className="text-xs text-slate-400 hover:underline"
          >
            ← Back to dashboard
          </Link>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">
            {patent.invention_title}
          </h2>
        </div>
        <StatusBadge status={patent.application_status} />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {!canGenerate && (
        <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
          AI drafting is available while the application is in a pre-filing
          status (Draft through Draft Generated). Current status:{" "}
          {patent.application_status}.
        </p>
      )}

      <div className="mb-6 flex gap-1 border-b border-slate-200" role="tablist" aria-label="Draft workspace sections">
        {(
          [
            ["drafting", "AI Drafting"],
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
        // Read-only: the Patent Agent can see everything the Innovator
        // filled in, but never edits it here.
        <BasicInfoTab patentId={patentId} editable={false} />
      ) : tab === "questionnaire" ? (
        <QuestionnaireTab patentId={patentId} editable={false} />
      ) : tab === "collaboration" ? (
        <CollaborationPanel patentId={patentId} canManageCalendar={true} />
      ) : (
        <>
          <div className="mb-6 flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4">
            <div>
              <p className="text-sm font-medium text-slate-700">
                {anySectionGenerated
                  ? "Regenerate all sections"
                  : "Generate initial draft"}
              </p>
              <p className="text-xs text-slate-400">
                Uses the latest submitted questionnaire. Each section is
                generated independently and can be regenerated on its own below
                without affecting the others.
              </p>
            </div>
            {canGenerate && (
              <button
                onClick={generateAll}
                disabled={generatingAll}
                className="whitespace-nowrap rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              >
                {generatingAll ? "Generating…" : "Generate all sections"}
              </button>
            )}
          </div>

          <div className="space-y-4">
            {SECTION_TYPES.map((section) => {
              const slot = slots.find((s) => s.section_type === section);
              const latest = slot?.latest ?? null;
              return (
                <div
                  key={section}
                  className="rounded-lg border border-slate-200 bg-white p-4"
                >
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-slate-700">
                      {SECTION_LABELS[section]}
                      {latest && (
                        <span className="ml-2 text-xs font-normal text-slate-400">
                          v{latest.version_number} · {latest.processing_status}
                        </span>
                      )}
                    </h3>
                    {canGenerate && (
                      <button
                        onClick={() => regenerate(section)}
                        disabled={generatingSection === section}
                        className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      >
                        {generatingSection === section
                          ? "Generating…"
                          : latest
                            ? "Regenerate"
                            : "Generate"}
                      </button>
                    )}
                  </div>

                  {!latest && (
                    <p className="text-xs text-slate-400">Not generated yet.</p>
                  )}
                  {latest && (
                    <>
                      <p className="whitespace-pre-wrap text-sm text-slate-700">
                        {latest.ai_response}
                      </p>
                      <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
                        <span>
                          {latest.ai_provider}
                          {latest.ai_model ? ` (${latest.ai_model})` : ""}
                        </span>
                        <button
                          onClick={() => toggleVersions(section)}
                          className="text-blue-600 hover:underline"
                        >
                          {expanded === section ? "Hide" : "Show"} version
                          history
                        </button>
                      </div>
                      {expanded === section && versions[section] && (
                        <div className="mt-2 space-y-1 border-t border-slate-100 pt-2">
                          {versions[section].map((v) => (
                            <div key={v.id} className="text-xs text-slate-500">
                              <span className="font-medium text-slate-700">
                                v{v.version_number}
                              </span>{" "}
                              — {v.processing_status} ·{" "}
                              {new Date(v.created_at).toLocaleString()}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>

          <DocumentGenerationPanel
            patentId={patentId}
            statusAllowsGeneration={
              patent.application_status === "Under Review" ||
              patent.application_status === "Draft Generated"
            }
            applicationStatus={patent.application_status}
            allSectionsCompleted={SECTION_TYPES.every(
              (section) =>
                slots.find((s) => s.section_type === section)?.latest
                  ?.processing_status === "Completed",
            )}
            onChanged={loadPatent}
          />

          <RefinePanel
            patentId={patentId}
            canRefine={canGenerate}
          />

          <FormsPanel
            patentId={patentId}
            statusAllowsGeneration={
              patent.application_status === "Under Review" ||
              patent.application_status === "Draft Generated"
            }
            applicationStatus={patent.application_status}
            inventionTitle={patent.invention_title}
            onChanged={loadPatent}
          />
        </>
      )}
    </DashboardShell>
  );
}
