import { useCallback, useEffect, useState } from "react";
import { apiFetch, getFriendlyError, LONG_REQUEST_TIMEOUT_MS } from "../lib/api";
import { LoadingState } from "./LoadingState";
import {
  SECTION_LABELS,
  SECTION_TYPES,
  type AIOutputOut,
  type DraftSectionSlot,
  type SectionType,
} from "../lib/types";

/** Innovator-visible AI drafts: the five legacy sections, nothing else.
 *
 * The agent workspace (`DraftWorkspacePage`) keeps documents, refinement,
 * and forms. This panel is deliberately narrower: view the latest text per
 * section, (re)generate, and browse version history. The backend enforces
 * who may generate and in which statuses; a 403/400 here surfaces its
 * message instead of a dead button.
 */
export function DraftsTab({
  patentId,
  canGenerate,
}: {
  patentId: string;
  canGenerate: boolean;
}) {
  const [slots, setSlots] = useState<DraftSectionSlot[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generatingAll, setGeneratingAll] = useState(false);
  const [generatingSection, setGeneratingSection] =
    useState<SectionType | null>(null);
  const [expanded, setExpanded] = useState<SectionType | null>(null);
  const [versions, setVersions] = useState<Record<string, AIOutputOut[]>>({});

  const load = useCallback(async () => {
    try {
      setSlots(
        await apiFetch<DraftSectionSlot[]>(`/api/patents/${patentId}/draft`),
      );
      setError(null);
    } catch (err) {
      setError(
        getFriendlyError("DraftsTab.load", err, "Failed to load draft sections"),
      );
    }
  }, [patentId]);

  useEffect(() => {
    setSlots(null);
    void load();
  }, [patentId, load]);

  async function generate(sections?: SectionType[]) {
    const single = sections?.length === 1 ? sections[0] : null;
    setGeneratingAll(single === null);
    if (single) setGeneratingSection(single);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/draft/generate`, {
        method: "POST",
        body: JSON.stringify(sections ? { section_types: sections } : {}),
        timeoutMs: LONG_REQUEST_TIMEOUT_MS,
      });
      setVersions({});
      await load();
    } catch (err) {
      setError(
        getFriendlyError("DraftsTab.generate", err, "Failed to generate draft"),
      );
    } finally {
      setGeneratingAll(false);
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
          getFriendlyError(
            "DraftsTab.versions",
            err,
            "Failed to load version history",
          ),
        );
      }
    }
  }

  if (slots === null) {
    return error ? (
      <p className="text-sm text-red-600">{error}</p>
    ) : (
      <LoadingState />
    );
  }

  const anySectionGenerated = slots.some((s) => s.latest !== null);

  return (
    <div>
      {error && (
        <p className="mb-3 text-sm text-red-600">{error}</p>
      )}
      <div className="mb-6 flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4">
        <div>
          <p className="text-sm font-medium text-slate-700">
            {anySectionGenerated ? "Regenerate all sections" : "Generate initial draft"}
          </p>
          <p className="text-xs text-slate-400">
            Uses the latest submitted questionnaire. Each section is
            generated independently and can be regenerated on its own below
            without affecting the others.
          </p>
        </div>
        {canGenerate && (
          <button
            onClick={() => generate()}
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
          const busy =
            generatingAll || generatingSection === section;
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
                    onClick={() => generate([section])}
                    disabled={busy}
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
                      {expanded === section ? "Hide" : "Show"} version history
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
    </div>
  );
}
