"""Lifecycle regression tests: recalling submissions, innovator drafts."""
import threading

import pytest
from fastapi import HTTPException


def _stub_common(monkeypatch, patent, questionnaire):
    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(resources, "require_patent", lambda *args, **kwargs: patent)
    monkeypatch.setattr(
        resources, "_questionnaire", lambda *args, **kwargs: questionnaire
    )
    return resources


def test_creator_recalls_submitted_patent_to_draft(monkeypatch) -> None:
    from app.api import resources

    patent = {
        "id": "p1",
        "application_status": "Submitted",
        "created_by": "u1",
        "assigned_patent_agent_id": None,
    }
    questionnaire = {
        "id": "q1",
        "questionnaire_status": "Completed",
        "problem_statement": "kept",
    }
    _stub_common(monkeypatch, patent, questionnaire)
    sets: list = []
    patches: list = []
    audits: list = []

    def fake_set(pid, fields):
        sets.append((pid, fields))
        return {**patent, **fields}

    monkeypatch.setattr(resources, "_set_patent", fake_set)
    monkeypatch.setattr(
        resources, "patch_doc", lambda *args: patches.append(args)
    )
    monkeypatch.setattr(resources, "log_activity", lambda *args: audits.append(args))
    user = {"uid": "u1", "role_codes": ["INNOVATOR"]}

    out = resources.recall_patent("p1", user)

    assert sets == [("p1", {"application_status": "Draft"})]
    assert ("questionnaires", "q1") == (patches[0][0], patches[0][1])
    assert patches[0][2]["questionnaire_status"] == "In Progress"
    assert ("u1", "PatentRecalled", "PatentApplication", "p1") in audits
    assert out["application_status"] == "Draft"


def test_recall_requires_owner_or_admin(monkeypatch) -> None:
    from app.api import resources

    patent = {
        "id": "p1",
        "application_status": "Submitted",
        "created_by": "owner",
        "assigned_patent_agent_id": None,
    }
    _stub_common(
        monkeypatch, patent, {"id": "q1", "questionnaire_status": "Completed"}
    )
    with pytest.raises(HTTPException) as exc:
        resources.recall_patent("p1", {"uid": "stranger", "role_codes": ["INNOVATOR"]})
    assert exc.value.status_code == 403


def test_recall_refuses_non_submitted_and_assigned(monkeypatch) -> None:
    from app.api import resources

    base = {"id": "p1", "created_by": "u1", "assigned_patent_agent_id": None}
    q = {"id": "q1", "questionnaire_status": "Completed"}
    _stub_common(monkeypatch, {**base, "application_status": "Under Review"}, q)
    with pytest.raises(HTTPException) as exc:
        resources.recall_patent("p1", {"uid": "u1", "role_codes": ["INNOVATOR"]})
    assert exc.value.status_code == 400

    _stub_common(
        monkeypatch,
        {**base, "application_status": "Submitted", "assigned_patent_agent_id": "a9"},
        q,
    )
    with pytest.raises(HTTPException) as exc:
        resources.recall_patent("p1", {"uid": "u1", "role_codes": ["INNOVATOR"]})
    assert exc.value.status_code == 400


def test_innovator_role_holds_draft_permissions() -> None:
    from app.services.rbac import DEFAULT_GRANTS, permission_codes

    assert {10, 11} <= set(DEFAULT_GRANTS[4])
    assert "DRAFTS_GENERATE" in permission_codes({"role_codes": ["INNOVATOR"]})


def test_creator_generates_draft_while_in_draft(monkeypatch) -> None:
    from app.api import resources
    from app.services import drafting

    patent = {
        "id": "p1",
        "application_status": "Draft",
        "created_by": "u1",
        "assigned_patent_agent_id": None,
    }
    questionnaire = {"id": "q1", "questionnaire_status": "Completed"}
    _stub_common(monkeypatch, patent, questionnaire)
    created: list = []
    lock = threading.Lock()
    monkeypatch.setattr(resources, "query_docs", lambda *a, **k: [])
    monkeypatch.setattr(resources, "_draft_outputs", lambda *a, **k: [])
    monkeypatch.setattr(
        resources.extraction_store, "load_context", lambda *a, **k: ""
    )
    monkeypatch.setattr(
        drafting, "_stub_text", lambda *args: "A draft body."
    )
    monkeypatch.setattr(resources, "allocate_counter", lambda *a, **k: 1)

    def _create(collection, data, **kwargs):
        with lock:
            created.append(dict(data))
        return {"id": "d-new", **data}

    monkeypatch.setattr(resources, "create_doc", _create)
    monkeypatch.setattr(resources, "_set_patent", lambda *a, **k: None)
    monkeypatch.setattr(resources, "notify_many", lambda *a, **k: None)
    monkeypatch.setattr(resources, "log_activity", lambda *a: None)

    out = resources.generate_draft(
        "p1", {"section_types": ["ABSTRACT"]}, {"uid": "u1", "role_codes": ["INNOVATOR"]}
    )

    assert len(created) == 1
    assert created[0]["ai_response"] == "A draft body."
    assert out[0]["section_type"] == "ABSTRACT"


def test_non_creator_innovator_cannot_generate(monkeypatch) -> None:
    from app.api import resources

    patent = {
        "id": "p1",
        "application_status": "Draft",
        "created_by": "owner",
        "assigned_patent_agent_id": None,
    }
    _stub_common(
        monkeypatch,
        patent,
        {"id": "q1", "questionnaire_status": "Completed"},
    )
    with pytest.raises(HTTPException) as exc:
        resources.generate_draft(
            "p1",
            {"section_types": ["ABSTRACT"]},
            {"uid": "stranger", "role_codes": ["INNOVATOR"]},
        )
    assert exc.value.status_code == 403


def test_generate_refuses_filed_applications(monkeypatch) -> None:
    from app.api import resources

    patent = {
        "id": "p1",
        "application_status": "Filed",
        "created_by": "u1",
        "assigned_patent_agent_id": None,
    }
    _stub_common(
        monkeypatch,
        patent,
        {"id": "q1", "questionnaire_status": "Completed"},
    )
    with pytest.raises(HTTPException) as exc:
        resources.generate_draft(
            "p1", {"section_types": ["ABSTRACT"]}, {"uid": "u1", "role_codes": ["INNOVATOR"]}
        )
    assert exc.value.status_code == 400
