import { useEffect, useState } from "react";
import { apiFetch, getFriendlyError, LONG_REQUEST_TIMEOUT_MS } from "../lib/api";
import {
  REFINE_FIELD_LABELS,
  REFINE_GROUPS,
  type RefinedGroupOut,
} from "../lib/types";
import { LoadingState } from "./LoadingState";
import { ErrorState } from "./ErrorState";

interface Props {
  patentId: string;
  /** Mirrors the refine gate: Under Review, assigned agent or admin. */
  canRefine: boolean;
}

/** AI-refined filing values, stored separately from the questionnaire and
 * editable in place. Saving creates a new version; the raw answers never
 * change. Form rendering reads these values first. */
export function RefinePanel({ patentId, canRefine }: Props) {
  const [groups, setGroups] = useState<Record<string, RefinedGroupOut> | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [refining, setRefining] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  async function load() {
    try {
      const data = await apiFetch<Record<string, RefinedGroupOut>>(
        `/api/patents/${patentId}/form-fields`,
      );
      setGroups(data);
      const seed: Record<string, Record<string, string>> = {};
      for (const [code, group] of Object.entries(data)) {
        seed[code] = Object.fromEntries(
          Object.entries(group.fields).map(([k, v]) => [k, v ?? ""]),
        );
      }
      setDrafts(seed);
    } catch (err) {
      setError(getFriendlyError("RefinePanel.load", err, "Failed to load refined fields"));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  async function refine(code: string) {
    setRefining(code);
    setError(null);
    setSavedMsg(null);
    try {
      await apiFetch(`/api/patents/${patentId}/forms/refine`, {
        method: "POST",
        body: JSON.stringify({ groups: [code] }),
        timeoutMs: LONG_REQUEST_TIMEOUT_MS,
      });
      await load();
    } catch (err) {
      setError(getFriendlyError("RefinePanel.refine", err, "Failed to refine fields"));
    } finally {
      setRefining(null);
    }
  }

  async function save(code: string) {
    const group = groups?.[code];
    if (!group) return;
    const changed: Record<string, string | null> = {};
    for (const key of Object.keys(group.fields)) {
      const next = (drafts[code]?.[key] ?? "").trim();
      const current = (group.fields[key] ?? "").trim();
      if (next !== current) changed[key] = next || null;
    }
    if (Object.keys(changed).length === 0) {
      setSavedMsg("No changes to save.");
      setTimeout(() => setSavedMsg(null), 3000);
      return;
    }
    setSaving(code);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/form-fields`, {
        method: "PATCH",
        body: JSON.stringify({ group: code, fields: changed }),
      });
      setSavedMsg("Saved as a new version.");
      setTimeout(() => setSavedMsg(null), 4000);
      await load();
    } catch (err) {
      setError(getFriendlyError("RefinePanel.save", err, "Failed to save edits"));
    } finally {
      setSaving(null);
    }
  }

  if (groups === null) {
    return error ? (
      <ErrorState message={error} onRetry={load} />
    ) : (
      <LoadingState compact label="Loading refined fields…" />
    );
  }

  return (
    <div className="mt-8">
      <h3 className="mb-1 text-sm font-semibold text-slate-700">AI-refined filing values</h3>
      <p className="mb-1 text-xs text-slate-400">
        The AI rephrases the questionnaire into filing-quality values. Review and edit
        them here — saving creates a new version without touching the questionnaire.
      </p>
      <p className="mb-3 text-xs text-slate-400">
        Refinement sends questionnaire answers and selected document excerpts to the
        configured AI provider; the embodiments group may also send downscaled drawings
        when vision is enabled.
      </p>

      {error && (
        <div role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}
      {savedMsg && (
        <div role="status" className="mb-4 rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {savedMsg}
        </div>
      )}

      <div className="space-y-4">
        {REFINE_GROUPS.map(({ code, label }) => {
          const group = groups[code];
          return (
            <div key={code} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-sm font-semibold text-slate-700">
                  {label}
                  {group && (
                    <span className="ml-2 text-xs font-normal text-slate-400">
                      v{group.version_number}
                      {group.ai_provider && group.ai_provider !== "stub" ? ` · ${group.ai_provider}` : " · draft"}
                    </span>
                  )}
                </h4>
                {canRefine && (
                  <button
                    onClick={() => refine(code)}
                    disabled={refining !== null}
                    className="rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
                  >
                    {refining === code ? "Refining…" : group ? "Re-refine" : "Refine with AI"}
                  </button>
                )}
              </div>

              {!group && (
                <p className="text-xs text-slate-400">
                  Not refined yet. {canRefine ? "Use “Refine with AI” to generate the first version, or fill the questionnaire and refine." : ""}
                </p>
              )}

              {group?.warnings.map((w) => (
                <p key={w} className="mb-1 text-xs text-amber-700">{w}</p>
              ))}
              {group && group.used_figures.length > 0 && (
                <p className="mb-1 text-xs text-slate-500">
                  Figures referenced: {group.used_figures.join(", ")}
                </p>
              )}

              {group && (
                <>
                  <div className="space-y-3">
                    {Object.keys(group.fields).map((key) => (
                      <div key={key}>
                        <label className="mb-1 flex items-center gap-2 text-xs font-medium text-slate-600">
                          {REFINE_FIELD_LABELS[key] ?? key}
                          {group.origin[key] === "user" && (
                            <span className="rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">
                              Edited
                            </span>
                          )}
                          {group.origin[key] === "fallback" && (
                            <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                              Raw
                            </span>
                          )}
                        </label>
                        <textarea
                          value={drafts[code]?.[key] ?? ""}
                          disabled={!canRefine}
                          onChange={(e) =>
                            setDrafts((d) => ({
                              ...d,
                              [code]: { ...(d[code] ?? {}), [key]: e.target.value },
                            }))
                          }
                          rows={key.length < 20 ? 2 : 4}
                          className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm disabled:bg-slate-50"
                        />
                      </div>
                    ))}
                  </div>
                  {canRefine && (
                    <button
                      onClick={() => save(code)}
                      disabled={saving !== null}
                      className="mt-3 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    >
                      {saving === code ? "Saving…" : "Save edits as new version"}
                    </button>
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
