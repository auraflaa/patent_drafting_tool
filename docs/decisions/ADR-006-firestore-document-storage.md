# ADR-006: Word-only documents stored in Firestore

## Status

Accepted — extends [ADR-005](./ADR-005-firestore-only-runtime.md).

## Date

2026-10-29

## Context

ADR-005 made Firebase the only backend and kept uploaded attachments,
templates, and generated documents in Cloud Storage. That left a second
provider in the design for three reasons that no longer hold:

- The project has no Cloud Storage bucket. Creating one needs a billing
  account, so every upload path depended on a local emulator that only works
  on a developer machine.
- The product's documents are Word files. A generated DOCX is tens of
  kilobytes; the largest realistic specification is a few hundred kilobytes.
  Firestore's 1 MiB per-document limit is therefore comfortable once the
  bytes are compressed, and a separate object store buys nothing.
- Two systems of record means two sets of credentials, two failure modes, and
  two places where an orphaned file can hide. A metadata row and its bytes
  can drift apart with no cheap way to notice.

PDF was the second output format. It also justified a headless LibreOffice
install in the image, which is the single largest contributor to image size
and the only reason the runtime could not run on a serverless host.

## Decision

1. **One collection holds the bytes.** `blobs/{blobId}` stores
   `data` (gzip), `encoding`, `content_type`, `size_bytes`, `stored_bytes`,
   and `sha256`. `files`, `templates`, `documents`, and `document_versions`
   reference a blob by id and never carry document bytes.
2. **Compress before writing.** Gzip at level 6 with `mtime=0` keeps output
   deterministic, so the same input produces the same `sha256` and the same
   stored size. Reads decompress and verify the hash; a mismatch is an error,
   not a silent corruption.
3. **Cap below the platform limit.** `MAX_STORED_BYTES = 900_000` leaves
   roughly 148 KB of the 1 MiB document budget for field names and Firestore's
   own encoding. A larger compressed payload fails with a 413 that names the
   limit, before the provider rejects the write with an opaque error.
4. **Word is the only stored document form.**
   - Generation accepts `DOCX` only; a `PDF` request returns 400 telling the
     caller to export from a word processor.
   - Uploaded PDFs are converted to DOCX in-process with `pdf2docx` (PyMuPDF
     plus python-docx, no LibreOffice) and the converted file is validated as
     a safe DOCX before storage. No PDF is ever written to Firestore.
   - Other allowlisted attachment types (images, drawings, spreadsheets) are
     still accepted and stored compressed, because they are evidence rather
     than deliverables.
5. **Keep the REST shape.** The contract keys `stored_path`, `storage_path`,
   and `template_out.file_path` keep their names but now carry a blob id. A
   converted upload reports the new `original_file_name` (`*.docx`),
   `source_file_name` (the original PDF), and `converted_from_pdf: true`, so
   the UI can explain what happened without a separate endpoint.
6. **No browser access.** `firestore.rules` denies all client reads and
   writes, so a blob id is not a capability: every download goes through an
   authorised API route that re-checks the patent and the permission.
7. **No LibreOffice in the image.** The Dockerfile installs no office suite;
   PDF imports run in the API process, which keeps the single-instance
   assumption in ADR-003 intact.

## Alternatives Considered

### Keep Cloud Storage and wait for billing
- Pros: no size cap, no compression step, streaming downloads for free.
- Cons: blocks every upload path until a billing account exists; keeps a
  second provider, a second credential, and a second failure mode for files
  that are small by nature.
- Rejected: the dependency is avoidable, so it should be removed rather than
  waited on.

### Base64-encode the bytes into the metadata document
- Pros: one read instead of two, no join.
- Cons: base64 inflates by ~33% against a hard 1 MiB ceiling, and every list
  query would fetch payloads it does not need.
- Rejected: a separate `blobs` row keeps list endpoints cheap.

### Chunk each file across many Firestore documents
- Pros: no practical size limit; supports very large scans.
- Cons: multi-document writes are not atomic, so a partial write leaves a
  file that looks present but cannot be read; cleanup needs a sweep job; and
  the added complexity only pays off for files this product does not have.
- Rejected: revisit only if a real document approaches the cap.

### Keep PDF output and convert with LibreOffice
- Pros: users get the format courts and filing portals often ask for.
- Cons: an office suite in the image, a subprocess per request, a
  non-serverless runtime, and PDFs that cannot be stored under the cap.
- Rejected: a DOCX opens in every word processor and exports a PDF in one
  click, so the format belongs to the user's tool, not the server.

## Consequences

- **Storage cost**: files count against the Firestore document quota rather
  than a bucket. At this project's sizes the free tier is ample, but a
  bulk-import feature would need the chunking design above.
- **Upload size**: the effective ceiling is compressed size, not request
  size. Highly compressible DOCX files near the 10 MiB upload limit can still
  exceed the blob cap; the 413 message states the limit the user hit.
- **Integrity**: a corrupted blob is detected on read (hash mismatch) instead
  of being served. There is no repair path beyond re-upload, because there is
  no second copy.
- **Orphans**: a failed metadata write deletes the blob it just created.
  Deletes remove the blob before the row, and blob deletion is best effort so
  a missing blob never blocks metadata cleanup.
- **Conversion fidelity**: `pdf2docx` reconstructs layout heuristically, so a
  converted PDF can reorder a heading relative to body text. The original PDF
  name is preserved in `source_file_name` so the user can compare.
- **Logging**: `pdf2docx` calls `logging.basicConfig(level=INFO)` at import;
  `pdf_to_docx` restores the root logger level around the import so API logs
  stay at their configured level.
- **Removed surface**: no `FIREBASE_STORAGE_BUCKET`, no
  `STORAGE_EMULATOR_HOST`, no `VITE_FIREBASE_STORAGE_BUCKET`, no
  `PDF_CONVERSION_ENABLED`, no `pdf_generation_enabled` capability, no
  `soffice` lookup, and no `app/services/storage.py`.
