"""The questionnaire registry is the single source of truth.

A field added in one place must appear in PATCH validation, projections, and
version snapshots — this suite fails if the lists drift apart.
"""
import pytest
from fastapi import HTTPException

from app.api import resources
from app.services import projections, questionnaire_schema


def test_every_registry_field_is_projected() -> None:
    doc = {key: None for key in questionnaire_schema.QUESTIONNAIRE_FIELDS}
    doc["id"] = "q1"
    payload = projections.questionnaire_out(doc)
    for key in questionnaire_schema.QUESTIONNAIRE_FIELDS:
        assert key in payload, f"{key} missing from questionnaire_out"


def test_every_registry_field_is_versioned() -> None:
    doc = {key: None for key in questionnaire_schema.QUESTIONNAIRE_FIELDS}
    doc["id"] = "q1"
    payload = projections.questionnaire_version_out(doc)
    for key in questionnaire_schema.QUESTIONNAIRE_FIELDS:
        assert key in payload, f"{key} missing from questionnaire_version_out"


def test_patch_accepts_every_registry_field() -> None:
    payload = {
        key: (True if spec.kind == "boolean" else "value")
        for key, spec in questionnaire_schema.FIELD_BY_KEY.items()
    }
    data = resources._questionnaire_patch(payload)
    assert set(data) == set(questionnaire_schema.QUESTIONNAIRE_FIELDS)


def test_patch_rejects_unknown_keys() -> None:
    with pytest.raises(HTTPException) as exc:
        resources._questionnaire_patch({"not_a_field": "x"})
    assert exc.value.status_code == 422
    assert "not_a_field" in str(exc.value.detail)


def test_patch_enforces_field_limits() -> None:
    spec = questionnaire_schema.FIELD_BY_KEY["invention_keyword"]
    with pytest.raises(HTTPException) as exc:
        resources._questionnaire_patch(
            {"invention_keyword": "x" * (spec.limit + 1)}
        )
    assert exc.value.status_code == 422


def test_patch_rejects_non_boolean_for_boolean_fields() -> None:
    with pytest.raises(HTTPException) as exc:
        resources._questionnaire_patch({"has_existing_drawings": "yes"})
    assert exc.value.status_code == 422


def test_ai_groups_reference_registry_fields() -> None:
    for group, keys in questionnaire_schema.AI_GROUPS.items():
        assert keys, f"{group} has no fields"
        for key in keys:
            assert questionnaire_schema.FIELD_BY_KEY[key].ai_group == group


def test_required_for_forms_are_registry_fields() -> None:
    for key in questionnaire_schema.REQUIRED_FOR_FORMS:
        assert key in questionnaire_schema.FIELD_BY_KEY
    assert "invention_keyword" in questionnaire_schema.REQUIRED_FOR_FORMS
