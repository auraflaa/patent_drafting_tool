import { useEffect, useRef, useState } from "react";
import { apiFetch, apiImageUrl, getFriendlyError } from "../lib/api";
import type { FigureOut, FileOut } from "../lib/types";

/** Per-file figure review: thumbnails, usable/rejected status, caption edit,
 * include toggle, and "use anyway" for rejected candidates. Only usable and
 * included figures reach the drawings sheet. */
export function FiguresStrip({ patentId, file }: { patentId: string; file: FileOut }) {
  const [open, setOpen] = useState(false);
  const [figures, setFigures] = useState<FigureOut[] | null>(null);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [captions, setCaptions] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Object URLs live in a ref so the unmount cleanup revokes the *current*
  // set: a bare [] effect would close over the initial (empty) map and leak
  // every thumbnail. The state copy below is only what React renders.
  const urlsRef = useRef<Record<string, string>>({});
  useEffect(() => {
    const urls = urlsRef.current;
    return () => {
      for (const url of Object.values(urls)) URL.revokeObjectURL(url);
    };
  }, []);

  async function load() {
    try {
      const data = await apiFetch<FigureOut[]>(
        `/api/patents/${patentId}/files/${file.id}/figures`,
      );
      setFigures(data);
      const next: Record<string, string> = {};
      for (const fig of data) {
        if (fig.has_image) {
          try {
            next[fig.id] = await apiImageUrl(
              `/api/patents/${patentId}/files/${file.id}/figures/${fig.id}/image`,
            );
          } catch {
            // a missing crop hides the thumbnail, not the row
          }
        }
      }
      setUrls((prev) => {
        for (const url of Object.values(prev)) URL.revokeObjectURL(url);
        urlsRef.current = next;
        return next;
      });
    } catch (err) {
      setError(getFriendlyError("FiguresStrip.load", err, "Failed to load figures"));
    }
  }

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && figures === null) await load();
  }

  async function patch(id: string, body: Record<string, unknown>) {
    setBusy(id);
    setError(null);
    try {
      const updated = await apiFetch<FigureOut>(
        `/api/patents/${patentId}/files/${file.id}/figures/${id}`,
        { method: "PATCH", body: JSON.stringify(body) },
      );
      setFigures((prev) => prev?.map((f) => (f.id === id ? updated : f)) ?? null);
    } catch (err) {
      setError(getFriendlyError("FiguresStrip.patch", err, "Failed to update figure"));
    } finally {
      setBusy(null);
    }
  }

  if (file.extraction_figure_count === 0) return null;

  const usable = figures?.filter((f) => f.usable === "usable" && f.include_in_drawings).length ?? null;

  return (
    <div className="mt-2">
      <button
        onClick={toggle}
        aria-expanded={open}
        className="text-xs font-medium text-blue-600 hover:underline"
      >
        {open ? "Hide" : "Show"} figures ({file.extraction_figure_count}
        {usable !== null && ` · ${usable} selected`})
      </button>
      {error && <p role="alert" className="mt-1 text-xs text-red-600">{error}</p>}
      {open && figures === null && <p className="mt-1 text-xs text-slate-400">Loading…</p>}
      {open && figures !== null && (
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {figures.map((fig) => (
            <div key={fig.id} className="rounded-md border border-slate-200 p-2">
              {urls[fig.id] ? (
                <img
                  src={urls[fig.id]}
                  alt={fig.caption || fig.label || "Extracted figure"}
                  className="mb-1 max-h-40 w-full rounded object-contain bg-slate-50"
                  loading="lazy"
                />
              ) : (
                <p className="mb-1 text-xs text-slate-400">
                  {fig.has_image ? "Preview unavailable." : "Table — no image."}
                </p>
              )}
              <p className="text-xs font-medium text-slate-700">
                {fig.label || `Figure · p.${fig.page || "—"}`}
              </p>
              <p className="text-xs text-slate-500">
                {fig.caption || "No caption."}{" "}
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                    fig.usable === "usable"
                      ? "bg-emerald-100 text-emerald-700"
                      : fig.usable === "rejected"
                        ? "bg-red-100 text-red-700"
                        : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {fig.usable === "usable" ? "Usable" : fig.usable === "rejected" ? "Rejected" : "Unreviewed"}
                </span>
              </p>
              {fig.reason && <p className="text-[11px] text-slate-400">{fig.reason}</p>}
              {fig.vision_description && (
                <p className="text-[11px] text-slate-500">
                  <span className="font-medium">Vision:</span> {fig.vision_caption && `${fig.vision_caption} — `}{fig.vision_description}
                </p>
              )}
              <div className="mt-1 flex items-center gap-2">
                <input
                  aria-label={`Caption for ${fig.label || "figure"}`}
                  placeholder="Caption override"
                  defaultValue={fig.caption}
                  key={`${fig.id}-${fig.caption}`}
                  onChange={(e) =>
                    setCaptions((c) => ({ ...c, [fig.id]: e.target.value }))
                  }
                  className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs"
                />
                <button
                  disabled={busy === fig.id}
                  onClick={() => patch(fig.id, { caption: captions[fig.id] ?? fig.caption })}
                  className="shrink-0 rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  Save
                </button>
              </div>
              <div className="mt-1 flex items-center gap-3 text-xs">
                <label className="flex items-center gap-1 text-slate-600">
                  <input
                    type="checkbox"
                    checked={fig.include_in_drawings}
                    disabled={busy === fig.id}
                    onChange={() => patch(fig.id, { include_in_drawings: !fig.include_in_drawings })}
                  />
                  Include
                </label>
                {fig.usable === "rejected" && (
                  <button
                    disabled={busy === fig.id}
                    onClick={() => patch(fig.id, { usable: "usable" })}
                    title="Approve this candidate for the drawings sheet anyway"
                    className="text-blue-600 hover:underline disabled:opacity-50"
                  >
                    Use anyway
                  </button>
                )}
                {fig.usable === "usable" && fig.reason === "approved by user" && (
                  <button
                    disabled={busy === fig.id}
                    onClick={() => patch(fig.id, { usable: "rejected" })}
                    className="text-slate-500 hover:underline disabled:opacity-50"
                  >
                    Reject
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
