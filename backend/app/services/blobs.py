"""Compressed document bytes stored in Firestore.

Firestore is the only system of record (ADR-005), so uploaded attachments,
templates, and generated Word documents live in the same database as their
metadata. Each file is gzip-compressed and written as one document in the
`blobs` collection; the owning row (`files`, `templates`, `documents`,
`document_versions`) keeps the blob id, never the bytes.

Firestore caps a document at 1 MiB (1 048 576 bytes). The compressed payload
is capped well below that so the metadata fields and field names still fit,
and larger files are rejected with a clear `BlobTooLarge` instead of a
provider error that the UI cannot explain.

The browser never reads this collection directly: `firestore.rules` denies
all client access and every download goes through an authorised API route.
"""
from __future__ import annotations

import gzip
import hashlib
import logging

from app.core.firebase import FirebaseNotConfigured
from app.services.repository import create_doc, delete_doc, get_doc_or_none

logger = logging.getLogger(__name__)

COLLECTION = "blobs"
ENCODING = "gzip"
# 900 KB leaves ~148 KB of the 1 MiB document budget for field names, the
# content type, hashes, and Firestore's own encoding overhead.
MAX_STORED_BYTES = 900_000
COMPRESSION_LEVEL = 6


class BlobError(RuntimeError):
    """A Firestore blob operation failed; the message is safe to show."""


class BlobTooLarge(BlobError):
    """The compressed file does not fit in one Firestore document."""

    def __init__(self, original_bytes: int, stored_bytes: int) -> None:
        self.original_bytes = original_bytes
        self.stored_bytes = stored_bytes
        super().__init__(
            "This file is too large to store. It needs "
            f"{_kilobytes(stored_bytes)} KB after compression, and Firestore "
            f"keeps at most {_kilobytes(MAX_STORED_BYTES)} KB per file. "
            "Upload a smaller file or split it into parts."
        )


class BlobNotFound(BlobError):
    """No stored file exists for that id."""


def _kilobytes(size: int) -> int:
    return max(1, round(size / 1000))


def compress(data: bytes) -> bytes:
    """Gzip a payload deterministically (mtime=0 keeps hashes stable)."""
    return gzip.compress(data, compresslevel=COMPRESSION_LEVEL, mtime=0)


def decompress(data: bytes) -> bytes:
    return gzip.decompress(data)


def put_blob(
    data: bytes,
    content_type: str | None = None,
    *,
    blob_id: str | None = None,
) -> dict:
    """Compress and store `data`, returning the blob metadata row."""
    if not data:
        raise BlobError("The file is empty.")
    compressed = compress(data)
    if len(compressed) > MAX_STORED_BYTES:
        raise BlobTooLarge(len(data), len(compressed))
    record = {
        "data": compressed,
        "encoding": ENCODING,
        "content_type": content_type or "application/octet-stream",
        "size_bytes": len(data),
        "stored_bytes": len(compressed),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    try:
        return create_doc(COLLECTION, record, doc_id=blob_id)
    except FirebaseNotConfigured as exc:
        raise BlobError(
            "Firestore is not configured, so files cannot be stored."
        ) from exc
    except Exception as exc:
        raise BlobError(f"Could not write the file to Firestore: {exc}") from exc


def read_blob(blob_id: str | None) -> bytes:
    """Read and decompress one stored file, verifying its SHA-256."""
    if not blob_id:
        raise BlobNotFound("No stored file is available.")
    try:
        record = get_doc_or_none(COLLECTION, str(blob_id))
    except FirebaseNotConfigured as exc:
        raise BlobError(
            "Firestore is not configured, so files cannot be read."
        ) from exc
    except Exception as exc:
        raise BlobError(f"Could not read the file from Firestore: {exc}") from exc
    if record is None:
        raise BlobNotFound("No stored file is available.")
    payload = record.get("data")
    if not isinstance(payload, (bytes, bytearray)):
        raise BlobError("The stored file has an unexpected format.")
    if record.get("encoding") != ENCODING:
        raise BlobError("The stored file uses an unsupported encoding.")
    try:
        content = decompress(bytes(payload))
    except OSError as exc:
        raise BlobError("The stored file is damaged and cannot be read.") from exc
    expected = record.get("sha256")
    if expected and hashlib.sha256(content).hexdigest() != expected:
        raise BlobError("The stored file failed its integrity check.")
    return content


def delete_blob(blob_id: str | None) -> None:
    """Best-effort delete: a missing or unreadable blob must not block cleanup."""
    if not blob_id:
        return
    try:
        delete_doc(COLLECTION, str(blob_id))
    except Exception as exc:  # noqa: BLE001 - cleanup is deliberately best effort
        logger.warning(
            "blob_delete_failed", extra={"event": "blob_delete_failed"}, exc_info=exc
        )
