"""Small Firestore repository helpers shared by the API routers.

Firestore is the only system of record (ADR-005). Documents keep their
string IDs; callers never assume numeric identifiers. Queries intentionally
avoid composite indexes: equality filters are pushed to Firestore and any
ordering is done in Python, which is fine at the scale this single-instance
app targets (ADR-003).
"""
from datetime import datetime, timezone
from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException
from google.cloud import firestore

from app.core.firebase import db

MAX_QUERY_LIMIT = 1000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(data: dict[str, Any]) -> dict[str, Any]:
    """Drop internal/projection keys before writing a document."""
    return {k: v for k, v in data.items() if not k.startswith("_")}


def get_doc_or_none(collection: str, doc_id: str) -> dict | None:
    snap = db().collection(collection).document(str(doc_id)).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    data["id"] = snap.id
    return data


def get_doc(collection: str, doc_id: str) -> dict:
    data = get_doc_or_none(collection, doc_id)
    if data is None:
        raise HTTPException(404, f'{collection.rstrip("s").capitalize()} not found.')
    return data


def query_docs(
    collection: str,
    *,
    filters: Iterable[tuple[str, str, Any]] | None = None,
    limit: int = MAX_QUERY_LIMIT,
) -> list[dict]:
    """Run equality/array-contains filters and return plain dicts with IDs."""
    query = db().collection(collection)
    for field, op, value in filters or ():
        # Keyword form: the positional overload of where() is deprecated and
        # emits a UserWarning on every query with newer SDKs.
        query = query.where(filter=firestore.FieldFilter(field, op, value))
    out: list[dict] = []
    for snap in query.limit(max(1, min(limit, MAX_QUERY_LIMIT))).stream():
        item = snap.to_dict() or {}
        item["id"] = snap.id
        out.append(item)
    return out


def list_docs(collection: str, *, limit: int = MAX_QUERY_LIMIT) -> list[dict]:
    return query_docs(collection, limit=limit)


def allocate_counter(
    collection: str,
    doc_id: str,
    *,
    field: str = "next_version",
    floor: int = 0,
) -> int:
    """Atomically claim the next integer in a counter document.

    Generation and template upload used read-max-then-write, so two requests
    arriving together could both compute the same version number and one
    would silently overwrite the other's metadata. A Firestore transaction
    serialises the read and the write across workers.
    """

    @firestore.transactional
    def _claim(transaction) -> int:
        ref = db().collection(collection).document(str(doc_id))
        snapshot = ref.get(transaction=transaction)
        stored = 0
        if snapshot.exists:
            stored = int((snapshot.to_dict() or {}).get(field) or 0)
        value = max(stored, floor) + 1
        transaction.set(
            ref,
            {field: value, "updated_at": now_iso()},
            merge=True,
        )
        return value

    return _claim(db().transaction())


def set_latest_version(
    collection: str,
    doc_id: str,
    version_number: int,
    fields: dict,
) -> dict:
    """Point a document at `version_number` only when it is still the newest.

    Concurrent generations can finish out of order. Without this guard the
    slower request would overwrite `stored_path` with an older file after the
    newer one had already completed.
    """

    @firestore.transactional
    def _apply(transaction) -> None:
        ref = db().collection(collection).document(str(doc_id))
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            raise HTTPException(404, "Document not found.")
        current = int((snapshot.to_dict() or {}).get("latest_version") or 0)
        if version_number < current:
            return
        payload = clean({**fields, "latest_version": version_number})
        payload["updated_at"] = now_iso()
        transaction.set(ref, payload, merge=True)

    _apply(db().transaction())
    return get_doc(collection, doc_id)


def create_doc(collection: str, data: dict, doc_id: str | None = None) -> dict:
    ref = (
        db().collection(collection).document(str(doc_id))
        if doc_id
        else db().collection(collection).document()
    )
    payload = clean(data)
    payload.setdefault("created_at", now_iso())
    payload["updated_at"] = now_iso()
    ref.set(payload)
    payload["id"] = ref.id
    return payload


def patch_doc(collection: str, doc_id: str, data: dict) -> dict:
    ref = db().collection(collection).document(str(doc_id))
    if not ref.get().exists:
        raise HTTPException(404, f'{collection.rstrip("s").capitalize()} not found.')
    payload = clean(data)
    payload["updated_at"] = now_iso()
    ref.set(payload, merge=True)
    return get_doc(collection, doc_id)


def delete_doc(collection: str, doc_id: str) -> None:
    ref = db().collection(collection).document(str(doc_id))
    if not ref.get().exists:
        raise HTTPException(404, f'{collection.rstrip("s").capitalize()} not found.')
    ref.delete()


def _sort_key(value: Any) -> tuple[int, float, str]:
    """Map one field value into a totally ordered bucket.

    Firestore can return unlike types for the same field (an old numeric
    timestamp next to a new ISO string), so values are ranked by kind first and
    compared inside their own kind. Ints and floats share a numeric bucket
    instead of sorting as different type names.
    """
    if isinstance(value, bool):
        return (3, float(value), "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    moment: datetime | None = None
    if isinstance(value, datetime):
        moment = value
    elif callable(getattr(value, "timestamp", None)):  # Firestore Timestamp
        try:
            return (1, float(value.timestamp()), "")
        except Exception:
            return (4, 0.0, repr(value))
    if moment is not None:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return (1, moment.timestamp(), "")
    if isinstance(value, str):
        return (2, 0.0, value)
    return (4, 0.0, repr(value))


def sort_docs(
    items: list[dict], field: str, *, reverse: bool = False
) -> list[dict]:
    """Sort in Python so Firestore composite indexes are never required.

    Records without the field always come last, in both directions: reversing a
    "newest first" list must not push undated rows to the top.
    """
    present = [item for item in items if item.get(field) is not None]
    missing = [item for item in items if item.get(field) is None]
    return sorted(
        present, key=lambda item: _sort_key(item.get(field)), reverse=reverse
    ) + missing
