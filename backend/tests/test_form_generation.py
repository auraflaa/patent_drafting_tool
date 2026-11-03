"""Tests for statutory form set generation, status and finalization."""
import pytest
from fastapi import HTTPException

from app.api import resources
from app.services import form_generation, forms


def _profile():
    return {
        "questionnaire": {
            "invention_keyword": "widget",
            "title_keyword": "WIDGET",
            "problem_keyword": "drift",
            "claim_keyword": "guide",
            "data1": "rail",
            "data2": "wiper",
            "field": "f",
            "domain": "d",
            "area": "a",
            "one_line_about_field": "one",
            "two_lines_about_domain": "two",
            "three_lines_about_area": "three",
            "four_lines_about_problem": "problem",
            "four_lines_about_solution": "solution",
            "advantage1": "a1",
            "advantage2": "a2",
            "exemplary_scenario": "ex",
            "detailed_exemplary_scenario": "dex",
            "best_working_method": "best",
            "prior_art": "US 1",
        },
        "applicant": {
            "full_name_or_org_name": "Example Labs",
            "country": "India",
            "address": "1 Test St",
        },
        "inventors": [{"full_name": "Alice", "country": "India", "address": "2 Test St"}],
        "agent": {},
        "counts": {"page_count": "13", "claim_count": "04"},
        "generated_date": "3rd day of November 2026",
    }


@pytest.fixture()
def fakes(monkeypatch):
    store = {"documents": {}, "versions": [], "jobs": []}

    def fake_query(collection, filters=None):
        if collection == "questionnaires":
            return [{"id": "q1", **_profile()["questionnaire"]}]
        if collection == "applicants":
            return [{"id": "a1", "is_primary": True, **_profile()["applicant"]}]
        if collection == "inventors":
            return [
                {"id": f"i{n}", **inv}
                for n, inv in enumerate(_profile()["inventors"])
            ]
        if collection == "documents":
            return list(store["documents"].values())
        if collection == "document_versions":
            return store["versions"]
        if collection == "document_jobs":
            return store["jobs"]
        if collection == "file_figures":
            return []
        return []

    def fake_create(collection, data, doc_id=None):
        record = {"id": doc_id or f"{collection}-{len(store['jobs'])}", **data}
        if collection == "documents":
            store["documents"][record["id"]] = record
        elif collection == "document_versions":
            store["versions"].append(record)
        elif collection == "document_jobs":
            store["jobs"].append(record)
        return record

    def fake_patch(collection, doc_id, data):
        for row in store["jobs"]:
            if row["id"] == doc_id:
                row.update(data)
                return row
        return {"id": doc_id, **data}

    monkeypatch.setattr(form_generation, "query_docs", fake_query)
    monkeypatch.setattr(form_generation, "create_doc", fake_create)
    monkeypatch.setattr(form_generation, "patch_doc", fake_patch)
    monkeypatch.setattr(
        form_generation, "get_doc_or_none", lambda collection, doc_id: None
    )
    monkeypatch.setattr(form_generation, "allocate_counter", lambda *a, **k: 1)
    monkeypatch.setattr(
        form_generation,
        "set_latest_version",
        lambda collection, doc_id, version, fields: {"id": doc_id, **fields},
    )
    monkeypatch.setattr(
        form_generation.blobs,
        "put_blob",
        lambda data, mime=None: {
            "id": "blob1",
            "size_bytes": len(data),
            "stored_bytes": len(data),
        },
    )
    monkeypatch.setattr(form_generation.blobs, "delete_blob", lambda blob_id: None)
    monkeypatch.setattr(
        extraction_store := form_generation.extraction_store,
        "usable_figure_count",
        lambda patent_id: 1,
    )
    monkeypatch.setattr(
        extraction_store, "figures_for_patent", lambda patent_id: []
    )
    monkeypatch.setattr(
        extraction_store, "read_figure_image", lambda row: (_ for _ in ()).throw(AssertionError("no images"))
    )
    return store


def test_generate_form_set_renders_all_five(fakes):
    result = form_generation.generate_form_set("p1", {"uid": "u1"})

    assert len(result["results"]) == 5
    assert {row["form_code"] for row in result["results"]} == {
        "FORM1",
        "FORM2",
        "FORM3",
        "FORM5",
        "DRAWINGS",
    }
    assert all(row["status"] == "Completed" for row in result["results"])
    assert result["batch_id"]
    assert len(fakes["documents"]) == 5
    assert len(fakes["versions"]) == 5


def test_generate_form_set_accepts_a_subset(fakes):
    result = form_generation.generate_form_set("p1", {"uid": "u1"}, codes=["FORM1"])

    assert [row["form_code"] for row in result["results"]] == ["FORM1"]
    assert len(fakes["documents"]) == 1


def test_generate_form_set_records_a_failed_form(fakes, monkeypatch):
    real_render = forms.render_form

    def broken(code, context, figures=None, template_bytes=None):
        if code == "FORM2":
            raise forms.FormRenderError("FORM2 is missing required value(s): field.")
        return real_render(code, context, figures=figures)

    monkeypatch.setattr(form_generation.forms, "render_form", broken)

    result = form_generation.generate_form_set("p1", {"uid": "u1"})

    by_code = {row["form_code"]: row for row in result["results"]}
    assert by_code["FORM2"]["status"] == "Failed"
    assert "field" in by_code["FORM2"]["error"]
    assert by_code["FORM1"]["status"] == "Completed"


def test_finalize_requires_documents_figures_and_fields(fakes, monkeypatch):
    with pytest.raises(form_generation.FinalizeError) as exc:
        form_generation.finalize("p1", {"uid": "u1"})
    assert "Generate all forms" in str(exc.value)

    form_generation.generate_form_set("p1", {"uid": "u1"})
    monkeypatch.setattr(
        form_generation.extraction_store, "usable_figure_count", lambda patent_id: 0
    )
    with pytest.raises(form_generation.FinalizeError) as exc:
        form_generation.finalize("p1", {"uid": "u1"})
    assert "sketch or drawing" in str(exc.value)


def test_finalize_locks_the_set(fakes):
    form_generation.generate_form_set("p1", {"uid": "u1"})

    result = form_generation.finalize("p1", {"uid": "u1"})

    assert result["finalized_by"] == "u1"
    assert result["finalized_at"]
    assert result["usable_figure_count"] == 1


def test_form_status_reports_missing_fields(fakes, monkeypatch):
    monkeypatch.setattr(
        form_generation.extraction_store, "usable_figure_count", lambda patent_id: 0
    )
    status = form_generation.form_status("p1")

    assert len(status["forms"]) == 5
    assert status["missing_sketch_warning"] is True
    assert status["usable_figure_count"] == 0
    form1 = next(card for card in status["forms"] if card["form_code"] == "FORM1")
    assert form1["generated"] is False
    assert form1["missing_fields"] == []  # the fixture profile is complete

    monkeypatch.setattr(
        form_generation.extraction_store, "usable_figure_count", lambda patent_id: 1
    )
    status = form_generation.form_status("p1")
    assert status["missing_sketch_warning"] is False
    assert status["usable_figure_count"] == 1


def test_generate_route_rejects_unknown_codes(monkeypatch):
    monkeypatch.setattr(resources, "require_patent", lambda *args: {"id": "p1"})
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "_assert_forms_agent", lambda patent, user, action: None
    )
    monkeypatch.setattr(resources, "_assert_generation_allowed", lambda patent: None)

    with pytest.raises(HTTPException) as exc:
        resources.generate_forms("p1", {"codes": ["NOPE"]}, {"uid": "u1"})
    assert exc.value.status_code == 400


def test_finalize_route_maps_gate_errors(monkeypatch):
    monkeypatch.setattr(resources, "require_patent", lambda *args: {"id": "p1"})
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "_assert_forms_agent", lambda patent, user, action: None
    )
    monkeypatch.setattr(
        resources.form_generation, "finalize", lambda *args: (_ for _ in ()).throw(
            form_generation.FinalizeError("blocked")
        )
    )

    with pytest.raises(HTTPException) as exc:
        resources.finalize_forms("p1", {"uid": "u1"})
    assert exc.value.status_code == 400
    assert "blocked" in str(exc.value.detail)


def _route_guards(monkeypatch, status="Under Review"):
    monkeypatch.setattr(
        resources,
        "require_patent",
        lambda *args: {"id": "p1", "application_status": status},
    )
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "_assert_forms_agent", lambda patent, user, action: None
    )
    monkeypatch.setattr(resources, "_assert_generation_allowed", lambda patent: None)
    monkeypatch.setattr(resources, "_reap_stale_jobs", lambda patent_id: None)


def test_generate_route_renders_the_set(fakes, monkeypatch):
    _route_guards(monkeypatch)

    out = resources.generate_forms("p1", {}, {"uid": "u1"})

    assert out["batch_id"]
    assert len(out["results"]) == 5
    assert all(row["status"] == "Completed" for row in out["results"])


def test_generate_route_rejects_unknown_form_types(monkeypatch):
    _route_guards(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        resources.generate_forms("p1", {"codes": ["FORM9"]}, {"uid": "u1"})
    assert exc.value.status_code == 400


def test_form_download_and_versions_reject_unknown_codes(monkeypatch):
    _route_guards(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        resources.download_form("p1", "FORM9", {"uid": "u1"})
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        resources.form_versions("p1", "FORM9", {"uid": "u1"})
    assert exc.value.status_code == 404


def test_finalize_blocks_a_newer_failed_job(fakes, monkeypatch):
    form_generation.generate_form_set("p1", {"uid": "u1"})
    fakes["jobs"].append(
        {
            "id": "job-failed",
            "patent_application_id": "p1",
            "form_code": "FORM1",
            "status": "Failed",
            "error_message": "boom",
            "completed_at": "2999-01-01T00:00:00+00:00",
            "started_at": "2999-01-01T00:00:00+00:00",
        }
    )

    with pytest.raises(form_generation.FinalizeError) as exc:
        form_generation.finalize("p1", {"uid": "u1"})
    assert "FORM1" in str(exc.value)


def test_refine_route_stops_at_the_deadline(monkeypatch):
    _route_guards(monkeypatch)
    monkeypatch.setattr(resources.form_ai, "BATCH_DEADLINE_SECONDS", -1)
    monkeypatch.setattr(
        resources.form_generation,
        "build_profile",
        lambda patent_id, counts=None: {"questionnaire": {}},
    )
    monkeypatch.setattr(
        resources.form_ai,
        "refine_group",
        lambda *args, **kwargs: {
            "fields": {},
            "origin": {},
            "figure_refs": {},
            "used_figures": [],
            "provider": "stub",
            "model": "stub",
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        resources, "can_review_draft", lambda patent, user: True
    )
    monkeypatch.setattr(
        resources,
        "_questionnaire",
        lambda patent_id: {"id": "q1", "questionnaire_status": "Completed"},
    )
    created = []
    monkeypatch.setattr(
        resources,
        "create_doc",
        lambda c, d, doc_id=None: created.append(
            {"id": doc_id or f"{c}-{len(created)}", **d}
        )
        or {"id": doc_id or f"{c}-{len(created) - 1}", **d},
    )
    monkeypatch.setattr(resources, "query_docs", lambda c, filters=None: [])
    monkeypatch.setattr(resources, "log_activity", lambda *args: None)

    out = resources.refine_form_fields(
        "p1",
        {"groups": ["FORM_METADATA", "FORM_BACKGROUND"]},
        {"uid": "u1"},
    )

    assert len(out) == 1  # second group never started
    assert out[0]["group"] == "FORM_METADATA"
