# ADR-008: Sheet-driven statutory forms with AI-assisted refinement

## Status

Accepted — extends [ADR-004](./ADR-004-stub-first-ai.md),
[ADR-006](./ADR-006-firestore-document-storage.md) and
[ADR-007](./ADR-007-document-ingestion.md).

## Date

2026-11-03

## Context

The current document flow generates five AI text sections and substitutes them
into one bundled Form 1 layout. The team supplied a reference pack
(`data.xlsx`, `final.py`, and five DOCX templates) showing the intended
statutory output: FORM1 (application), FORM2 (complete specification), FORM3
(statement), FORM5 (inventorship declaration) and a drawings sheet, all filled
from a questionnaire-style row. The reference pack is a **design reference
only**: its sample data, fake US prior-art paragraphs, and hardcoded
institution/agent details must not be shipped.

The product needs:

- one comprehensive questionnaire that supplies every value any form needs;
- uploaded documents (text, figures, sketches) feeding the draft;
- images placed into the drawings sheet (and later inline);
- mostly deterministic output, with AI only where judgement is needed;
- a single small drafting disclosure instead of repeated "draft only" text;
- a hard gate when no usable sketch exists.

## Decision

1. **The model never edits Word.** It returns validated JSON field values and
   figure references; a deterministic renderer fills the templates. A text
   model cannot safely manipulate OOXML and tool-calling would be
   provider-specific.
2. **Deterministic core:** questionnaire → canonical profile → template
   mapping → docxtpl render → image embed → disclosure. The system works
   without an AI key.
3. **AI assist layer:** three grouped calls rephrase long-form answers into
   filing-quality fields; an optional vision pass classifies/captions figures
   and suggests placement. Outputs are stored as versioned, editable
   suggestions; invalid output falls back to raw values.
4. **Questionnaire registry:** one backend schema drives PATCH validation,
   projections, version snapshots, frontend groups, AI keys, and per-form
   required-field validation. Unknown keys return 422.
5. **Templates are reference only.** The five DOCX are bundled under
   `app/templates/forms/`. Hardcoded sample content (fake US patents, MIT
   World Peace University, agent Pranav Bhat, fixed dates/counts) is replaced
   with placeholders or config values. Prior art comes from the `prior_art`
   questionnaire field, never from fabricated references.
6. **Figure extraction:** PDF pages are rendered and passed through a YOLO
   detector (pluggable ONNX, CPU or CUDA provider) to find figure/drawing
   regions; embedded images from DOCX/PPTX and direct image uploads are also
   candidates. Deterministic screening (size, blank, duplicate, aspect)
   precedes optional vision classification. Users may override a rejection
   ("Use anyway").
7. **Finalize gate:** form generation is allowed without a usable figure, but
   the set is marked Incomplete and Finalize is blocked until at least one
   usable figure is selected. Finalize is an explicit action recording
   `finalized_at/by`.
8. **One disclosure:** each generated form ends with a single italic grey
   paragraph: "This is for drafting purposes only." No per-section draft-only
   text remains in prompts, stubs, or UI.
9. **Per-form documents:** one `documents` row per form code
   (`FORM1`, `FORM2`, `FORM3`, `FORM5`, `DRAWINGS`), own version counter, and
   a set-level job with per-form results.

## Alternatives considered

### Model edits the template directly (tools / Word automation)
- Rejected: provider-specific, untestable, and the model cannot see pixels or
  Word state. Server-side rendering is deterministic and portable.

### Whole-document JSON in one call
- Rejected: loses per-section regeneration and version history, and one
  malformed field destroys the entire output.

### Vision model required for all figures
- Rejected: most deployments run text-only. Vision is optional behind
  `AI_VISION_ENABLED`; deterministic screening plus user selection is the
  baseline.

### Fake prior art kept in FORM2
- Rejected: fabricated citations in a filing draft are unacceptable. The
  `prior_art` questionnaire field supplies real references; empty means the
  section is omitted with a warning.

## Consequences

- The five forms are legal filing artifacts; template repairs need review
  before they are used to produce output.
- A YOLO detector needs weights (never committed). Without a model the
  pipeline uses OpenDataLoader embedded images and direct uploads only.
- GPU inference is configured per deployment (`YOLO_PROVIDER=cuda|cpu`); the
  Docker image stays CPU-only.
- Questionnaire field changes must update the single registry, not five
  scattered lists.
- The old five-section AI generation path is deprecated once the form path is
  verified; old documents remain downloadable.
