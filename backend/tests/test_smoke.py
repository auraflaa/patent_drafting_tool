"""Offline smoke tests: the app boots, the contract is mounted, and the
pure-Python services behave. No Firebase credentials are required.
"""
import asyncio
from io import BytesIO

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app.core.config import (
    DEFAULT_SELF_HOSTED_UPLOAD_BYTES,
    DEFAULT_VERCEL_UPLOAD_BYTES,
    MIB,
    MULTIPART_OVERHEAD_BYTES,
    VERCEL_BODY_LIMIT_BYTES,
    Settings,
)
from app.services import documents, drafting
from app.services.rbac import (
    ALL_PERMISSION_IDS,
    ALL_ROLE_CODES,
    DEFAULT_GRANTS,
    REPORT_TYPE_NAMES,
    matrix,
)

# Paths the React client calls. Kept as a literal list on purpose: if one of
# them silently disappears from the API the frontend breaks at runtime, which
# no type-checker would catch.
CONTRACT_PATHS = {
    ("get", "/api/config/capabilities"),
    ("get", "/api/auth/me"),
    ("post", "/api/auth/logout"),
    ("post", "/api/auth/sync"),
    ("get", "/api/auth/pending-users"),
    ("post", "/api/auth/users/{user_id}/approve"),
    ("post", "/api/auth/users/{user_id}/reject"),
    ("get", "/api/teams"),
    ("post", "/api/teams"),
    ("get", "/api/teams/{team_id}"),
    ("post", "/api/teams/{team_id}/members"),
    ("delete", "/api/teams/{team_id}/members/{member_id}"),
    ("get", "/api/patents"),
    ("post", "/api/patents"),
    ("get", "/api/patents/available-agents"),
    ("get", "/api/patents/{patent_id}"),
    ("post", "/api/patents/{patent_id}/submit"),
    ("post", "/api/patents/{patent_id}/assign"),
    ("post", "/api/patents/{patent_id}/auto-assign"),
    ("post", "/api/patents/{patent_id}/reassign"),
    ("post", "/api/patents/{patent_id}/assignment/accept"),
    ("post", "/api/patents/{patent_id}/assignment/reject"),
    ("get", "/api/patents/{patent_id}/applicants"),
    ("post", "/api/patents/{patent_id}/applicants"),
    ("patch", "/api/patents/{patent_id}/applicants/{applicant_id}"),
    ("delete", "/api/patents/{patent_id}/applicants/{applicant_id}"),
    ("post", "/api/patents/{patent_id}/applicants/reorder"),
    ("get", "/api/patents/{patent_id}/inventors"),
    ("post", "/api/patents/{patent_id}/inventors"),
    ("patch", "/api/patents/{patent_id}/inventors/{inventor_id}"),
    ("delete", "/api/patents/{patent_id}/inventors/{inventor_id}"),
    ("post", "/api/patents/{patent_id}/inventors/reorder"),
    ("get", "/api/patents/{patent_id}/questionnaire"),
    ("patch", "/api/patents/{patent_id}/questionnaire"),
    ("post", "/api/patents/{patent_id}/questionnaire/submit"),
    ("get", "/api/patents/{patent_id}/questionnaire/versions"),
    ("get", "/api/patents/{patent_id}/draft"),
    ("post", "/api/patents/{patent_id}/draft/generate"),
    ("get", "/api/patents/{patent_id}/draft/{section_type}/versions"),
    ("get", "/api/patents/{patent_id}/comments"),
    ("post", "/api/patents/{patent_id}/comments"),
    ("get", "/api/patents/{patent_id}/files"),
    ("post", "/api/patents/{patent_id}/files"),
    ("get", "/api/patents/{patent_id}/files/{file_id}/download"),
    ("delete", "/api/patents/{patent_id}/files/{file_id}"),
    ("get", "/api/patents/{patent_id}/calendar-events"),
    ("post", "/api/patents/{patent_id}/calendar-events"),
    ("delete", "/api/patents/{patent_id}/calendar-events/{event_id}"),
    ("get", "/api/calendar/events"),
    ("get", "/api/patents/{patent_id}/documents"),
    ("post", "/api/patents/{patent_id}/documents/generate"),
    ("get", "/api/patents/{patent_id}/documents/jobs"),
    ("post", "/api/patents/{patent_id}/documents/jobs/{job_id}/retry"),
    ("get", "/api/patents/{patent_id}/documents/{document_id}/versions"),
    ("get", "/api/patents/{patent_id}/documents/{document_id}/download"),
    ("get", "/api/patents/{patent_id}/documents/versions/{version_id}/download"),
    ("get", "/api/templates/document-types"),
    ("get", "/api/templates"),
    ("post", "/api/templates"),
    ("post", "/api/templates/{template_id}/activate"),
    ("delete", "/api/templates/{template_id}"),
    ("get", "/api/notifications"),
    ("get", "/api/notifications/unread-count"),
    ("patch", "/api/notifications/{notification_id}/read"),
    ("post", "/api/notifications/read-all"),
    ("get", "/api/reports/dashboard"),
    ("get", "/api/reports"),
    ("get", "/api/reports/{report_type}"),
    ("get", "/api/reports/{report_type}/export"),
    ("get", "/api/reports/permissions/matrix"),
    ("post", "/api/reports/permissions/toggle"),
    ("get", "/api/rbac/matrix"),
    ("post", "/api/rbac/toggle"),
    ("get", "/api/rbac/users"),
    ("post", "/api/rbac/users/{target_id}/roles"),
    ("delete", "/api/rbac/users/{target_id}/roles/{role_code}"),
}


def test_root_reports_service_identity(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["health"] == "/health"
    assert "Patent" in body["name"]


def test_health_is_degraded_without_firebase_credentials(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_me_requires_a_bearer_token(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_rejects_a_garbage_token(client: TestClient) -> None:
    response = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code in {401, 503}


def test_openapi_mounts_the_whole_frontend_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    mounted = {
        (method, path)
        for path, operations in schema["paths"].items()
        for method in operations
    }
    missing = sorted(CONTRACT_PATHS - mounted)
    assert not missing, f"missing from the API: {missing}"


def test_legacy_auth_endpoints_are_gone(client: TestClient) -> None:
    for path in ("/api/auth/refresh", "/api/auth/dev-login", "/api/auth/google/login"):
        assert client.post(path).status_code == 404


def test_rbac_catalog_is_consistent() -> None:
    assert len(ALL_ROLE_CODES) == 4
    assert len(ALL_PERMISSION_IDS) == 27
    catalog = matrix()
    assert {role["role_code"] for role in catalog["roles"]} == set(ALL_ROLE_CODES)
    assert len(catalog["permissions"]) == 27
    # Super Admin always holds everything and cannot be toggled.
    assert DEFAULT_GRANTS[1] == set(ALL_PERMISSION_IDS)
    super_admin_grants = {
        grant["permission_id"]
        for grant in catalog["grants"]
        if grant["role_id"] == 1
    }
    assert super_admin_grants == set(ALL_PERMISSION_IDS)


def test_every_report_type_is_known() -> None:
    assert set(REPORT_TYPE_NAMES) == {
        "patent_applications",
        "documents",
        "calendar_events",
        "users",
    }


def test_stub_draft_always_carries_the_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.services import drafting
    monkeypatch.setattr(settings, "ai_api_url", "")
    monkeypatch.setattr(settings, "ai_api_key", "")
    monkeypatch.setattr(settings, "ai_model", "")
    patent = {"invention_title": "Self-sealing widget"}
    questionnaire = {
        "invention_type": "Utility",
        "problem_statement": "Widgets leak.",
        "proposed_solution": "Add a gasket.",
    }
    for section in drafting.SECTION_TYPES:
        text, provider, model = drafting.generate_section(patent, questionnaire, section)
        assert provider == "stub"
        assert model is None
        assert drafting.DRAFT_WARNING in text
        assert "Self-sealing widget" in text or section == "CLAIMS"


def test_unknown_draft_section_is_rejected() -> None:
    try:
        drafting.generate_section({}, {}, "GLOSSARY")
    except drafting.AIGenerationError as exc:
        assert "GLOSSARY" in str(exc)
    else:  # pragma: no cover - the assert above is the real check
        raise AssertionError("expected AIGenerationError")


def test_builtin_docx_layout_renders_and_is_inspectable() -> None:
    patent = {"invention_title": "Self-sealing widget"}
    sections = {section: f"{section} body" for section in drafting.SECTION_TYPES}
    content = documents.render_docx(patent, sections, None)
    assert content.startswith(b"PK")
    assert len(content) > 5_000

    unknown, unused, parse_error = documents.inspect_template(content)
    assert parse_error is None
    assert unknown == []
    # The built-in layout contains no Jinja tags, so every known placeholder is
    # reported as unused.
    assert set(unused) == set(documents.KNOWN_PLACEHOLDERS)


def test_document_context_carries_the_watermark_and_title() -> None:
    context = documents.build_context(
        {"invention_title": "Self-sealing widget"}, {"ABSTRACT": "An abstract."}
    )
    assert context["TITLE"] == "Self-sealing widget"
    assert context["WATERMARK_TEXT"] == documents.WATERMARK_TEXT
    assert context["ABSTRACT"] == "An abstract."
    assert context["CLAIMS"] == "Not generated."


# ---------------------------------------------------------------------------
# Deployment limits
# ---------------------------------------------------------------------------


def test_capabilities_are_public_and_describe_the_limits(client: TestClient) -> None:
    response = client.get("/api/config/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "deployment_target",
        "max_upload_size_bytes",
        "max_request_body_bytes",
        "max_stored_size_bytes",
    }
    assert body["deployment_target"] in {"self_hosted", "vercel"}
    assert body["max_upload_size_bytes"] > 0
    assert body["max_request_body_bytes"] >= body["max_upload_size_bytes"]
    # The stored-file limit is the real ceiling on attachments (ADR-006) and is
    # smaller than the request limit, so the UI can describe both honestly.
    assert body["max_stored_size_bytes"] < body["max_upload_size_bytes"]
    assert response.headers["cache-control"] == "no-store"


def test_upload_limit_zero_uses_the_profile_default() -> None:
    local = Settings(
        deployment_target="self_hosted", max_upload_size_bytes=0, _env_file=None
    )
    assert local.upload_limit_bytes == DEFAULT_SELF_HOSTED_UPLOAD_BYTES

    vercel = Settings(
        deployment_target="vercel", max_upload_size_bytes=0, _env_file=None
    )
    assert vercel.upload_limit_bytes == DEFAULT_VERCEL_UPLOAD_BYTES


def test_explicit_upload_limits_are_kept_off_vercel() -> None:
    settings = Settings(
        deployment_target="self_hosted",
        max_upload_size_bytes=2 * MIB,
        _env_file=None,
    )
    assert settings.upload_limit_bytes == 2 * MIB
    assert settings.request_body_limit_bytes == 2 * MIB + MULTIPART_OVERHEAD_BYTES

    # A lower explicit limit is a ceiling, not a value to raise to the cap.
    smaller = Settings(
        deployment_target="vercel",
        max_upload_size_bytes=1 * MIB,
        _env_file=None,
    )
    assert smaller.upload_limit_bytes == 1 * MIB


def test_vercel_profile_clamps_explicit_limits_below_the_body_cap() -> None:
    settings = Settings(
        deployment_target="vercel",
        max_upload_size_bytes=10 * MIB,
        _env_file=None,
    )
    assert settings.upload_limit_bytes == (
        VERCEL_BODY_LIMIT_BYTES - MULTIPART_OVERHEAD_BYTES
    )
    assert settings.request_body_limit_bytes == VERCEL_BODY_LIMIT_BYTES


def test_request_body_guard_rejects_oversized_uploads(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)
    response = client.post(
        "/api/auth/sync",
        content=b"x" * (MULTIPART_OVERHEAD_BYTES * 2),
        headers={
            "Content-Type": "application/json",
            "Origin": "http://localhost:5173",
        },
    )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]
    # The guard must sit inside CORS, or the browser sees a CORS error
    # instead of the 413 detail.
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_wraps_host_rejections(client: TestClient) -> None:
    """TrustedHost must sit inside CORS so a browser can read its 400."""
    response = client.post(
        "/api/auth/sync",
        content=b"{}",
        headers={
            "Host": "evil.example.com",
            "Origin": "http://localhost:5173",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_security_headers_land_on_route_and_rejection_responses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok = client.get("/")
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert ok.headers["x-frame-options"] == "DENY"
    assert ok.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in ok.headers["permissions-policy"]

    # The body guard rejects before routing, so this proves the header layer
    # wraps middleware-generated responses too, not just route responses.
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)

    def chunks():
        for _ in range(3):
            yield b"x" * MULTIPART_OVERHEAD_BYTES

    rejected = client.post(
        "/api/auth/sync",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert rejected.status_code == 413
    assert rejected.headers["x-content-type-options"] == "nosniff"


def test_unhandled_errors_stay_readable_by_the_browser(client: TestClient) -> None:
    from app.core import security
    from app.main import app

    def boom():
        raise RuntimeError("boom")

    app.dependency_overrides[security.current_user] = boom
    try:
        response = client.get(
            "/api/auth/me", headers={"Origin": "http://localhost:5173"}
        )
    finally:
        app.dependency_overrides.pop(security.current_user, None)

    assert response.status_code == 500
    assert response.json()["detail"].startswith("RuntimeError")
    # Starlette's own Exception handler runs outside user middleware. If the
    # catch-all regresses, the browser sees a CORS error instead of this body.
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_request_body_guard_counts_chunked_bodies(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)

    def chunks():
        for _ in range(3):
            yield b"x" * MULTIPART_OVERHEAD_BYTES

    response = client.post(
        "/api/auth/sync",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


def test_read_upload_stops_one_chunk_past_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)
    upload = UploadFile(filename="big.bin", file=BytesIO(b"x" * 4096))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(resources._read_upload(upload))
    assert exc.value.status_code == 413


def test_documents_are_word_only_and_pdf_output_is_rejected() -> None:
    from app.api import resources

    resources._ensure_format_supported("DOCX")

    with pytest.raises(HTTPException) as exc:
        resources._ensure_format_supported("PDF")
    assert exc.value.status_code == 400
    assert "DOCX" in str(exc.value.detail)

    with pytest.raises(HTTPException) as unknown:
        resources._ensure_format_supported("ODT")
    assert unknown.value.status_code == 400
    assert "DOCX" in str(unknown.value.detail)


def test_chunks_streams_and_closes_the_blob() -> None:
    from app.api import resources

    class FakeStream:
        def __init__(self, data: bytes) -> None:
            self.buffer = BytesIO(data)
            self.closed = False

        def read(self, size: int) -> bytes:
            return self.buffer.read(size)

        def close(self) -> None:
            self.closed = True

    stream = FakeStream(b"a" * 10)
    assert b"".join(resources._chunks(stream, chunk_size=4)) == b"a" * 10
    assert stream.closed


def test_inline_service_account_json_is_validated() -> None:
    from app.core import firebase
    from app.core.config import Settings

    assert firebase._credentials_from_json("") is None
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase._credentials_from_json("{not-json")
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase._credentials_from_json("[]")
    # Parsed JSON that is not a usable certificate also fails as configuration.
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase._credentials_from_json('{"type": "service_account"}')

    settings = Settings(
        firebase_service_account_json='{"private_key": "super-secret"}',
        _env_file=None,
    )
    assert "super-secret" not in repr(settings)


def test_download_filenames_cannot_break_headers() -> None:
    from app.api import resources

    cleaned = resources._clean_filename('report"\r\nX-Injected: 1.csv')
    assert cleaned == "report'  X-Injected: 1.csv"
    assert resources._clean_filename("../../etc/passwd") == "passwd"
    # Backslashes are separators on Windows even though PurePath on Linux
    # treats them as ordinary characters.
    assert "\\" not in resources._clean_filename(r"..\..\windows\system32\x.txt")


def test_download_filename_header_is_ascii_safe_for_any_script() -> None:
    from app.api import resources

    header = resources._content_disposition("特許 出願.docx")["Content-Disposition"]
    # Starlette encodes every header as Latin-1; a raw Unicode filename raises.
    header.encode("latin-1")
    assert 'filename="' in header
    assert "filename*=UTF-8''" in header
    assert "%E7%89%B9%E8%A8%B1" in header

    long_header = resources._content_disposition("a" * 400 + ".pdf")[
        "Content-Disposition"
    ]
    assert len(long_header) < 500
    assert ".pdf" in long_header


def test_report_cells_cannot_start_a_spreadsheet_formula() -> None:
    from app.api import resources

    assert resources._csv_safe('=HYPERLINK("http://evil", "click")').startswith("'=")
    assert resources._csv_safe("+1+1").startswith("'+")
    assert resources._csv_safe("@SUM(A1)").startswith("'@")
    assert resources._csv_safe("ordinary title") == "ordinary title"
    assert resources._csv_safe(None) == ""


def test_bootstrap_admin_requires_a_verified_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import security
    from app.core.config import settings

    monkeypatch.setattr(settings, "bootstrap_admin_email", "owner@example.com")
    unverified = security._new_profile(
        "u1", {"email": "owner@example.com", "email_verified": False}
    )
    assert unverified["account_status"] == "pending"
    assert unverified["role_codes"] == ["INNOVATOR"]

    verified = security._new_profile(
        "u2", {"email": "owner@example.com", "email_verified": True}
    )
    assert verified["account_status"] == "approved"
    assert verified["role_codes"] == ["SUPER_ADMIN"]


def test_ai_key_is_a_header_and_never_echoed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.services import drafting

    secret = "super-secret-key"
    monkeypatch.setattr(settings, "ai_api_url", "https://example.ai/v1/chat/completions")
    monkeypatch.setattr(settings, "ai_api_key", secret)
    monkeypatch.setattr(settings, "ai_model", "test-model")
    seen: dict = {}

    def fake_post(url: str, **kwargs):
        seen.update(kwargs)
        request = httpx.Request("POST", f"{url}?key={secret}")
        raise httpx.HTTPStatusError(
            f"Client error '400 Bad Request' for url '{request.url}'",
            request=request,
            response=httpx.Response(400, request=request),
        )

    monkeypatch.setattr(drafting.httpx, "post", fake_post)
    with pytest.raises(drafting.AIGenerationError) as exc:
        drafting._ai_text({"invention_title": "Test"}, {}, "ABSTRACT")

    assert secret not in str(exc.value)
    assert "key" not in seen
    assert seen["headers"]["Authorization"] == f"Bearer {secret}"


def test_ai_retries_a_rate_limit_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.services import drafting

    monkeypatch.setattr(settings, "ai_api_url", "https://example.ai/v1/chat/completions")
    monkeypatch.setattr(settings, "ai_api_key", "secret")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    sleeps: list[float] = []
    monkeypatch.setattr(drafting.time, "sleep", sleeps.append)

    calls = {"n": 0, "body": None}

    def fake_post(url: str, **kwargs):
        calls["n"] += 1
        calls["body"] = kwargs["json"]
        request = httpx.Request("POST", url)
        if calls["n"] == 1:
            return httpx.Response(
                429, headers={"retry-after": "7"}, request=request
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {"message": {"content": drafting.DRAFT_WARNING}}
                ]
            },
        )

    monkeypatch.setattr(drafting.httpx, "post", fake_post)

    text = drafting._ai_text({"invention_title": "Test"}, {}, "ABSTRACT")

    assert calls["n"] == 2
    assert sleeps == [7.0]
    assert calls["body"]["max_tokens"] == drafting.MAX_COMPLETION_TOKENS
    assert drafting.DRAFT_WARNING in text


def test_ai_stops_after_the_retry_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.services import drafting

    monkeypatch.setattr(settings, "ai_api_url", "https://example.ai/v1/chat/completions")
    monkeypatch.setattr(settings, "ai_api_key", "secret")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(drafting.time, "sleep", lambda seconds: None)

    calls = {"n": 0}

    def fake_post(url: str, **kwargs):
        calls["n"] += 1
        request = httpx.Request("POST", url)
        return httpx.Response(429, request=request)

    monkeypatch.setattr(drafting.httpx, "post", fake_post)
    with pytest.raises(drafting.AIGenerationError, match="HTTP 429"):
        drafting._ai_text({"invention_title": "Test"}, {}, "ABSTRACT")

    assert calls["n"] == drafting.MAX_AI_ATTEMPTS


def test_ai_rejects_partial_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.services import drafting

    monkeypatch.setattr(settings, "ai_api_url", "https://example.ai/v1/chat/completions")
    monkeypatch.setattr(settings, "ai_api_key", "secret")
    monkeypatch.setattr(settings, "ai_model", "")

    with pytest.raises(drafting.AIGenerationError) as exc:
        drafting.generate_section({"invention_title": "Test"}, {}, "ABSTRACT")

    assert "AI_MODEL" in str(exc.value)


def test_ai_rejects_plain_http_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.services import drafting

    monkeypatch.setattr(settings, "ai_api_url", "http://example.ai/v1/chat/completions")
    monkeypatch.setattr(settings, "ai_api_key", "secret")
    monkeypatch.setattr(settings, "ai_model", "test-model")

    # The key travels in a header, so plain http would expose it.
    with pytest.raises(drafting.AIGenerationError) as exc:
        drafting._ai_text({"invention_title": "Test"}, {}, "ABSTRACT")

    assert "https" in str(exc.value)


def _docx_bytes() -> bytes:
    from app.services import documents

    return documents._render_builtin(
        {"invention_title": "Test"},
        {key: f"Text for {key}" for key, _ in documents.SECTION_ORDER},
    )


def test_upload_allowlist_and_content_sniffing() -> None:
    from app.services import uploads

    allowed = (".pdf", ".docx", ".txt")

    with pytest.raises(uploads.UploadValidationError):
        uploads.validate_upload("payload.exe", b"MZ", allowed_extensions=allowed, max_bytes=1024)

    # The extension alone is not enough: an HTML file renamed to .pdf fails.
    with pytest.raises(uploads.UploadValidationError) as exc:
        uploads.validate_upload(
            "report.pdf",
            b"<html><script>alert(1)</script></html>",
            allowed_extensions=allowed,
            max_bytes=1024,
        )
    assert "does not match" in str(exc.value)

    good = uploads.validate_upload(
        "report.pdf", b"%PDF-1.7\n...", allowed_extensions=allowed, max_bytes=1024
    )
    assert good.mime_type == "application/pdf"

    too_big = uploads.validate_upload
    with pytest.raises(uploads.UploadTooLarge):
        too_big(
            "notes.txt", b"a" * 2048, allowed_extensions=allowed, max_bytes=1024
        )


def test_upload_filename_cannot_escape_or_carry_control_characters() -> None:
    from app.services import uploads

    name = uploads.sanitize_filename('..\\..\\evil\r\n"name".pdf')
    assert "\\" not in name
    assert "/" not in name
    assert "\r" not in name and "\n" not in name
    assert '"' not in name
    assert name.endswith(".pdf")

    long_name = uploads.sanitize_filename("a" * 400 + ".docx")
    assert len(long_name) <= uploads.MAX_FILENAME_LENGTH
    assert long_name.endswith(".docx")


def test_docx_content_is_checked_before_parsing() -> None:
    import zipfile

    from app.services import uploads

    uploads.assert_safe_docx(_docx_bytes())

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    missing_part = BytesIO()
    with zipfile.ZipFile(missing_part, "w") as archive:
        archive.writestr("readme.txt", "not a docx")
    with pytest.raises(uploads.UploadValidationError) as exc:
        uploads.assert_safe_docx(missing_part.getvalue())
    assert "missing" in str(exc.value)

    with pytest.raises(uploads.UploadValidationError):
        uploads.assert_safe_docx(b"PK\x03\x04not-really-a-zip")


def test_profile_fields_are_bounded_and_typed() -> None:
    from app.api import auth

    assert auth._profile_patch({"full_name": "  Ada Lovelace  "}) == {
        "full_name": "Ada Lovelace"
    }
    assert auth._profile_patch({"bio": "line one\nline two"}) == {
        "bio": "line one\nline two"
    }
    assert auth._profile_patch({"profile_picture": ""}) == {"profile_picture": ""}

    with pytest.raises(HTTPException) as exc:
        auth._profile_patch({"full_name": "x" * (auth.PROFILE_FIELD_LIMITS["full_name"] + 1)})
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException):
        auth._profile_patch({"organization": {"nested": "no"}})

    with pytest.raises(HTTPException):
        auth._profile_patch({"full_name": "bad\x00name"})

    with pytest.raises(HTTPException):
        auth._profile_patch({"profile_picture": "javascript:alert(1)"})

    # Unknown keys are ignored rather than written through to Firestore.
    assert auth._profile_patch({"account_status": "approved"}) == {}


def test_api_csp_is_strict_but_docs_stays_usable(client: TestClient) -> None:
    api = client.get("/api/config/capabilities")
    assert "default-src 'none'" in api.headers["content-security-policy"]

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers


def test_unexpected_generation_errors_are_not_echoed() -> None:
    from app.api import resources
    from app.services import documents

    curated = documents.DocumentGenerationError("Generate every AI draft first.")
    assert resources._job_error_message(curated) == "Generate every AI draft first."

    unexpected = resources._job_error_message(
        RuntimeError("C:/secret/path/to/template.docx")
    )
    assert "secret" not in unexpected
    assert "server logs" in unexpected


def test_request_id_is_echoed_and_untrusted_values_are_replaced(
    client: TestClient,
) -> None:
    supplied = client.get(
        "/api/config/capabilities", headers={"X-Request-ID": "support-ticket-42"}
    )
    assert supplied.headers["x-request-id"] == "support-ticket-42"

    # A header value that could break logging or response headers is replaced
    # with a generated hex ID rather than reflected.
    hostile = client.get(
        "/api/config/capabilities", headers={"X-Request-ID": "bad value\r\nx: y"}
    )
    generated = hostile.headers["x-request-id"]
    assert generated != "bad value\r\nx: y"
    assert len(generated) == 32
    assert all(char in "0123456789abcdef" for char in generated)


def test_firebase_recovers_from_a_failed_client_initialisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import firebase

    original = (firebase._app, firebase._db)
    calls = {"count": 0}

    def flaky_client(app, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("credentials unavailable")
        return "db-sentinel"

    try:
        firebase._app = object()
        firebase._db = None
        monkeypatch.setattr(firebase.firestore, "client", flaky_client)

        with pytest.raises(RuntimeError):
            firebase.initialize_firebase()

        # The failed attempt must not leave db() returning None on the retry.
        firebase.initialize_firebase()
        assert firebase._db == "db-sentinel"
    finally:
        firebase._app, firebase._db = original


def test_resource_text_fields_are_bounded_and_typed() -> None:
    from app.api import resources

    assert resources._bounded_text("  Ada  ", "full_name", 10) == "Ada"
    assert resources._bounded_text(None, "full_name", 10) is None
    assert resources._bounded_text("   ", "full_name", 10) is None
    assert (
        resources._bounded_text(
            "line one\nline two", "address", 100, allow_newlines=True
        )
        == "line one\nline two"
    )

    with pytest.raises(HTTPException) as exc:
        resources._bounded_text("x" * 11, "full_name", 10)
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException):
        resources._bounded_text({"nested": "no"}, "full_name", 10)

    with pytest.raises(HTTPException):
        resources._bounded_text("line one\nline two", "full_name", 100)

    texts = resources._party_texts(
        {"full_name": " Ada ", "address": "A\nB"},
        resources.INVENTOR_TEXT_LIMITS,
        only_present=True,
    )
    assert texts == {"full_name": "Ada", "address": "A\nB"}

    with pytest.raises(HTTPException):
        resources._party_texts(
            {"email": 42}, resources.INVENTOR_TEXT_LIMITS, only_present=True
        )

    questionnaire = resources._questionnaire_patch(
        {"problem_statement": "  A problem  ", "keywords": "a, b"}
    )
    assert questionnaire == {
        "problem_statement": "A problem",
        "keywords": "a, b",
    }

    limit = resources.QUESTIONNAIRE_TEXT_LIMITS["problem_statement"]
    with pytest.raises(HTTPException) as q_exc:
        resources._questionnaire_patch({"problem_statement": "x" * (limit + 1)})
    assert q_exc.value.status_code == 422

    with pytest.raises(HTTPException):
        resources._questionnaire_patch({"has_existing_drawings": "yes"})


def test_calendar_delete_checks_the_manage_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    checked: list[str] = []
    monkeypatch.setattr(resources, "require_patent", lambda *args: {"id": "p1"})
    monkeypatch.setattr(resources, "_can_manage_calendar", lambda *args: True)

    def deny(user, code):
        checked.append(code)
        raise HTTPException(403, "denied")

    monkeypatch.setattr(resources, "ensure_permission", deny)

    with pytest.raises(HTTPException) as exc:
        resources.delete_calendar_event(
            "p1", "e1", {"uid": "u1", "role_codes": []}
        )
    assert exc.value.status_code == 403
    assert checked == ["CALENDAR_MANAGE"]


def test_users_report_stays_admin_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import resources
    from app.services import rbac

    admin = {"uid": "admin", "role_codes": ["ADMIN"]}
    innovator = {"uid": "u1", "role_codes": ["INNOVATOR"]}

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(resources, "has_permission", lambda *args: True)
    monkeypatch.setattr(resources, "can_download_report", lambda *args: True)
    monkeypatch.setattr(
        resources, "is_admin", lambda user: "ADMIN" in user["role_codes"]
    )

    innovator_rows = resources.report_catalog(innovator)
    assert "users" not in {row["report_type"] for row in innovator_rows}

    admin_rows = resources.report_catalog(admin)
    assert "users" in {row["report_type"] for row in admin_rows}

    with pytest.raises(HTTPException) as exc:
        resources._assert_report_access("users", innovator)
    assert exc.value.status_code == 403
    resources._assert_report_access("users", admin)

    with pytest.raises(ValueError):
        rbac.toggle_report_permission(3, "users", True)


def test_reject_user_blocks_self_and_super_admins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import auth

    monkeypatch.setattr(auth, "ensure_permission", lambda *args: None)

    with pytest.raises(HTTPException) as self_exc:
        auth.reject_user(
            "u1", None, {"uid": "u1", "role_codes": ["SUPER_ADMIN"]}
        )
    assert self_exc.value.status_code == 400

    monkeypatch.setattr(
        auth,
        "get_doc",
        lambda collection, uid: {"id": uid, "role_codes": ["SUPER_ADMIN"]},
    )
    with pytest.raises(HTTPException) as admin_exc:
        auth.reject_user(
            "u2", None, {"uid": "u1", "role_codes": ["SUPER_ADMIN"]}
        )
    assert admin_exc.value.status_code == 400


def test_approval_rejection_and_role_changes_are_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import auth, resources

    audit: list[tuple] = []
    writes: list[dict] = []

    target = {
        "id": "u2",
        "email": "new@example.com",
        "full_name": "New User",
        "role_codes": ["INNOVATOR", "PATENT_AGENT"],
        "account_status": "pending",
    }
    admin = {"uid": "admin", "role_codes": ["SUPER_ADMIN"]}

    monkeypatch.setattr(auth, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(auth, "get_doc", lambda *args: dict(target))
    monkeypatch.setattr(
        auth,
        "write_doc",
        lambda _collection, _id, data, **_kwargs: writes.append(data),
    )
    monkeypatch.setattr(auth, "log_activity", lambda *args: audit.append(args))

    auth.approve_user("u2", {"role_codes": ["INNOVATOR"]}, admin)
    auth.reject_user("u2", None, admin)

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(resources, "get_doc", lambda *args: dict(target))
    monkeypatch.setattr(resources, "patch_doc", lambda *args: None)
    monkeypatch.setattr(
        resources, "log_activity", lambda *args: audit.append(args)
    )

    resources.assign_role("u2", {"role_code": "ADMIN"}, admin)
    resources.revoke_role("u2", "INNOVATOR", admin)

    assert ("admin", "UserApproved", "User", "u2") in audit
    assert ("admin", "UserRejected", "User", "u2") in audit
    assert ("admin", "RoleAssigned", "User", "u2") in audit
    assert ("admin", "RoleRevoked", "User", "u2") in audit
    assert len(writes) == 2


def test_ai_output_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import drafting

    monkeypatch.setattr(
        drafting,
        "_stub_text",
        lambda *args: "x" * (drafting.MAX_OUTPUT_CHARS + 1),
    )
    with pytest.raises(drafting.AIGenerationError):
        drafting.generate_section({"invention_title": "Test"}, {}, "ABSTRACT")


def test_questionnaire_routes_enforce_their_catalogued_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The RBAC catalog lists separate edit and submit grants for questionnaires."""
    from app.api import resources

    checked: list[str] = []
    monkeypatch.setattr(
        resources,
        "require_patent",
        lambda *args: {"id": "p1", "application_status": "Draft"},
    )
    monkeypatch.setattr(resources, "can_edit_basic_info", lambda *args: True)

    def deny(user, code):
        checked.append(code)
        raise HTTPException(403, "denied")

    monkeypatch.setattr(resources, "ensure_permission", deny)

    with pytest.raises(HTTPException) as edit_exc:
        resources.update_questionnaire("p1", {}, {"uid": "u1"})
    with pytest.raises(HTTPException) as submit_exc:
        resources.submit_questionnaire("p1", {"uid": "u1"})

    assert edit_exc.value.status_code == 403
    assert submit_exc.value.status_code == 403
    assert checked == ["QUESTIONNAIRE_EDIT", "QUESTIONNAIRE_SUBMIT"]


def test_update_patent_rejects_non_owners_and_submitted_applications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATENTS_EDIT is a real grant, but it must not override ownership or state."""
    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(resources, "is_admin", lambda user: False)
    monkeypatch.setattr(resources, "is_patent_creator", lambda patent, user: False)
    monkeypatch.setattr(
        resources,
        "require_patent",
        lambda *args: {"id": "p1", "application_status": "Draft"},
    )

    with pytest.raises(HTTPException) as owner_exc:
        resources.update_patent(
            "p1",
            {"invention_title": "A new title"},
            {"uid": "u2", "role_codes": ["INNOVATOR"]},
        )
    assert owner_exc.value.status_code == 403

    monkeypatch.setattr(resources, "is_patent_creator", lambda patent, user: True)
    monkeypatch.setattr(
        resources,
        "require_patent",
        lambda *args: {"id": "p1", "application_status": "Submitted"},
    )
    with pytest.raises(HTTPException) as state_exc:
        resources.update_patent(
            "p1",
            {"invention_title": "A new title"},
            {"uid": "u1", "role_codes": ["INNOVATOR"]},
        )
    assert state_exc.value.status_code == 400


def test_pending_users_requires_the_approval_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import auth

    def deny(user, code):
        assert code == "USERS_APPROVE"
        raise HTTPException(403, "denied")

    monkeypatch.setattr(auth, "ensure_permission", deny)

    with pytest.raises(HTTPException) as exc:
        auth.pending_users({"uid": "u1", "role_codes": ["INNOVATOR"]})

    assert exc.value.status_code == 403


def test_secondary_writes_never_fail_the_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed notification or activity row must not 500 a committed write."""
    from app.services import projections

    logged: list[str] = []

    def boom(*args, **kwargs):
        raise RuntimeError("firestore unavailable")

    monkeypatch.setattr(projections, "create_doc", boom)
    monkeypatch.setattr(projections, "list_docs", boom)
    monkeypatch.setattr(
        projections,
        "log_event",
        lambda logger, level, event, **fields: logged.append(event),
    )

    projections.notify_many({"u1", "u2"}, "p1", "Submitted")
    projections.notify_admins("p1", "Submitted")
    projections.log_activity("u1", "PatentSubmitted", "PatentApplication", "p1")

    assert logged.count("notification_write_failed") == 2
    assert "admin_lookup_failed" in logged
    assert "activity_write_failed" in logged


def test_submit_patent_requires_a_completed_questionnaire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete questionnaire would become read-only and block drafting."""
    from app.api import resources

    patent = {"id": "p1", "created_by": "u1", "application_status": "Draft"}
    writes: list[tuple] = []
    monkeypatch.setattr(resources, "require_patent", lambda *args: patent)
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "_questionnaire", lambda *args: {"questionnaire_status": "In Progress"}
    )
    monkeypatch.setattr(
        resources, "_set_patent", lambda *args: writes.append(args) or patent
    )

    with pytest.raises(HTTPException) as exc:
        resources.submit_patent("p1", {"uid": "u1", "role_codes": ["INNOVATOR"]})

    assert exc.value.status_code == 400
    assert "questionnaire" in exc.value.detail.lower()
    assert writes == []


def test_submit_patent_accepts_a_completed_questionnaire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    patent = {"id": "p1", "created_by": "u1", "application_status": "Draft"}
    monkeypatch.setattr(resources, "require_patent", lambda *args: patent)
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "_questionnaire", lambda *args: {"questionnaire_status": "Completed"}
    )
    monkeypatch.setattr(
        resources,
        "_set_patent",
        lambda *args: {**patent, "application_status": "Submitted"},
    )
    monkeypatch.setattr(resources, "notify_admins", lambda *args: None)
    monkeypatch.setattr(resources, "log_activity", lambda *args: None)

    result = resources.submit_patent(
        "p1", {"uid": "u1", "role_codes": ["INNOVATOR"]}
    )

    assert result["application_status"] == "Submitted"


def test_assign_rejects_an_application_already_awaiting_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only admins may move an already-assigned application (via /reassign)."""
    from app.api import resources

    patent = {
        "id": "p1",
        "created_by": "u1",
        "application_status": "Awaiting Patent Agent Acceptance",
        "assigned_patent_agent_id": "agent-1",
    }
    monkeypatch.setattr(resources, "require_patent", lambda *args: patent)
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)

    with pytest.raises(HTTPException) as exc:
        resources.assign_agent(
            "p1",
            {"patent_agent_id": "agent-2"},
            {"uid": "u1", "role_codes": ["INNOVATOR"]},
        )

    assert exc.value.status_code == 400


def test_assign_records_the_initial_assignment_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    patent = {
        "id": "p1",
        "created_by": "u1",
        "application_status": "Submitted",
        "assigned_patent_agent_id": None,
    }
    recorded: list[tuple] = []
    monkeypatch.setattr(resources, "require_patent", lambda *args: patent)
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(resources, "_agent_or_404", lambda *args: {"id": "agent-2"})
    monkeypatch.setattr(
        resources,
        "_set_patent",
        lambda *args: {**patent, "application_status": "Awaiting Patent Agent Acceptance"},
    )
    monkeypatch.setattr(
        resources,
        "_record_assignment",
        lambda *args: recorded.append(args),
    )
    monkeypatch.setattr(resources, "notify_many", lambda *args, **kwargs: None)
    monkeypatch.setattr(resources, "log_activity", lambda *args: None)

    resources.assign_agent(
        "p1",
        {"patent_agent_id": "agent-2"},
        {"uid": "u1", "role_codes": ["INNOVATOR"]},
    )

    assert recorded == [("p1", None, "agent-2", "Initial assignment", "u1")]


def test_truncated_ai_completion_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A length-limited completion must not be stored as a finished draft."""
    from app.services import drafting

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {"message": {"content": "half a claim"}, "finish_reason": "length"}
                ]
            }

    monkeypatch.setattr(drafting.settings, "ai_api_url", "https://example.test/v1/chat/completions")
    monkeypatch.setattr(drafting.settings, "ai_api_key", "test-key")
    monkeypatch.setattr(drafting.settings, "ai_model", "test-model")
    monkeypatch.setattr(drafting, "_post_chat", lambda prompt: FakeResponse())

    with pytest.raises(drafting.AIGenerationError) as exc:
        drafting._ai_text({"invention_title": "Test"}, {}, "ABSTRACT")

    assert "truncat" in str(exc.value).lower()


def test_activate_template_refuses_a_template_that_failed_to_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activating a broken template would break generation for every document."""
    from app.api import resources

    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources,
        "get_doc",
        lambda *args: {"id": "t1", "template_parse_error": "bad zip"},
    )

    with pytest.raises(HTTPException) as exc:
        resources.activate_template("t1", {"uid": "admin"})

    assert exc.value.status_code == 400
    assert "parse" in exc.value.detail.lower()


def test_delete_template_refuses_the_active_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    deleted: list[str] = []
    monkeypatch.setattr(resources, "ensure_permission", lambda *args: None)
    monkeypatch.setattr(
        resources, "get_doc", lambda *args: {"id": "t1", "is_active": True}
    )
    monkeypatch.setattr(resources, "delete_doc", lambda *args: deleted.append(args[1]))

    with pytest.raises(HTTPException) as exc:
        resources.delete_template("t1", {"uid": "admin"})

    assert exc.value.status_code == 400
    assert deleted == []


def test_delete_file_removes_the_record_before_the_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed blob delete must not leave a row pointing at missing bytes."""
    from app.api import resources

    order: list[tuple] = []
    monkeypatch.setattr(resources, "require_patent", lambda *args: {"id": "p1"})
    monkeypatch.setattr(resources, "is_admin", lambda user: False)
    monkeypatch.setattr(resources, "has_permission", lambda user, code: False)
    monkeypatch.setattr(
        resources,
        "get_doc",
        lambda *args: {
            "id": "f1",
            "blob_id": "b1",
            "patent_application_id": "p1",
            "uploaded_by": "u1",
        },
    )
    monkeypatch.setattr(
        resources, "delete_doc", lambda *args: order.append(("doc", args[1]))
    )
    monkeypatch.setattr(
        resources.blobs, "delete_blob", lambda blob_id: order.append(("blob", blob_id))
    )
    monkeypatch.setattr(
        resources,
        "log_activity",
        lambda *args: order.append(("audit", args[1])),
    )

    resources.delete_file("p1", "f1", {"uid": "u1"})

    assert order == [("doc", "f1"), ("blob", "b1"), ("audit", "FileDeleted")]


def test_patent_calendar_requires_the_view_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources

    checked: list[str] = []
    monkeypatch.setattr(resources, "require_patent", lambda *args: {"id": "p1"})

    def deny(user, code):
        checked.append(code)
        raise HTTPException(403, "denied")

    monkeypatch.setattr(resources, "ensure_permission", deny)

    with pytest.raises(HTTPException) as exc:
        resources.list_patent_events("p1", {"uid": "u1"})

    assert exc.value.status_code == 403
    assert checked == ["CALENDAR_VIEW"]


def test_production_warns_when_allowed_hosts_is_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main
    from app.core.config import settings

    warnings: list[str] = []
    monkeypatch.setattr(
        main.logger, "warning", lambda message, *args: warnings.append(message)
    )

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "allowed_hosts", "*")
    main.warn_insecure_hosts()
    assert any("ALLOWED_HOSTS" in message for message in warnings)

    warnings.clear()
    monkeypatch.setattr(settings, "allowed_hosts", "api.example.com")
    main.warn_insecure_hosts()
    assert not warnings
