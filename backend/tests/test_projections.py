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
