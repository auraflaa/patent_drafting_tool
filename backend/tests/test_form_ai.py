"""Tests for AI field refinement: validation, stub fallback, and endpoints."""
import json

import pytest

from app.api import resources
from app.services import extraction_store, form_ai


def _raw():
    return {
        "invention_keyword": "self-cleaning solar array",
        "title_keyword": "SELF-CLEANING SOLAR ARRAY",
        "problem_keyword": "soiling losses",
        "claim_keyword": "cleaning mechanism",
        "data1": "wiper blade",
        "data2": "rail assembly",
        "field": "renewable energy",
        "domain": "photovoltaic systems",
        "area": "panel maintenance",
    }


def test_validate_accepts_a_well_formed_group():
    payload = {
        "fields": _raw(),
        "used_figures": [],
    }

    fields, used = form_ai.validate_group_output("FORM_METADATA", payload, set())

    assert fields["invention_keyword"] == "self-cleaning solar array"
    assert used == []


def test_validate_rejects_wrong_keys_lengths_and_slogans():
    with pytest.raises(form_ai.RefineError):
        form_ai.validate_group_output(
            "FORM_METADATA", {"fields": {"nope": "x"}, "used_figures": []}, set()
        )
    with pytest.raises(form_ai.RefineError):
        form_ai.validate_group_output(
            "FORM_METADATA",
            {"fields": {**_raw(), "invention_keyword": "x" * 201}, "used_figures": []},
            set(),
        )
    with pytest.raises(form_ai.RefineError):
        form_ai.validate_group_output(
            "FORM_METADATA",
            {"fields": {**_raw(), "invention_keyword": "This invention is great."}, "used_figures": []},
            set(),
        )


def test_validate_markers_only_in_embodiments():
    fields = {
        "exemplary_scenario": "Morning.\n\n[[FIG:fig-1]]",
        "detailed_exemplary_scenario": "Details.",
        "best_working_method": "Mount it.",
    }
    cleaned, used = form_ai.validate_group_output(
        "FORM_EMBODIMENTS",
        {"fields": fields, "used_figures": ["fig-1"]},
        {"fig-1"},
    )
    assert used == ["fig-1"]

    with pytest.raises(form_ai.RefineError):
        form_ai.validate_group_output(
            "FORM_EMBODIMENTS",
            {"fields": {**fields, "used_figures": None}, "used_figures": ["fig-9"]},
            {"fig-1"},
        )
    with pytest.raises(form_ai.RefineError):
        form_ai.validate_group_output(
            "FORM_METADATA",
            {"fields": {**_raw(), "field": "See [[FIG:fig-1]]"}, "used_figures": []},
            {"fig-1"},
        )


def test_refine_group_uses_the_stub_without_a_provider(monkeypatch):
    monkeypatch.setattr(form_ai.settings, "ai_api_url", "")
    monkeypatch.setattr(form_ai.settings, "ai_api_key", "")
    monkeypatch.setattr(form_ai.settings, "ai_model", "")

    result = form_ai.refine_group("p1", {}, "FORM_METADATA", raw_values=_raw())

    assert result["provider"] == "stub"
    assert result["fields"]["invention_keyword"] == "self-cleaning solar array"
    assert result["warnings"]


def test_refine_group_falls_back_on_invalid_model_output(monkeypatch):
    monkeypatch.setattr(form_ai.settings, "ai_api_url", "https://example.test/v1")
    monkeypatch.setattr(form_ai.settings, "ai_api_key", "key")
    monkeypatch.setattr(form_ai.settings, "ai_model", "model")
    monkeypatch.setattr(
        form_ai, "_post_messages", lambda messages, max_tokens: {"choices": []}
    )

    result = form_ai.refine_group("p1", {}, "FORM_METADATA", raw_values=_raw())

    assert result["origin"]["invention_keyword"] == "fallback"
    assert result["fields"]["invention_keyword"] == "self-cleaning solar array"
    assert result["warnings"]


def test_refine_group_repairs_once_then_accepts(monkeypatch):
    monkeypatch.setattr(form_ai.settings, "ai_api_url", "https://example.test/v1")
    monkeypatch.setattr(form_ai.settings, "ai_api_key", "key")
    monkeypatch.setattr(form_ai.settings, "ai_model", "model")
    calls = {"n": 0}

    def fake_post(messages, max_tokens):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"choices": [{"message": {"content": "not json"}}]}
        return {
            "choices": [
                {"message": {"content": json.dumps({"fields": _raw(), "used_figures": []})}}
            ]
        }

    monkeypatch.setattr(form_ai, "_post_messages", fake_post)

    result = form_ai.refine_group("p1", {}, "FORM_METADATA", raw_values=_raw())

    assert calls["n"] == 2
    assert result["origin"]["invention_keyword"] == "ai"


def _route_stubs(monkeypatch, **overrides):
    patent = {
        "id": "p1",
        "application_status": "Under Review",
        "assigned_patent_agent_id": "u1",
    }
    monkeypatch.setattr(resources, "require_patent", lambda *args: patent)
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "can_review_draft", lambda patent, user: True
    )
    monkeypatch.setattr(
        resources,
        "_questionnaire",
        lambda patent_id: {"id": "q1", "questionnaire_status": "Completed"},
    )
    created = []

    def fake_create(collection, data, doc_id=None):
        record = {"id": doc_id or f"{collection}-{len(created)}", **data}
        created.append(record)
        return record

    monkeypatch.setattr(resources, "create_doc", fake_create)
    monkeypatch.setattr(
        resources,
        "query_docs",
        lambda collection, filters=None: overrides.get(collection, []),
    )
    monkeypatch.setattr(resources, "log_activity", lambda *args: None)
    return created


def test_refine_route_stores_one_row_per_group(monkeypatch):
    _route_stubs(monkeypatch)
    monkeypatch.setattr(
        resources.form_generation,
        "build_profile",
        lambda patent_id, counts=None: {"questionnaire": {}},
    )
    monkeypatch.setattr(
        resources.form_ai,
        "refine_group",
        lambda patent_id, profile, group, raw_values=None, _cache=None: {
            "fields": {key: None for key in resources.form_ai.AI_GROUPS[group]},
            "origin": {},
            "figure_refs": {},
            "used_figures": [],
            "provider": "stub",
            "model": "stub",
            "warnings": [],
        },
    )

    out = resources.refine_form_fields("p1", {"groups": ["FORM_METADATA"]}, {"uid": "u1"})

    assert len(out) == 1
    assert out[0]["group"] == "FORM_METADATA"
    assert out[0]["version_number"] == 1


def test_update_form_fields_creates_a_user_version(monkeypatch):
    base = {
        "id": "d1",
        "section_type": "FORM_METADATA",
        "version_number": 1,
        "fields": {"invention_keyword": "old"},
        "origin": {"invention_keyword": "ai"},
    }
    _route_stubs(monkeypatch, drafts=[base])

    out = resources.update_form_fields(
        "p1",
        {"group": "FORM_METADATA", "fields": {"invention_keyword": "new"}},
        {"uid": "u1"},
    )

    assert out["version_number"] == 2
    assert out["fields"]["invention_keyword"] == "new"
    assert out["origin"]["invention_keyword"] == "user"


def test_update_form_fields_rejects_unknown_keys(monkeypatch):
    from fastapi import HTTPException

    _route_stubs(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        resources.update_form_fields(
            "p1", {"group": "FORM_METADATA", "fields": {"nope": "x"}}, {"uid": "u1"}
        )
    assert exc.value.status_code == 422


def _vision_flags(monkeypatch):
    monkeypatch.setattr(form_ai.settings, "ai_vision_enabled", True)
    monkeypatch.setattr(form_ai.settings, "ai_api_url", "https://example.test/v1")
    monkeypatch.setattr(form_ai.settings, "ai_api_key", "key")
    monkeypatch.setattr(form_ai.settings, "ai_model", "model")
    monkeypatch.setattr(form_ai, "_VISION_DISABLED", False)


def test_classify_figures_updates_rows(monkeypatch):
    _vision_flags(monkeypatch)
    rows = [
        {
            "id": "g1",
            "usable": "rejected",
            "reason": "too small",
            "has_image": True,
            "image_blob_id": "b1",
        },
        {
            "id": "g2",
            "usable": "usable",
            "reason": "",
            "has_image": True,
            "image_blob_id": "b2",
        },
    ]
    patched = {}
    monkeypatch.setattr(
        form_ai.extraction_store, "figures_for_patent", lambda patent_id: rows
    )
    monkeypatch.setattr(
        form_ai.extraction_store, "read_figure_image", lambda row: b"\xff\xd8fake"
    )
    monkeypatch.setattr(
        form_ai, "_downscale", lambda image, edge: image
    )
    monkeypatch.setattr(
        form_ai,
        "_post_messages",
        lambda messages, max_tokens: {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"figures": ['
                            '{"id": "g1", "usable": true, "kind": "sketch", '
                            '"confidence": 0.9, "caption": "FIG. 1", '
                            '"description": "A wiper.", "placement": "drawings", '
                            '"reason": "clear drawing"}, '
                            '{"id": "g2", "usable": true, "kind": "diagram", '
                            '"confidence": 0.7, "caption": "FIG. 2", '
                            '"description": "A rail.", "placement": "drawings", '
                            '"reason": "clear"}]}'
                        )
                    }
                }
            ]
        },
    )
    monkeypatch.setattr(
        "app.services.repository.patch_doc",
        lambda collection, doc_id, data: patched.setdefault(doc_id, data),
    )

    result = form_ai.classify_figures("p1")

    assert result["classified"] == 2
    assert patched["g1"]["usable"] == "usable"
    assert "vision approved" in patched["g1"]["reason"]
    assert "usable" not in patched["g2"]
    assert patched["g2"]["vision_description"] == "A rail."
    assert patched["g2"]["kind"] == "diagram"


def test_classify_figures_is_inert_without_vision(monkeypatch):
    monkeypatch.setattr(form_ai.settings, "ai_vision_enabled", False)

    assert form_ai.classify_figures("p1")["classified"] == 0


def test_refine_group_falls_back_to_text_when_vision_refused(monkeypatch):
    _vision_flags(monkeypatch)
    calls = {"n": 0}

    monkeypatch.setattr(
        form_ai,
        "select_context",
        lambda patent_id, query, max_chars, _cache=None: (
            "",
            [
                {
                    "alias": "fig-1",
                    "id": "g1",
                    "label": "FIG. 1",
                    "caption": "Wiper",
                    "page": 1,
                    "source": "spec.pdf",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        form_ai.extraction_store, "read_figure_image", lambda row: b"\xff\xd8fake"
    )
    monkeypatch.setattr(form_ai, "_downscale", lambda image, edge: image)

    def fake_post(messages, max_tokens):
        calls["n"] += 1
        if calls["n"] == 1:
            raise form_ai._VisionRejected("image content not supported")
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"fields": {"exemplary_scenario": "A scenario.", '
                            '"detailed_exemplary_scenario": "Details.", '
                            '"best_working_method": "Mount it."}, '
                            '"used_figures": []}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(form_ai, "_post_messages", fake_post)

    result = form_ai.refine_group(
        "p1",
        {},
        "FORM_EMBODIMENTS",
        raw_values={
            "exemplary_scenario": "A scenario.",
            "detailed_exemplary_scenario": "Details.",
            "best_working_method": "Mount it.",
        },
    )

    assert calls["n"] == 2
    assert result["fields"]["exemplary_scenario"] == "A scenario."
    assert any("text only" in warning for warning in result["warnings"])
    assert form_ai._VISION_DISABLED is True


def test_select_context_ranks_and_budgets(monkeypatch):
    monkeypatch.setattr(
        "app.services.form_ai.query_docs",
        lambda collection, filters=None: (
            [{"id": "f1", "original_file_name": "spec.pdf"}]
            if collection == "files"
            else []
        ),
    )
    text = (
        "Unrelated filler paragraph about office supplies and weather.\n\n"
        "The wiper blade travels along the rail assembly to clean the panel.\n\n"
        "Another filler paragraph about lunch menus and parking."
    )
    monkeypatch.setattr(
        "app.services.form_ai.query_docs",
        lambda collection, filters=None: (
            [{"id": "f1", "original_file_name": "spec.pdf"}]
            if collection == "files"
            else []
        ),
    )
    monkeypatch.setattr(
        form_ai.extraction_store,
        "query_docs",
        lambda collection, filters=None: [
            {
                "file_id": "f1",
                "status": extraction_store.READY,
                "extracted_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(
        form_ai.extraction_store,
        "read_text",
        lambda file_id: text.encode("utf-8"),
    )
    monkeypatch.setattr(
        form_ai.extraction_store,
        "read_text",
        lambda file_id: text.encode("utf-8"),
    )
    monkeypatch.setattr(
        form_ai.extraction_store,
        "figures_for_patent",
        lambda patent_id: [
            {
                "id": "fig1",
                "label": "FIG. 1",
                "caption": "Wiper",
                "page": 2,
                "source": "spec.pdf",
                "usable": "usable",
                "include_in_drawings": True,
                "has_image": True,
            }
        ],
    )

    excerpts, figures = form_ai.select_context("p1", "wiper blade rail panel", 200)

    assert "wiper blade" in excerpts
    assert "lunch menus" not in excerpts
    assert len(excerpts) <= 200
    assert figures[0]["alias"] == "fig-1"


def test_classify_route_calls_the_service(monkeypatch):
    monkeypatch.setattr(resources, "require_patent", lambda *args: {"id": "p1"})
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(resources, "can_review_draft", lambda patent, user: True)
    monkeypatch.setattr(
        resources.form_ai, "classify_figures", lambda patent_id: {"classified": 3}
    )

    assert resources.classify_figures("p1", {"uid": "u1"}) == {"classified": 3}


def test_repair_retry_sends_text_only(monkeypatch):
    _vision_flags(monkeypatch)
    sent = []

    monkeypatch.setattr(
        form_ai,
        "select_context",
        lambda patent_id, query, max_chars, _cache=None: (
            "",
            [
                {
                    "alias": "fig-1",
                    "id": "g1",
                    "label": "FIG. 1",
                    "caption": "Wiper",
                    "page": 1,
                    "source": "spec.pdf",
                    "image_blob_id": "b1",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        form_ai.extraction_store, "read_figure_image", lambda row: b"\xff\xd8fake"
    )
    monkeypatch.setattr(form_ai, "_downscale", lambda image, edge: image)

    def fake_post(messages, max_tokens):
        sent.append(messages)
        if len(sent) == 1:
            assert any(
                isinstance(block, dict) and block.get("type") == "image_url"
                for message in messages
                if isinstance(message, dict)
                for block in (
                    message["content"]
                    if isinstance(message.get("content"), list)
                    else []
                )
            ), "first attempt must include the figure image"
            return {"choices": [{"message": {"content": "not json"}}]}
        for message in messages:
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                assert not any(
                    isinstance(block, dict) and block.get("type") == "image_url"
                    for block in content
                ), "repair retry must be text-only"
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"fields": {"exemplary_scenario": "A scenario.", '
                            '"detailed_exemplary_scenario": "Details.", '
                            '"best_working_method": "Mount it."}, '
                            '"used_figures": []}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(form_ai, "_post_messages", fake_post)

    result = form_ai.refine_group(
        "p1",
        {},
        "FORM_EMBODIMENTS",
        raw_values={
            "exemplary_scenario": "A scenario.",
            "detailed_exemplary_scenario": "Details.",
            "best_working_method": "Mount it.",
        },
    )

    assert len(sent) == 2
    assert result["fields"]["exemplary_scenario"] == "A scenario."


def test_classify_skips_user_reviewed_rows(monkeypatch):
    _vision_flags(monkeypatch)
    rows = [
        {
            "id": "g1",
            "usable": "rejected",
            "reason": "too small",
            "reviewed_by_user": True,
            "has_image": True,
            "image_blob_id": "b1",
        },
    ]
    patched = {}
    monkeypatch.setattr(
        form_ai.extraction_store, "figures_for_patent", lambda patent_id: rows
    )
    monkeypatch.setattr(
        form_ai.extraction_store, "read_figure_image", lambda row: b"\xff\xd8fake"
    )
    monkeypatch.setattr(form_ai, "_downscale", lambda image, edge: image)
    monkeypatch.setattr(
        form_ai,
        "_post_messages",
        lambda messages, max_tokens: {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"figures": [{"id": "g1", "usable": true, '
                            '"kind": "sketch", "confidence": 0.99, '
                            '"caption": "FIG. 1", "description": "A wiper.", '
                            '"placement": "drawings", "reason": "clear"}]}'
                        )
                    }
                }
            ]
        },
    )
    monkeypatch.setattr(
        "app.services.repository.patch_doc",
        lambda collection, doc_id, data: patched.setdefault(doc_id, data),
    )

    result = form_ai.classify_figures("p1")

    assert result["classified"] == 0
    assert patched == {}

