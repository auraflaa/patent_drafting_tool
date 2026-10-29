import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { apiDownload, apiFetch, apiUpload, getRuntimeCapabilities } from "../lib/api";
import { formatFileSize } from "../lib/format";
import type { RuntimeCapabilities } from "../lib/api";
import { LoadingState } from "./LoadingState";
import { EmptyState } from "./EmptyState";
import {
  CALENDAR_EVENT_TYPES,
  type CalendarEventCreate,
  type CalendarEventOut,
  type CommentOut,
  type FileOut,
} from "../lib/types";

type SubTab = "comments" | "files" | "calendar";

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** Comments, supporting Files, and Calendar Events for one patent
 * application — shown to anyone who can view the application.
 * `canManageCalendar` gates calendar create/delete (assigned Agent or
 * Admin only, mirroring the backend's own check). */
export function CollaborationPanel({
  patentId,
  canManageCalendar,
}: {
  patentId: string;
  canManageCalendar: boolean;
}) {
  const [subTab, setSubTab] = useState<SubTab>("comments");

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex gap-1 border-b border-slate-200 px-4 pt-2">
        {(
          [
            ["comments", "Comments"],
            ["files", "Files"],
            ["calendar", "Calendar"],
          ] as [SubTab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setSubTab(key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              subTab === key
                ? "border-slate-900 text-slate-900"
                : "border-transparent text-slate-400 hover:text-slate-600"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="p-4">
        {subTab === "comments" && <CommentsSection patentId={patentId} />}
        {subTab === "files" && <FilesSection patentId={patentId} />}
        {subTab === "calendar" && (
          <CalendarSection patentId={patentId} canManage={canManageCalendar} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Comments
// ---------------------------------------------------------------------------

function CommentsSection({ patentId }: { patentId: string }) {
  const { user } = useAuth();
  const [comments, setComments] = useState<CommentOut[] | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setComments(await apiFetch<CommentOut[]>(`/api/patents/${patentId}/comments`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load comments");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  async function post(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/comments`, {
        method: "POST",
        body: JSON.stringify({ comment_text: text }),
      });
      setText("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to post comment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      <div className="mb-4 max-h-80 space-y-3 overflow-y-auto">
        {comments === null && <LoadingState />}
        {comments?.length === 0 && (
          <EmptyState title="No comments yet." message="Start the discussion below." />
        )}
        {comments?.map((c) => (
          <div key={c.id} className="rounded-md bg-slate-50 px-3 py-2">
            <div className="mb-0.5 flex items-baseline justify-between gap-2">
              <span className="text-xs font-semibold text-slate-700">
                {c.user_full_name ?? `User #${c.user_id}`}
                {c.user_id === user?.id && (
                  <span className="ml-1 font-normal text-slate-400">(you)</span>
                )}
              </span>
              <span className="text-[11px] text-slate-400">{formatDateTime(c.created_at)}</span>
            </div>
            <p className="whitespace-pre-wrap text-sm text-slate-700">{c.comment_text}</p>
          </div>
        ))}
      </div>

      <form onSubmit={post} className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add a comment…"
          maxLength={5000}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={busy || !text.trim()}
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          Post
        </button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------

function FilesSection({ patentId }: { patentId: string }) {
  const { user, hasRole, hasPermission } = useAuth();
  const isAdmin = hasRole("ADMIN") || hasRole("SUPER_ADMIN");
  // Mirrors the backend rule: uploaders may remove their own file, while the
  // catalogued FILES_DELETE grant is what allows deleting someone else's.
  const canDeleteAny = isAdmin || hasPermission("FILES_DELETE");
  const [files, setFiles] = useState<FileOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [capabilities, setCapabilities] = useState<RuntimeCapabilities | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getRuntimeCapabilities()
      .then(setCapabilities)
      .catch(() => setCapabilities(null));
  }, []);

  async function load() {
    try {
      setFiles(await apiFetch<FileOut[]>(`/api/patents/${patentId}/files`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load files");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  async function onFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await apiUpload(`/api/patents/${patentId}/files`, file);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload file");
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function download(f: FileOut) {
    try {
      await apiDownload(
        `/api/patents/${patentId}/files/${f.id}/download`,
        f.original_file_name ?? `file-${f.id}`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download file");
    }
  }

  async function remove(f: FileOut) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/files/${f.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete file");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      <div className="mb-4 space-y-2">
        {files === null && <LoadingState />}
        {files?.length === 0 && (
          <EmptyState title="No files uploaded yet." />
        )}
        {files?.map((f) => (
          <div
            key={f.id}
            className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2"
          >
            <div>
              <p className="text-sm font-medium text-slate-800">{f.original_file_name}</p>
              <p className="text-xs text-slate-400">
                {formatFileSize(f.file_size_bytes)} · {f.uploaded_by_name ?? "Unknown"} ·{" "}
                {formatDateTime(f.created_at)}
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => download(f)}
                className="rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                Download
              </button>
              {(canDeleteAny || f.uploaded_by === user?.id) && (
                <button
                  onClick={() => remove(f)}
                  disabled={busy}
                  className="rounded-md border border-red-200 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                >
                  Delete
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div>
        <input
          ref={fileInputRef}
          type="file"
          onChange={onFileChosen}
          disabled={busy}
          className="text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white hover:file:bg-slate-700"
        />
        <p className="mt-1 text-xs text-slate-400">
          {capabilities
            ? `Up to ${formatFileSize(capabilities.max_upload_size_bytes)} per upload, stored compressed in Firestore (about ${formatFileSize(capabilities.max_stored_size_bytes)} after compression).`
            : "Files are stored compressed in Firestore."}{" "}
          Executable files aren't allowed.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Calendar events
// ---------------------------------------------------------------------------

const EMPTY_EVENT: CalendarEventCreate = {
  event_type: CALENDAR_EVENT_TYPES[0],
  event_date: "",
};

function CalendarSection({ patentId, canManage }: { patentId: string; canManage: boolean }) {
  const [events, setEvents] = useState<CalendarEventOut[] | null>(null);
  const [form, setForm] = useState<CalendarEventCreate>(EMPTY_EVENT);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setEvents(await apiFetch<CalendarEventOut[]>(`/api/patents/${patentId}/calendar-events`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load calendar events");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!form.event_date) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/calendar-events`, {
        method: "POST",
        body: JSON.stringify({
          event_type: form.event_type,
          event_date: new Date(form.event_date).toISOString(),
        }),
      });
      setForm(EMPTY_EVENT);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create event");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/calendar-events/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete event");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      <div className="mb-4 space-y-2">
        {events === null && <LoadingState />}
        {events?.length === 0 && (
          <EmptyState title="No calendar events yet." />
        )}
        {events?.map((ev) => (
          <div
            key={ev.id}
            className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2"
          >
            <div>
              <p className="text-sm font-medium text-slate-800">{ev.event_type}</p>
              <p className="text-xs text-slate-400">{formatDateTime(ev.event_date)}</p>
            </div>
            {canManage && (
              <button
                onClick={() => remove(ev.id)}
                disabled={busy}
                className="rounded-md border border-red-200 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                Delete
              </button>
            )}
          </div>
        ))}
      </div>

      {canManage ? (
        <form onSubmit={create} className="flex flex-wrap items-end gap-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Event type</label>
            <select
              value={form.event_type}
              onChange={(e) =>
                setForm({ ...form, event_type: e.target.value as CalendarEventCreate["event_type"] })
              }
              className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            >
              {CALENDAR_EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Date &amp; time</label>
            <input
              type="datetime-local"
              value={form.event_date}
              onChange={(e) => setForm({ ...form, event_date: e.target.value })}
              className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={busy || !form.event_date}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            Add event
          </button>
        </form>
      ) : (
        <p className="text-xs text-slate-400">
          Only the assigned Patent Agent or an Admin can add calendar events.
        </p>
      )}
    </div>
  );
}
