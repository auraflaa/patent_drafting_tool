import { useEffect, useState } from "react";
import { apiDownload, apiFetch, ApiError } from "../lib/api";
import type {
  DocumentGenerationJobOut,
  DocumentOut,
  DocumentVersionOut,
} from "../lib/types";
import { LoadingState } from "./LoadingState";

interface Props {
  patentId: string;
  /** Mirrors the backend gate in can_generate_documents: status must be
   * "Under Review" or "Draft Generated", checked by the caller. */
  statusAllowsGeneration: boolean;
  applicationStatus: string;
  allSectionsCompleted: boolean;
}

export function DocumentGenerationPanel({
  patentId,
  statusAllowsGeneration,
  applicationStatus,
  allSectionsCompleted,
}: Props) {
  const [documents, setDocuments] = useState<DocumentOut[] | null>(null);
  const [jobs, setJobs] = useState<DocumentGenerationJobOut[] | null>(null);
  const [versions, setVersions] = useState<Record<string, DocumentVersionOut[]>>({});
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadDocuments() {
    try {
      setDocuments(await apiFetch<DocumentOut[]>(`/api/patents/${patentId}/documents`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
    }
  }

  async function loadJobs() {
    try {
      setJobs(await apiFetch<DocumentGenerationJobOut[]>(`/api/patents/${patentId}/documents/jobs`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load generation jobs");
    }
  }

  useEffect(() => {
    loadDocuments();
    loadJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  const canGenerate = statusAllowsGeneration && allSectionsCompleted;

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      const job = await apiFetch<DocumentGenerationJobOut>(
        `/api/patents/${patentId}/documents/generate`,
        { method: "POST", body: JSON.stringify({ output_format: "DOCX" }) }
      );
      if (job.status === "Failed") {
        setError(`Generation failed: ${job.error_message ?? "unknown error"}`);
      }
      await Promise.all([loadDocuments(), loadJobs()]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to generate document");
    } finally {
      setGenerating(false);
    }
  }

  async function retry(jobId: string) {
    setRetrying(jobId);
    setError(null);
    try {
      const job = await apiFetch<DocumentGenerationJobOut>(
        `/api/patents/${patentId}/documents/jobs/${jobId}/retry`,
        { method: "POST" }
      );
      if (job.status === "Failed") {
        setError(`Retry failed again: ${job.error_message ?? "unknown error"}`);
      }
      await Promise.all([loadDocuments(), loadJobs()]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to retry generation");
    } finally {
      setRetrying(null);
    }
  }

  async function toggleVersions(documentId: string) {
    if (expandedDocId === documentId) {
      setExpandedDocId(null);
      return;
    }
    setExpandedDocId(documentId);
    if (!versions[documentId]) {
      try {
        const data = await apiFetch<DocumentVersionOut[]>(
          `/api/patents/${patentId}/documents/${documentId}/versions`
        );
        setVersions((v) => ({ ...v, [documentId]: data }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load document version history");
      }
    }
  }

  async function download(documentId: string) {
    try {
      await apiDownload(
        `/api/patents/${patentId}/documents/${documentId}/download`,
        "document.docx"
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    }
  }

  async function downloadVersion(versionId: string, versionNumber: number) {
    try {
      await apiDownload(
        `/api/patents/${patentId}/documents/versions/${versionId}/download`,
        `document-v${versionNumber}.docx`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    }
  }

  return (
    <div className="mt-8">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">Documents</h3>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {(documents === null || jobs === null) && (
        <LoadingState compact label="Loading documents…" />
      )}

      {!statusAllowsGeneration && (
        <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
          Document generation is available once the application is Under Review (current
          status: {applicationStatus}).
        </p>
      )}
      {statusAllowsGeneration && !allSectionsCompleted && (
        <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
          Complete AI drafting for every section above before generating documents.
        </p>
      )}

      <div className="mb-6 flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4">
        <div>
          <p className="text-sm font-medium text-slate-700">
            {documents && documents.length > 0 ? "Regenerate application document" : "Generate application document"}
          </p>
          <p className="text-xs text-slate-400">
            Assembles the latest AI-drafted sections into a filed-style Word document. Each
            generation creates a new, downloadable version — nothing is overwritten.
          </p>
        </div>
        {canGenerate && (
          <button
            onClick={generate}
            disabled={generating}
            className="whitespace-nowrap rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {generating ? "Generating…" : "Generate DOCX"}
          </button>
        )}
      </div>

      {documents && documents.length > 0 && (
        <div className="mb-6 space-y-3">
          {documents.map((doc) => (
            <div key={doc.id} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-700">
                    Application Document
                    {doc.watermark_status && (
                      <span className="ml-2 rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-red-600">
                        {doc.watermark_status}
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-slate-400">
                    {doc.output_format}
                    {doc.generated_at && ` · generated ${new Date(doc.generated_at).toLocaleString()}`}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => download(doc.id)}
                    className="text-xs font-medium text-blue-600 hover:underline"
                  >
                    Download latest
                  </button>
                  <button
                    onClick={() => toggleVersions(doc.id)}
                    className="text-xs text-slate-500 hover:underline"
                  >
                    {expandedDocId === doc.id ? "Hide" : "Show"} versions
                  </button>
                </div>
              </div>

              {expandedDocId === doc.id && versions[doc.id] && (
                <div className="mt-3 space-y-1 border-t border-slate-100 pt-3">
                  {versions[doc.id].map((v) => (
                    <div key={v.id} className="flex items-center justify-between text-xs text-slate-500">
                      <span>
                        <span className="font-medium text-slate-700">v{v.version_number}</span>
                        {v.generated_at && ` · ${new Date(v.generated_at).toLocaleString()}`}
                        {v.change_summary && (
                          <span className="ml-2 text-slate-400">— {v.change_summary}</span>
                        )}
                      </span>
                      <button
                        onClick={() =>
                          downloadVersion(v.id, v.version_number)
                        }
                        className="text-blue-600 hover:underline"
                      >
                        Download
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {jobs && jobs.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="mb-2 text-xs font-semibold text-slate-500">Generation history</p>
          <div className="space-y-1.5">
            {jobs.map((job) => (
              <div key={job.id} className="flex items-center justify-between text-xs">
                <span
                  className={
                    job.status === "Completed"
                      ? "text-emerald-700"
                      : job.status === "Failed"
                        ? "text-red-600"
                        : "text-slate-500"
                  }
                >
                  Job #{job.id}
                  {job.retried_from_job_id && ` (retry of #${job.retried_from_job_id})`} —{" "}
                  {job.status}
                  {job.completed_at && ` · ${new Date(job.completed_at).toLocaleString()}`}
                </span>
                {job.status === "Failed" && (
                  <button
                    onClick={() => retry(job.id)}
                    disabled={retrying !== null}
                    className="rounded border border-slate-300 px-2 py-0.5 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {retrying === job.id ? "Retrying…" : "Retry"}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
