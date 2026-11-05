import { useEffect, useState } from "react";
import { apiDownload, apiFetch, getFriendlyError, LONG_REQUEST_TIMEOUT_MS } from "../lib/api";
import type {
  DocumentVersionOut,
  FormCardOut,
  FormsGenerateOut,
  FormsStatusOut,
} from "../lib/types";
import { LoadingState } from "./LoadingState";
import { ErrorState } from "./ErrorState";

interface Props {
  patentId: string;
  /** Mirrors the backend gate in generate_forms: Under Review or Draft Generated. */
  statusAllowsGeneration: boolean;
  applicationStatus: string;
  inventionTitle: string;
  onChanged?: () => void;
}

/** Statutory forms generated from the questionnaire (FORM1/2/3/5 + Drawings).
 * Each form is its own card with status, missing fields, versions, and a
 * filing-style download name. Finalize is blocked until every form exists
 * and at least one usable drawing is selected. */
export function FormsPanel({
  patentId,
  statusAllowsGeneration,
  applicationStatus,
  inventionTitle,
  onChanged,
}: Props) {
  const [status, setStatus] = useState<FormsStatusOut | null>(null);
  const [versions, setVersions] = useState<Record<string, DocumentVersionOut[]>>({});
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generatingCode, setGeneratingCode] = useState<string | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const [showCounts, setShowCounts] = useState(false);
  const [counts, setCounts] = useState<Record<string, string>>({});

  /** Attachment counts for the Form 1 fee table. Page counts cannot be
   * computed (Word does not paginate); the drawings count is derived
   * server-side from the selected figures. */
  const COUNT_FIELDS = [
    { key: "page_count", label: "Spec pages", hint: "e.g. 13" },
    { key: "claim_count", label: "Claims", hint: "e.g. 04" },
    { key: "claims_page_count", label: "Claim pages", hint: "e.g. 01" },
    { key: "abstract_page_count", label: "Abstract pages", hint: "e.g. 01" },
    { key: "drawing_page_count", label: "Drawing pages", hint: "e.g. 02" },
  ] as const;

  function countsPayload(): Record<string, Record<string, string>> {
    const filled: Record<string, string> = {};
    for (const { key } of COUNT_FIELDS) {
      const value = (counts[key] ?? "").trim();
      if (value) filled[key] = value;
    }
    return Object.keys(filled).length > 0 ? { counts: filled } : {};
  }

  async function load() {
    try {
      setStatus(await apiFetch<FormsStatusOut>(`/api/patents/${patentId}/forms`));
    } catch (err) {
      setError(getFriendlyError("FormsPanel.load", err, "Failed to load forms"));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  function fileSlug(): string {
    const slug = (inventionTitle || "patent")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60);
    return slug || "patent";
  }

  async function generate(codes?: string[]) {
    if (codes) setGeneratingCode(codes[0]);
    else setGenerating(true);
    setError(null);
    setNotices([]);
    try {
      const out = await apiFetch<FormsGenerateOut>(
        `/api/patents/${patentId}/forms/generate`,
        {
          method: "POST",
          body: JSON.stringify(codes ? { codes, ...countsPayload() } : countsPayload()),
          timeoutMs: LONG_REQUEST_TIMEOUT_MS,
        },
      );
      const failed = out.results.filter((r) => r.status === "Failed");
      if (failed.length > 0) {
        setError(
          `Generated with ${failed.length} failure(s): ` +
            failed.map((r) => `${r.form_code}: ${r.error ?? "unknown error"}`).join("; "),
        );
      }
      const notes = out.results.flatMap((r) =>
        (r.warnings ?? []).map((w) => `${r.form_code}: ${w}`),
      );
      if (notes.length > 0) setNotices(notes);
      setVersions({});
      await load();
      onChanged?.();
    } catch (err) {
      setError(getFriendlyError("FormsPanel.generate", err, "Failed to generate forms"));
    } finally {
      setGenerating(false);
      setGeneratingCode(null);
    }
  }

  async function finalize() {
    setFinalizing(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/forms/finalize`, { method: "POST" });
      await load();
      onChanged?.();
    } catch (err) {
      setError(getFriendlyError("FormsPanel.finalize", err, "Failed to finalize"));
    } finally {
      setFinalizing(false);
    }
  }

  async function toggleVersions(code: string) {
    if (expandedCode === code) {
      setExpandedCode(null);
      return;
    }
    setExpandedCode(code);
    if (!versions[code]) {
      try {
        const data = await apiFetch<DocumentVersionOut[]>(
          `/api/patents/${patentId}/forms/${code}/versions`,
        );
        setVersions((v) => ({ ...v, [code]: data }));
      } catch (err) {
        setError(getFriendlyError("FormsPanel.versions", err, "Failed to load version history"));
      }
    }
  }

  async function download(code: string, version: number) {
    try {
      await apiDownload(
        `/api/patents/${patentId}/forms/${code}/download`,
        `${fileSlug()}-${code}-v${version}.docx`,
      );
    } catch (err) {
      setError(getFriendlyError("FormsPanel.download", err, "Download failed"));
    }
  }

  const allGenerated = (status?.forms ?? []).every((f) => f.generated);
  const anyMissing = (status?.forms ?? []).some((f) => f.missing_fields.length > 0);
  const canFinalize =
    status !== null &&
    allGenerated &&
    !anyMissing &&
    (status.usable_figure_count ?? 0) > 0 &&
    !status.finalized_at;

  if (status === null) {
    return error ? (
      <ErrorState message={error} onRetry={load} />
    ) : (
      <LoadingState compact label="Loading forms…" />
    );
  }

  return (
    <div className="mt-8">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">Statutory Forms</h3>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </div>
      )}
      {notices.length > 0 && (
        <div
          role="status"
          className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700"
        >
          {notices.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </div>
      )}

      {status.missing_sketch_warning && (
        <div
          role="alert"
          className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700"
        >
          No potential sketch or drawing was found. Upload a sketch or drawing before
          this patent can be finalized. Draft generation still works without one.
        </div>
      )}

      {status.finalized_at && (
        <p className="mb-4 rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          Finalized{status.finalized_at && ` · ${new Date(status.finalized_at).toLocaleString()}`}.
          {status.usable_figure_count} usable drawing{status.usable_figure_count === 1 ? "" : "s"} selected.
        </p>
      )}

      {!statusAllowsGeneration && (
        <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
          Form generation is available once the application is Under Review (current
          status: {applicationStatus}).
        </p>
      )}

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <button
          onClick={() => setShowCounts((v) => !v)}
          aria-expanded={showCounts}
          className="text-xs font-medium text-slate-700 hover:underline"
        >
          {showCounts ? "Hide" : "Set"} attachment counts (optional)
        </button>
        <p className="mt-1 text-xs text-slate-400">
          Page and claim counts for the Form 1 fee table — Word cannot paginate,
          so these are entered manually. Drawings are counted automatically
          ({status.usable_figure_count} selected).
        </p>
        {showCounts && (
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {COUNT_FIELDS.map(({ key, label, hint }) => (
              <label key={key} className="block text-xs text-slate-600">
                {label}
                <input
                  value={counts[key] ?? ""}
                  onChange={(e) =>
                    setCounts((c) => ({ ...c, [key]: e.target.value }))
                  }
                  placeholder={hint}
                  inputMode="numeric"
                  className="mt-0.5 w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
                />
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="mb-6 flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4">
        <div>
          <p className="text-sm font-medium text-slate-700">
            {allGenerated ? "Regenerate all forms" : "Generate statutory forms"}
          </p>
          <p className="text-xs text-slate-400">
            Renders FORM1, FORM2, FORM3, FORM5 and the Drawings sheet from the
            questionnaire. Each generation creates a new version — nothing is
            overwritten.
          </p>
        </div>
        {statusAllowsGeneration && (
          <button
            onClick={() => generate()}
            disabled={generating}
            className="whitespace-nowrap rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {generating ? "Generating…" : "Generate all forms"}
          </button>
        )}
      </div>

      <div className="mb-6 space-y-3">
        {status.forms.map((form) => (
          <FormCard
            key={form.form_code}
            form={form}
            usableFigures={status.usable_figure_count}
            canGenerate={statusAllowsGeneration}
            generating={generatingCode === form.form_code}
            expanded={expandedCode === form.form_code}
            versions={versions[form.form_code]}
            onGenerate={() => generate([form.form_code])}
            onToggleVersions={() => toggleVersions(form.form_code)}
            onDownload={() => download(form.form_code, form.latest_version ?? 1)}
          />
        ))}
      </div>

      <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4">
        <div>
          <p className="text-sm font-medium text-slate-700">Finalize</p>
          <p className="text-xs text-slate-400">
            Locks the generated set. Requires all five forms, complete fields, and
            at least one usable drawing ({status.usable_figure_count} selected).
          </p>
        </div>
        {statusAllowsGeneration && (
          <button
            onClick={finalize}
            disabled={!canFinalize || finalizing}
            title={
              status.finalized_at
                ? "Already finalized"
                : !allGenerated
                  ? "Generate all five forms first"
                  : anyMissing
                    ? "Complete the required questionnaire fields first"
                    : status.usable_figure_count === 0
                      ? "Select at least one usable drawing first"
                      : undefined
            }
            className="whitespace-nowrap rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {finalizing ? "Finalizing…" : status.finalized_at ? "Finalized" : "Finalize"}
          </button>
        )}
      </div>
    </div>
  );
}

function FormCard({
  form,
  usableFigures,
  canGenerate,
  generating,
  expanded,
  versions,
  onGenerate,
  onToggleVersions,
  onDownload,
}: {
  form: FormCardOut;
  usableFigures: number;
  canGenerate: boolean;
  generating: boolean;
  expanded: boolean;
  versions: DocumentVersionOut[] | undefined;
  onGenerate: () => void;
  onToggleVersions: () => void;
  onDownload: () => void;
}) {
  const badge = !form.generated ? (
    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
      Not generated
    </span>
  ) : form.job_status === "Failed" ? (
    <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
      Failed
    </span>
  ) : form.missing_fields.length > 0 ? (
    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
      Incomplete
    </span>
  ) : (
    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
      Generated
    </span>
  );

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-700">
            {form.label} <span className="ml-2">{badge}</span>
          </p>
          <p className="text-xs text-slate-400">
            {form.generated
              ? `v${form.latest_version}${form.generated_at ? ` · generated ${new Date(form.generated_at).toLocaleString()}` : ""}`
              : "Not generated yet."}
            {form.form_code === "DRAWINGS" && ` · ${usableFigures} usable drawing${usableFigures === 1 ? "" : "s"}`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {form.generated && (
            <>
              <button
                onClick={onDownload}
                className="text-xs font-medium text-blue-600 hover:underline"
              >
                Download latest
              </button>
              <button
                onClick={onToggleVersions}
                aria-expanded={expanded}
                className="text-xs text-slate-500 hover:underline"
              >
                {expanded ? "Hide" : "Show"} versions
              </button>
            </>
          )}
          {canGenerate && (
            <button
              onClick={onGenerate}
              disabled={generating}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {generating ? "Generating…" : form.generated ? "Regenerate" : "Generate"}
            </button>
          )}
        </div>
      </div>

      {form.job_error && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {form.job_error}
        </p>
      )}
      {form.missing_fields.length > 0 && (
        <p className="mt-2 text-xs text-amber-700">
          Missing: {form.missing_fields.join(", ")}
        </p>
      )}

      {expanded && versions && (
        <div className="mt-3 space-y-1 border-t border-slate-100 pt-3">
          {versions.map((v) => (
            <div key={v.id} className="flex items-center justify-between text-xs text-slate-500">
              <span>
                <span className="font-medium text-slate-700">v{v.version_number}</span>
                {v.generated_at && ` · ${new Date(v.generated_at).toLocaleString()}`}
                {v.figures_embedded.length > 0 && (
                  <span className="ml-2 text-slate-400">
                    — {v.figures_embedded.length} drawing{v.figures_embedded.length === 1 ? "" : "s"}
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
