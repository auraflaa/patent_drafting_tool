# FAQ

Short answers to questions that come up repeatedly. Longer guides:
[`GETTING_STARTED.md`](./GETTING_STARTED.md),
[`ARCHITECTURE.md`](./ARCHITECTURE.md),
[`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md).

## Product

**Is generated patent text legal advice?**
No. Every draft — stub or AI-generated — is a drafting aid with an explicit
not-legal-advice warning. A qualified patent professional must review anything
before filing.

**Who is this for?**
Innovators (disclose inventions), patent agents (review and draft), admins
(approve users, assign agents, manage templates), and super admins (roles,
permissions, reports). See README §3.

**Which backend does it use?**
Firebase only: Authentication for identity, Cloud Firestore for application
data and the stored documents. The old Postgres/SQLAlchemy stack was removed
in ADR-005, and the document bytes moved from Cloud Storage into Firestore in
ADR-006; there is no second system of record.

**Can I run it without Firebase?**
The backend boots without credentials, and the frontend builds, but nothing
beyond the login screen works: `/health` returns `503 degraded` and
authenticated calls fail. Use the Firebase Emulator Suite if you need an
offline-ish setup.

## Setup

**Where do the frontend Firebase values come from?**
Firebase console → Project settings → Your apps → Web app → SDK setup and
configuration. Put all five `VITE_FIREBASE_*` values in `frontend/.env`. They
are public identifiers, not secrets.

**Do I need the Realtime Database?**
No. Firestore is the only system of record (ADR-005); the `databaseURL` in the
Web app config is unused. All reads and writes go through the API.

**Why does `firestore.rules` deny everything?**
The browser signs in with Firebase Auth and then talks only to the FastAPI
backend. Firestore is reached by the Admin SDK, which bypasses Security Rules.
Denying every client request keeps the public Web API key from becoming a
data-access key, and it also protects the `blobs` collection, so a blob id is
not a capability. Deploy the rules with `firebase deploy --only firestore:rules`.

**Why do I get `403 awaiting approval`?**
New accounts are pending until an Admin approves them. The
`BOOTSTRAP_ADMIN_EMAIL` address becomes Super Admin on first sign-in and can
then approve others.

**Why does `auth/unauthorized-domain` appear after deploying?**
Add the production frontend domain under Firebase Authentication →
Authorized domains. `localhost` is pre-registered; other hosts are not.

**Port 8000 is already in use on my machine.**
Run the backend on another port (e.g. `8001`) and point `VITE_API_URL` at it,
or remap Compose ports. See
[`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md#ports-already-in-use).

**PDF generation fails locally.**
It no longer exists: documents are Word-only (ADR-006), and a PDF output
request returns `400`. Open the generated DOCX in Word, LibreOffice, or Google
Docs and export a PDF from there.

**Can I upload a PDF?**
Yes. It is converted to DOCX in-process with `pdf2docx` and the converted
Word file is what gets stored and downloaded; the original filename stays
visible in `source_file_name`. Scanned PDFs and very large files may exceed
the 900 KB compressed storage limit and return `413`.

## Contributing

**Where do I start?**
`CONTRIBUTING.md` (root) + `AGENTS.md` (root, agent-oriented). Pick a
`good first issue`, follow the commit-discipline rules (atomic commits, one
type per commit), and fill the PR template.

**Do I need Firebase credentials to run the tests?**
No. `backend/tests/` forces empty Firebase configuration and asserts boot,
the mounted frontend contract, and pure-Python services. Live Firebase
behaviour and real document storage are a manual checklist
(`backend/README.md` §7).

**Why is there no database container in Compose?**
Firestore is managed and external. Compose builds only the backend and
frontend images.

**How should I cite this project?**
See `CITATION.cff` at the repo root (GitHub renders a *Cite this repository*
button from it).

**What license is this?**
Apache-2.0 — see `LICENSE`. Contributions are accepted under the same license.
