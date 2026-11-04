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
