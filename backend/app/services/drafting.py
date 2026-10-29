"""AI drafting with a stub-first provider (ADR-004).

`AI_API_URL`/`AI_API_KEY`/`AI_MODEL` configure any OpenAI-compatible chat
endpoint. When unset, the stub never touches the network and returns
a clearly labelled draft. Generated text is a drafting aid, never legal advice.
"""
import logging
import time
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Providers rate-limit per minute (Groq's free tier: 8 000 TPM for the
# drafting models). One draft section is comfortably under 2 048 tokens; a
# larger ceiling only inflates the per-minute budget and the latency tail.
MAX_COMPLETION_TOKENS = 2048
# 429 and transient upstream failures are worth one more attempt: the token
# window slides, so a short wait usually clears it.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_AI_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 30.0
# A full five-section batch with retries could otherwise hold one request open
# for ~15 minutes, past every common proxy timeout. The route stops starting
# new sections after this budget and stores what it already produced.
BATCH_DEADLINE_SECONDS = 120.0

DRAFT_WARNING = (
    "DRAFT ONLY — this text was generated as a drafting aid and is not legal "
    "advice. A qualified patent professional must review and edit it before "
    "any filing."
)

SECTION_TYPES = ("ABSTRACT", "BACKGROUND", "SUMMARY", "DESCRIPTION", "CLAIMS")
SECTION_LABELS = {
    "ABSTRACT": "Abstract",
    "BACKGROUND": "Background",
    "SUMMARY": "Summary",
    "DESCRIPTION": "Detailed Description",
    "CLAIMS": "Claims",
}

# A draft output lands in one Firestore document (1 MiB cap). Leaving the
# provider's response unbounded would let one call exceed the document limit.
MAX_OUTPUT_CHARS = 60_000


class AIGenerationError(RuntimeError):
    pass


def _value(questionnaire: dict, field: str, fallback: str = "Not provided.") -> str:
    value = questionnaire.get(field)
    return str(value).strip() if value not in (None, "") else fallback


def _stub_text(patent: dict, questionnaire: dict, section: str) -> str:
    title = patent.get("invention_title") or "Untitled invention"
    problem = _value(questionnaire, "problem_statement")
    solution = _value(questionnaire, "proposed_solution")
    novelty = _value(questionnaire, "novelty_description")
    technical = _value(questionnaire, "technical_description")
    advantages = _value(questionnaire, "advantages", "No advantages recorded.")
    keywords = _value(questionnaire, "keywords", "No keywords recorded.")

    bodies = {
        "ABSTRACT": (
            f"A {questionnaire.get('invention_type') or 'technical'} invention titled "
            f"\"{title}\". {solution} The disclosed approach addresses: {problem}"
        ),
        "BACKGROUND": (
            f"Existing approaches to the problem addressed by \"{title}\" have "
            f"limitations. {problem} There remains a need for an improved solution."
        ),
        "SUMMARY": (
            f"Disclosed is {title}. In one aspect, {solution} The described "
            f"implementation is distinguished by: {novelty}"
        ),
        "DESCRIPTION": (
            f"Detailed description of \"{title}\".\n\n"
            f"Technical implementation: {technical}\n\n"
            f"Novelty: {novelty}\n\n"
            f"Advantages: {advantages}\n\n"
            f"Keywords: {keywords}"
        ),
        "CLAIMS": (
            f"1. A method for {title.lower()}, comprising the steps described in "
            f"the technical description.\n\n"
            f"2. The method of claim 1, wherein the implementation includes: "
            f"{novelty}\n\n"
            f"3. A system configured to perform the method of claim 1."
        ),
    }
    body = bodies.get(section, bodies["DESCRIPTION"])
    return f"{body}\n\n{DRAFT_WARNING}"


def _provider_label() -> str:
    """Human-readable provider name for the stored `ai_provider` field."""
    host = urlparse(settings.ai_api_url).hostname or ""
    return host or "openai-compatible"


def _retry_wait_seconds(response: httpx.Response, fallback: float) -> float:
    """Honour `Retry-After` when the provider sends it, else use backoff."""
    raw = (response.headers.get("retry-after") or "").strip()
    if raw:
        try:
            return min(max(float(raw), 0.0), MAX_RETRY_WAIT_SECONDS)
        except ValueError:
            pass
    return min(max(fallback, 0.0), MAX_RETRY_WAIT_SECONDS)


def _post_chat(prompt: str) -> httpx.Response:
    """POST one chat completion, retrying rate limits and transient 5xx.

    A 429 on a per-minute token budget clears as the window slides, so the
    same request usually succeeds on the next attempt.
    """
    delay = 2.0
    response = None
    for attempt in range(1, MAX_AI_ATTEMPTS + 1):
        response = httpx.post(
            settings.ai_api_url,
            # The key goes in an Authorization header, never the query string:
            # httpx puts the full URL in HTTPStatusError, which would leak the
            # key into API responses and logs.
            headers={
                "Authorization": f"Bearer {settings.ai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.ai_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": MAX_COMPLETION_TOKENS,
            },
            timeout=60.0,
        )
        if response.status_code not in RETRYABLE_STATUSES:
            return response
        if attempt == MAX_AI_ATTEMPTS:
            break
        wait = _retry_wait_seconds(response, delay)
        logger.info(
            "AI request returned %s; retrying in %.1fs (attempt %s/%s)",
            response.status_code,
            wait,
            attempt + 1,
            MAX_AI_ATTEMPTS,
        )
        time.sleep(wait)
        delay *= 3
    return response


def _ai_text(patent: dict, questionnaire: dict, section: str) -> str:
    if not settings.ai_api_url or not settings.ai_api_key or not settings.ai_model:
        raise AIGenerationError(
            "AI_API_URL, AI_API_KEY, and AI_MODEL must all be set to use AI drafting."
        )
    parsed = urlparse(settings.ai_api_url)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        # The API key travels in a header; a plain-http endpoint would expose it.
        raise AIGenerationError("AI_API_URL must use https (http is allowed only for localhost).")
    prompt = (
        "You are assisting a patent professional with a first draft. "
        "Return plain text only, no markdown. Always end with this exact "
        f"warning: {DRAFT_WARNING}\n\n"
        f"Section: {SECTION_LABELS.get(section, section)}\n"
        f"Invention title: {patent.get('invention_title')}\n"
        f"Invention type: {questionnaire.get('invention_type')}\n"
        f"Problem statement: {questionnaire.get('problem_statement')}\n"
        f"Proposed solution: {questionnaire.get('proposed_solution')}\n"
        f"Novelty: {questionnaire.get('novelty_description')}\n"
        f"Technical description: {questionnaire.get('technical_description')}\n"
        f"Advantages: {questionnaire.get('advantages')}\n"
        f"Prior art: {questionnaire.get('prior_art')}\n"
        f"Keywords: {questionnaire.get('keywords')}\n"
    )
    try:
        response = _post_chat(prompt)
        response.raise_for_status()
        payload = response.json()
        choice = payload["choices"][0]
        if choice.get("finish_reason") == "length":
            # Silently storing half a claim set is worse than failing: the
            # truncation is invisible once the text is in Firestore.
            raise AIGenerationError(
                "The AI response hit the token limit and would be truncated. "
                "Shorten the questionnaire or regenerate this section."
            )
        text = choice["message"]["content"].strip()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "AI request failed with HTTP %s", exc.response.status_code
        )
        raise AIGenerationError(
            f"AI request failed with HTTP {exc.response.status_code}."
        ) from exc
    except AIGenerationError:
        raise
    except Exception as exc:
        logger.warning("AI request failed: %s", type(exc).__name__)
        raise AIGenerationError(
            "AI request failed. Check the API key, model, and endpoint."
        ) from exc
    if DRAFT_WARNING not in text:
        text = f"{text}\n\n{DRAFT_WARNING}"
    return text


def generate_section(
    patent: dict, questionnaire: dict, section: str
) -> tuple[str, str, str | None]:
    """Return (text, provider, model) for one section."""
    if section not in SECTION_TYPES:
        raise AIGenerationError(f"Unknown section type: {section}")
    configured = [settings.ai_api_url, settings.ai_api_key, settings.ai_model]
    if any(configured) and not all(configured):
        # Half-configured AI used to send `"model": ""` to the provider and
        # surface as an opaque 502. Fail loudly and name the missing vars.
        raise AIGenerationError(
            "AI_API_URL, AI_API_KEY, and AI_MODEL must all be set, or all left empty."
        )
    if settings.ai_api_url:
        text, used_provider, model = (
            _ai_text(patent, questionnaire, section),
            _provider_label(),
            settings.ai_model,
        )
    else:
        text, used_provider, model = (
            _stub_text(patent, questionnaire, section),
            "stub",
            None,
        )
    if len(text) > MAX_OUTPUT_CHARS:
        raise AIGenerationError(
            "The generated draft exceeded the maximum length. Shorten the "
            "questionnaire or regenerate one section at a time."
        )
    return text, used_provider, model
