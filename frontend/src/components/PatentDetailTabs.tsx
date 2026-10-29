// Shared, reusable Basic Information + Questionnaire tabs, extracted from
// PatentWorkflowPage.tsx (the Innovator's editable workflow view) so the
// exact same, already-correct components can be reused read-only for
// Agent (DraftWorkspacePage) and Admin (AdminPatentDetailPage) — closes
// open item #13. Every field/panel below was already gated on an
// `editable` prop before this extraction, so passing `editable={false}`
// is all a read-only caller needs to do; no new read-only-specific code
// was written.
import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../lib/api";
import { LoadingState } from "./LoadingState";
import { EmptyState } from "./EmptyState";
import {
  APPLICANT_TYPES,
  INVENTION_TYPES,
  TECHNICAL_DETAILS_GUIDANCE,
  type ApplicantInput,
  type ApplicantOut,
  type ApplicantType,
  type InventionType,
  type InventorInput,
  type InventorOut,
  type QuestionnaireOut,
  type QuestionnaireUpdateInput,
  type QuestionnaireVersionOut,
} from "../lib/types";

const EMPTY_APPLICANT: ApplicantInput = {
  applicant_type: "Individual",
  full_name_or_org_name: "",
  address: "",
  country: "",
  postal_code: "",
  email: "",
  phone: "",
  is_primary: false,
};

const EMPTY_INVENTOR: InventorInput = {
  full_name: "",
  address: "",
  country: "",
  postal_code: "",
  email: "",
  phone: "",
};

/** Turns "" back into null so we don't send empty strings for optional
 * nullable fields the backend expects to be either populated or absent. */
function blankToNull<T extends object>(input: T): T {
  const out: Record<string, unknown> = {
    ...(input as Record<string, unknown>),
  };
  for (const key of Object.keys(out)) {
    if (out[key] === "") out[key] = null;
  }
  return out as T;
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Basic Information: Applicants & Inventors
// ---------------------------------------------------------------------------

export function BasicInfoTab({
  patentId,
  editable,
}: {
  patentId: string;
  editable: boolean;
}) {
  return (
    <div className="space-y-6">
      <ApplicantsPanel patentId={patentId} editable={editable} />
      <InventorsPanel patentId={patentId} editable={editable} />
    </div>
  );
}

function ApplicantsPanel({
  patentId,
  editable,
}: {
  patentId: string;
  editable: boolean;
}) {
  const [applicants, setApplicants] = useState<ApplicantOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<ApplicantInput>(EMPTY_APPLICANT);
  const [editingId, setEditingId] = useState<string | null>(null);

  async function load() {
    try {
      const data = await apiFetch<ApplicantOut[]>(
        `/api/patents/${patentId}/applicants`,
      );
      setApplicants(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load applicants",
      );
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  function startEdit(a: ApplicantOut) {
    setEditingId(a.id);
    setForm({
      applicant_type: a.applicant_type as ApplicantType,
      full_name_or_org_name: a.full_name_or_org_name,
      address: a.address ?? "",
      country: a.country ?? "",
      postal_code: a.postal_code ?? "",
      email: a.email ?? "",
      phone: a.phone ?? "",
      is_primary: a.is_primary,
    });
  }

  function resetForm() {
    setEditingId(null);
    setForm(EMPTY_APPLICANT);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form.full_name_or_org_name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const body = JSON.stringify(blankToNull(form));
      if (editingId) {
        await apiFetch(`/api/patents/${patentId}/applicants/${editingId}`, {
          method: "PATCH",
          body,
        });
      } else {
        await apiFetch(`/api/patents/${patentId}/applicants`, {
          method: "POST",
          body,
        });
      }
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save applicant");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/applicants/${id}`, {
        method: "DELETE",
      });
      if (editingId === id) resetForm();
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to remove applicant",
      );
    } finally {
      setBusy(false);
    }
  }

  async function move(index: number, direction: -1 | 1) {
    if (!applicants) return;
    const target = index + direction;
    if (target < 0 || target >= applicants.length) return;
    const reordered = [...applicants];
    [reordered[index], reordered[target]] = [
      reordered[target],
      reordered[index],
    ];
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<ApplicantOut[]>(
        `/api/patents/${patentId}/applicants/reorder`,
        {
          method: "POST",
          body: JSON.stringify({ ordered_ids: reordered.map((a) => a.id) }),
        },
      );
      setApplicants(result);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reorder applicants",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">
        Applicants{" "}
        <span className="font-normal text-slate-400">
          — exactly one must be primary
        </span>
      </h3>
      {error && <p className="mb-2 text-xs text-red-600">{error}</p>}

      {applicants === null && <LoadingState compact />}
      {applicants?.length === 0 && (
        <EmptyState title="No applicants yet." />
      )}

      <div className="space-y-2">
        {applicants?.map((a, i) => (
          <div
            key={a.id}
            className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2 text-sm"
          >
            <div>
              <span className="font-medium text-slate-900">
                {a.full_name_or_org_name}
              </span>{" "}
              <span className="text-xs text-slate-400">
                ({a.applicant_type}
                {a.country ? `, ${a.country}` : ""})
              </span>
              {a.is_primary && (
                <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                  Primary
                </span>
              )}
            </div>
            {editable && (
              <div className="flex items-center gap-2 text-xs">
                <button
                  onClick={() => move(i, -1)}
                  disabled={busy || i === 0}
                  className="text-slate-400 hover:text-slate-700 disabled:opacity-30"
                  title="Move up"
                >
                  ↑
                </button>
                <button
                  onClick={() => move(i, 1)}
                  disabled={busy || i === (applicants?.length ?? 1) - 1}
                  className="text-slate-400 hover:text-slate-700 disabled:opacity-30"
                  title="Move down"
                >
                  ↓
                </button>
                <button
                  onClick={() => startEdit(a)}
                  className="text-blue-600 hover:underline"
                >
                  Edit
                </button>
                <button
                  onClick={() => remove(a.id)}
                  disabled={busy}
                  className="text-red-600 hover:underline disabled:opacity-50"
                >
                  Remove
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {editable && (
        <form
          onSubmit={save}
          className="mt-4 grid grid-cols-2 gap-2 rounded-md bg-slate-50 p-3"
        >
          <select
            value={form.applicant_type}
            onChange={(e) =>
              setForm({
                ...form,
                applicant_type: e.target.value as ApplicantType,
              })
            }
            className="col-span-2 rounded-md border border-slate-300 px-2 py-1.5 text-sm sm:col-span-1"
          >
            {APPLICANT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Full name / organization name"
            value={form.full_name_or_org_name}
            onChange={(e) =>
              setForm({ ...form, full_name_or_org_name: e.target.value })
            }
            className="col-span-2 rounded-md border border-slate-300 px-2 py-1.5 text-sm sm:col-span-1"
          />
          <input
            type="text"
            placeholder="Address"
            value={form.address}
            onChange={(e) => setForm({ ...form, address: e.target.value })}
            className="col-span-2 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="text"
            placeholder="Country"
            value={form.country}
            onChange={(e) => setForm({ ...form, country: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="text"
            placeholder="Postal code"
            value={form.postal_code}
            onChange={(e) => setForm({ ...form, postal_code: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="email"
            placeholder="Email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="text"
            placeholder="Phone"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <label className="col-span-2 flex items-center gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={form.is_primary}
              onChange={(e) =>
                setForm({ ...form, is_primary: e.target.checked })
              }
            />
            Mark as primary applicant
          </label>
          <div className="col-span-2 flex gap-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {editingId ? "Save changes" : "Add applicant"}
            </button>
            {editingId && (
              <button
                type="button"
                onClick={resetForm}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

function InventorsPanel({
  patentId,
  editable,
}: {
  patentId: string;
  editable: boolean;
}) {
  const [inventors, setInventors] = useState<InventorOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<InventorInput>(EMPTY_INVENTOR);
  const [editingId, setEditingId] = useState<string | null>(null);

  async function load() {
    try {
      const data = await apiFetch<InventorOut[]>(
        `/api/patents/${patentId}/inventors`,
      );
      setInventors(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load inventors");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  function startEdit(inv: InventorOut) {
    setEditingId(inv.id);
    setForm({
      full_name: inv.full_name,
      address: inv.address ?? "",
      country: inv.country ?? "",
      postal_code: inv.postal_code ?? "",
      email: inv.email ?? "",
      phone: inv.phone ?? "",
    });
  }

  function resetForm() {
    setEditingId(null);
    setForm(EMPTY_INVENTOR);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form.full_name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const body = JSON.stringify(blankToNull(form));
      if (editingId) {
        await apiFetch(`/api/patents/${patentId}/inventors/${editingId}`, {
          method: "PATCH",
          body,
        });
      } else {
        await apiFetch(`/api/patents/${patentId}/inventors`, {
          method: "POST",
          body,
        });
      }
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save inventor");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patentId}/inventors/${id}`, {
        method: "DELETE",
      });
      if (editingId === id) resetForm();
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to remove inventor",
      );
    } finally {
      setBusy(false);
    }
  }

  async function move(index: number, direction: -1 | 1) {
    if (!inventors) return;
    const target = index + direction;
    if (target < 0 || target >= inventors.length) return;
    const reordered = [...inventors];
    [reordered[index], reordered[target]] = [
      reordered[target],
      reordered[index],
    ];
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<InventorOut[]>(
        `/api/patents/${patentId}/inventors/reorder`,
        {
          method: "POST",
          body: JSON.stringify({ ordered_ids: reordered.map((v) => v.id) }),
        },
      );
      setInventors(result);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reorder inventors",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">Inventors</h3>
      {error && <p className="mb-2 text-xs text-red-600">{error}</p>}

      {inventors === null && <LoadingState compact />}
      {inventors?.length === 0 && (
        <EmptyState title="No inventors yet." />
      )}

      <div className="space-y-2">
        {inventors?.map((inv, i) => (
          <div
            key={inv.id}
            className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2 text-sm"
          >
            <div>
              <span className="font-medium text-slate-900">
                {inv.full_name}
              </span>{" "}
              {inv.country && (
                <span className="text-xs text-slate-400">({inv.country})</span>
              )}
            </div>
            {editable && (
              <div className="flex items-center gap-2 text-xs">
                <button
                  onClick={() => move(i, -1)}
                  disabled={busy || i === 0}
                  className="text-slate-400 hover:text-slate-700 disabled:opacity-30"
                  title="Move up"
                >
                  ↑
                </button>
                <button
                  onClick={() => move(i, 1)}
                  disabled={busy || i === (inventors?.length ?? 1) - 1}
                  className="text-slate-400 hover:text-slate-700 disabled:opacity-30"
                  title="Move down"
                >
                  ↓
                </button>
                <button
                  onClick={() => startEdit(inv)}
                  className="text-blue-600 hover:underline"
                >
                  Edit
                </button>
                <button
                  onClick={() => remove(inv.id)}
                  disabled={busy}
                  className="text-red-600 hover:underline disabled:opacity-50"
                >
                  Remove
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {editable && (
        <form
          onSubmit={save}
          className="mt-4 grid grid-cols-2 gap-2 rounded-md bg-slate-50 p-3"
        >
          <input
            type="text"
            placeholder="Full name"
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            className="col-span-2 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="text"
            placeholder="Address"
            value={form.address}
            onChange={(e) => setForm({ ...form, address: e.target.value })}
            className="col-span-2 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="text"
            placeholder="Country"
            value={form.country}
            onChange={(e) => setForm({ ...form, country: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="text"
            placeholder="Postal code"
            value={form.postal_code}
            onChange={(e) => setForm({ ...form, postal_code: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="email"
            placeholder="Email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="text"
            placeholder="Phone"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <div className="col-span-2 flex gap-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {editingId ? "Save changes" : "Add inventor"}
            </button>
            {editingId && (
              <button
                type="button"
                onClick={resetForm}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Questionnaire
// ---------------------------------------------------------------------------

/** Every field the PATCH endpoint accepts; submit persists them all first. */
const QUESTIONNAIRE_FIELDS: (keyof QuestionnaireUpdateInput)[] = [
  "invention_type",
  "problem_statement",
  "proposed_solution",
  "novelty_description",
  "technical_description",
  "advantages",
  "prior_art",
  "keywords",
  "has_existing_drawings",
];

export function QuestionnaireTab({
  patentId,
  editable,
}: {
  patentId: string;
  editable: boolean;
}) {
  const [q, setQ] = useState<QuestionnaireOut | null>(null);
  const [versions, setVersions] = useState<QuestionnaireVersionOut[] | null>(
    null,
  );
  const [showVersions, setShowVersions] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [busySection, setBusySection] = useState<string | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);

  // Local editable draft, seeded from the loaded questionnaire.
  const [draft, setDraft] = useState<QuestionnaireUpdateInput>({});

  async function load() {
    try {
      const data = await apiFetch<QuestionnaireOut>(
        `/api/patents/${patentId}/questionnaire`,
      );
      setQ(data);
      setDraft({
        invention_type: data.invention_type,
        problem_statement: data.problem_statement,
        proposed_solution: data.proposed_solution,
        novelty_description: data.novelty_description,
        technical_description: data.technical_description,
        advantages: data.advantages,
        prior_art: data.prior_art,
        keywords: data.keywords,
        has_existing_drawings: data.has_existing_drawings,
      });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load questionnaire",
      );
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patentId]);

  async function loadVersions() {
    try {
      const data = await apiFetch<QuestionnaireVersionOut[]>(
        `/api/patents/${patentId}/questionnaire/versions`,
      );
      setVersions(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load version history",
      );
    }
  }

  async function saveSection(
    sectionKey: string,
    fields: (keyof QuestionnaireUpdateInput)[],
  ) {
    setBusySection(sectionKey);
    setSaveMsg(null);
    setError(null);
    try {
      const payload: QuestionnaireUpdateInput = {};
      for (const f of fields)
        (payload as Record<string, unknown>)[f] = draft[f] ?? null;
      const updated = await apiFetch<QuestionnaireOut>(
        `/api/patents/${patentId}/questionnaire`,
        {
          method: "PATCH",
          body: JSON.stringify(payload),
        },
      );
      setQ(updated);
      setSaveMsg("Saved");
      setTimeout(() => setSaveMsg(null), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setBusySection(null);
    }
  }

  async function submitQuestionnaire() {
    setSubmitBusy(true);
    setError(null);
    try {
      // Persist unsaved edits first: the backend validates the stored copy, so
      // a field typed but never saved would be reported as missing.
      const payload: QuestionnaireUpdateInput = {};
      for (const f of QUESTIONNAIRE_FIELDS)
        (payload as Record<string, unknown>)[f] = draft[f] ?? null;
      await apiFetch<QuestionnaireOut>(
        `/api/patents/${patentId}/questionnaire`,
        {
          method: "PATCH",
          body: JSON.stringify(payload),
        },
      );
      const updated = await apiFetch<QuestionnaireOut>(
        `/api/patents/${patentId}/questionnaire/submit`,
        { method: "POST" },
      );
      setQ(updated);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to submit questionnaire",
      );
    } finally {
      setSubmitBusy(false);
    }
  }

  const inventionType = draft.invention_type as
    InventionType | null | undefined;
  const techGuidance = inventionType
    ? TECHNICAL_DETAILS_GUIDANCE[inventionType]
    : null;

  const percent = useMemo(() => {
    if (!q?.completion_percentage) return 0;
    return Math.round(Number(q.completion_percentage));
  }, [q]);

  if (!q) {
    return error ? (
      <p className="text-sm text-red-600">{error}</p>
    ) : (
      <LoadingState />
    );
  }

  const isCompleted = q.questionnaire_status === "Completed";

  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-700">
            Progress{" "}
            <span className="font-normal text-slate-400">
              ({q.questionnaire_status})
            </span>
          </h3>
          <span className="text-xs text-slate-400">{percent}% complete</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-slate-900 transition-all"
            style={{ width: `${percent}%` }}
          />
        </div>
        {isCompleted && editable && (
          <p className="mt-2 text-xs text-amber-600">
            Editing any field below will reopen this questionnaire to "In
            Progress".
          </p>
        )}
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-700">
          Invention Type
        </h3>
        <select
          value={draft.invention_type ?? ""}
          disabled={!editable}
          onChange={(e) =>
            setDraft({
              ...draft,
              invention_type: (e.target.value || null) as InventionType | null,
            })
          }
          className="w-full max-w-xs rounded-md border border-slate-300 px-2.5 py-1.5 text-sm disabled:bg-slate-50"
        >
          <option value="">Select a type…</option>
          {INVENTION_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <p className="mt-2 text-xs text-slate-400">
          Choosing a type tailors the Technical Details guidance below.
        </p>
        {editable && (
          <button
            onClick={() => saveSection("invention_type", ["invention_type"])}
            disabled={busySection === "invention_type"}
            className="mt-3 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            Save
          </button>
        )}
      </section>

      <QSection
        title="About the Invention"
        editable={editable}
        busy={busySection === "about"}
        onSave={() =>
          saveSection("about", [
            "problem_statement",
            "proposed_solution",
            "novelty_description",
          ])
        }
      >
        <QField
          label="Problem Statement"
          value={draft.problem_statement}
          editable={editable}
          onChange={(v) => setDraft({ ...draft, problem_statement: v })}
          placeholder="What problem does this invention solve? Who experiences it and why does it matter?"
        />
        <QField
          label="Proposed Solution"
          value={draft.proposed_solution}
          editable={editable}
          onChange={(v) => setDraft({ ...draft, proposed_solution: v })}
          placeholder="Summarize, at a high level, how your invention solves the problem above."
        />
        <QField
          label="Novelty Description"
          value={draft.novelty_description}
          editable={editable}
          onChange={(v) => setDraft({ ...draft, novelty_description: v })}
          placeholder="What is new or non-obvious compared to existing approaches?"
        />
      </QSection>

      <QSection
        title="Technical Details"
        editable={editable}
        busy={busySection === "technical"}
        onSave={() => saveSection("technical", ["technical_description"])}
      >
        {!inventionType && (
          <p className="mb-2 text-xs text-amber-600">
            Select an Invention Type above for tailored guidance on what to
            include here.
          </p>
        )}
        <QField
          label={techGuidance?.label ?? "Technical Description"}
          value={draft.technical_description}
          editable={editable}
          onChange={(v) => setDraft({ ...draft, technical_description: v })}
          placeholder={
            techGuidance?.placeholder ??
            "Describe the technical implementation of your invention in detail."
          }
          rows={6}
        />
      </QSection>

      <QSection
        title="Additional Information"
        editable={editable}
        busy={busySection === "additional"}
        onSave={() =>
          saveSection("additional", [
            "advantages",
            "prior_art",
            "keywords",
            "has_existing_drawings",
          ])
        }
      >
        <QField
          label="Advantages (optional)"
          value={draft.advantages}
          editable={editable}
          onChange={(v) => setDraft({ ...draft, advantages: v })}
          placeholder="Key benefits over existing solutions."
        />
        <QField
          label="Prior Art (optional)"
          value={draft.prior_art}
          editable={editable}
          onChange={(v) => setDraft({ ...draft, prior_art: v })}
          placeholder="Related patents, products, or publications you're aware of."
        />
        <QField
          label="Keywords (optional)"
          value={draft.keywords}
          editable={editable}
          onChange={(v) => setDraft({ ...draft, keywords: v })}
          placeholder="Comma-separated search keywords."
        />
        <label className="flex items-center gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={draft.has_existing_drawings ?? false}
            disabled={!editable}
            onChange={(e) =>
              setDraft({ ...draft, has_existing_drawings: e.target.checked })
            }
          />
          I already have drawings/diagrams for this invention (optional)
        </label>
      </QSection>

      {saveMsg && <p className="text-xs text-emerald-600">{saveMsg}</p>}

      <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4">
        <div>
          <p className="text-sm font-medium text-slate-700">
            {isCompleted ? "Questionnaire submitted" : "Ready to submit?"}
          </p>
          <p className="text-xs text-slate-400">
            Submitting locks a permanent version snapshot. Required fields:
            Invention Type, Problem Statement, Proposed Solution, Novelty
            Description, Technical Description.
          </p>
        </div>
        {editable && !isCompleted && (
          <button
            onClick={submitQuestionnaire}
            disabled={submitBusy}
            className="whitespace-nowrap rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            Submit questionnaire
          </button>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <button
          onClick={() => {
            setShowVersions((v) => !v);
            if (!versions) loadVersions();
          }}
          className="text-sm font-medium text-blue-600 hover:underline"
        >
          {showVersions ? "Hide" : "Show"} version history
        </button>
        {showVersions && (
          <div className="mt-3 space-y-2">
            {versions === null && <LoadingState compact />}
            {versions?.length === 0 && (
              <EmptyState title="No submitted versions yet." />
            )}
            {versions?.map((v) => (
              <div
                key={v.id}
                className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600"
              >
                <span className="font-medium text-slate-800">
                  v{v.version_number}
                </span>{" "}
                — {v.version_status ?? "Completed"} · type:{" "}
                {v.invention_type ?? "—"}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function QSection({
  title,
  editable,
  busy,
  onSave,
  children,
}: {
  title: string;
  editable: boolean;
  busy: boolean;
  onSave: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">{title}</h3>
      <div className="space-y-3">{children}</div>
      {editable && (
        <button
          onClick={onSave}
          disabled={busy}
          className="mt-3 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          Save section
        </button>
      )}
    </section>
  );
}

function QField({
  label,
  value,
  editable,
  onChange,
  placeholder,
  rows = 3,
}: {
  label: string;
  value: string | null | undefined;
  editable: boolean;
  onChange: (v: string) => void;
  placeholder: string;
  rows?: number;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-slate-600">
        {label}
      </label>
      <textarea
        value={value ?? ""}
        disabled={!editable}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm disabled:bg-slate-50"
      />
    </div>
  );
}
