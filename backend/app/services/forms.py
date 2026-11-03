"""Deterministic statutory form renderer.

The model never touches Word: it returns validated field values, and this
module fills the templates. Rendering is sandboxed Jinja with fail-closed
undefined variables, so a missing required value raises with a field list
instead of rendering a blank legal form.

Post-processing (all deterministic):

* ``[[FIGURE_BLOCK]]`` — replaced with the selected figures, each centred
  with a caption, or a "no drawings selected" line.
* Empty optional paragraphs are kept as-is; the review screen warns about
  them instead of the renderer inventing content.
* Exactly one disclosure paragraph is appended to every form.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

import jinja2
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from jinja2.sandbox import SandboxedEnvironment

from app.core.config import settings
from app.services import form_specs
from app.services.form_specs import FormSpec

logger = logging.getLogger(__name__)

FIGURE_MARKER = "[[FIGURE_BLOCK]]"
NO_DRAWINGS_LINE = "No drawings were selected for this application."
DISCLOSURE_TEXT = "This is for drafting purposes only."
MAX_INVENTORS = 7

_JINJA_ENV = SandboxedEnvironment(undefined=jinja2.StrictUndefined)


class FormRenderError(RuntimeError):
    """The form cannot be rendered; the message names the missing values."""


def _ordinal(day: int) -> str:
    if 11 <= day <= 13:
        return f"{day}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def format_generated_date(moment: datetime | None = None) -> str:
    """Indian statutory date style: '3rd day of November 2026'."""
    moment = moment or datetime.now()
    return f"{_ordinal(moment.day)} day of {moment.strftime('%B %Y')}"


def build_context(
    *,
    questionnaire: dict,
    applicant: dict | None,
    inventors: list[dict],
    agent: dict | None = None,
    refined: dict | None = None,
    counts: dict | None = None,
    generated_date: str | None = None,
) -> dict:
    """Merge every value source into one template context.

    Precedence: refined AI values win over raw questionnaire answers, which
    win over derived defaults. Inventor slots beyond the supplied list stay
    empty strings so unused rows render blank signature lines.
    """
    context: dict[str, str] = {}
    context.update(
        {
            key: str(value or "")
            for key, value in (questionnaire or {}).items()
            if isinstance(value, str)
        }
    )
    for key, value in (refined or {}).items():
        if isinstance(value, str) and value.strip():
            context[key] = value

    applicant = applicant or {}
    # Parties are authoritative: the applicants/inventors collections decide
    # these slots, never stray questionnaire keys.
    context["applicant_name"] = applicant.get("full_name_or_org_name") or ""
    context["applicant_nationality"] = applicant.get("country") or ""
    context["applicant_country"] = applicant.get("country") or ""
    context["applicant_address"] = applicant.get("address") or ""

    ordered = sorted(inventors or [], key=lambda item: item.get("inventor_order", 0))
    for index in range(1, MAX_INVENTORS + 1):
        inventor = ordered[index - 1] if index <= len(ordered) else {}
        context[f"inventor{index}_name"] = inventor.get("full_name") or ""
        context[f"inventor{index}_nationality"] = inventor.get("country") or ""
        context[f"inventor{index}_country"] = inventor.get("country") or ""
        context[f"inventor{index}_address"] = inventor.get("address") or ""

    agent = agent or {}
    for key in (
        "agent_name",
        "agent_inpa",
        "agent_mobile",
        "agent_address",
        "agent_telephone",
        "agent_fax",
        "agent_email",
    ):
        context[key] = agent.get(key.removeprefix("agent_")) or ""

    for key, value in (counts or {}).items():
        if value not in (None, ""):
            context[key] = str(value)
    context.setdefault("generated_date", generated_date or format_generated_date())
    # Every declared variable exists (possibly blank) so StrictUndefined only
    # fails on genuinely unknown template variables, never on an optional the
    # caller did not supply. Required-field validation still fails closed.
    for spec in form_specs.FORMS:
        for key in form_specs.declared_variables(spec):
            context.setdefault(key, "")
    return context


def _missing_required(spec: FormSpec, context: dict) -> list[str]:
    return [key for key in spec.required if not str(context.get(key) or "").strip()]


def render_form(
    code: str,
    context: dict,
    *,
    figures: list[dict] | None = None,
    template_bytes: bytes | None = None,
) -> tuple[bytes, dict]:
    """Render one form. Returns (docx_bytes, report).

    The report carries ``figures_embedded``, ``figures_omitted`` and
    ``warnings`` (blank optional values, omitted figures). Anything that
    would produce a silently incomplete legal form raises instead.
    """
    spec = form_specs.BY_CODE[code]
    missing = _missing_required(spec, context)
    if missing:
        raise FormRenderError(
            f"{spec.label} is missing required value(s): {', '.join(missing)}."
        )
    if template_bytes is None:
        path = (
            Path(__file__).resolve().parent.parent / "templates" / spec.template
        )
        template_bytes = path.read_bytes()

    from docxtpl import DocxTemplate

    try:
        template = DocxTemplate(io.BytesIO(template_bytes))
        template.render(dict(context), jinja_env=_JINJA_ENV)
    except jinja2.UndefinedError as exc:
        raise FormRenderError(
            f"{spec.label} references an undeclared variable: {exc}"
        ) from exc
    except Exception as exc:
        raise FormRenderError(
            f"{spec.label} could not be rendered: {type(exc).__name__}"
        ) from exc

    document = template.docx
    report: dict = {
        "form": code,
        "figures_embedded": [],
        "figures_omitted": [],
        "warnings": _blank_warnings(spec, context),
    }
    if spec.supports_figures:
        _insert_figure_block(document, figures or [], report)
    _append_disclosure(document)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue(), report


def _blank_warnings(spec: FormSpec, context: dict) -> list[str]:
    warnings = []
    for key in spec.optional:
        if not str(context.get(key) or "").strip():
            warnings.append(f"{key} is blank")
    if not str(context.get("prior_art") or "").strip() and spec.code == "FORM2":
        warnings.append("prior_art is blank: the section renders empty")
    return warnings


def _insert_figure_block(
    document: Document, figures: list[dict], report: dict
) -> None:
    """Replace the marker paragraph with centred figures and captions."""
    marker = None
    for paragraph in document.paragraphs:
        if paragraph.text.strip() == FIGURE_MARKER:
            marker = paragraph
            break
    if marker is None:
        raise FormRenderError("The drawings template has no [[FIGURE_BLOCK]].")

    budget = settings.forms_image_budget_bytes
    used = 0
    if not figures:
        marker.text = NO_DRAWINGS_LINE
        return
    marker.text = ""
    last = marker._p
    for number, figure in enumerate(figures, start=1):
        image = figure.get("image_bytes")
        if not image:
            report["figures_omitted"].append(
                {"alias": figure.get("alias"), "reason": "no image bytes"}
            )
            continue
        prepared = _fit_image(image, budget - used)
        if prepared is None:
            report["figures_omitted"].append(
                {"alias": figure.get("alias"), "reason": "image budget exhausted"}
            )
            continue
        used += len(prepared)
        picture_paragraph = _paragraph_after(document, last)
        last = picture_paragraph._p
        picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        picture_paragraph.add_run().add_picture(
            io.BytesIO(prepared), width=_docx_inches(5.5)
        )
        caption_paragraph = _paragraph_after(document, last)
        last = caption_paragraph._p
        caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption_run = caption_paragraph.add_run(
            f"FIG. {number} — {figure.get('caption') or figure.get('label') or 'drawing'}"
        )
        caption_run.font.size = Pt(9)
        caption_run.font.color.rgb = RGBColor(0x40, 0x40, 0x40)
        report["figures_embedded"].append(figure.get("alias") or f"fig-{number}")
    # Remove the now-empty marker paragraph.
    marker._p.getparent().remove(marker._p)


def _paragraph_after(document: Document, element):
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph

    paragraph_element = OxmlElement("w:p")
    element.addnext(paragraph_element)
    return Paragraph(paragraph_element, document)


def _docx_inches(width: float):
    from docx.shared import Inches

    return Inches(width)


def _fit_image(image: bytes, budget: int) -> bytes | None:
    """Re-encode a figure so it fits the remaining budget, or None."""
    if budget <= 0:
        return None
    if len(image) <= budget and image.startswith(b"\xff\xd8"):
        return image
    try:
        import cv2
        import numpy as np
    except Exception:  # pragma: no cover - OpenCV ships with the app
        return image if len(image) <= budget else None
    decoded = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        return None
    height, width = decoded.shape[:2]
    longest = max(height, width)
    if longest > 1000:
        scale = 1000 / longest
        decoded = cv2.resize(
            decoded,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    for quality in (60, 45, 30):
        ok, buffer = cv2.imencode(
            ".jpg", decoded, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        )
        if ok and buffer.nbytes <= budget:
            return buffer.tobytes()
    return None


def _append_disclosure(document: Document) -> None:
    paragraph = document.add_paragraph()
    run = paragraph.add_run(DISCLOSURE_TEXT)
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x60, 0x60, 0x60)
