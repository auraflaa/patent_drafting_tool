"""Storage-side tests for extraction: the Firestore budget and prompt context."""

from app.services import extraction_store


def test_oversized_text_is_truncated_before_storage(monkeypatch):
    monkeypatch.setattr(extraction_store, "_BLOB_BUDGET", 200)
    source = "".join(f"{index:08x}" for index in range(2_000)) + "TAILMARK"

    text, truncated = extraction_store._fit_text(source)

    assert truncated is True
    assert len(text) < len(source)
    assert "TAILMARK" not in text
    assert len(extraction_store.blobs.compress(text.encode("utf-8"))) <= 200


def _context_fixture(monkeypatch, *, text: bytes = b"guide reduces drift"):
    files = [{"id": "f1", "original_file_name": "spec.pdf"}]
    rows = [
        {
            "file_id": "f1",
            "status": extraction_store.READY,
            "extracted_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "file_id": "f2",
            "status": extraction_store.FAILED,
            "extracted_at": "2026-01-02T00:00:00+00:00",
        },
    ]

    def fake_query(collection, **_kwargs):
        return files if collection == "files" else rows

    monkeypatch.setattr(extraction_store, "query_docs", fake_query)
    monkeypatch.setattr(extraction_store, "read_text", lambda _file_id: text)
    monkeypatch.setattr(
        extraction_store,
        "figures_for_file",
        lambda _file_id: [
            {
                "label": "FIG. 2",
                "caption": "FIG. 2",
                "page": 2,
                "kind": "image",
            }
        ],
    )


def test_context_names_the_file_and_its_figures(monkeypatch):
    _context_fixture(monkeypatch)

    context = extraction_store.load_context("p1", 1_000)

    assert context.startswith("### spec.pdf")
    assert "guide reduces drift" in context
    assert "FIG. 2, page 2" in context


def test_context_skips_failed_extractions_and_respects_the_cap(monkeypatch):
    _context_fixture(monkeypatch, text=b"0123456789" * 10)

    context = extraction_store.load_context("p1", 25)

    assert "### spec.pdf" in context
    assert context.count("0123456789") == 2  # 20 of the 25 characters
    assert "FIG. 2" not in context  # no budget left for the figure line

