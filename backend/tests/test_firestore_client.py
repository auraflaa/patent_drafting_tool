"""Regression tests for the long-uptime Firestore wedge.

A stale gRPC channel (left behind by a network change) used to sit inside the
SDK's five-minute retry budget. `/health` answered 503 after ~295 s and every
screen behind it stalled, which looked like "the server signed me out". These
tests pin the two properties that fix it: a bounded probe, and a client that is
recycled instead of reused after the transport breaks.
"""
import pytest
from google.api_core import exceptions as api_errors

from app.core import firebase


def test_read_retries_once_on_a_broken_channel(monkeypatch) -> None:
    attempts = {"count": 0}
    recycled: list[tuple] = []

    def operation() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise api_errors.ServiceUnavailable("tcp handshaker shutdown")
        return "ok"

    monkeypatch.setattr(
        firebase, "recycle_db", lambda *args, **kwargs: recycled.append(args)
    )

    assert firebase.firestore_read(operation) == "ok"
    assert attempts["count"] == 2
    assert recycled, "the stale client must be dropped before the retry"


def test_read_reports_a_retryable_outage_after_the_second_failure(
    monkeypatch,
) -> None:
    def operation():
        raise api_errors.ServiceUnavailable("socket is null")

    monkeypatch.setattr(firebase, "recycle_db", lambda *args, **kwargs: None)

    with pytest.raises(firebase.FirestoreUnavailable):
        firebase.firestore_read(operation)


def test_write_is_never_replayed(monkeypatch) -> None:
    """A timed-out write may have committed; replaying could duplicate it."""
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        raise api_errors.DeadlineExceeded("deadline exceeded")

    monkeypatch.setattr(firebase, "recycle_db", lambda *args, **kwargs: None)

    with pytest.raises(firebase.FirestoreUnavailable):
        firebase.firestore_write(operation)
    assert attempts["count"] == 1


def test_security_errors_are_not_mistaken_for_an_outage(monkeypatch) -> None:
    def operation():
        raise api_errors.PermissionDenied("missing or insufficient permissions")

    monkeypatch.setattr(firebase, "recycle_db", lambda *args, **kwargs: None)

    with pytest.raises(api_errors.PermissionDenied):
        firebase.firestore_read(operation)


def test_recycle_forces_the_next_call_to_build_a_new_client(monkeypatch) -> None:
    monkeypatch.setattr(firebase, "_db", "stale-client")
    monkeypatch.setattr(
        firebase,
        "initialize_firebase",
        lambda: setattr(firebase, "_db", "fresh-client"),
    )

    firebase.recycle_db("test")

    assert firebase.db() == "fresh-client"


def test_health_probe_is_bounded_and_unretried(monkeypatch) -> None:
    """`/health` must answer in seconds even when Firestore is wedged."""
    seen: dict = {}

    class Query:
        def limit(self, _count):
            return self

        def get(self, **kwargs):
            seen.update(kwargs)
            return []

    class FakeDb:
        def collection(self, _name):
            return Query()

    monkeypatch.setattr(firebase, "db", lambda: FakeDb())

    firebase.firestore_ping()

    assert seen["retry"] is None
    assert seen["timeout"] <= 5


def test_a_failed_probe_recycles_the_client(monkeypatch) -> None:
    class Query:
        def limit(self, _count):
            return self

        def get(self, **_kwargs):
            raise api_errors.DeadlineExceeded("deadline exceeded")

    class FakeDb:
        def collection(self, _name):
            return Query()

    monkeypatch.setattr(firebase, "db", lambda: FakeDb())
    monkeypatch.setattr(firebase, "_db", "stale-client")

    with pytest.raises(api_errors.DeadlineExceeded):
        firebase.firestore_ping()

    assert firebase._db is None
