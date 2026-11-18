"""Firestore blob storage: compression, the document-size cap, and integrity."""
import os

import pytest

from app.services import blobs


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict:
    """An in-memory stand-in for the `blobs` collection."""
    records: dict[str, dict] = {}

    def fake_create(collection: str, data: dict, doc_id: str | None = None) -> dict:
        assert collection == blobs.COLLECTION
        blob_id = doc_id or f"blob-{len(records) + 1}"
        row = {**data, "id": blob_id}
        records[blob_id] = row
        return row

    def fake_get(collection: str, doc_id: str) -> dict | None:
        assert collection == blobs.COLLECTION
        return records.get(doc_id)

    def fake_delete(collection: str, doc_id: str) -> None:
        del records[doc_id]

    monkeypatch.setattr(blobs, "create_doc", fake_create)
    monkeypatch.setattr(blobs, "get_doc_or_none", fake_get)
    monkeypatch.setattr(blobs, "delete_doc", fake_delete)
    return records


def test_blob_round_trip_compresses_and_verifies(store: dict) -> None:
    payload = b"patent draft text " * 500
    meta = blobs.put_blob(payload, "text/plain")

    assert meta["id"] in store
    stored = store[meta["id"]]
    assert stored["encoding"] == "gzip"
    assert stored["data"][:2] == b"\x1f\x8b"
    assert stored["stored_bytes"] < stored["size_bytes"]
    assert blobs.read_blob(meta["id"]) == payload


def test_blob_rejects_a_payload_that_cannot_fit(store: dict) -> None:
    # Random bytes do not compress, so this reliably exceeds the cap.
    oversized = os.urandom(blobs.MAX_STORED_BYTES + 2_000)
    with pytest.raises(blobs.BlobTooLarge) as exc:
        blobs.put_blob(oversized, "application/octet-stream")

    assert "too large" in str(exc.value).lower()
    assert store == {}


def test_blob_detects_corruption(store: dict) -> None:
    meta = blobs.put_blob(b"hello" * 100, "text/plain")
    store[meta["id"]]["sha256"] = "0" * 64

    with pytest.raises(blobs.BlobError, match="integrity"):
        blobs.read_blob(meta["id"])


def test_missing_blob_raises_not_found(store: dict) -> None:
    with pytest.raises(blobs.BlobNotFound):
        blobs.read_blob("does-not-exist")
    with pytest.raises(blobs.BlobNotFound):
        blobs.read_blob(None)


def test_delete_blob_is_best_effort(store: dict) -> None:
    meta = blobs.put_blob(b"data", "text/plain")
    blobs.delete_blob(meta["id"])
    assert meta["id"] not in store
    # A missing id must never block the metadata cleanup that follows.
    blobs.delete_blob("missing")
    blobs.delete_blob(None)
