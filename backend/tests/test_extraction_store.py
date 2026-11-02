"""Storage-side tests for extraction: the Firestore document budget."""

from app.services import extraction_store


def test_oversized_text_is_truncated_before_storage(monkeypatch):
    monkeypatch.setattr(extraction_store, "_BLOB_BUDGET", 200)
    source = "".join(f"{index:08x}" for index in range(2_000)) + "TAILMARK"

    text, truncated = extraction_store._fit_text(source)

    assert truncated is True
    assert len(text) < len(source)
    assert "TAILMARK" not in text
    assert len(extraction_store.blobs.compress(text.encode("utf-8"))) <= 200
