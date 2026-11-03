"""Statutory form registry.

The five bundled filing forms and the exact variables each one declares.
`declared_variables` is the contract the renderer enforces: a template that
gains or loses a placeholder without updating this file fails the golden
test instead of silently rendering blanks.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormSpec:
    code: str
    label: str
    template: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    supports_figures: bool = False


def _inventor_variables() -> tuple[str, ...]:
    variables: list[str] = []
    for index in range(1, 8):
        variables.extend(
            (
                f"inventor{index}_name",
                f"inventor{index}_nationality",
                f"inventor{index}_address",
            )
        )
    return tuple(variables)


def _inventor_variables_with_country() -> tuple[str, ...]:
    variables: list[str] = []
    for index in range(1, 8):
        variables.extend(
            (
                f"inventor{index}_name",
                f"inventor{index}_nationality",
                f"inventor{index}_country",
                f"inventor{index}_address",
            )
        )
    return tuple(variables)


_AGENT = (
    "agent_name",
    "agent_inpa",
    "agent_mobile",
    "agent_address",
    "agent_telephone",
    "agent_fax",
    "agent_email",
)
_APPLICANT = (
    "applicant_name",
    "applicant_nationality",
    "applicant_address",
)
_COUNTS = (
    "page_count",
    "claim_count",
    "claims_page_count",
    "abstract_page_count",
    "drawing_count",
    "drawing_page_count",
)

FORM1 = FormSpec(
    code="FORM1",
    label="Form 1 — Application for Grant",
    template="forms/FORM1.docx",
    required=(
        "applicant_name",
        "applicant_nationality",
        "applicant_address",
        "title_keyword",
        "generated_date",
        "inventor1_name",
    ),
    optional=_AGENT + _COUNTS + ("applicant_country",) + _inventor_variables_with_country(),
    supports_figures=False,
)

FORM2 = FormSpec(
    code="FORM2",
    label="Form 2 — Complete Specification",
    template="forms/FORM2.docx",
    required=(
        "title_keyword",
        "applicant_name",
        "applicant_address",
        "field",
        "domain",
        "area",
        "invention_keyword",
        "one_line_about_field",
        "two_lines_about_domain",
        "three_lines_about_area",
        "four_lines_about_problem",
        "four_lines_about_solution",
        "advantage1",
        "advantage2",
        "problem_keyword",
        "claim_keyword",
        "data1",
        "data2",
        "exemplary_scenario",
        "detailed_exemplary_scenario",
        "best_working_method",
        "generated_date",
    ),
    optional=(
        "prior_art",
        "agent_name",
        "agent_inpa",
        "applicant_nationality",
        "page_count",
    ),
    supports_figures=False,
)

FORM3 = FormSpec(
    code="FORM3",
    label="Form 3 — Statement and Undertaking",
    template="forms/FORM3.docx",
    required=(
        "applicant_name",
        "applicant_nationality",
        "applicant_address",
        "generated_date",
    ),
    optional=_AGENT,
    supports_figures=False,
)

FORM5 = FormSpec(
    code="FORM5",
    label="Form 5 — Declaration as to Inventorship",
    template="forms/FORM5.docx",
    required=(
        "applicant_name",
        "applicant_address",
        "generated_date",
        "inventor1_name",
    ),
    optional=_AGENT + _APPLICANT + _inventor_variables(),
    supports_figures=False,
)

DRAWINGS = FormSpec(
    code="DRAWINGS",
    label="Drawings",
    template="forms/diagrams.docx",
    required=(
        "applicant_name",
        "title_keyword",
    ),
    optional=(),
    supports_figures=True,
)

FORMS: tuple[FormSpec, ...] = (FORM1, FORM2, FORM3, FORM5, DRAWINGS)
BY_CODE: dict[str, FormSpec] = {spec.code: spec for spec in FORMS}
FORM_CODES: tuple[str, ...] = tuple(spec.code for spec in FORMS)

# The only template variables a generate request may supply directly.
# Everything else comes from the questionnaire, refined fields, parties,
# agent settings, or derived values — never from caller input. Without this,
# a counts entry could overwrite e.g. applicant_name in the context.
COUNT_KEYS = frozenset(
    {
        "page_count",
        "claim_count",
        "claims_page_count",
        "abstract_page_count",
        "drawing_count",
        "drawing_page_count",
    }
)


def declared_variables(spec: FormSpec) -> frozenset[str]:
    """Every variable a form may reference.

    The drawings sheet takes figures through the ``[[FIGURE_BLOCK]]`` marker,
    which is not a Jinja variable and therefore not declared here.
    """
    return frozenset(set(spec.required) | set(spec.optional))
