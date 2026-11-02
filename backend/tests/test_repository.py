"""Tests for the Firestore repository helpers (sorting, querying)."""

from app.services.repository import sort_docs


def test_sort_docs_handles_mixed_types_without_raising():
    """Mixed-type fields must not raise TypeError during sorting."""
    items = [
        {"id": "a", "value": 10},
        {"id": "b", "value": "apple"},
        {"id": "c", "value": None},
        {"id": "d", "value": 2},
        {"id": "e", "value": "banana"},
    ]
    result = sort_docs(items, "value")
    # None should sort last
    assert result[-1]["id"] == "c"
    # No exception raised
    assert len(result) == 5


def test_sort_docs_sorts_ints_numerically():
    items = [
        {"id": "a", "n": 10},
        {"id": "b", "n": 2},
        {"id": "c", "n": 1},
    ]
    result = sort_docs(items, "n")
    assert [d["id"] for d in result] == ["c", "b", "a"]


def test_sort_docs_sorts_strings_lexicographically():
    items = [
        {"id": "a", "s": "banana"},
        {"id": "b", "s": "apple"},
        {"id": "c", "s": "cherry"},
    ]
    result = sort_docs(items, "s")
    assert [d["id"] for d in result] == ["b", "a", "c"]


def test_sort_docs_none_sorts_last():
    items = [
        {"id": "a", "v": None},
        {"id": "b", "v": "apple"},
        {"id": "c", "v": None},
    ]
    result = sort_docs(items, "v")
    assert result[0]["id"] == "b"
    assert result[-1]["id"] in ("a", "c")


def test_sort_docs_reverse():
    items = [
        {"id": "a", "n": 1},
        {"id": "b", "n": 2},
        {"id": "c", "n": 3},
    ]
    result = sort_docs(items, "n", reverse=True)
    assert [d["id"] for d in result] == ["c", "b", "a"]


def test_sort_docs_empty_list():
    assert sort_docs([], "field") == []


def test_sort_docs_missing_field():
    items = [
        {"id": "a"},
        {"id": "b", "field": "value"},
    ]
    result = sort_docs(items, "field")
    assert result[0]["id"] == "b"
    assert result[1]["id"] == "a"


def test_sort_docs_reverse_keeps_missing_values_last():
    """Newest-first lists must not surface undated rows at the top."""
    items = [
        {"id": "a", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "b", "created_at": None},
        {"id": "c", "created_at": "2025-01-01T00:00:00Z"},
        {"id": "d"},
    ]
    result = sort_docs(items, "created_at", reverse=True)
    assert [d["id"] for d in result][:2] == ["c", "a"]
    assert {d["id"] for d in result[2:]} == {"b", "d"}


def test_sort_docs_orders_ints_and_floats_together():
    items = [
        {"id": "a", "n": 10},
        {"id": "b", "n": 2.5},
        {"id": "c", "n": 3},
    ]
    result = sort_docs(items, "n")
    assert [d["id"] for d in result] == ["b", "c", "a"]


def test_sort_docs_orders_datetimes_without_raising_on_naive_values():
    from datetime import datetime, timezone

    items = [
        {"id": "a", "at": datetime(2024, 1, 1, tzinfo=timezone.utc)},
        {"id": "b", "at": datetime(2025, 1, 1)},
    ]
    result = sort_docs(items, "at")
    assert [d["id"] for d in result] == ["a", "b"]


def test_query_docs_uses_keyword_field_filters(monkeypatch):
    """The positional where() overload is deprecated and warns on every call."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    from app.services import repository

    calls: list[tuple[tuple, dict]] = []

    class FakeQuery:
        def where(self, *args, **kwargs):
            calls.append((args, kwargs))
            return self

        def limit(self, _count):
            return self

        def stream(self, **_kwargs):
            return []

    class FakeDb:
        def collection(self, _name):
            return FakeQuery()

    monkeypatch.setattr(repository, "db", FakeDb)

    repository.query_docs(
        "patents",
        filters=[("created_by", "==", "u1"), ("tags", "array_contains", "x")],
    )

    assert len(calls) == 2
    for args, kwargs in calls:
        assert args == ()
        assert isinstance(kwargs["filter"], FieldFilter)