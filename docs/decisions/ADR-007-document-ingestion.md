# ADR-007: Read uploads for drafting, and default to Form 1

## Status

Accepted - extends [ADR-003](./ADR-003-single-instance.md) and
[ADR-006](./ADR-006-firestore-document-storage.md).

## Date

2026-11-02

## Context

Uploads were stored and never read. The drafting model saw only the
questionnaire, so a specification, a prior-art PDF, or a deck supplied as
context had no effect on the generated sections. The same gap applied to
templates: until an administrator uploaded one, document generation used a
plain heading list with none of the layout a patent office expects.

Firestore remains the only system of record and caps one document at 1 MiB
(ADR-005/ADR-006). Extraction produces three different things - prose,
layout, and image crops - and a long filing can exceed that cap on its own.

## Decision

1. **Extract once, right after the upload is stored.** The file row and its
   blob are written first; extraction then runs in-process in the same
   request (ADR-003 has no job queue). A parse failure is recorded on the
   file as `failed`, `unsupported`, or `unavailable`; it never fails the
   upload. The response already allows 180 s, and a 200-page PDF is seconds
   of CPU.
2. **Use OpenDataLoader for PDF, native readers for everything else.** PDF
   text, per-element layout with bounding boxes, and embedded images come
   from `opendataloader-pdf` (Apache-2.0, Java 11+, CPU only). DOCX/PPTX use
   python-docx/python-pptx; TXT/MD are decoded. Legacy binary `.doc`/`.ppt`
   are reported as unsupported with a message to re-save them, rather than
   adding a second converter.
3. **Store text, layout, and crops as separate blobs.** `file_extractions`
   (one per file) points at gzipped markdown and layout JSON;
   `file_figures` rows carry page, `[left, bottom, right, top]`, caption,
   optional label, and a gzipped JPEG blob. Text that does not fit is
   truncated (with a flag); an oversized figure JPEG is dropped while its
   metadata row is kept. Deleting an upload cascades to all of it.
4. **Drafting includes every ready extraction, capped by characters.** The
   prompt gets the extracted markdown and a figure index naming captions and
   pages, truncated to `MAX_CONTEXT_CHARACTERS`. Uploaded text is wrapped in
   BEGIN/END markers and described as evidence, never instructions.
5. **Figure classification is optional.** A YOLOX-tiny ONNX model can label
   crops when `YOLOX_MODEL_PATH` is set. Weights are never committed; without
   a model the OpenDataLoader boxes are used unchanged. Only decoded
   `[x1, y1, x2, y2, score, class]` exports are supported, and any classifier
   error leaves extraction intact.
6. **Templates are PDF or Word, and Form 1 is the default.** Template upload
   accepts `.docx` and `.pdf` (converted to Word before inspection) and
   rejects anything else. When no active template row exists, generation
   renders the bundled `Form_1_Patent_Application.docx`, which carries the
   title and specification placeholders plus the draft-only warning. An
   uploaded template always wins.

## Consequences

- A fresh deployment produces a real application layout without seeding
  Firestore.
- Extraction adds a Java dependency to the runtime image; the Dockerfile
  installs a headless JRE, and the gunicorn timeout grew to 240 s to cover
  conversion plus extraction.
- Drafting prompts can grow to the context cap; the questionnaire stays
  first, and the cap keeps a long filing from crowding it out.
- A PDF is still not stored: its DOCX conversion is the stored file, while
  extraction reads the original bytes during the request. Re-extracting a
  failed PDF therefore needs a re-upload.
