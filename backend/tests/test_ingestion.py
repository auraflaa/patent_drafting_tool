"""Offline tests for document ingestion and its storage helpers.

The extractor is the only part of the upload path that shells out to a JVM, so
these tests replace OpenDataLoader with a stub that writes the same files it
does. That keeps the suite credential-free and Java-free while pinning the
contract the rest of the app relies on: text, page-numbered figures with
captions, and a status that never raises.
"""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services import ingestion


def _jpeg(width: int = 40, height: int = 30) -> bytes:
    image = np.full((height, width, 3), 240, dtype=np.uint8)
    cv2.rectangle(image, (4, 4), (width - 4, height - 4), (20, 20, 20), 1)
    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return buffer.tobytes()


def _pdf_fixture(monkeypatch, tmp_path: Path, elements: list[dict]) -> None:
    """Make `ingestion.extract` see an OpenDataLoader run without Java."""

    class FakeOpenDataLoader:
        @staticmethod
        def convert(**kwargs) -> None:
            output = Path(kwargs["output_dir"])
            (output / "input.md").write_text(
                "# Widget\n\nThe guide reduces drift.", encoding="utf-8"
            )
            (output / "input.json").write_text(
                json.dumps({"number of pages": 2, "kids": elements}),
                encoding="utf-8",
            )
            images = output / "input_images"
            images.mkdir(exist_ok=True)
            (images / "imageFile1.jpeg").write_bytes(_jpeg())

    monkeypatch.setattr(ingestion, "opendataloader_pdf", FakeOpenDataLoader)
    monkeypatch.setattr(ingestion.shutil, "which", lambda _name: "java")


def test_pdf_extraction_returns_text_figures_and_captions(monkeypatch, tmp_path):
    _pdf_fixture(
        monkeypatch,
        tmp_path,
        [
            {
                "type": "heading",
                "page number": 2,
                "bounding box": [72.0, 689.5, 102.6, 702.2],
                "content": "FIG. 2",
            },
            {
                "type": "image",
                "page number": 2,
                "bounding box": [72.0, 432.0, 472.0, 672.0],
                "source": "input_images/imageFile1.jpeg",
            },
        ],
    )

    result = ingestion.extract("filing.pdf", b"%PDF-1.4 stub")

    assert result.status == ingestion.READY
    assert result.page_count == 2
    assert "reduces drift" in result.text
    assert len(result.figures) == 1
    figure = result.figures[0]
    assert figure.page == 2
    assert figure.bbox == [72.0, 432.0, 472.0, 672.0]
    assert figure.caption == "FIG. 2"
    assert figure.label == "FIG. 2"
    assert figure.image and figure.image.startswith(b"\xff\xd8")


def test_a_caption_on_another_page_is_not_borrowed(monkeypatch, tmp_path):
    _pdf_fixture(
        monkeypatch,
        tmp_path,
        [
            {
                "type": "heading",
                "page number": 1,
                "bounding box": [72.0, 689.5, 102.6, 702.2],
                "content": "FIG. 1",
            },
            {
                "type": "image",
                "page number": 2,
                "bounding box": [72.0, 432.0, 472.0, 672.0],
                "source": "input_images/imageFile1.jpeg",
            },
        ],
    )

    result = ingestion.extract("filing.pdf", b"%PDF-1.4 stub")

    assert result.figures[0].caption == ""
    assert result.figures[0].label == ""


def test_a_figure_source_cannot_escape_the_temp_directory(monkeypatch, tmp_path):
    _pdf_fixture(
        monkeypatch,
        tmp_path,
        [
            {
                "type": "image",
                "page number": 1,
                "bounding box": [0, 0, 10, 10],
                "source": "../../etc/passwd",
            }
        ],
    )

    result = ingestion.extract("filing.pdf", b"%PDF-1.4 stub")

    assert result.status == ingestion.READY
    assert result.figures[0].image is None


def test_missing_java_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(ingestion.shutil, "which", lambda _name: None)

    result = ingestion.extract("filing.pdf", b"%PDF-1.4 stub")

    assert result.status == ingestion.UNAVAILABLE
    assert "Java" in result.error


def test_unparseable_input_never_raises(monkeypatch):
    class Exploding:
        @staticmethod
        def convert(**_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(ingestion, "opendataloader_pdf", Exploding)
    monkeypatch.setattr(ingestion.shutil, "which", lambda _name: "java")

    result = ingestion.extract("filing.pdf", b"%PDF-1.4 stub")

    assert result.status == ingestion.FAILED
    assert "boom" in result.error


def test_plain_text_and_unsupported_types_are_distinguished():
    text = ingestion.extract("notes.md", "# Heading\n\nSome text.".encode("utf-8"))
    assert text.status == ingestion.READY
    assert text.text.startswith("# Heading")

    legacy = ingestion.extract("old.doc", b"\xd0\xcf\x11\xe0")
    assert legacy.status == ingestion.UNSUPPORTED
    assert ".docx" in legacy.error


def test_docx_extraction_reads_paragraphs_and_tables():
    import io

    from docx import Document

    document = Document()
    document.add_paragraph("The guide comprises a first member.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Part"
    table.rows[0].cells[1].text = "Function"
    buffer = io.BytesIO()
    document.save(buffer)

    result = ingestion.extract("spec.docx", buffer.getvalue())

    assert result.status == ingestion.READY
    assert "first member" in result.text
    assert "Part | Function" in result.text
    assert result.figures[0].kind == "table"


def test_direct_image_upload_becomes_a_figure():
    result = ingestion.extract("sketch.png", _jpeg())

    assert result.status == ingestion.READY
    assert len(result.figures) == 1
    assert result.figures[0].kind == "image"
    assert result.figures[0].image is not None


def test_direct_image_upload_rejects_garbage():
    result = ingestion.extract("sketch.png", b"not an image at all" * 500)

    assert result.status == ingestion.FAILED
