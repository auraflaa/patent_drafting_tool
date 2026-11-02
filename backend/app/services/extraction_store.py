"""Persist extraction output next to the uploaded file it came from.

Firestore is the only system of record, so everything lives in documents:

* ``file_extractions`` - one row per file: status, counts, and the blob ids of
  the gzipped markdown and layout JSON.
* ``file_figures`` - one row per image/table: page, bounding box, caption,
  optional classification, and the blob id of the cropped JPEG.

A blob is a separate document because Firestore caps one document at 1 MiB; the
same limit applies to a figure JPEG, so an oversized crop is dropped from the
blob store and the metadata row kept. Text is the part drafting must have, so it
is truncated to fit rather than dropped.
"""
from __future__ import annotations

import json
import logging

from app.core.config import MAX_STORED_BYTES
from app.services import blobs, ingestion
from app.services.ingestion import FAILED, READY, Extraction, Figure
from app.services.repository import (
    create_doc,
    delete_doc,
    get_doc_or_none,
    now_iso,
    query_docs,
    sort_docs,
    write_doc,
)

logger = logging.getLogger(__name__)

EXTRACTIONS = "file_extractions"
FIGURES = "file_figures"

# Leave room for the row's own fields inside the 900 KB envelope.
_BLOB_BUDGET = MAX_STORED_BYTES - 4_000


def save_extraction(
    *,
    file_id: str,
    patent_id: str,
    extraction: Extraction,
) -> dict:
    """Store one extraction and its figures, replacing any previous result."""
    delete_for_file(file_id)
    text_blob_id = None
    layout_blob_id = None
    text, truncated = _fit_text(extraction.text)
    if text.strip():
        stored = blobs.put_blob(text.encode("utf-8"), "text/markdown")
        text_blob_id = stored["id"]
    layout = extraction.layout or {}
    if layout.get("elements"):
        payload = json.dumps(layout, ensure_ascii=False).encode("utf-8")
        try:
            layout_blob_id = blobs.put_blob(payload, "application/json")["id"]
        except blobs.BlobTooLarge:
            # The outline is a convenience; the text and the figure rows are
            # what drafting depends on, so a huge outline is simply skipped.
            logger.info(
                "extraction_layout_omitted",
                extra={"event": "extraction_layout_omitted", "file_id": file_id},
            )
    record = create_doc(
        EXTRACTIONS,
        {
            "file_id": file_id,
            "patent_application_id": patent_id,
            "status": extraction.status,
            "method": extraction.method,
            "page_count": extraction.page_count,
            "text_characters": len(text),
            "text_truncated": truncated,
            "has_text": bool(text.strip()),
            "figure_count": len(extraction.figures),
            "text_blob_id": text_blob_id,
            "layout_blob_id": layout_blob_id,
            "error": extraction.error,
            "extracted_at": now_iso(),
        },
        doc_id=file_id,
    )
    for figure in extraction.figures:
        _save_figure(file_id, patent_id, figure)
    return record


def ingest_upload(
    *,
    file_id: str,
    patent_id: str,
    filename: str,
    content: bytes,
) -> dict:
    """Extract an already-stored upload and return fields for its files row.

    Called inside the upload request. Whatever happens here, the caller gets a
    dict back and the upload still succeeds: a document the drafting model
    cannot read is a reduced feature, not a failed upload.
    """
    try:
        extraction = ingestion.extract(filename, content)
    except Exception as exc:  # noqa: BLE001 - ingest must never break an upload
        logger.warning(
            "extraction_crashed",
            extra={"event": "extraction_crashed", "error_type": type(exc).__name__},
            exc_info=exc,
        )
        extraction = Extraction(
            status=FAILED, error="The document could not be parsed."
        )
    try:
        record = save_extraction(
            file_id=file_id, patent_id=patent_id, extraction=extraction
        )
    except Exception as exc:  # noqa: BLE001 - storage trouble is not an upload error
        logger.warning(
            "extraction_store_failed",
            extra={
                "event": "extraction_store_failed",
                "error_type": type(exc).__name__,
            },
            exc_info=exc,
        )
        return {
            "extraction_status": FAILED,
            "extraction_figure_count": 0,
            "extraction_page_count": 0,
            "extraction_text_available": False,
            "extraction_error": "Extraction finished but could not be stored.",
        }
    return {
        "extraction_status": record.get("status"),
        "extraction_figure_count": record.get("figure_count") or 0,
        "extraction_page_count": record.get("page_count") or 0,
        "extraction_text_available": bool(record.get("has_text")),
        "extraction_error": (record.get("error") or "")[:300],
    }


def _save_figure(file_id: str, patent_id: str, figure: Figure) -> None:
    image_blob_id = None
    if figure.image:
        try:
            image_blob_id = blobs.put_blob(
                figure.image, figure.content_type or "image/jpeg"
            )["id"]
        except blobs.BlobTooLarge:
            logger.info(
                "figure_image_omitted",
                extra={"event": "figure_image_omitted", "file_id": file_id},
            )
        except blobs.BlobError:
            logger.warning(
                "figure_image_failed",
                extra={"event": "figure_image_failed", "file_id": file_id},
            )
    create_doc(
        FIGURES,
        {
            "file_id": file_id,
            "patent_application_id": patent_id,
            "page": figure.page,
            "bbox": figure.bbox,
            "kind": figure.kind,
            "caption": figure.caption,
            "label": figure.label,
            "confidence": figure.confidence,
            "content_type": figure.content_type,
            "has_image": image_blob_id is not None,
            "image_blob_id": image_blob_id,
        },
    )


def _fit_text(text: str) -> tuple[str, bool]:
    """Truncate text until its gzip form fits in one Firestore document."""
    if not text:
        return "", False
    raw = text.encode("utf-8")
    if len(blobs.compress(raw)) <= _BLOB_BUDGET:
        return text, False
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if len(blobs.compress(text[:middle].encode("utf-8"))) <= _BLOB_BUDGET:
            low = middle
        else:
            high = middle - 1
    return text[:low], True


def get_extraction(file_id: str) -> dict | None:
    return get_doc_or_none(EXTRACTIONS, file_id)


def figures_for_file(file_id: str) -> list[dict]:
    rows = query_docs(FIGURES, filters=[("file_id", "==", file_id)])
    return sort_docs(rows, "page")


def get_figure(figure_id: str) -> dict | None:
    return get_doc_or_none(FIGURES, figure_id)


def read_text(file_id: str) -> bytes:
    record = get_extraction(file_id)
    if record is None or not record.get("text_blob_id"):
        raise blobs.BlobNotFound("No extracted text is available for this file.")
    return blobs.read_blob(record["text_blob_id"])


def read_figure_image(figure: dict) -> bytes:
    if not figure.get("image_blob_id"):
        raise blobs.BlobNotFound("No image is stored for this figure.")
    return blobs.read_blob(figure["image_blob_id"])


def delete_for_file(file_id: str) -> None:
    """Best-effort cleanup so deleting an upload leaves no orphaned blobs.

    The file row is already gone when this runs, so a datastore hiccup must not
    turn a successful delete into a 500. Failures are logged and the delete
    stands; the alternative is an upload that cannot be removed at all.
    """
    try:
        record = get_doc_or_none(EXTRACTIONS, file_id)
    except Exception as exc:  # noqa: BLE001 - cleanup is deliberately best effort
        logger.warning(
            "extraction_lookup_failed",
            extra={"event": "extraction_lookup_failed", "file_id": file_id},
            exc_info=exc,
        )
        return
    if record is not None:
        blobs.delete_blob(record.get("text_blob_id"))
        blobs.delete_blob(record.get("layout_blob_id"))
    try:
        figures = figures_for_file(file_id)
    except Exception as exc:  # noqa: BLE001 - cleanup is deliberately best effort
        logger.warning(
            "figure_lookup_failed",
            extra={"event": "figure_lookup_failed", "file_id": file_id},
            exc_info=exc,
        )
        figures = []
    for figure in figures:
        blobs.delete_blob(figure.get("image_blob_id"))
        try:
            delete_doc(FIGURES, figure["id"])
        except Exception as exc:  # noqa: BLE001 - cleanup is deliberately best effort
            logger.warning(
                "figure_delete_failed",
                extra={"event": "figure_delete_failed", "file_id": file_id},
                exc_info=exc,
            )
    if record is not None:
        try:
            delete_doc(EXTRACTIONS, file_id)
        except Exception as exc:  # noqa: BLE001 - cleanup is deliberately best effort
            logger.warning(
                "extraction_delete_failed",
                extra={"event": "extraction_delete_failed", "file_id": file_id},
                exc_info=exc,
            )


def mark_status(file_id: str, status: str, error: str = "") -> None:
    """Record a failure without inventing an extraction row's contents."""
    write_doc(
        EXTRACTIONS,
        file_id,
        {
            "file_id": file_id,
            "status": status,
            "error": error,
            "has_text": False,
            "text_truncated": False,
            "figure_count": 0,
            "extracted_at": now_iso(),
        },
    )


def load_context(patent_id: str, max_characters: int) -> str:
    """Compose the extract text of every ready upload for the drafting model.

    Figures are described by their caption and page rather than their pixels:
    the model reads text, and a page reference is enough for a patent attorney
    to find the drawing in the source document.
    """
    if max_characters <= 0:
        return ""
    files = {
        doc["id"]: doc
        for doc in query_docs(
            "files", filters=[("patent_application_id", "==", patent_id)]
        )
    }
    rows = query_docs(
        EXTRACTIONS, filters=[("patent_application_id", "==", patent_id)]
    )
    rows = sort_docs(rows, "extracted_at")
    blocks: list[str] = []
    remaining = max_characters
    for row in rows:
        if row.get("status") != READY or remaining <= 0:
            continue
        file_id = row.get("file_id")
        if not file_id or file_id not in files:
            continue
        name = files[file_id].get("original_file_name") or file_id
        try:
            text = read_text(file_id).decode("utf-8", errors="replace").strip()
        except blobs.BlobError:
            continue
        if not text:
            continue
        figures = figures_for_file(file_id)
        figure_line = _figure_line(figures)
        body = text[:remaining]
        remaining -= len(body)
        block = f"### {name}\n{body}"
        if figure_line and remaining > len(figure_line):
            block += f"\n{figure_line}"
            remaining -= len(figure_line)
        blocks.append(block)
        if remaining <= 0:
            break
    return "\n\n".join(blocks)


def _figure_line(figures: list[dict]) -> str:
    parts: list[str] = []
    for figure in figures:
        name = figure.get("label") or ""
        caption = (figure.get("caption") or "").strip()
        page = figure.get("page") or 0
        if caption and caption not in name:
            name = f"{name} ({caption})" if name else caption
        if not name:
            name = "Table" if figure.get("kind") == "table" else "Figure"
        if page:
            name = f"{name}, page {page}"
        parts.append(name)
    if not parts:
        return ""
    return "Figures in this file: " + "; ".join(parts) + "."
