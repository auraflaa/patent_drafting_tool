# Pull request template

> Fill in every section. Small, focused PRs merge fastest. See `CONTRIBUTING.md`.

## Summary

<!-- What does this PR change and why? One paragraph. -->

## Linked issues

<!-- e.g. Fixes #123, Relates to #45. Required for feat/fix. -->

- Fixes #
- Relates to #

## Type

<!-- Check one. -->

- [ ] `feat` — new feature
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `ci` — CI, workflows, Docker, repo infra
- [ ] `chore` — deps, tooling, housekeeping
- [ ] `refactor` — no behavior change
- [ ] `test` — tests only

## Scope

<!-- Check all that apply. -->

- [ ] Backend (`backend/`)
- [ ] Frontend (`frontend/`)
- [ ] Docs (`README`, `docs/`, `backend/README`, `DEPLOYMENT`)
- [ ] CI/CD (`.github/workflows`, `Dockerfile`, `docker-compose.yml`)
- [ ] Community health (templates, CoC, Security, Accessibility)

## Changes

<!-- Bullet list of the actual changes. Keep it reviewable. -->

-
-
-

## Testing

<!-- How did you verify this? Paste commands + outcomes. CI alone is not enough for workflow/UI changes. -->

### Backend

```text
# Paste: python -m compileall app / pip install / pytest output
```

### Frontend

```text
# Paste: npm run lint / npm run build output
```

### Manual QA (required for workflow, auth, RBAC, UI changes)

- [ ] Innovator: create team → patent → questionnaire → submit
- [ ] Admin: assign / auto-assign agent
- [ ] Agent: accept → generate draft → generate document
- [ ] Admin/Super Admin: approve user, manage template, export report
- [ ] N/A — docs/CI-only change (explain):

## Screenshots / recordings

<!-- Required for any UI change. Before + after where applicable. -->

| Before | After |
|---|---|
|  |  |

## Accessibility

<!-- Required for UI changes. -->

- [ ] Keyboard-only walkthrough passes (tab order, focus visible, no traps)
- [ ] Screen-reader spot check (labels announced, errors announced)
- [ ] 200% zoom usable, no clipped content
- [ ] Status/color changes also have text labels
- [ ] N/A — no UI change

## Security considerations

- [ ] No secrets, tokens, or service-account JSON added
- [ ] Auth guards preserved (`ensure_permission` / `is_admin` backend, `ProtectedRoute` frontend)
- [ ] Upload validation unchanged or tightened (size, extensions)
- [ ] No new `*` CORS origins or widened hosts
- [ ] N/A — docs/CI-only change

## Docs updated

- [ ] `README.md` / `docs/` updated (if behavior, env, or routes changed)
- [ ] `backend/.env.example` / `frontend/.env.example` updated (if env changed)
- [ ] `CHANGELOG.md` Unreleased entry added
- [ ] N/A — no user-facing change

## Checklist

- [ ] Single logical change; no unrelated reformatting or scope creep
- [ ] Conventional-commit title (`feat:`, `fix:`, `docs:`, `ci:`, …)
- [ ] Linked issues filled in
- [ ] Tests evidence pasted above; CI is green
- [ ] No `.env`, `secrets/*.json`, `dist/`, `venv/`, or `__pycache__/` committed
- [ ] I have read `CONTRIBUTING.md` and follow the `CODE_OF_CONDUCT.md`
