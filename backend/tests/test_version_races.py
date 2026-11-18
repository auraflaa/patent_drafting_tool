"""Concurrency regression tests: version numbers must be unique under races.

Questionnaire submits and draft generations used to derive the next version
from a read list (`max + 1`), so two concurrent requests minted the same
number. Both routes now claim versions through the transactional
`allocate_counter`, and these tests pin that wiring with real threads.
"""
import threading

import pytest

from app.services.projections import (
    QUESTIONNAIRE_FIELDS,
    REQUIRED_QUESTIONNAIRE_FIELDS,
)


class _FakeCounters:
    """Thread-safe stand-in for the transactional allocate_counter."""

    def __init__(self) -> None:
        self._store: dict = {}
        self._lock = threading.Lock()

    def __call__(self, collection, doc_id, *, field="next_version", floor=0):
        with self._lock:
            value = max(self._store.get((collection, doc_id), 0), floor) + 1
            self._store[(collection, doc_id)] = value
            return value


def _full_questionnaire() -> dict:
    return {
        "id": "q1",
        "patent_application_id": "p1",
        "questionnaire_status": "Completed",
        "completion_percentage": "100.00",
        **{field: "filled answer" for field in QUESTIONNAIRE_FIELDS},
    }


def test_concurrent_submits_mint_distinct_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    snapshots: list = []
    lock = threading.Lock()
    monkeypatch.setattr(resources, "allocate_counter", _FakeCounters())
    monkeypatch.setattr(
        resources, "require_patent", lambda *a, **k: {"id": "p1"}
    )
    monkeypatch.setattr(
        resources, "_assert_basic_info_editable", lambda *a, **k: None
    )
    monkeypatch.setattr(
        resources, "_questionnaire", lambda *a, **k: _full_questionnaire()
    )
    monkeypatch.setattr(
        resources, "query_docs", lambda *a, **k: [{"version_number": 1}]
    )

    def _create(collection, data, **kwargs):
        with lock:
            snapshots.append(dict(data))
        return {"id": f"qv-{data['version_number']}", **data}

    monkeypatch.setattr(resources, "create_doc", _create)
    monkeypatch.setattr(resources, "patch_doc", lambda *a, **k: None)
    monkeypatch.setattr(resources, "_set_patent", lambda *a, **k: None)
    monkeypatch.setattr(
        resources, "get_doc", lambda *a, **k: _full_questionnaire()
    )
    monkeypatch.setattr(resources, "log_activity", lambda *a: None)

    user = {"uid": "u1", "role_codes": ["INNOVATOR"]}
    errors: list = []

    def _submit():
        try:
            resources.submit_questionnaire("p1", user)
        except Exception as exc:  # noqa: BLE001 - collected, then re-raised
            errors.append(exc)

    threads = [threading.Thread(target=_submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(snapshots) == 2
    assert len({snap["version_number"] for snap in snapshots}) == 2


def test_concurrent_refines_mint_distinct_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refine path had the same read-max-then-write race as submit/draft."""
    from app.api import resources
    from app.services import form_ai

    created: list = []
    lock = threading.Lock()
    monkeypatch.setattr(resources, "allocate_counter", _FakeCounters())
    monkeypatch.setattr(
        resources,
        "require_patent",
        lambda *a, **k: {
            "id": "p1",
            "application_status": "Under Review",
            "created_by": "u1",
        },
    )
    monkeypatch.setattr(resources, "can_review_draft", lambda *a: True)
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "_questionnaire", lambda *a, **k: _full_questionnaire()
    )
    monkeypatch.setattr(
        resources.form_generation,
        "build_profile",
        lambda *a, **k: {"questionnaire": _full_questionnaire()},
    )
    monkeypatch.setattr(
        resources, "query_docs", lambda *a, **k: []
    )
    monkeypatch.setattr(
        form_ai, "query_docs", lambda collection, filters=None: []
    )
    monkeypatch.setattr(
        form_ai.extraction_store, "query_docs", lambda *a, **k: []
    )
    monkeypatch.setattr(
        form_ai.extraction_store, "figures_for_patent", lambda *a, **k: []
    )

    def _create(collection, data, **kwargs):
        with lock:
            created.append(dict(data))
        return {"id": f"r-{data['version_number']}", **data}

    monkeypatch.setattr(resources, "create_doc", _create)
    monkeypatch.setattr(resources, "refined_group_out", lambda doc: dict(doc))
    monkeypatch.setattr(resources, "log_activity", lambda *a: None)

    user = {"uid": "agent1", "role_codes": ["PATENT_AGENT"]}
    errors: list = []

    def _refine():
        try:
            resources.refine_form_fields(
                "p1", {"groups": ["FORM_METADATA"]}, user
            )
        except Exception as exc:  # noqa: BLE001 - collected, then re-raised
            errors.append(exc)

    threads = [threading.Thread(target=_refine) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(created) == 2
    assert len({doc["version_number"] for doc in created}) == 2


def test_concurrent_draft_generations_mint_distinct_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    created: list = []
    lock = threading.Lock()
    monkeypatch.setattr(resources, "allocate_counter", _FakeCounters())
    monkeypatch.setattr(
        resources,
        "require_patent",
        lambda *a, **k: {
            "id": "p1",
            "application_status": "Under Review",
            "created_by": "u1",
        },
    )
    monkeypatch.setattr(resources, "can_access_drafts", lambda *a: True)
    monkeypatch.setattr(
        resources,
        "_questionnaire",
        lambda *a, **k: {"id": "q1", "questionnaire_status": "Completed"},
    )
    monkeypatch.setattr(resources, "query_docs", lambda *a, **k: [])
    monkeypatch.setattr(resources, "_draft_outputs", lambda *a, **k: [])
    monkeypatch.setattr(
        resources.extraction_store, "load_context", lambda *a, **k: ""
    )

    def _create(collection, data, **kwargs):
        with lock:
            created.append(dict(data))
        return {"id": f"d-{data['version_number']}", **data}

    monkeypatch.setattr(resources, "create_doc", _create)
    monkeypatch.setattr(resources, "_set_patent", lambda *a, **k: None)
    monkeypatch.setattr(resources, "notify_many", lambda *a, **k: None)
    monkeypatch.setattr(resources, "log_activity", lambda *a: None)

    user = {"uid": "agent1", "role_codes": ["PATENT_AGENT"]}
    errors: list = []

    def _generate():
        try:
            resources.generate_draft(
                "p1", {"section_types": ["ABSTRACT"]}, user
            )
        except Exception as exc:  # noqa: BLE001 - collected, then re-raised
            errors.append(exc)

    threads = [threading.Thread(target=_generate) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(created) == 2
    assert len({doc["version_number"] for doc in created}) == 2
