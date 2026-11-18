# Accessibility Statement

**Target:** WCAG 2.2 AA for the `frontend/` web application.
**Status:** In progress — this document states commitments, current support, and known gaps so contributors can close them systematically.

---

## 1. Commitments

- All new UI must be keyboard-operable, screen-reader legible, and usable at 200% zoom.
- Color is never the only signal — status also uses text labels (`StatusBadge` always renders the status string).
- Interactive elements meet minimum target size (24×24 CSS px, aim for 44×44 on primary actions).
- PRs that add or change UI must include keyboard + screen-reader notes and screenshots (see PR template).
- Accessibility regressions are treated as bugs, not enhancements.

## 2. Current support

| Area | Implementation |
|---|---|
| Routing / structure | Semantic landmarks via `DashboardShell` (header + main), descriptive page titles per dashboard |
| Auth gates | `ProtectedRoute` redirects (`/login`, `/pending-approval`, `/not-authorized`) render plain-text explanations, not bare redirects |
| Status communication | `StatusBadge` pairs color with text; status colors centralized in `src/lib/types.ts` (`STATUS_COLOR`) |
| Forms | Controlled inputs with inline error text and labels on login, questionnaire, and workflow fields |
| Notifications | `NotificationBell` exposes unread count as text (`{count}`), not color-only; dropdown is button-triggered |
| Calendar | FullCalendar month view with text event titles; agenda list available via FullCalendar's list affordances |
| Reports | Table reports paired with `DashboardSummaryCards` numeric summaries |

## 3. Known gaps (help wanted)

| Gap | Impact | Tracking guidance |
|---|---|---|
| FullCalendar density + keyboard grid navigation | Keyboard-only users may struggle with dense month cells | Label issues `a11y` + `calendar`; propose list-view default or roving-tabindex fixes |
| Color-contrast debt in Tailwind defaults | Some muted grays may fail 4.5:1 body-text contrast | Audit with axe/Lighthouse; fix tokens in `tailwind.config.js` |
| Focus-visible styling is implicit (browser default) | Low-vision keyboard users lose track of focus | Add explicit `:focus-visible` rings in `index.css` |
| No `prefers-reduced-motion` handling | Motion-sensitive users get full animation | Add media-query guard for transitions |
| Live-region announcements missing (upload, assignment, approval toasts) | Screen-reader users miss async updates | Add `aria-live="polite"` status regions |
| Skip-to-content link missing in `DashboardShell` | Keyboard users tab through the header on every page | Add skip link as a first `DashboardShell` change |

If you find a barrier not listed here, open a Bug report with the `accessibility` label and include: page/route, role, browser + assistive tech, steps, expected vs actual, and a screenshot or recording.

## 4. How we test

- **Automated (CI, lightweight):** `npm run build` includes `tsc -b` (catches missing labels/props); contributors should run axe DevTools or Lighthouse locally on changed pages and paste scores into the PR.
- **Manual (required for UI PRs):** tab through the changed flow with keyboard only; test with a screen reader (NVDA/VoiceOver); zoom to 200%; check `prefers-reduced-motion`.
- **Future:** add `vitest` + `@axe-core` checks for critical flows (login, patent creation, questionnaire submit) — tracked as a `help wanted` issue.

## 5. Feedback and escalation

- Accessibility bugs: [open an issue](https://github.com/auraflaa/patent_drafting_tool/issues) with label `accessibility`.
- Enforcement follows the [Code of Conduct](./CODE_OF_CONDUCT.md) — dismissive responses to access needs are conduct violations.
- This statement will be reviewed on every minor release and updated in `CHANGELOG.md`.
