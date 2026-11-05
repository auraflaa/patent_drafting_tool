"""Regression tests for the SECURITY.md hardening pass (PR #1 follow-up).

Covers: Super Admin grant/revoke gating, sandboxed fail-closed DOCX
rendering, unknown-placeholder activation refusal, and control-character
rejection in AI output paths.
"""
from io import BytesIO

import pytest
from fastapi import HTTPException


def _template_bytes(paragraph_text: str) -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph(paragraph_text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _sections():
    from app.services import drafting

    return {section: f"{section} body" for section in drafting.SECTION_TYPES}


# --- Super Admin grant/revoke gating ---------------------------------------


def test_approve_super_admin_requires_super_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import auth

    monkeypatch.setattr(auth, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        auth, "get_doc", lambda *args: {"id": "u2", "account_status": "pending"}
    )
    monkeypatch.setattr(
        auth, "write_doc", lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not write")
        )
    )

    with pytest.raises(HTTPException) as exc:
        auth.approve_user(
            "u2",
            {"role_codes": ["SUPER_ADMIN"]},
            {"uid": "admin", "role_codes": ["ADMIN"]},
        )
    assert exc.value.status_code == 403


def test_approve_super_admin_by_super_admin_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import auth

    writes: list = []
    monkeypatch.setattr(auth, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        auth, "get_doc", lambda *args: {"id": "u2", "account_status": "pending"}
    )
    monkeypatch.setattr(
        auth, "write_doc", lambda _c, _i, data, **_k: writes.append(data)
    )
    monkeypatch.setattr(auth, "log_activity", lambda *args: None)

    auth.approve_user(
        "u2",
        {"role_codes": ["SUPER_ADMIN"]},
        {"uid": "root", "role_codes": ["SUPER_ADMIN"]},
    )
    assert writes and writes[0]["role_codes"] == ["SUPER_ADMIN"]


def test_assign_and_revoke_super_admin_require_super_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources,
        "get_doc",
        lambda *args: {"id": "u2", "role_codes": ["INNOVATOR", "SUPER_ADMIN"]},
    )
    non_sa = {"uid": "admin", "role_codes": ["ADMIN"]}

    with pytest.raises(HTTPException) as exc:
        resources.assign_role("u2", {"role_code": "SUPER_ADMIN"}, non_sa)
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        resources.revoke_role("u2", "SUPER_ADMIN", non_sa)
    assert exc.value.status_code == 403

    # Self-revocation stays a 400, not a 403.
    with pytest.raises(HTTPException) as exc:
        resources.revoke_role(
            "root", "SUPER_ADMIN", {"uid": "root", "role_codes": ["SUPER_ADMIN"]}
        )
    assert exc.value.status_code == 400


# --- Sandboxed, fail-closed template rendering ------------------------------


def test_render_docx_unknown_placeholder_fails_closed() -> None:
    from app.services import documents

    template = _template_bytes("Title: {{ NO_SUCH_PLACEHOLDER }}")
    with pytest.raises(documents.DocumentGenerationError) as exc:
        documents.render_docx({"invention_title": "Widget"}, _sections(), template)
    assert "NO_SUCH_PLACEHOLDER" in str(exc.value) or "unknown" in str(
        exc.value
    ).lower()


def test_render_docx_blocks_template_code_execution() -> None:
    from app.services import documents

    template = _template_bytes("Title: {{ ''.__class__.__mro__ }}")
    with pytest.raises(documents.DocumentGenerationError):
        documents.render_docx({"invention_title": "Widget"}, _sections(), template)


def test_activate_template_refuses_unknown_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources,
        "get_doc",
        lambda *args: {
            "id": "t1",
            "template_parse_error": None,
            "unknown_placeholders": ["NOPE"],
        },
    )
    with pytest.raises(HTTPException) as exc:
        resources.activate_template("t1", {"uid": "admin"})
    assert exc.value.status_code == 400
    assert "NOPE" in exc.value.detail


# --- Control characters in AI output ----------------------------------------


def test_approve_user_cannot_demote_a_super_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Abuse case: an Admin with USERS_APPROVE strips a Super Admin via approve."""
    from app.api import auth

    writes: list = []
    monkeypatch.setattr(auth, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        auth,
        "get_doc",
        lambda *args: {
            "id": "sa1",
            "email": "sa@example.com",
            "full_name": "SA One",
            "account_status": "approved",
            "role_codes": ["SUPER_ADMIN"],
        },
    )
    monkeypatch.setattr(
        auth, "write_doc", lambda *args, **kwargs: writes.append(args)
    )
    monkeypatch.setattr(auth, "log_activity", lambda *args: None)

    with pytest.raises(HTTPException) as exc:
        auth.approve_user(
            "sa1",
            {"role_codes": ["INNOVATOR"]},
            {"uid": "admin", "role_codes": ["ADMIN"]},
        )
    assert exc.value.status_code == 403
    assert writes == []


def test_approve_user_super_admin_may_change_super_admin_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import auth

    monkeypatch.setattr(auth, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        auth,
        "get_doc",
        lambda *args: {
            "id": "sa1",
            "email": "sa@example.com",
            "full_name": "SA One",
            "account_status": "approved",
            "role_codes": ["SUPER_ADMIN"],
        },
    )
    monkeypatch.setattr(auth, "write_doc", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth, "log_activity", lambda *args: None)
    monkeypatch.setattr(
        auth,
        "list_docs",
        lambda *args, **kwargs: [
            {"id": "sa1", "role_codes": ["SUPER_ADMIN"]},
            {"id": "root", "role_codes": ["SUPER_ADMIN"]},
        ],
    )

    auth.approve_user(
        "sa1",
        {"role_codes": ["INNOVATOR"]},
        {"uid": "root", "role_codes": ["SUPER_ADMIN"]},
    )


def test_revoke_last_super_admin_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Abuse case: demoting the only remaining Super Admin locks everyone out."""
    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources,
        "get_doc",
        lambda *args: {"id": "sa1", "role_codes": ["SUPER_ADMIN"]},
    )
    monkeypatch.setattr(
        resources,
        "list_docs",
        lambda *args, **kwargs: [{"id": "sa1", "role_codes": ["SUPER_ADMIN"]}],
    )

    with pytest.raises(HTTPException) as exc:
        resources.revoke_role(
            "sa1", "SUPER_ADMIN", {"uid": "root", "role_codes": ["SUPER_ADMIN"]}
        )
    assert exc.value.status_code == 400


def test_revoke_super_admin_allowed_when_another_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources,
        "get_doc",
        lambda *args: {
            "id": "sa1",
            "email": "sa@example.com",
            "full_name": "SA One",
            "account_status": "approved",
            "role_codes": ["INNOVATOR", "SUPER_ADMIN"],
        },
    )
    monkeypatch.setattr(
        resources,
        "list_docs",
        lambda *args, **kwargs: [
            {"id": "sa1", "role_codes": ["SUPER_ADMIN"]},
            {"id": "sa2", "role_codes": ["SUPER_ADMIN"]},
        ],
    )
    monkeypatch.setattr(resources, "patch_doc", lambda *args, **kwargs: None)
    monkeypatch.setattr(resources, "log_activity", lambda *args: None)

    resources.revoke_role(
        "sa1", "SUPER_ADMIN", {"uid": "root", "role_codes": ["SUPER_ADMIN"]}
    )


def test_generate_section_rejects_control_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import drafting

    monkeypatch.setattr(
        drafting, "_stub_text", lambda *args: "clean start\x00bad end"
    )
    with pytest.raises(drafting.AIGenerationError) as exc:
        drafting.generate_section({"invention_title": "T"}, {}, "ABSTRACT")
    assert "control" in str(exc.value).lower()


def test_validate_group_output_rejects_control_characters() -> None:
    from app.services import form_ai

    payload = {
        "fields": {
            "invention_keyword": "self-cleaning solar array",
            "title_keyword": "SELF-CLEANING SOLAR ARRAY",
            "problem_keyword": "soiling\x07losses",
            "claim_keyword": "cleaning mechanism",
            "data1": "wiper blade",
            "data2": "rail assembly",
            "field": "renewable energy",
            "domain": "photovoltaic systems",
            "area": "panel maintenance",
        },
        "used_figures": [],
    }
    with pytest.raises(form_ai.RefineError) as exc:
        form_ai.validate_group_output("FORM_METADATA", payload, set())
    assert "control" in str(exc.value).lower()


def test_create_team_rejects_overlong_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    created: list = []
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "create_doc", lambda *args, **kwargs: created.append(args)
    )

    with pytest.raises(HTTPException) as exc:
        resources.create_team(
            {"team_name": "T" * 201}, {"uid": "u1", "role_codes": ["ADMIN"]}
        )
    assert exc.value.status_code == 422
    assert created == []


def test_profile_bio_rejects_control_characters_but_allows_newlines() -> None:
    from app.api import auth

    with pytest.raises(HTTPException) as exc:
        auth._profile_patch({"bio": "line one\x00line two"})
    assert exc.value.status_code == 422

    assert auth._profile_patch({"bio": "line one\nline two"}) == {
        "bio": "line one\nline two"
    }


def test_create_comment_rejects_control_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    created: list = []
    monkeypatch.setattr(
        resources, "require_patent", lambda *args, **kwargs: {"id": "p1"}
    )
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "create_doc", lambda *args, **kwargs: created.append(args)
    )

    with pytest.raises(HTTPException) as exc:
        resources.create_comment(
            "p1",
            {"comment_text": "looks good\x01overall"},
            {"uid": "u1", "role_codes": ["INNOVATOR"]},
        )
    assert exc.value.status_code == 400
    assert created == []


def test_generate_forms_rejects_unknown_counts_and_long_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    generated: list = []
    monkeypatch.setattr(
        resources, "require_patent", lambda *args, **kwargs: {"id": "p1"}
    )
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(resources, "_assert_forms_agent", lambda *args: None)
    monkeypatch.setattr(resources, "_assert_generation_allowed", lambda *args: None)
    monkeypatch.setattr(resources, "query_docs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        resources,
        "form_generation",
        type(
            "StubGen",
            (),
            {
                "generate_form_set": staticmethod(
                    lambda *args, **kwargs: generated.append(kwargs)
                )
            },
        )(),
    )

    with pytest.raises(HTTPException) as exc:
        resources.generate_forms(
            "p1",
            {"counts": {"page_count": "9" * 41}},
            {"uid": "u1", "role_codes": ["ADMIN"]},
        )
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        resources.generate_forms(
            "p1",
            {"counts": {"applicant_name": "Mallory"}},
            {"uid": "u1", "role_codes": ["ADMIN"]},
        )
    assert exc.value.status_code == 400
    assert generated == []


def test_reap_stale_jobs_reaps_jobs_without_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    patched: list = []
    monkeypatch.setattr(
        resources,
        "query_docs",
        lambda *args, **kwargs: [
            {"id": "j1", "status": "Processing", "patent_application_id": "p1"}
        ],
    )
    monkeypatch.setattr(
        resources, "patch_doc", lambda *args, **kwargs: patched.append(args)
    )

    resources._reap_stale_jobs("p1")

    assert [call[0] for call in patched] == ["document_jobs"]


def test_list_patents_filters_by_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources,
        "visible_patents",
        lambda user: [
            {"id": "p1", "team_id": "t1", "invention_title": "One"},
            {"id": "p2", "team_id": "t2", "invention_title": "Two"},
        ],
    )
    monkeypatch.setattr(
        resources, "_visible_team", lambda team_id, user: {"id": team_id}
    )
    user = {"uid": "u1", "role_codes": ["INNOVATOR"]}

    mine = resources.list_patents(team_id="t1", limit=1000, user=user)
    assert [doc["id"] for doc in mine] == ["p1"]
    # NOTE: called with explicit values because FastAPI only resolves the
    # Query() defaults inside real requests; direct calls see the default.
    everything = resources.list_patents(team_id=None, limit=None, user=user)
    assert [doc["id"] for doc in everything] == ["p1", "p2"]


def test_list_patents_limit_bounds_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources,
        "visible_patents",
        lambda user: [
            {
                "id": f"p{index}",
                "invention_title": f"T{index}",
                "created_at": f"2026-01-{index + 1:02d}T00:00:00+00:00",
            }
            for index in range(5)
        ],
    )
    user = {"uid": "u1", "role_codes": ["INNOVATOR"]}

    page = resources.list_patents(team_id=None, limit=2, user=user)
    assert [doc["id"] for doc in page] == ["p4", "p3"]  # newest first

    everything = resources.list_patents(team_id=None, limit=1000, user=user)
    assert [doc["id"] for doc in everything] == ["p4", "p3", "p2", "p1", "p0"]


def test_export_report_streams_csv_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The export must stream (bounded memory) with byte-identical output."""
    import asyncio

    from fastapi.responses import StreamingResponse

    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(resources, "_assert_report_access", lambda *args: None)
    monkeypatch.setattr(
        resources, "can_download_report", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        resources,
        "_report_rows",
        lambda *args, **kwargs: [
            {"title": "Normal", "owner": "alice@example.com"},
            {"title": "=cmd|'/c calc'!A0", "owner": "mallory@example.com"},
        ],
    )

    response = resources.export_report(
        "patent_applications", user={"uid": "admin", "role_codes": ["ADMIN"]}
    )

    assert isinstance(response, StreamingResponse)

    async def _collect():
        return b"".join(
            [
                chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
                async for chunk in response.body_iterator
            ]
        )

    body = asyncio.run(_collect()).decode("utf-8")
    assert "Normal" in body
    # Formula cells stay neutralised, exactly as before the streaming change.
    assert "'=cmd" in body


def test_export_route_points_at_export_report() -> None:
    """The streaming refactor must not strand the decorator on the helper."""
    from app.api import resources

    route = next(
        r
        for r in resources.router.routes
        if getattr(r, "path", None) == "/reports/{report_type}/export"
    )
    assert route.endpoint is resources.export_report
