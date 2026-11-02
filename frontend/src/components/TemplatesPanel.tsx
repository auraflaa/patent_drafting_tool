// Templates admin panel (NEW — closes open item #24 from the handover:
// there was previously no Templates UI and no real merging). Lets
// Admin/Super Admin upload a .docx per document_type, see the full
// version history, activate an older version, or delete a non-active one.
//
// The uploaded .docx is the source of truth for layout/letterhead — this
// UI only manages which file is active per document_type; the actual
// Jinja-in-DOCX merge happens server-side in backend/app/services/documents.py
// via docxtpl. Placeholders the template author can use:
// {{ TITLE }} {{ WATERMARK_TEXT }} {{ ABSTRACT }} {{ BACKGROUND }}
// {{ SUMMARY }} {{ DESCRIPTION }} {{ CLAIMS }}

import { useEffect, useRef, useState } from "react";
import { apiFetch, apiUpload } from "../lib/api";
import { LoadingState } from "./LoadingState";
import { ErrorState } from "./ErrorState";
import type { TemplateOut } from "../lib/types";

export function TemplatesPanel() {
  const [documentTypes, setDocumentTypes] = useState<string[] | null>(null);
  const [selectedType, setSelectedType] = useState<string>("");
  const [templates, setTemplates] = useState<TemplateOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [uploadWarning, setUploadWarning] = useState<TemplateOut | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function loadDocumentTypes() {
    try {
      const types = await apiFetch<string[]>("/api/templates/document-types");
      setDocumentTypes(types);
      if (types.length > 0) setSelectedType((prev) => prev || types[0]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load document types");
    }
  }

  async function loadTemplates(documentType: string) {
    if (!documentType) return;
    try {
      const data = await apiFetch<TemplateOut[]>(
        `/api/templates?document_type=${encodeURIComponent(documentType)}`,
      );
      setTemplates(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load templates");
    }
  }

  useEffect(() => {
    loadDocumentTypes();
  }, []);

  useEffect(() => {
    if (selectedType) loadTemplates(selectedType);
    setUploadWarning(null);
  }, [selectedType]);

  async function handleUpload(file: File) {
    if (!selectedType) return;
    const name = file.name.toLowerCase();
    const isWord = name.endsWith(".docx");
    const isPdf = name.endsWith(".pdf");
    if (!isWord && !isPdf) {
      setError(
        name.endsWith(".doc")
          ? "Legacy .doc templates cannot be read. Save the file as .docx or PDF."
          : "Templates must be a .docx or .pdf file.",
      );
      return;
    }
    setUploading(true);
    setError(null);
    setUploadWarning(null);
    try {
      const uploaded = await apiUpload<TemplateOut>("/api/templates", file, "upload", {
        document_type: selectedType,
        activate: true,
      });
      // Closes open item #31 — surface placeholder validation results
      // right away, since a typo'd/unsupported placeholder or a template
      // docxtpl can't parse would otherwise only be discovered the hard
      // way, silently, at generation time.
      if (
        uploaded.template_parse_error ||
        (uploaded.unknown_placeholders && uploaded.unknown_placeholders.length > 0)
      ) {
        setUploadWarning(uploaded);
      }
      await loadTemplates(selectedType);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function activate(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await apiFetch(`/api/templates/${id}/activate`, { method: "POST" });
      await loadTemplates(selectedType);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Activate failed");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await apiFetch(`/api/templates/${id}`, { method: "DELETE" });
      await loadTemplates(selectedType);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusyId(null);
    }
  }

  if (documentTypes === null)
    return error ? (
      <ErrorState message={error} onRetry={loadDocumentTypes} />
    ) : (
      <LoadingState />
    );

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-red-600">{error}</p>}

      {uploadWarning && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
          <div className="mb-1 flex items-center justify-between">
            <p className="font-medium">
              Uploaded "{uploadWarning.original_file_name}" — but it's worth a second look:
            </p>
            <button
              onClick={() => setUploadWarning(null)}
              className="text-amber-600 hover:underline"
            >
              Dismiss
            </button>
          </div>
          {uploadWarning.template_parse_error && (
            <p className="mb-1">⚠️ {uploadWarning.template_parse_error}</p>
          )}
          {uploadWarning.unknown_placeholders && uploadWarning.unknown_placeholders.length > 0 && (
            <p className="mb-1">
              ⚠️ Found placeholder{uploadWarning.unknown_placeholders.length > 1 ? "s" : ""} this
              app doesn't recognize:{" "}
              <code>
                {uploadWarning.unknown_placeholders.map((p) => `{{ ${p} }}`).join(", ")}
              </code>
              . They'll render blank rather than being filled in — check for typos against the
              supported placeholder list below.
            </p>
          )}
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
          Document type
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            {documentTypes.map((dt) => (
              <option key={dt} value={dt}>
                {dt}
              </option>
            ))}
          </select>

          <label className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 cursor-pointer">
            {uploading ? "Uploading…" : "Upload new version (.docx or .pdf)"}
            <input
              ref={fileInputRef}
              type="file"
              accept=".docx,.pdf"
              disabled={uploading}
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload(file);
              }}
            />
          </label>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          PDF templates are converted to Word on upload. Uploading activates the new
          version immediately. Placeholders the .docx can use:{" "}
          <code>{"{{ TITLE }} {{ WATERMARK_TEXT }} {{ ABSTRACT }} {{ BACKGROUND }} {{ SUMMARY }} {{ DESCRIPTION }} {{ CLAIMS }}"}</code>
        </p>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-left">
              <th className="px-3 py-2 font-medium text-slate-600">Version</th>
              <th className="px-3 py-2 font-medium text-slate-600">File</th>
              <th className="px-3 py-2 font-medium text-slate-600">Status</th>
              <th className="px-3 py-2 font-medium text-slate-600">Uploaded by</th>
              <th className="px-3 py-2 font-medium text-slate-600">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(templates ?? []).map((t) => (
              <tr key={t.id} className="border-b border-slate-100">
                <td className="px-3 py-2 font-medium text-slate-900">v{t.version_number}</td>
                <td className="px-3 py-2 text-slate-700">{t.original_file_name ?? "—"}</td>
                <td className="px-3 py-2">
                  {t.is_active ? (
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                      Active
                    </span>
                  ) : (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                      Inactive
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-slate-600">{t.edited_by_name ?? "—"}</td>
                <td className="px-3 py-2">
                  <div className="flex gap-2">
                    {!t.is_active && (
                      <button
                        disabled={busyId === t.id}
                        onClick={() => activate(t.id)}
                        className="rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      >
                        Activate
                      </button>
                    )}
                    <button
                      disabled={busyId === t.id}
                      onClick={() => remove(t.id)}
                      className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                      title={t.is_active ? "Deleting the active version falls back to the plain layout" : undefined}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {templates !== null && templates.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-slate-400">
                  No templates uploaded yet for this document type — document generation will
                  use the bundled Form 1 layout.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
