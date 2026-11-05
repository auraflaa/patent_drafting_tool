"""Single source of truth for questionnaire fields.

One registry drives PATCH validation and limits, projections, version
snapshots, frontend groups, AI refine keys, and per-form required-field
validation. Adding a question means adding one `FieldSpec` here — not five
scattered lists.

`required_for_forms` marks the values a statutory form cannot render without;
`ai_group` marks the long-form fields the rephrasing pass may refine.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    group: str
    kind: str  # text | longtext | select | boolean
    limit: int
    required_for_forms: bool = False
    ai_group: str | None = None
    help_text: str = ""


# Existing answers kept as source material for the AI rephrasing pass.
_EXISTING = (
    FieldSpec("invention_type", "Invention type", "identity", "select", 80),
    FieldSpec(
        "problem_statement",
        "Problem statement",
        "background",
        "longtext",
        20_000,
    ),
    FieldSpec(
        "proposed_solution",
        "Proposed solution",
        "solution",
        "longtext",
        20_000,
    ),
    FieldSpec(
        "novelty_description",
        "Novelty",
        "background",
        "longtext",
        20_000,
    ),
    FieldSpec(
        "technical_description",
        "Technical description",
        "embodiments",
        "longtext",
        20_000,
    ),
    FieldSpec(
        "advantages",
        "Advantages",
        "solution",
        "longtext",
        20_000,
    ),
    FieldSpec(
        "prior_art",
        "Prior art",
        "background",
        "longtext",
        20_000,
        help_text="Real references only; the renderer omits the section when empty.",
    ),
    FieldSpec("keywords", "Keywords", "identity", "text", 2_000),
    FieldSpec("has_existing_drawings", "Existing drawings", "drawings", "boolean", 0),
)

# Patent-specific values every statutory form needs.
_NEW = (
    FieldSpec(
        "invention_keyword",
        "Invention keyword",
        "identity",
        "text",
        200,
        required_for_forms=True,
        ai_group="FORM_METADATA",
        help_text="Short noun phrase used in the title, description and claims.",
    ),
    FieldSpec(
        "title_keyword",
        "Title keyword",
        "identity",
        "text",
        200,
        required_for_forms=True,
        ai_group="FORM_METADATA",
        help_text="After 'A SYSTEM AND METHOD FOR ENABLING'; uppercase.",
    ),
    FieldSpec(
        "problem_keyword",
        "Problem keyword",
        "identity",
        "text",
        200,
        required_for_forms=True,
        ai_group="FORM_METADATA",
    ),
    FieldSpec(
        "claim_keyword",
        "Claim subject",
        "identity",
        "text",
        200,
        required_for_forms=True,
        ai_group="FORM_METADATA",
    ),
    FieldSpec(
        "data1",
        "Claim component 1",
        "identity",
        "text",
        500,
        required_for_forms=True,
        ai_group="FORM_METADATA",
    ),
    FieldSpec(
        "data2",
        "Claim component 2",
        "identity",
        "text",
        500,
        required_for_forms=True,
        ai_group="FORM_METADATA",
    ),
    FieldSpec(
        "field",
        "Field of invention",
        "field",
        "text",
        500,
        required_for_forms=True,
        ai_group="FORM_METADATA",
    ),
    FieldSpec(
        "domain",
        "Domain",
        "field",
        "text",
        500,
        required_for_forms=True,
        ai_group="FORM_METADATA",
    ),
    FieldSpec(
        "area",
        "Area",
        "field",
        "text",
        500,
        required_for_forms=True,
        ai_group="FORM_METADATA",
    ),
    FieldSpec(
        "one_line_about_field",
        "One line about the field",
        "background",
        "longtext",
        1_000,
        required_for_forms=True,
        ai_group="FORM_BACKGROUND",
    ),
    FieldSpec(
        "two_lines_about_domain",
        "Two lines about the domain",
        "background",
        "longtext",
        1_500,
        required_for_forms=True,
        ai_group="FORM_BACKGROUND",
    ),
    FieldSpec(
        "three_lines_about_area",
        "Three lines about the area",
        "background",
        "longtext",
        2_000,
        required_for_forms=True,
        ai_group="FORM_BACKGROUND",
    ),
    FieldSpec(
        "four_lines_about_problem",
        "Four lines about the problem",
        "background",
        "longtext",
        3_000,
        required_for_forms=True,
        ai_group="FORM_BACKGROUND",
    ),
    FieldSpec(
        "four_lines_about_solution",
        "Four lines about the solution",
        "solution",
        "longtext",
        3_000,
        required_for_forms=True,
        ai_group="FORM_BACKGROUND",
    ),
    FieldSpec(
        "advantage1",
        "First object",
        "solution",
        "longtext",
        1_500,
        required_for_forms=True,
        ai_group="FORM_BACKGROUND",
    ),
    FieldSpec(
        "advantage2",
        "Second object",
        "solution",
        "longtext",
        1_500,
        required_for_forms=True,
        ai_group="FORM_BACKGROUND",
    ),
    FieldSpec(
        "exemplary_scenario",
        "Exemplary scenario",
        "embodiments",
        "longtext",
        6_000,
        required_for_forms=True,
        ai_group="FORM_EMBODIMENTS",
    ),
    FieldSpec(
        "detailed_exemplary_scenario",
        "Detailed exemplary scenario",
        "embodiments",
        "longtext",
        12_000,
        required_for_forms=True,
        ai_group="FORM_EMBODIMENTS",
    ),
    FieldSpec(
        "best_working_method",
        "Best working method",
        "embodiments",
        "longtext",
        6_000,
        required_for_forms=True,
        ai_group="FORM_EMBODIMENTS",
    ),
)

QUESTIONNAIRE_FIELDS: tuple[str, ...] = tuple(
    spec.key for spec in (*_EXISTING, *_NEW)
)
FIELD_BY_KEY: dict[str, FieldSpec] = {
    spec.key: spec for spec in (*_EXISTING, *_NEW)
}
TEXT_LIMITS: dict[str, int] = {
    spec.key: spec.limit
    for spec in (*_EXISTING, *_NEW)
    if spec.kind in {"text", "longtext"}
}
REQUIRED_FOR_FORMS: tuple[str, ...] = tuple(
    spec.key for spec in (*_EXISTING, *_NEW) if spec.required_for_forms
)
AI_GROUPS: dict[str, tuple[str, ...]] = {
    group: tuple(spec.key for spec in (*_EXISTING, *_NEW) if spec.ai_group == group)
    for group in ("FORM_METADATA", "FORM_BACKGROUND", "FORM_EMBODIMENTS")
}

# Kept for the pre-existing submit gate; form generation uses
# REQUIRED_FOR_FORMS instead.
REQUIRED_QUESTIONNAIRE_FIELDS = (
    "invention_type",
    "problem_statement",
    "proposed_solution",
    "novelty_description",
    "technical_description",
)


def group_fields(group: str) -> tuple[FieldSpec, ...]:
    return tuple(spec for spec in (*_EXISTING, *_NEW) if spec.group == group)


def groups() -> tuple[str, ...]:
    seen: list[str] = []
    for spec in (*_EXISTING, *_NEW):
        if spec.group not in seen:
            seen.append(spec.group)
    return tuple(seen)
