"""Turn an uploaded document into text, a layout outline and figure crops.

Drafting reads prose, and a patent filing carries most of its meaning in its
figures. Both come out of one parse so a document is read once:

* PDF - OpenDataLoader (Apache-2.0, Java 11+, CPU only) emits markdown, a
  per-element JSON outline with bounding boxes, and the embedded images.
* DOCX/PPTX - python-docx / python-pptx for text plus embedded pictures.
* TXT/MD - decoded as UTF-8 (with a Windows fallback).

Extraction can never fail an upload. The file is already stored when this runs,
so every problem is returned as an ``Extraction`` whose ``status`` explains it:
``ready``, ``failed``, ``unsupported`` or ``unavailable``.

Figure detection is optional. YOLOv10-b DocLayNet weights (Apache-2.0) are
never committed; without ``YOLO_MODEL_PATH`` the pipeline uses embedded
images and direct uploads only.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

try:  # Present in production; tests replace it with a stub.
    import opendataloader_pdf
except Exception:  # pragma: no cover - exercised only on a bare install
    opendataloader_pdf = None  # type: ignore[assignment]

READY = "ready"
FAILED = "failed"
UNSUPPORTED = "unsupported"
UNAVAILABLE = "unavailable"

PDF_EXTENSIONS = {".pdf"}
WORD_EXTENSIONS = {".docx"}
SLIDE_EXTENSIONS = {".pptx"}
TEXT_EXTENSIONS = {".txt", ".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# "FIG. 2", "Figure 2A", "TABLE 3" - the labels examiners actually use.
_CAPTION_RE = re.compile(
    r"^\s*(fig(?:ure)?\.?|table)\s*\d+[a-z]?(?![0-9a-z])", re.I
)
_LABEL_RE = re.compile(r"^\s*((?:fig(?:ure)?\.?)|table)\s*(\d+[a-z]?)", re.I)

_MAX_LAYOUT_ELEMENTS = 1_500
_MAX_ELEMENT_CHARS = 2_000
_MAX_FIGURE_BYTES = 800_000
_MAX_FIGURE_EDGE = 1_400
_JPEG_QUALITIES = (82, 70, 55, 40)


@dataclass
class Figure:
    """One image or table, with the page and box it occupies."""

    page: int = 0
    bbox: list[float] = field(default_factory=list)
    kind: str = "image"
    caption: str = ""
    label: str = ""
    confidence: float | None = None
    image: bytes | None = None
    content_type: str = "image/jpeg"
    source_name: str = ""
    # Set by the producer when known ("usable"); screening decides otherwise.
    usable: str | None = None


@dataclass
class Extraction:
    status: str = UNSUPPORTED
    method: str = ""
    text: str = ""
    layout: dict = field(default_factory=dict)
    figures: list[Figure] = field(default_factory=list)
    page_count: int = 0
    error: str = ""

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


def extract(filename: str, content: bytes) -> Extraction:
    """Parse one upload. Never raises; inspect ``status`` for the outcome."""
    if not settings.ingestion_enabled:
        return Extraction(
            status=UNSUPPORTED,
            error="Document extraction is turned off for this deployment.",
        )
    if not content:
        return Extraction(status=FAILED, error="The file is empty.")
    extension = Path(filename or "").suffix.lower()
    try:
        if extension in PDF_EXTENSIONS:
            result = _extract_pdf(content)
        elif extension in WORD_EXTENSIONS:
            result = _extract_docx(content)
        elif extension in SLIDE_EXTENSIONS:
            result = _extract_pptx(content)
        elif extension in TEXT_EXTENSIONS:
            result = _extract_text(content)
        elif extension in IMAGE_EXTENSIONS:
            result = _extract_image(content, extension)
        elif extension == ".doc":
            result = Extraction(
                status=UNSUPPORTED,
                method="doc",
                error=(
                    "Legacy .doc files cannot be read. Save the file as .docx "
                    "or PDF and upload it again."
                ),
            )
        elif extension == ".ppt":
            result = Extraction(
                status=UNSUPPORTED,
                method="ppt",
                error=(
                    "Legacy .ppt files cannot be read. Save the file as .pptx "
                    "or PDF and upload it again."
                ),
            )
        else:
            result = Extraction(
                status=UNSUPPORTED,
                error=f"Text extraction is not available for {extension or 'this file type'}.",
            )
    except Exception as exc:  # noqa: BLE001 - extraction must not break an upload
        logger.warning(
            "ingestion_failed",
            extra={"event": "ingestion_failed", "error_type": type(exc).__name__},
            exc_info=exc,
        )
        return Extraction(
            status=FAILED,
            method=extension.lstrip("."),
            error=_short_error(exc),
        )
    result.figures = result.figures[: settings.max_figures_per_file]
    return result


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _extract_pdf(content: bytes) -> Extraction:
    if opendataloader_pdf is None:
        return Extraction(
            status=UNAVAILABLE,
            method="opendataloader",
            error="PDF extraction needs Java 11 or newer on the server. Install Java, or upload a DOCX version of the document.",
        )
    java = settings.java_binary or "java"
    if shutil.which(java) is None:
        return Extraction(
            status=UNAVAILABLE,
            method="opendataloader",
            error=(
                "PDF extraction needs Java 11 or newer on the server. "
                "Install Java, or upload a DOCX version of the document."
            ),
        )
    with tempfile.TemporaryDirectory(prefix="pdt-ingest-") as tmp:
        root = Path(tmp)
        source = root / "input.pdf"
        source.write_bytes(content)
        output = root / "out"
        output.mkdir()
        try:
            opendataloader_pdf.convert(
                input_path=[str(source)],
                output_dir=str(output),
                format="json,markdown",
                image_output="external",
                image_format="jpeg",
                quiet=True,
                threads=str(min(os.cpu_count() or 1, 8)),
            )
        except Exception as exc:  # noqa: BLE001 - the JVM reports many shapes
            return Extraction(
                status=FAILED,
                method="opendataloader",
                error=_short_error(exc) or "The PDF could not be parsed.",
            )
        markdown_path = output / "input.md"
        json_path = output / "input.json"
        text = (
            markdown_path.read_text(encoding="utf-8", errors="replace")
            if markdown_path.exists()
            else ""
        )
        data: dict = {}
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return Extraction(
                    status=FAILED,
                    method="opendataloader",
                    error=f"The extracted layout could not be read: {_short_error(exc)}",
                )
        elements = list(_walk_elements(data))
        figures = _pdf_figures(elements, output)
        detection_note = ""
        if settings.yolo_model_path:
            # Vector drawings have no embedded images; the detector finds
            # them on the rendered page. Duplicates of OpenDataLoader boxes
            # are dropped by IoU.
            from app.services import figure_detection

            holder: dict = {}
            detected = figure_detection.detect_pdf_figures(content, error_out=holder)
            if holder.get("error"):
                # The extraction itself succeeded, so this rides along as a
                # note (surfaced in the file badge tooltip), not a failure:
                # "no figures" and "detector broken" look identical otherwise.
                detection_note = (
                    f"Figure detection unavailable: {holder['error']}"
                )
            figures = figure_detection.merge_detections(figures, detected)
        page_count = int(data.get("number of pages") or 0)
        if not page_count:
            page_count = max((figure.page for figure in figures), default=0)
        return Extraction(
            status=READY,
            method="opendataloader",
            text=text,
            layout={"elements": _trim_elements(elements)},
            figures=figures,
            page_count=page_count,
            error=detection_note,
        )


def _walk_elements(node: dict):
    for child in node.get("kids") or []:
        if not isinstance(child, dict):
            continue
        yield child
        yield from _walk_elements(child)


def _trim_elements(elements: list[dict]) -> list[dict]:
    trimmed: list[dict] = []
    for element in elements[:_MAX_LAYOUT_ELEMENTS]:
        content = element.get("content")
        trimmed.append(
            {
                "type": element.get("type"),
                "page": _as_int(element.get("page number")),
                "bbox": _as_bbox(element.get("bounding box")),
                "content": (
                    _squash(str(content))[:_MAX_ELEMENT_CHARS]
                    if content is not None
                    else ""
                ),
                "source": element.get("source") or "",
                "heading_level": element.get("heading level"),
            }
        )
    return trimmed


def _pdf_figures(elements: list[dict], output: Path) -> list[Figure]:
    graphics = [
        element
        for element in elements
        if element.get("type") in {"image", "table"}
    ]
    captions = [
        (
            _as_int(element.get("page number")),
            _as_bbox(element.get("bounding box")),
            _squash(str(element.get("content") or "")),
        )
        for element in elements
        if element.get("type") != "image"
        and _CAPTION_RE.match(str(element.get("content") or ""))
    ]
    figures: list[Figure] = []
    for element in graphics:
        page = _as_int(element.get("page number"))
        bbox = _as_bbox(element.get("bounding box"))
        kind = "table" if element.get("type") == "table" else "image"
        figure = Figure(page=page, bbox=bbox, kind=kind)
        figure.caption = _caption_for(page, bbox, captions)
        figure.label = _label_from(figure.caption)
        if kind == "image":
            raw = _read_extracted_image(output, element.get("source"))
            prepared = _prepare_image(raw) if raw else None
            if prepared is not None:
                figure.image, figure.content_type = prepared
            figure.source_name = str(element.get("source") or "")
        figures.append(figure)
    return figures


def _read_extracted_image(output: Path, source) -> bytes | None:
    if not source:
        return None
    candidate = (output / str(source)).resolve()
    try:
        candidate.relative_to(output.resolve())
    except ValueError:
        return None  # a malformed source must not read outside the temp dir
    try:
        return candidate.read_bytes()
    except OSError:
        return None


def _caption_for(
    page: int,
    bbox: list[float],
    captions: list[tuple[int, list[float], str]],
    *,
    max_gap: float = 180.0,
) -> str:
    """Pick the closest FIG./TABLE label on the same page.

    Patent drawings put the label directly above or below the drawing, so the
    nearest caption wins; a page number is never enough on its own, because
    most pages carry no figure at all.
    """
    best: tuple[float, str] | None = None
    for caption_page, caption_bbox, text in captions:
        if caption_page != page or not text:
            continue
        gap = _vertical_gap(caption_bbox, bbox)
        if gap is None or gap > max_gap:
            continue
        if best is None or gap < best[0]:
            best = (gap, text)
    return best[1] if best else ""


def _vertical_gap(a: list[float], b: list[float]) -> float | None:
    """Distance between two boxes when one sits above the other."""
    if len(a) < 4 or len(b) < 4:
        return None
    above = a[1] - b[3]  # a's bottom minus b's top
    below = b[1] - a[3]  # b's bottom minus a's top
    gaps = [gap for gap in (above, below) if gap >= -4]
    return min(gaps) if gaps else None


def _label_from(caption: str) -> str:
    match = _LABEL_RE.match(caption or "")
    if not match:
        return ""
    prefix = "Table" if match.group(1).lower().startswith("tab") else "FIG."
    return f"{prefix} {match.group(2).upper()}"


# ---------------------------------------------------------------------------
# Word and slides
# ---------------------------------------------------------------------------


def _extract_docx(content: bytes) -> Extraction:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(_stream(content))
    blocks: list[str] = []
    figures: list[Figure] = []
    caption = ""
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if _CAPTION_RE.match(text):
                caption = _squash(text)
            if text:
                blocks.append(text)
            for rel_id in child.xpath(".//a:blip/@r:embed"):
                figure = _embedded_figure(document.part, rel_id, caption)
                if figure is not None:
                    figures.append(figure)
                # A caption describes the image it precedes, not every image
                # after it: consume once so later images do not inherit it.
                caption = ""
        elif tag == "tbl":
            table = Table(child, document)
            rows = [
                " | ".join(cell.text.strip() for cell in row.cells)
                for row in table.rows
            ]
            if rows:
                blocks.append("\n".join(rows))
                figures.append(
                    Figure(
                        kind="table",
                        caption=caption,
                        label=_label_from(caption),
                    )
                )
                caption = ""
    text = "\n\n".join(blocks)
    layout = {
        "elements": [
            {"type": "paragraph", "content": block[: _MAX_ELEMENT_CHARS]}
            for block in blocks
        ]
    }
    return Extraction(
        status=READY,
        method="python-docx",
        text=text,
        layout=layout,
        figures=figures,
        page_count=0,
    )


def _extract_pptx(content: bytes) -> Extraction:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    presentation = Presentation(_stream(content))
    blocks: list[str] = []
    figures: list[Figure] = []
    for index, slide in enumerate(presentation.slides, start=1):
        caption = ""
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if _CAPTION_RE.match(text):
                    caption = _squash(text)
                if text:
                    blocks.append(text)
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    blob = shape.image.blob
                    content_type = shape.image.content_type
                except Exception:  # noqa: BLE001 - a broken picture is skippable
                    blob = None
                if blob:
                    prepared = _prepare_image(blob)
                    if prepared is not None:
                        image, prepared_type = prepared
                        figures.append(
                            Figure(
                                page=index,
                                kind="image",
                                caption=caption,
                                label=_label_from(caption),
                                image=image,
                                content_type=prepared_type,
                            )
                        )
                    else:
                        figures.append(
                            Figure(
                                page=index,
                                kind="image",
                                caption=caption,
                                label=_label_from(caption),
                                content_type=content_type,
                            )
                        )
                    # Consume-once, as in DOCX: a caption belongs to the
                    # image it precedes, not every image after it.
                    caption = ""
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                blocks.append(notes)
    return Extraction(
        status=READY,
        method="python-pptx",
        text="\n\n".join(blocks),
        layout={
            "elements": [
                {"type": "slide", "content": block[: _MAX_ELEMENT_CHARS]}
                for block in blocks
            ]
        },
        figures=figures,
        page_count=len(presentation.slides),
    )


def _embedded_figure(part, rel_id: str, caption: str) -> Figure | None:
    try:
        image = part.related_parts[rel_id]
        blob = image.blob
    except Exception:  # noqa: BLE001 - a broken relationship is skippable
        return None
    prepared = _prepare_image(blob)
    figure = Figure(
        kind="image",
        caption=caption,
        label=_label_from(caption),
    )
    if prepared is not None:
        figure.image, figure.content_type = prepared
    return figure


# ---------------------------------------------------------------------------
# Direct image uploads
# ---------------------------------------------------------------------------


def _extract_image(content: bytes, extension: str) -> Extraction:
    """Treat an uploaded image as a single figure candidate."""
    prepared = _prepare_image(content)
    figures: list[Figure] = []
    if prepared is not None:
        image, content_type = prepared
        figures.append(
            Figure(
                page=0,
                kind="image",
                image=image,
                content_type=content_type,
            )
        )
    return Extraction(
        status=READY if figures else FAILED,
        method="image",
        text="",
        layout={"elements": []},
        figures=figures,
        page_count=0,
        error="" if figures else "The image could not be read.",
    )


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


def _extract_text(content: bytes) -> Extraction:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 never fails
        text = content.decode("utf-8", errors="replace")
    return Extraction(status=READY, method="text", text=text, page_count=0)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def _prepare_image(raw: bytes) -> tuple[bytes, str] | None:
    """Downscale and JPEG-compress a figure so it fits in one document.

    Firestore caps a document at 1 MiB and a gzip of an already-compressed JPEG
    barely shrinks, so the byte budget has to be enforced here.
    """
    if not raw:
        return None
    if raw.startswith(b"\xff\xd8") and len(raw) <= _MAX_FIGURE_BYTES:
        return raw, "image/jpeg"
    try:
        import cv2
        import numpy as np
    except Exception:  # pragma: no cover - OpenCV is a hard dependency of docgen
        return (raw, "image/jpeg") if len(raw) <= _MAX_FIGURE_BYTES else None
    try:
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    except Exception:  # noqa: BLE001 - a corrupt image is not fatal
        return None
    if image is None:
        return None
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        # Composite transparency onto white: a patent drawing on a transparent
        # background would otherwise turn black in a JPEG.
        alpha = image[:, :, 3:4].astype("float32") / 255.0
        colour = image[:, :, :3].astype("float32")
        image = (colour * alpha + 255.0 * (1.0 - alpha)).astype("uint8")
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest > _MAX_FIGURE_EDGE:
        scale = _MAX_FIGURE_EDGE / longest
        image = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    for quality in _JPEG_QUALITIES:
        ok, buffer = cv2.imencode(
            ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        )
        if ok and buffer.nbytes <= _MAX_FIGURE_BYTES:
            return buffer.tobytes(), "image/jpeg"
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stream(content: bytes):
    from io import BytesIO

    return BytesIO(content)


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_bbox(value) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return []
    try:
        return [round(float(item), 2) for item in value[:4]]
    except (TypeError, ValueError):
        return []


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _short_error(exc: Exception) -> str:
    """First line of an exception, trimmed for a user-facing field."""
    message = _squash(str(exc)) or type(exc).__name__
    return message[:300]
