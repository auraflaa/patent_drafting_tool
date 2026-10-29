# ADR-004: Stub-first AI drafting with optional OpenAI-compatible provider

## Status
Accepted

## Date
2026-10-16

## Context
Draft generation (`POST /api/patents/{id}/draft/generate`) can call an external LLM, but the project must work fully offline: local development without API keys, CI without network credentials, and tests that never touch the network. Generated text is a draft aid, never filed directly.

## Decision
`AI_API_URL`, `AI_API_KEY`, and `AI_MODEL` are all unset by default. The stub returns a clearly labelled placeholder plus a not-legal-advice warning and still persists a versioned `drafts` record (one document per section), so the whole workflow is exercisable without keys. When all three are set, the backend calls that OpenAI-compatible chat endpoint through `httpx`; setting some but not all is a configuration error rather than a silent fallback, and `AI_API_URL` must be `https` (plain `http` is allowed only for localhost, because the key travels in a header).

## Alternatives Considered

### Provider-specific branches (gemini, groq, ...)
- Pros: tailored request/response handling per vendor.
- Cons: vendor lock-in, more code, harder to add new providers.
- Rejected: a single OpenAI-compatible `chat/completions` endpoint covers Gemini, Groq/Qwen, local Llama, and others with one code path.

### No stub — error when unconfigured
- Pros: honest about missing capability.
- Cons: blocks the entire draft workflow (versions, documents UI, agent walkthroughs) for anyone without a key.
- Rejected: the workflow, not just the prose, is what needs testing.

## Consequences
- Placeholder content must stay obviously non-final; the warning travels with every stub response and is re-appended if a real provider omits it.
- Adding a new provider means only setting three env vars (`AI_API_URL`, `AI_API_KEY`, `AI_MODEL`), no code changes.
- `ai_provider` stores the endpoint host and `ai_model` the model name, so the two stay distinguishable in the UI.
- Never commit `AI_API_KEY`; rotation procedures in `SECURITY.md` apply.
