from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MIB = 1024 * 1024

# Vercel rejects request/response bodies above 4.5 MB before the app runs.
# Keep uploads below that with room for multipart boundaries and form fields.
VERCEL_BODY_LIMIT_BYTES = 4_500_000
MULTIPART_OVERHEAD_BYTES = 64 * 1024
DEFAULT_SELF_HOSTED_UPLOAD_BYTES = 10 * MIB
DEFAULT_VERCEL_UPLOAD_BYTES = 4 * MIB


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_name: str = 'Patent Filing & Lifecycle Management Platform API'
    environment: str = 'development'
    firebase_project_id: str = ''
    firebase_service_account_path: str = 'secrets/firebase-service-account.json'
    # Inline JSON for hosts that cannot mount a file (Vercel, Cloud Run secrets).
    # Takes precedence over the path; store it in the platform's secret manager.
    firebase_service_account_json: str = Field(default='', repr=False)
    firestore_database_id: str = ''
    firebase_emulator_host: str = ''
    bootstrap_admin_email: str = ''
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    allowed_hosts: str = '*'
    # Requests per minute per client for the mutating /api/auth endpoints.
    # 0 disables the limiter. Session endpoints are exempt (see ratelimit.py).
    auth_rate_limit_per_minute: int = Field(default=60, ge=0)
    # `vercel` clamps the upload limit below Vercel's 4.5 MB function body cap.
    deployment_target: Literal['self_hosted', 'vercel'] = 'self_hosted'
    # 0 means "use the deployment target's default".
    max_upload_size_bytes: int = Field(default=0, ge=0)
    # Allowlist, not a deny-list: an extension is accepted only when it is
    # listed here, and the bytes are then checked against the extension.
    # PDFs are accepted and converted to DOCX before storage (ADR-006).
    allowed_upload_extensions: str = (
        '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.odt,.txt,.csv,.md,.rtf,'
        '.png,.jpg,.jpeg,.gif,.webp,.tif,.tiff'
    )
    ai_api_url: str = ''
    ai_api_key: str = Field(default='', repr=False)
    ai_model: str = ''

    @property
    def allowed_extensions(self) -> tuple[str, ...]:
        return tuple(
            item.strip().lower()
            for item in self.allowed_upload_extensions.split(',')
            if item.strip()
        )

    @property
    def upload_limit_bytes(self) -> int:
        """Effective per-file limit, clamped to the host platform's cap."""
        if self.max_upload_size_bytes:
            limit = self.max_upload_size_bytes
        elif self.deployment_target == 'vercel':
            limit = DEFAULT_VERCEL_UPLOAD_BYTES
        else:
            limit = DEFAULT_SELF_HOSTED_UPLOAD_BYTES
        if self.deployment_target == 'vercel':
            limit = min(limit, VERCEL_BODY_LIMIT_BYTES - MULTIPART_OVERHEAD_BYTES)
        return max(1, limit)

    @property
    def request_body_limit_bytes(self) -> int:
        """Limit for the whole request, including multipart overhead."""
        limit = self.upload_limit_bytes + MULTIPART_OVERHEAD_BYTES
        if self.deployment_target == 'vercel':
            limit = min(limit, VERCEL_BODY_LIMIT_BYTES)
        return limit

    def capabilities(self) -> dict:
        """Public runtime limits the frontend uses to fail fast and adapt."""
        return {
            'deployment_target': self.deployment_target,
            'max_upload_size_bytes': self.upload_limit_bytes,
            'max_request_body_bytes': self.request_body_limit_bytes,
        }


settings = Settings()
