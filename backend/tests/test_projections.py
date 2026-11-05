"""Unit tests for the Firestore -> REST projections."""
import types

from app.services import projections


class _Ref:
    def __init__(self, team_id: str) -> None:
        self.team_id = team_id


class _Members:
    def __init__(self, team_id: str) -> None:
        self.team_id = team_id

    def document(self, _uid: str) -> _Ref:
        return _Ref(self.team_id)


class _Team:
    def __init__(self, team_id: str) -> None:
        self.team_id = team_id

    def collection(self, _name: str) -> _Members:
        return _Members(self.team_id)


class _Teams:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def document(self, team_id: str) -> _Team:
        self.requested.append(team_id)
        return _Team(team_id)


class _FakeDb:
    def __init__(self, member_of: set[str]) -> None:
        self.member_of = member_of
        self.teams = _Teams()
        self.get_all_calls = 0

    def collection(self, _name: str) -> _Teams:
        return self.teams

    def get_all(self, refs, **_kwargs):
        self.get_all_calls += 1
        return [
            types.SimpleNamespace(
                exists=ref.team_id in self.member_of,
                reference=types.SimpleNamespace(
                    parent=types.SimpleNamespace(
                        parent=types.SimpleNamespace(id=ref.team_id)
                    )
                ),
            )
            for ref in refs
        ]


def test_member_team_ids_never_needs_a_collection_group_index(monkeypatch):
    """A collection-group query fails with FAILED_PRECONDITION unless the
    operator creates an index, which silently hid team applications. The
    lookup must work from the team documents alone."""
    fake = _FakeDb(member_of={"team-2"})
    monkeypatch.setattr(projections, "db", lambda: fake)
    monkeypatch.setattr(
        projections,
        "list_docs",
        lambda _collection: [{"id": "team-1"}, {"id": "team-2"}, {"id": "team-3"}],
    )

    assert projections.member_team_ids("user-1") == {"team-2"}
    assert fake.get_all_calls == 1


def test_member_team_ids_is_empty_without_teams(monkeypatch):
    fake = _FakeDb(member_of=set())
    monkeypatch.setattr(projections, "db", lambda: fake)
    monkeypatch.setattr(projections, "list_docs", lambda _collection: [])

    assert projections.member_team_ids("user-1") == set()
    assert fake.get_all_calls == 0


def test_user_out_title_cases_account_status():
    base = {"id": "u1", "email": "a@example.com", "full_name": "A"}
    assert projections.user_out({**base, "account_status": "pending"})[
        "account_status"
    ] == "Pending"
    assert projections.user_out({**base, "account_status": "approved"})[
        "account_status"
    ] == "Approved"
    assert projections.user_out({**base, "account_status": "rejected"})[
        "account_status"
    ] == "Rejected"
    # Unknown or missing states fall back to Pending, never leak raw text.
    assert projections.user_out({**base, "account_status": "weird"})[
        "account_status"
    ] == "Pending"
    assert projections.user_out({"uid": "u9"})["id"] == "u9"


def test_questionnaire_out_covers_every_registry_field():
    from app.services.questionnaire_schema import QUESTIONNAIRE_FIELDS

    doc = {"id": "q1", "questionnaire_status": "Completed",
           "completion_percentage": "nonsense",
           "stray_key": "must not leak"}
    doc.update({key: f"value-{key}" for key in QUESTIONNAIRE_FIELDS})

    payload = projections.questionnaire_out(doc)

    for key in QUESTIONNAIRE_FIELDS:
        assert payload[key] == f"value-{key}"
    assert "stray_key" not in payload
    assert payload["completion_percentage"] == "0.00"
    assert payload["questionnaire_status"] == "Completed"


def test_patent_visible_matrix(monkeypatch):
    patent = {
        "id": "p1",
        "created_by": "owner",
        "assigned_patent_agent_id": "agent",
        "team_id": "t1",
    }
    admin = {"uid": "root", "role_codes": ["SUPER_ADMIN"]}
    assert projections.patent_visible(patent, admin) is True
    assert projections.patent_visible(
        patent, {"uid": "owner", "role_codes": ["INNOVATOR"]}
    ) is True
    assert projections.patent_visible(
        patent, {"uid": "agent", "role_codes": ["PATENT_AGENT"]}
    ) is True
    monkeypatch.setattr(
        projections, "user_team_ids", lambda user: {"t1"}
    )
    assert projections.patent_visible(
        patent, {"uid": "mate", "role_codes": ["INNOVATOR"]}
    ) is True
    monkeypatch.setattr(projections, "user_team_ids", lambda user: set())
    assert projections.patent_visible(
        patent, {"uid": "stranger", "role_codes": ["INNOVATOR"]}
    ) is False


def test_require_patent_enforces_visibility(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(projections, "get_doc_or_none", lambda *args: None)
    with pytest.raises(HTTPException) as exc:
        projections.require_patent("missing", {"uid": "u1", "role_codes": []})
    assert exc.value.status_code == 404

    patent = {"id": "p1", "created_by": "owner", "team_id": "t1"}
    monkeypatch.setattr(projections, "get_doc_or_none", lambda *args: patent)
    monkeypatch.setattr(projections, "user_team_ids", lambda user: set())
    with pytest.raises(HTTPException) as exc:
        projections.require_patent(
            "p1", {"uid": "stranger", "role_codes": ["INNOVATOR"]}
        )
    assert exc.value.status_code == 403

    assert projections.require_patent(
        "p1", {"uid": "owner", "role_codes": ["INNOVATOR"]}
    ) == patent


def test_patent_out_exposes_a_fixed_key_set():
    doc = {"id": "p1", "team_id": "t1", "invention_title": "X",
           "internal_note": "must not leak"}
    payload = projections.patent_out(doc)
    assert set(payload) == {
        "id", "team_id", "invention_title", "application_status",
        "assigned_patent_agent_id", "ai_status", "questionnaire_status",
        "document_status", "filing_status", "official_application_number",
        "filing_date", "created_by", "created_at", "updated_at",
    }
    assert payload["application_status"] == "Draft"
