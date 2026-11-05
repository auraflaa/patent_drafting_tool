"""PDF uploads are converted to Word and never stored as PDF."""
from io import BytesIO

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.api import resources
from app.services import documents


def _sample_pdf(text: str = "Self-Regulating Insulated Bottle") -> bytes:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 720), text)
    payload = document.tobytes()
    document.close()
    return payload


def test_pdf_to_docx_returns_a_real_word_document() -> None:
    pytest.importorskip("pdf2docx")
    payload = _sample_pdf()

    converted = documents.pdf_to_docx(payload)

    assert converted.startswith(b"PK")
    from docx import Document

    text = "\n".join(p.text for p in Document(BytesIO(converted)).paragraphs)
    assert "Insulated Bottle" in text


def test_pdf_to_docx_rejects_bytes_that_are_not_a_pdf() -> None:
    with pytest.raises(documents.DocumentGenerationError, match="could not be read"):
        documents.pdf_to_docx(b"not a pdf at all")


def test_prepare_upload_converts_a_pdf_to_word() -> None:
    pytest.importorskip("pdf2docx")
    payload = _sample_pdf("Phase-Change Sleeve")
    upload = UploadFile(filename="drawing.pdf", file=BytesIO(payload))

    prepared = resources._prepare_upload(upload, payload)

    assert prepared.converted_from_pdf is True
    assert prepared.filename == "drawing.docx"
    assert prepared.source_filename == "drawing.pdf"
    assert prepared.mime_type == documents.DOCX_MIME
    assert prepared.content.startswith(b"PK")


def test_prepare_upload_keeps_other_attachments_unchanged() -> None:
    content = b"meeting notes"
    upload = UploadFile(filename="notes.txt", file=BytesIO(content))

    prepared = resources._prepare_upload(upload, content)

    assert prepared.converted_from_pdf is False
    assert prepared.filename == "notes.txt"
    assert prepared.source_filename is None
    assert prepared.mime_type.startswith("text/plain")
    assert prepared.content == content


def test_prepare_upload_reports_a_conversion_failure_as_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_content: bytes) -> bytes:
        raise documents.DocumentGenerationError("The PDF could not be read.")

    monkeypatch.setattr(resources.docgen, "pdf_to_docx", broken)
    content = b"%PDF-1.4 truncated"
    upload = UploadFile(filename="broken.pdf", file=BytesIO(content))

    with pytest.raises(HTTPException) as exc:
        resources._prepare_upload(upload, content)

    assert exc.value.status_code == 400
    assert "could not be read" in str(exc.value.detail)
