"""Statutory form set orchestration: profile → render → store → version.

One batch renders every requested form independently. A form that fails is
recorded on its own job row; the rest of the set still completes. Retrying
targets one form, never the whole set.
"""
from __future__ import annotations

import logging
import uuid

from app.core.config import settings
from app.services import blobs, extraction_store, forms
from app.services.documents import DOCX_MIME
from app.services.form_specs import BY_CODE, FORM_CODES
from app.services.repository import (
    allocate_counter,
    create_doc,
    get_doc_or_none,
    now_iso,
    patch_doc,
    query_docs,
    set_latest_version,
    sort_docs,
)

logger = logging.getLogger(__name__)

OUTPUT_FORMAT = "DOCX"
FORM_SETS = "form_sets"


def _questionnaire(patent_id: str) -> dict:
    rows = query_docs(
        "questionnaires", filters=[("patent_application_id", "==", patent_id)]
    )
    return rows[0] if rows else {}


def _primary_applicant(patent_id: str) -> dict:
    rows = query_docs(
        "applicants", filters=[("patent_application_id", "==", patent_id)]
    )
    for row in rows:
        if row.get("is_primary"):
            return row
    return rows[0] if rows else {}


def _inventors(patent_id: str) -> list[dict]:
    rows = query_docs(
        "inventors", filters=[("patent_application_id", "==", patent_id)]
    )
    return sort_docs(rows, "inventor_order")


def _agent() -> dict:
    return {
        "name": settings.forms_agent_name,
        "inpa": settings.forms_agent_inpa,
        "mobile": settings.forms_agent_mobile,
        "address": settings.forms_agent_address,
        "telephone": settings.forms_agent_telephone,
        "fax": settings.forms_agent_fax,
        "email": settings.forms_agent_email,
    }


def _selected_figures(patent_id: str) -> list[dict]:
    """Usable, included figures with image bytes, in sheet order."""
    selected = []
    for row in extraction_store.figures_for_patent(patent_id):
        if (
            row.get("usable") != "usable"
            or not row.get("include_in_drawings", True)
            or not row.get("image_blob_id")
        ):
            continue
        try:
            image = extraction_store.read_figure_image(row)
        except Exception:  # noqa: BLE001 - one bad blob skips one figure
            continue
        selected.append(
            {
                "alias": row.get("label") or row["id"],
                "caption": row.get("caption_override") or row.get("caption") or "",
                "label": row.get("label") or "",
                "image_bytes": image,
            }
        )
    return selected


def _refined_fields(patent_id: str) -> dict:
    """Latest refined value per field across the three AI groups.

    User edits win automatically: PATCH saves a new version, and the newest
    version per group is what renders.
    """
    from app.services.form_ai import GROUPS

    rows = query_docs("drafts", filters=[("patent_application_id", "==", patent_id)])
    latest: dict[str, dict] = {}
    for row in rows:
        if row.get("section_type") not in GROUPS:
            continue
        current = latest.get(row["section_type"])
        if current is None or int(row.get("version_number") or 0) > int(
            current.get("version_number") or 0
        ):
            latest[row["section_type"]] = row
    merged: dict = {}
    for group in GROUPS:
        merged.update(latest.get(group, {}).get("fields") or {})
    return merged


def build_profile(patent_id: str, counts: dict | None = None) -> dict:
    """Assemble the render profile from Firestore rows and settings."""
    questionnaire = _questionnaire(patent_id)
    return {
        "questionnaire": questionnaire,
        "refined": _refined_fields(patent_id),
        "applicant": _primary_applicant(patent_id),
        "inventors": _inventors(patent_id),
        "agent": _agent(),
        "counts": dict(counts or {}),
        "generated_date": forms.format_generated_date(),
    }


def profile_context(profile: dict) -> dict:
    return forms.build_context(
        questionnaire=profile["questionnaire"],
        applicant=profile["applicant"],
        inventors=profile["inventors"],
        agent=profile["agent"],
        refined=profile.get("refined") or {},
        counts=profile["counts"],
        generated_date=profile["generated_date"],
    )


def missing_form_fields(code: str, context: dict) -> list[str]:
    return [key for key in BY_CODE[code].required if not str(context.get(key) or "").strip()]


def generate_form_set(
    patent_id: str,
    user: dict,
    *,
    codes: list[str] | None = None,
    counts: dict | None = None,
) -> dict:
    """Render the requested forms; one job row each. Never raises."""
    wanted = [code for code in (codes or list(FORM_CODES)) if code in BY_CODE]
    if not wanted:
        wanted = list(FORM_CODES)
    batch_id = uuid.uuid4().hex
    profile = build_profile(patent_id, counts)
    context = profile_context(profile)
    figures = _selected_figures(patent_id)
    # The drawings count is derived from the selected figures; claim and
    # page counts stay manual until the review UI supplies them.
    context["drawing_count"] = str(len(figures))
    results = []
    for code in wanted:
        results.append(_render_one(patent_id, user, batch_id, code, context, figures))
    try:
        _record_set(patent_id, batch_id)
    except Exception:  # noqa: BLE001 - the set row is bookkeeping, not output
        logger.warning("form_set_record_failed", extra={"batch_id": batch_id})
    return {"batch_id": batch_id, "results": results}


def _render_one(
    patent_id: str,
    user: dict,
    batch_id: str,
    code: str,
    context: dict,
    figures: list[dict],
) -> dict:
    job = create_doc(
        "document_jobs",
        {
            "patent_application_id": patent_id,
            "batch_id": batch_id,
            "form_code": code,
            "output_format": OUTPUT_FORMAT,
            "status": "Processing",
            "triggered_by": user["uid"],
            "retried_from_job_id": None,
            "error_message": None,
            "started_at": now_iso(),
            "completed_at": None,
        },
    )
    try:
        payload, report = forms.render_form(code, dict(context), figures=figures)
        stored = blobs.put_blob(payload, DOCX_MIME)
        _store_version(patent_id, user, code, stored, report)
        job = patch_doc(
            "document_jobs",
            job["id"],
            {
                "status": "Completed",
                "error_message": None,
                "completed_at": now_iso(),
            },
        )
        return {
            "form_code": code,
            "status": "Completed",
            "job_id": job["id"],
            "figures_embedded": report["figures_embedded"],
            "figures_omitted": report["figures_omitted"],
            "warnings": report["warnings"],
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - one form never fails the set
        if not isinstance(exc, forms.FormRenderError):
            logger.warning(
                "form_render_failed",
                extra={"form": code, "error_type": type(exc).__name__},
                exc_info=exc,
            )
        if isinstance(exc, forms.FormRenderError):
            message = str(exc)[:500]
        elif isinstance(exc, blobs.BlobTooLarge):
            # Curated and safe to show; reworded for generation (it is not
            # an upload): the drawings pushed the form over the blob cap.
            message = (
                "The generated form does not fit in storage. "
                "Deselect some drawings or shorten the refined text, "
                "then generate again."
            )
        else:
            message = (
                "The form could not be generated. Try again or contact support."
            )
        job = patch_doc(
            "document_jobs",
            job["id"],
            {"status": "Failed", "error_message": message, "completed_at": now_iso()},
        )
        return {
            "form_code": code,
            "status": "Failed",
            "job_id": job["id"],
            "figures_embedded": [],
            "figures_omitted": [],
            "warnings": [],
            "error": message,
        }


def _store_version(
    patent_id: str, user: dict, code: str, stored: dict, report: dict
) -> None:
    doc_id = f"{patent_id}:{code}:{OUTPUT_FORMAT}"
    stamp = now_iso()
    versions = query_docs(
        "document_versions", filters=[("patent_application_id", "==", patent_id)]
    )
    previous_max = max(
        [int(doc.get("version_number") or 0) for doc in versions if doc.get("document_id") == doc_id]
        or [0]
    )
    version_number = allocate_counter(
        "document_counters", f"{patent_id}:{OUTPUT_FORMAT}:{code}", floor=previous_max
    )
    fields = {
        "generated_by": user["uid"],
        "generated_at": stamp,
        "stored_path": stored["id"],
        "file_size_bytes": stored["size_bytes"],
        "stored_size_bytes": stored["stored_bytes"],
    }
    existing = get_doc_or_none("documents", doc_id)
    try:
        if existing is None:
            create_doc(
                "documents",
                {
                    "patent_application_id": patent_id,
                    "document_type": code,
                    "output_format": OUTPUT_FORMAT,
                    "watermark_status": "DRAFT",
                    **fields,
                    "latest_version": version_number,
                },
                doc_id=doc_id,
            )
        else:
            set_latest_version("documents", doc_id, version_number, fields)
        create_doc(
            "document_versions",
            {
                "document_id": doc_id,
                "patent_application_id": patent_id,
                "version_number": version_number,
                "change_summary": f"Generated {code}",
                "generated_by": user["uid"],
                "generated_at": stamp,
                "storage_path": stored["id"],
                "figures_embedded": report["figures_embedded"],
                "figures_omitted": report["figures_omitted"],
            },
        )
    except Exception:
        blobs.delete_blob(stored["id"])
        raise


def _record_set(patent_id: str, batch_id: str) -> None:
    stamp = now_iso()
    existing = get_doc_or_none(FORM_SETS, patent_id)
    if existing is None:
        create_doc(
            FORM_SETS,
            {
                "patent_application_id": patent_id,
                "latest_batch_id": batch_id,
                "generated_at": stamp,
                "finalized_at": None,
                "finalized_by": None,
                "usable_figure_count": extraction_store.usable_figure_count(patent_id),
            },
            doc_id=patent_id,
        )
    else:
        patch_doc(
            FORM_SETS,
            patent_id,
            {
                "latest_batch_id": batch_id,
                "generated_at": stamp,
                "usable_figure_count": extraction_store.usable_figure_count(patent_id),
            },
        )


def form_status(patent_id: str) -> dict:
    """Per-form generation state plus the finalize gate inputs."""
    profile = build_profile(patent_id)
    context = profile_context(profile)
    documents = {
        doc.get("document_type"): doc
        for doc in query_docs(
            "documents", filters=[("patent_application_id", "==", patent_id)]
        )
    }
    jobs = query_docs(
        "document_jobs", filters=[("patent_application_id", "==", patent_id)]
    )
    latest_job: dict[str, dict] = {}
    for job in sort_docs(jobs, "started_at"):
        if job.get("form_code"):
            latest_job[job["form_code"]] = job
    form_set = get_doc_or_none(FORM_SETS, patent_id)
    usable = extraction_store.usable_figure_count(patent_id)
    cards = []
    for code in FORM_CODES:
        document = documents.get(code)
        job = latest_job.get(code)
        cards.append(
            {
                "form_code": code,
                "label": BY_CODE[code].label,
                "generated": document is not None,
                "latest_version": (document or {}).get("latest_version"),
                "generated_at": (document or {}).get("generated_at"),
                "job_status": (job or {}).get("status"),
                "job_error": (job or {}).get("error_message"),
                "job_completed_at": (job or {}).get("completed_at"),
                "missing_fields": missing_form_fields(code, context),
            }
        )
    return {
        "forms": cards,
        "usable_figure_count": usable,
        "missing_sketch_warning": usable == 0,
        "finalized_at": (form_set or {}).get("finalized_at"),
        "finalized_by": (form_set or {}).get("finalized_by"),
    }


def finalize(patent_id: str, user: dict) -> dict:
    """Lock the generated set. Requires complete fields and a usable figure."""
    status = form_status(patent_id)
    incomplete = [card["form_code"] for card in status["forms"] if not card["generated"]]
    if incomplete:
        raise FinalizeError(
            "Generate all forms before finalizing. Missing: "
            + ", ".join(incomplete)
            + "."
        )
    stale = sorted(
        {
            card["form_code"]
            for card in status["forms"]
            if card["generated"]
            and card["job_status"] == "Failed"
            and (card["job_completed_at"] or "") >= (card["generated_at"] or "")
        }
    )
    if stale:
        raise FinalizeError(
            "Re-generate after the latest failure before finalizing: "
            + ", ".join(stale)
            + "."
        )
    missing = sorted(
        {field for card in status["forms"] for field in card["missing_fields"]}
    )
    if missing:
        raise FinalizeError(
            "Complete the required fields before finalizing: "
            + ", ".join(missing)
            + "."
        )
    if status["usable_figure_count"] == 0:
        raise FinalizeError(
            "No potential sketch or drawing was found. Upload a sketch or "
            "drawing before this patent can be finalized."
        )
    stamp = now_iso()
    existing = get_doc_or_none(FORM_SETS, patent_id)
    fields = {
        "finalized_at": stamp,
        "finalized_by": user["uid"],
        "usable_figure_count": status["usable_figure_count"],
    }
    if existing is None:
        create_doc(
            FORM_SETS,
            {"patent_application_id": patent_id, **fields},
            doc_id=patent_id,
        )
    else:
        patch_doc(FORM_SETS, patent_id, fields)
    return {"patent_application_id": patent_id, **fields}


class FinalizeError(RuntimeError):
    pass
