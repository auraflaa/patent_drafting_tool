"""Golden render tests for the five statutory forms.

Each form renders from the anonymised fixture with strict undefined handling.
A template that gains or loses a placeholder without a registry update fails
here instead of shipping a blank legal form.
"""
import io
import json
import re
import zipfile
from pathlib import Path

import pytest
from docx import Document

from app.services import form_specs, forms

FIXTURE = Path(__file__).parent / "fixtures" / "form_profile.json"


@pytest.fixture(scope="module")
def profile() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def context(profile) -> dict:
    questionnaire = dict(profile["questionnaire"])
    applicant = dict(profile["applicant"])
    inventors = list(profile["inventors"])
    agent = dict(profile["config"])
    context = forms.build_context(
        questionnaire=questionnaire,
        applicant=applicant,
        inventors=inventors,
        agent=agent,
        counts={
            "page_count": "13",
            "claim_count": "04",
            "claims_page_count": "01",
            "abstract_page_count": "01",
            "drawing_page_count": "02",
            "drawing_count": "02",
        },
    )
    figures = list(profile["figures"])
    for figure in figures:
        figure["image_bytes"] = _jpeg_bytes()
    return {**context, "_figures": figures}


def _jpeg_bytes() -> bytes:
    import cv2
    import numpy as np

    image = np.full((300, 400, 3), 240, dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (390, 290), (20, 20, 20), 2)
    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return buffer.tobytes()


def _render(code: str, context: dict) -> tuple[bytes, dict, Document]:
    figures = context.get("_figures", []) if code == "DRAWINGS" else []
    payload, report = forms.render_form(code, dict(context), figures=figures)
    assert payload.startswith(b"PK")
    return payload, report, Document(io.BytesIO(payload))


def _template_variables(path: Path) -> set[str]:
    """Every placeholder in the body, headers and footers of a template."""
    names: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name == "word/document.xml" or re.match(
                r"word/(header|footer)\d+\.xml$", name
            ):
                names.update(
                    re.findall(
                        r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}",
                        archive.read(name).decode("utf-8", errors="replace"),
                    )
                )
    return names


def test_all_spec_variables_exist_in_their_templates() -> None:
    for spec in form_specs.FORMS:
        path = (
            Path(forms.__file__).resolve().parent.parent
            / "templates"
            / spec.template
        )
        names = _template_variables(path)
        if spec.code == "DRAWINGS":
            assert "[[FIGURE_BLOCK]]" in zipfile.ZipFile(path).read(
                "word/document.xml"
            ).decode("utf-8", errors="replace")
            names.discard("applicant_name")
            names.discard("title_keyword")
        declared = set(spec.required) | set(spec.optional)
        assert names <= declared, (
            f"{spec.code} has undeclared placeholders: {sorted(names - declared)}"
        )


def test_form1_renders_applicant_inventors_title_and_warning(context) -> None:
    payload, report, doc = _render("FORM1", context)
    text = "\n".join(
        cell.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
    )
    assert "Example Energy Labs" in text
    assert "Alice Example" in text
    assert "Bob Example" in text
    assert "SELF-CLEANING SOLAR ARRAY" in text
    assert "{{" not in text
    assert "MIT" not in text
    assert "Pranav" not in text
    body = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert body.rstrip().endswith(forms.DISCLOSURE_TEXT)
    assert body.count(forms.DISCLOSURE_TEXT) == 1


def test_form2_renders_narrative_prior_art_and_solution(context) -> None:
    payload, report, doc = _render("FORM2", context)
    body = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "US Patent No." not in body
    assert "JP Morgan" not in body
    assert "US 9,000,000: Manual panel washer" in body
    assert "A wiper travels on a rail" in body
    assert "Reduces cleaning labor." in body
    assert "self-cleaning solar array" in body
    assert "{{" not in body
    assert "four_lines_about_problem" not in body.lower().replace(" ", "_")
    assert "four_lines_about_solution" not in body.lower().replace(" ", "_")
    assert body.rstrip().endswith(forms.DISCLOSURE_TEXT)


def test_form3_renders_applicant_and_date(context) -> None:
    payload, report, doc = _render("FORM3", context)
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs) + "\n".join(
        cell.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
    )
    assert "Example Energy Labs" in text
    assert "MIT" not in text
    assert "19th day of February 2023" not in text
    assert "{{" not in text


def test_form5_renders_inventors(context) -> None:
    payload, report, doc = _render("FORM5", context)
    text = "\n".join(
        cell.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
    )
    assert "Example Energy Labs" in text
    assert "Alice Example" in text
    assert "Bob Example" in text
    assert "MIT" not in text
    assert "{{" not in text


def test_drawings_embeds_selected_figures(context) -> None:
    payload, report, doc = _render("DRAWINGS", context)
    assert report["figures_embedded"] == ["fig-1", "fig-2"]
    assert report["figures_omitted"] == []
    assert "[[FIGURE_BLOCK]]" not in "\n".join(
        paragraph.text for paragraph in doc.paragraphs
    )
    captions = [
        paragraph.text
        for paragraph in doc.paragraphs
        if paragraph.text.startswith("FIG.")
    ]
    assert len(captions) == 2
    assert "Exploded view" in captions[0]


def test_drawings_without_figures_renders_notice(context) -> None:
    payload, report = forms.render_form(
        "DRAWINGS", dict(context), figures=[]
    )
    doc = Document(io.BytesIO(payload))
    assert any(
        forms.NO_DRAWINGS_LINE in paragraph.text for paragraph in doc.paragraphs
    )
    assert report["figures_embedded"] == []


def test_missing_required_values_fail_closed(context) -> None:
    thin = {key: value for key, value in context.items() if key != "title_keyword"}
    with pytest.raises(forms.FormRenderError) as exc:
        forms.render_form("FORM1", thin)
    assert "title_keyword" in str(exc.value)


def test_seven_inventors_render(profile) -> None:
    questionnaire = dict(profile["questionnaire"])
    profile_inventors = [
        {"full_name": f"Inventor {index}", "country": "India", "address": "Addr"}
        for index in range(1, 8)
    ]
    rebuilt = forms.build_context(
        questionnaire=questionnaire,
        applicant={
            "full_name_or_org_name": "Example Energy Labs",
            "country": "India",
            "address": "1 Test Street",
        },
        inventors=profile_inventors,
        agent={},
        counts={},
    )
    assert rebuilt["inventor7_name"] == "Inventor 7"
    payload, _ = forms.render_form("FORM1", rebuilt)
    doc = Document(io.BytesIO(payload))
    text = "\n".join(
        cell.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
    )
    assert "Inventor 7" in text
    assert "{{" not in text
