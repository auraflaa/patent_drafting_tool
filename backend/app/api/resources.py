"""Firestore-backed resource API.

Every endpoint the React client calls is implemented here against Firebase
Auth and Firestore, which also stores the compressed document bytes
(ADR-006). Response shapes intentionally match the original snake_case REST
contract (string IDs, Title-Case lifecycle statuses, `roles`,
`invention_title`, ...) so the existing UI keeps working without a
parallel compatibility layer.
"""
import csv
import io
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.limits import upload_limit_detail
from app.core.logging import log_event
from app.core.security import (
    active_user,
    ensure_permission,
    ensure_super_admin_survives,
    has_permission,
    is_admin,
    is_super_admin,
)
from app.services import blobs
from app.services import documents as docgen
from app.services import drafting
from app.services import extraction_store
from app.services import form_ai
from app.services import form_generation
from app.services import uploads
from app.services.form_specs import BY_CODE as FORM_BY_CODE
from app.services.form_specs import COUNT_KEYS
from app.services.questionnaire_schema import FIELD_BY_KEY
from app.services.projections import (
    CALENDAR_EVENT_TYPES,
    PRE_ASSIGNMENT_STATUSES,
    QUESTIONNAIRE_FIELDS,
    REQUIRED_QUESTIONNAIRE_FIELDS,
    TERMINAL_STATUSES,
    active_assignment_count,
    ai_output_out,
    applicant_out,
    can_edit_basic_info,
    can_review_draft,
    calendar_event_out,
    comment_out,
    document_job_out,
    document_out,
    document_version_out,
    figure_out,
    refined_group_out,
    file_out,
    inventor_out,
    is_patent_creator,
    is_team_member,
    log_activity,
    notification_out,
    notify_admins,
    notify_many,
    patent_out,
    patent_participants,
    questionnaire_completion,
    questionnaire_out,
    questionnaire_version_out,
    require_patent,
    team_detail_out,
    team_out,
    template_out,
    upcoming_events,
    user_out,
    visible_patents,
)
from app.services.rbac import (
    ALL_ROLE_CODES,
    PATENT_AGENT,
    REPORT_TYPE_NAMES,
    REPORT_TYPES,
    can_download_report,
    matrix,
    report_matrix,
    toggle_grant,
    toggle_report_permission,
)
from app.services.repository import (
    allocate_counter,
    create_doc,
    delete_doc,
    get_doc,
    get_doc_or_none,
    list_docs,
    now_iso,
    patch_doc,
    query_docs,
    set_latest_version,
    sort_docs,
    write_doc,
)

router = APIRouter()

logger = logging.getLogger(__name__)

DOCUMENT_TYPE = "Patent Application"


@router.get("/config/capabilities", tags=["Configuration"])
def runtime_capabilities(response: Response):
    """Public runtime limits; the UI uses these to fail fast and adapt."""
    capabilities = settings.capabilities()
    response.headers["Cache-Control"] = "no-store"
    return capabilities


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _users_by_id() -> dict[str, dict]:
    return {doc["id"]: doc for doc in list_docs("users")}


def _title_map() -> dict[str, str]:
    return {
        doc["id"]: doc.get("invention_title") or ""
        for doc in list_docs("patents")
    }


MAX_DOWNLOAD_FILENAME = 150


def _clean_filename(name: str) -> str:
    """Reduce a user-supplied name to a header-safe basename.

    Control characters become spaces so a newline cannot start a header,
    quotes are replaced because they delimit the `filename` parameter, and
    backslashes are replaced because Windows names use them as separators
    even though `PurePath` on Linux does not.
    """
    safe = PurePath(name or "download").name
    safe = "".join(ch if ch.isprintable() else " " for ch in safe)
    safe = safe.replace('"', "'").replace("\\", "_").strip()
    if len(safe) > MAX_DOWNLOAD_FILENAME:
        suffix = PurePath(safe).suffix
        keep = MAX_DOWNLOAD_FILENAME - len(suffix)
        safe = f"{safe[:keep]}{suffix}" if keep > 0 else safe[:MAX_DOWNLOAD_FILENAME]
    return safe or "download"


def _content_disposition(filename: str) -> dict[str, str]:
    """Always-ASCII `filename` plus RFC 5987 `filename*` for other scripts.

    Starlette encodes headers as Latin-1, so a Japanese or emoji filename in
    the plain parameter would raise `UnicodeEncodeError` and turn a download
    into a 500. The ASCII fallback keeps old clients working; modern browsers
    prefer the UTF-8 parameter.
    """
    safe = _clean_filename(filename)
    ascii_name = safe.encode("ascii", "replace").decode("ascii")
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(safe, safe='')}"
        )
    }


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formulas in exported CSV cells."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _now() -> str:
    return now_iso()


def _set_patent(patent_id: str, fields: dict) -> dict:
    return patch_doc("patents", patent_id, fields)


def _parse_iso(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Dates must be ISO-8601 timestamps."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


# Firestore caps a document at 1 MiB. These bounds keep every text field far
# below that, reject non-string payloads instead of stringifying them, and stop
# control characters from reaching stored text or CSV exports.
# USPTO titles are capped at 500 characters (37 CFR 1.72(a)); this is a
# little above typical drafting guidance and still far below a Firestore doc.
MAX_TITLE_CHARS = 500
# Reassignment and rejection reasons are free text; keep them well below the
# Firestore document limit like every other user-supplied string.
MAX_REASON_CHARS = 2_000
APPLICANT_TEXT_LIMITS = {
    "full_name_or_org_name": 200,
    "address": 500,
    "country": 80,
    "postal_code": 32,
    "email": 254,
    "phone": 40,
}
INVENTOR_TEXT_LIMITS = {
    "full_name": 200,
    "address": 500,
    "country": 80,
    "postal_code": 32,
    "email": 254,
    "phone": 40,
}
MULTILINE_FIELDS = {"address"}

# Counts are caller-supplied template variables (fee-table page/claim totals).
# Cap them well below any rendering budget; unknown keys are rejected here so
# a misspelled field surfaces instead of being silently dropped downstream.
MAX_COUNT_CHARS = 40


def _bounded_text(
    value, field: str, limit: int, *, allow_newlines: bool = False
) -> str | None:
    """Return a stripped string, or reject it with a 422.

    `None` and blank strings mean "clear this field". Anything else must be a
    string within `limit`; newlines and tabs are only accepted where the field
    is expected to be multi-line.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{field} must be a string.",
        )
    text = value.strip()
    if not text:
        return None
    if len(text) > limit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{field} must be at most {limit} characters.",
        )
    allowed_controls = {"\n", "\r", "\t"} if allow_newlines else set()
    if any(
        (ord(char) < 32 or ord(char) == 127) and char not in allowed_controls
        for char in text
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{field} must not contain control characters.",
        )
    return text


def _party_texts(
    payload: dict, limits: dict[str, int], *, only_present: bool
) -> dict[str, str | None]:
    return {
        field: _bounded_text(
            payload.get(field),
            field,
            limit,
            allow_newlines=field in MULTILINE_FIELDS,
        )
        for field, limit in limits.items()
        if not only_present or field in payload
    }


def _questionnaire_patch(payload: dict) -> dict:
    unknown = sorted(set(payload) - set(QUESTIONNAIRE_FIELDS))
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unknown questionnaire field(s): " + ", ".join(unknown) + ".",
        )
    data: dict = {}
    for field in QUESTIONNAIRE_FIELDS:
        if field not in payload:
            continue
        spec = FIELD_BY_KEY[field]
        value = payload[field]
        if spec.kind == "boolean":
            if value is not None and not isinstance(value, bool):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"{field} must be a boolean.",
                )
            data[field] = value
            continue
        data[field] = _bounded_text(
            value,
            field,
            spec.limit,
            allow_newlines=True,
        )
    return data


def _agent_or_404(agent_id: str) -> dict:
    agent = get_doc_or_none("users", str(agent_id))
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent Agent not found.")
    if (
        PATENT_AGENT not in (agent.get("role_codes") or [])
        or agent.get("account_status") != "approved"
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The selected user is not an approved Patent Agent.",
        )
    agent["id"] = agent.get("id") or str(agent_id)
    return agent


def _available_agents() -> list[dict]:
    agents = [
        doc
        for doc in list_docs("users")
        if PATENT_AGENT in (doc.get("role_codes") or [])
        and doc.get("account_status") == "approved"
    ]
    rows = [
        {
            "id": agent["id"],
            "full_name": agent.get("full_name") or "",
            "email": agent.get("email") or "",
            "active_assignment_count": active_assignment_count(agent["id"]),
        }
        for agent in agents
    ]
    return sorted(
        rows, key=lambda row: (row["active_assignment_count"], row["full_name"].lower())
    )


def _visible_team(team_id: str, user: dict) -> dict:
    team = get_doc_or_none("teams", str(team_id))
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    if not (
        is_admin(user)
        or team.get("created_by") == user["uid"]
        or is_team_member(team["id"], user["uid"])
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this team.")
    return team


def _questionnaire(patent_id: str) -> dict:
    found = query_docs(
        "questionnaires", filters=[("patent_application_id", "==", patent_id)], limit=1
    )
    if found:
        return found[0]
    return create_doc(
        "questionnaires",
        {
            "patent_application_id": patent_id,
            "questionnaire_status": "Not Started",
            "completion_percentage": "0.00",
        },
    )


def _questionnaire_payload(questionnaire: dict) -> dict:
    return questionnaire_out(questionnaire)


def _assert_basic_info_editable(
    patent: dict, user: dict, *, permission: str = "BASIC_INFO_EDIT"
) -> None:
    if patent.get("application_status") != "Draft":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Basic information is read-only after the application is submitted.",
        )
    if not can_edit_basic_info(patent, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the application owner (or an Admin) can edit basic information.",
        )
    ensure_permission(user, permission)


def _ordered_items(
    collection: str, patent_id: str, order_field: str
) -> list[dict]:
    items = query_docs(
        collection, filters=[("patent_application_id", "==", patent_id)]
    )
    return sorted(items, key=lambda doc: (doc.get(order_field) or 0, doc["id"]))


def _validate_ids(ordered_ids: list[str], existing: list[dict]) -> None:
    existing_ids = {doc["id"] for doc in existing}
    if set(ordered_ids) != existing_ids or len(ordered_ids) != len(existing):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ordered_ids must contain every item exactly once.",
        )


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


@router.get("/teams")
def list_teams(user: dict = Depends(active_user)):
    ensure_permission(user, "TEAMS_VIEW")
    teams = list_docs("teams")
    if not is_admin(user):
        teams = [
            team
            for team in teams
            if team.get("created_by") == user["uid"]
            or is_team_member(team["id"], user["uid"])
        ]
    teams = sort_docs(teams, "created_at")
    return [team_out(team) for team in teams]


@router.post("/teams", status_code=status.HTTP_201_CREATED)
def create_team(payload: dict, user: dict = Depends(active_user)):
    ensure_permission(user, "TEAMS_MANAGE")
    name = _bounded_text(payload.get("team_name"), "team_name", 200)
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team_name is required.")
    team = create_doc(
        "teams",
        {
            "team_name": name,
            "team_status": "Active",
            "created_by": user["uid"],
        },
    )
    write_doc(
        f"teams/{team['id']}/members",
        user["uid"],
        {
            "user_id": user["uid"],
            "membership_status": "Active",
            "added_by": user["uid"],
            "created_at": _now(),
        },
        merge=False,
    )
    log_activity(user["uid"], "TeamCreated", "Team", team["id"])
    return team_out(team)


@router.get("/teams/{team_id}")
def get_team(team_id: str, user: dict = Depends(active_user)):
    ensure_permission(user, "TEAMS_VIEW")
    return team_detail_out(_visible_team(team_id, user))


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
def add_team_member(team_id: str, payload: dict, user: dict = Depends(active_user)):
    ensure_permission(user, "TEAMS_MANAGE")
    team = _visible_team(team_id, user)
    if not (is_admin(user) or team.get("created_by") == user["uid"]):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the team owner can add members."
        )
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "email is required.")
    matches = [
        doc for doc in list_docs("users") if (doc.get("email") or "").lower() == email
    ]
    if not matches:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No account exists for that email yet. Ask them to sign in first.",
        )
    member = matches[0]
    write_doc(
        f"teams/{team_id}/members",
        member["id"],
        {
            "user_id": member["id"],
            "membership_status": "Active",
            "added_by": user["uid"],
            "created_at": _now(),
        },
        merge=True,
    )
    return team_detail_out(team)


@router.delete("/teams/{team_id}/members/{member_id}")
def remove_team_member(
    team_id: str, member_id: str, user: dict = Depends(active_user)
):
    ensure_permission(user, "TEAMS_MANAGE")
    team = _visible_team(team_id, user)
    if not (is_admin(user) or team.get("created_by") == user["uid"]):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the team owner can remove members."
        )
    if str(member_id) == str(team.get("created_by")):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The team owner cannot be removed."
        )
    delete_doc(
        f"teams/{team_id}/members",
        str(member_id),
        not_found="Team member not found.",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Patent applications
# ---------------------------------------------------------------------------


@router.get("/patents/available-agents")
def available_agents(user: dict = Depends(active_user)):
    ensure_permission(user, "PATENTS_ASSIGN")
    return _available_agents()


@router.get("/patents")
def list_patents(user: dict = Depends(active_user)):
    ensure_permission(user, "PATENTS_VIEW")
    return [patent_out(doc) for doc in sort_docs(visible_patents(user), "created_at", reverse=True)]


@router.post("/patents", status_code=status.HTTP_201_CREATED)
def create_patent(payload: dict, user: dict = Depends(active_user)):
    ensure_permission(user, "PATENTS_CREATE")
    title = _bounded_text(
        payload.get("invention_title"), "invention_title", MAX_TITLE_CHARS
    )
    team_id = payload.get("team_id")
    if not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invention_title is required.")
    if not team_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team_id is required.")
    _visible_team(str(team_id), user)

    patent = create_doc(
        "patents",
        {
            "team_id": str(team_id),
            "invention_title": title,
            "application_status": "Draft",
            "assigned_patent_agent_id": None,
            "ai_status": "Not Started",
            "questionnaire_status": "Not Started",
            "document_status": "Not Started",
            "filing_status": "Not Started",
            "official_application_number": None,
            "filing_date": None,
            "created_by": user["uid"],
        },
    )
    create_doc(
        "questionnaires",
        {
            "patent_application_id": patent["id"],
            "questionnaire_status": "Not Started",
            "completion_percentage": "0.00",
        },
    )
    log_activity(user["uid"], "PatentCreated", "PatentApplication", patent["id"])
    return patent_out(patent)


@router.get("/patents/{patent_id}")
def get_patent(patent_id: str, user: dict = Depends(active_user)):
    ensure_permission(user, "PATENTS_VIEW")
    return patent_out(require_patent(patent_id, user))


@router.patch("/patents/{patent_id}")
def update_patent(patent_id: str, payload: dict, user: dict = Depends(active_user)):
    """Rename a draft application. The title is the only editable field."""
    ensure_permission(user, "PATENTS_EDIT")
    patent = require_patent(patent_id, user)
    if not (is_patent_creator(patent, user) or is_admin(user)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the application owner can edit it."
        )
    if patent.get("application_status") != "Draft":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only Draft applications can be edited.",
        )
    if "invention_title" not in payload:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invention_title is required."
        )
    title = _bounded_text(
        payload.get("invention_title"), "invention_title", MAX_TITLE_CHARS
    )
    if not title:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invention_title is required."
        )
    updated = _set_patent(patent_id, {"invention_title": title})
    log_activity(user["uid"], "PatentEdited", "PatentApplication", patent_id)
    return patent_out(updated)


@router.post("/patents/{patent_id}/submit")
def submit_patent(patent_id: str, user: dict = Depends(active_user)):
    ensure_permission(user, "PATENTS_SUBMIT")
    patent = require_patent(patent_id, user)
    if not (is_patent_creator(patent, user) or is_admin(user)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the application owner can submit it."
        )
    if patent.get("application_status") != "Draft":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only Draft applications can be submitted.",
        )
    # Submitting freezes the questionnaire (`_assert_basic_info_editable` only
    # allows edits while the application is Draft) and draft generation
    # requires a Completed questionnaire, so an incomplete one would strand
    # the application permanently.
    questionnaire = _questionnaire(patent_id)
    if questionnaire.get("questionnaire_status") != "Completed":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Submit the questionnaire before submitting the application. "
            "The questionnaire becomes read-only afterwards.",
        )
    updated = _set_patent(patent_id, {"application_status": "Submitted"})
    notify_admins(patent_id, "Submitted")
    log_activity(user["uid"], "PatentSubmitted", "PatentApplication", patent_id)
    return patent_out(updated)


def _record_assignment(
    patent_id: str,
    previous: str | None,
    agent_id: str,
    reason: str,
    changed_by: str,
) -> None:
    """Append the audit row every assignment change must leave behind."""
    create_doc(
        "assignment_history",
        {
            "patent_application_id": patent_id,
            "from_agent_id": previous,
            "to_agent_id": agent_id,
            "reason": reason,
            "changed_by": changed_by,
        },
    )


@router.post("/patents/{patent_id}/assign")
def assign_agent(patent_id: str, payload: dict, user: dict = Depends(active_user)):
    ensure_permission(user, "PATENTS_ASSIGN")
    patent = require_patent(patent_id, user)
    if not (is_patent_creator(patent, user) or is_admin(user)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the application owner can assign an agent."
        )
    if patent.get("application_status") != "Submitted":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "An agent can only be assigned to a submitted application that has "
            "not been accepted yet.",
        )
    agent_id = payload.get("patent_agent_id")
    if not agent_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "patent_agent_id is required."
        )
    _agent_or_404(str(agent_id))
    previous = patent.get("assigned_patent_agent_id")
    updated = _set_patent(
        patent_id,
        {
            "assigned_patent_agent_id": str(agent_id),
            "application_status": "Awaiting Patent Agent Acceptance",
        },
    )
    _record_assignment(
        patent_id, previous, str(agent_id), "Initial assignment", user["uid"]
    )
    notify_many({str(agent_id)}, patent_id, "Assigned")
    log_activity(user["uid"], "AgentAssigned", "PatentApplication", patent_id)
    return patent_out(updated)


@router.post("/patents/{patent_id}/auto-assign")
def auto_assign_agent(patent_id: str, user: dict = Depends(active_user)):
    ensure_permission(user, "PATENTS_ASSIGN")
    patent = require_patent(patent_id, user)
    if not (is_patent_creator(patent, user) or is_admin(user)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the application owner can assign an agent."
        )
    if patent.get("application_status") != "Submitted":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "An agent can only be assigned to a submitted application that has "
            "not been accepted yet.",
        )
    agents = _available_agents()
    if not agents:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No approved Patent Agents are available."
        )
    agent_id = agents[0]["id"]
    previous = patent.get("assigned_patent_agent_id")
    updated = _set_patent(
        patent_id,
        {
            "assigned_patent_agent_id": agent_id,
            "application_status": "Awaiting Patent Agent Acceptance",
        },
    )
    _record_assignment(
        patent_id, previous, agent_id, "Auto-assignment", user["uid"]
    )
    notify_many({agent_id}, patent_id, "Assigned")
    log_activity(user["uid"], "AgentAutoAssigned", "PatentApplication", patent_id)
    return patent_out(updated)


@router.post("/patents/{patent_id}/reassign")
def reassign_agent(patent_id: str, payload: dict, user: dict = Depends(active_user)):
    ensure_permission(user, "PATENTS_REASSIGN")
    if not is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required.")
    patent = require_patent(patent_id, user)
    current = patent.get("application_status")
    if current in PRE_ASSIGNMENT_STATUSES or current in TERMINAL_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This application is not in a reassignable state.",
        )
    agent_id = payload.get("patent_agent_id")
    reason = _bounded_text(payload.get("reason"), "reason", MAX_REASON_CHARS)
    if not agent_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "patent_agent_id is required."
        )
    if not reason:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A reassignment reason is required."
        )
    _agent_or_404(str(agent_id))
    previous = patent.get("assigned_patent_agent_id")
    updated = _set_patent(
        patent_id,
        {
            "assigned_patent_agent_id": str(agent_id),
            "application_status": "Awaiting Patent Agent Acceptance",
        },
    )
    _record_assignment(patent_id, previous, str(agent_id), reason, user["uid"])
    notify_many({str(agent_id)}, patent_id, "Assigned")
    if previous:
        notify_many({str(previous)}, patent_id, "Reassigned")
    log_activity(user["uid"], "AgentReassigned", "PatentApplication", patent_id)
    return patent_out(updated)


@router.post("/patents/{patent_id}/assignment/accept")
def accept_assignment(patent_id: str, user: dict = Depends(active_user)):
    patent = require_patent(patent_id, user)
    if patent.get("assigned_patent_agent_id") != user["uid"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This application is not assigned to you."
        )
    if patent.get("application_status") != "Awaiting Patent Agent Acceptance":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "There is no pending assignment to accept."
        )
    updated = _set_patent(patent_id, {"application_status": "Under Review"})
    notify_many({str(patent.get("created_by"))}, patent_id, "Accepted")
    log_activity(user["uid"], "AssignmentAccepted", "PatentApplication", patent_id)
    return patent_out(updated)


@router.post("/patents/{patent_id}/assignment/reject")
def reject_assignment(
    patent_id: str, payload: dict | None = None, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    if patent.get("assigned_patent_agent_id") != user["uid"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This application is not assigned to you."
        )
    if patent.get("application_status") != "Awaiting Patent Agent Acceptance":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "There is no pending assignment to reject."
        )
    payload = payload or {}
    updated = _set_patent(
        patent_id,
        {
            "assigned_patent_agent_id": None,
            "application_status": "Submitted",
        },
    )
    reason = _bounded_text(payload.get("reason"), "reason", MAX_REASON_CHARS)
    _record_assignment(
        patent_id,
        user["uid"],
        None,
        reason or "Declined by agent",
        user["uid"],
    )
    notify_many({str(patent.get("created_by"))}, patent_id, "Rejected")
    log_activity(user["uid"], "AssignmentRejected", "PatentApplication", patent_id)
    return patent_out(updated)


# ---------------------------------------------------------------------------
# Applicants and inventors
# ---------------------------------------------------------------------------


APPLICANT_TYPES = {"Individual", "Startup", "Company", "University"}
APPLICANT_FIELDS = (
    "applicant_type",
    "full_name_or_org_name",
    "address",
    "country",
    "postal_code",
    "email",
    "phone",
    "is_primary",
)


def _apply_primary(patent_id: str, keep_id: str) -> None:
    for doc in query_docs(
        "applicants", filters=[("patent_application_id", "==", patent_id)]
    ):
        if doc["id"] != keep_id and doc.get("is_primary"):
            patch_doc("applicants", doc["id"], {"is_primary": False})


@router.get("/patents/{patent_id}/applicants")
def list_applicants(patent_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    return [
        applicant_out(doc)
        for doc in _ordered_items("applicants", patent_id, "display_order")
    ]


@router.post("/patents/{patent_id}/applicants", status_code=status.HTTP_201_CREATED)
def create_applicant(patent_id: str, payload: dict, user: dict = Depends(active_user)):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user)
    applicant_type = payload.get("applicant_type") or "Individual"
    if applicant_type not in APPLICANT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown applicant_type.")
    texts = _party_texts(payload, APPLICANT_TEXT_LIMITS, only_present=False)
    name = texts.pop("full_name_or_org_name")
    if not name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "full_name_or_org_name is required."
        )
    existing = _ordered_items("applicants", patent_id, "display_order")
    data = {
        "patent_application_id": patent_id,
        "applicant_type": applicant_type,
        "full_name_or_org_name": name,
        **texts,
        "is_primary": bool(payload.get("is_primary")) or not existing,
        "display_order": len(existing),
    }
    created = create_doc("applicants", data)
    if created["is_primary"]:
        _apply_primary(patent_id, created["id"])
    return applicant_out(get_doc("applicants", created["id"]))


@router.patch("/patents/{patent_id}/applicants/{applicant_id}")
def update_applicant(
    patent_id: str,
    applicant_id: str,
    payload: dict,
    user: dict = Depends(active_user),
):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user)
    applicant = get_doc("applicants", applicant_id)
    if applicant.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Applicant not found.")
    data = {key: payload[key] for key in APPLICANT_FIELDS if key in payload}
    if "applicant_type" in data and data["applicant_type"] not in APPLICANT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown applicant_type.")
    data.update(_party_texts(payload, APPLICANT_TEXT_LIMITS, only_present=True))
    if "full_name_or_org_name" in data and not data["full_name_or_org_name"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "full_name_or_org_name is required."
        )
    if data.get("is_primary") is False and applicant.get("is_primary"):
        others = [
            doc
            for doc in _ordered_items("applicants", patent_id, "display_order")
            if doc["id"] != applicant_id and doc.get("is_primary")
        ]
        if not others:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "At least one applicant must be primary.",
            )
    updated = patch_doc("applicants", applicant_id, data)
    if updated.get("is_primary"):
        _apply_primary(patent_id, applicant_id)
    return applicant_out(get_doc("applicants", applicant_id))


@router.delete("/patents/{patent_id}/applicants/{applicant_id}")
def delete_applicant(
    patent_id: str, applicant_id: str, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user)
    applicant = get_doc("applicants", applicant_id)
    if applicant.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Applicant not found.")
    delete_doc("applicants", applicant_id)
    remaining = _ordered_items("applicants", patent_id, "display_order")
    if applicant.get("is_primary") and remaining:
        patch_doc("applicants", remaining[0]["id"], {"is_primary": True})
    for index, doc in enumerate(remaining):
        if int(doc.get("display_order") or 0) != index:
            patch_doc("applicants", doc["id"], {"display_order": index})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/patents/{patent_id}/applicants/reorder")
def reorder_applicants(
    patent_id: str, payload: dict, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user)
    existing = _ordered_items("applicants", patent_id, "display_order")
    ordered_ids = [str(value) for value in payload.get("ordered_ids") or []]
    _validate_ids(ordered_ids, existing)
    for index, item_id in enumerate(ordered_ids):
        patch_doc("applicants", item_id, {"display_order": index})
    return [
        applicant_out(doc)
        for doc in _ordered_items("applicants", patent_id, "display_order")
    ]


@router.get("/patents/{patent_id}/inventors")
def list_inventors(patent_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    return [
        inventor_out(doc)
        for doc in _ordered_items("inventors", patent_id, "inventor_order")
    ]


@router.post("/patents/{patent_id}/inventors", status_code=status.HTTP_201_CREATED)
def create_inventor(patent_id: str, payload: dict, user: dict = Depends(active_user)):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user)
    texts = _party_texts(payload, INVENTOR_TEXT_LIMITS, only_present=False)
    name = texts["full_name"]
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "full_name is required.")
    existing = _ordered_items("inventors", patent_id, "inventor_order")
    data = {
        "patent_application_id": patent_id,
        "user_id": payload.get("user_id"),
        **texts,
        "inventor_order": len(existing),
    }
    created = create_doc("inventors", data)
    return inventor_out(created)


@router.patch("/patents/{patent_id}/inventors/{inventor_id}")
def update_inventor(
    patent_id: str,
    inventor_id: str,
    payload: dict,
    user: dict = Depends(active_user),
):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user)
    inventor = get_doc("inventors", inventor_id)
    if inventor.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventor not found.")
    data = _party_texts(payload, INVENTOR_TEXT_LIMITS, only_present=True)
    if "full_name" in data and not data["full_name"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "full_name is required.")
    return inventor_out(patch_doc("inventors", inventor_id, data))


@router.delete("/patents/{patent_id}/inventors/{inventor_id}")
def delete_inventor(
    patent_id: str, inventor_id: str, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user)
    inventor = get_doc("inventors", inventor_id)
    if inventor.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventor not found.")
    delete_doc("inventors", inventor_id)
    remaining = _ordered_items("inventors", patent_id, "inventor_order")
    for index, doc in enumerate(remaining):
        if int(doc.get("inventor_order") or 0) != index:
            patch_doc("inventors", doc["id"], {"inventor_order": index})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/patents/{patent_id}/inventors/reorder")
def reorder_inventors(
    patent_id: str, payload: dict, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user)
    existing = _ordered_items("inventors", patent_id, "inventor_order")
    ordered_ids = [str(value) for value in payload.get("ordered_ids") or []]
    _validate_ids(ordered_ids, existing)
    for index, item_id in enumerate(ordered_ids):
        patch_doc("inventors", item_id, {"inventor_order": index})
    return [
        inventor_out(doc)
        for doc in _ordered_items("inventors", patent_id, "inventor_order")
    ]


# ---------------------------------------------------------------------------
# Questionnaire
# ---------------------------------------------------------------------------


@router.get("/patents/{patent_id}/questionnaire")
def get_questionnaire(patent_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    return _questionnaire_payload(_questionnaire(patent_id))


@router.patch("/patents/{patent_id}/questionnaire")
def update_questionnaire(
    patent_id: str, payload: dict, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user, permission="QUESTIONNAIRE_EDIT")
    questionnaire = _questionnaire(patent_id)
    data = _questionnaire_patch(payload)
    merged = {**questionnaire, **data}
    if merged.get("questionnaire_status") == "Completed":
        merged["questionnaire_status"] = "In Progress"
    computed_status, percentage = questionnaire_completion(merged)
    merged["questionnaire_status"] = computed_status
    merged["completion_percentage"] = percentage
    data["questionnaire_status"] = computed_status
    data["completion_percentage"] = percentage
    patch_doc("questionnaires", questionnaire["id"], data)
    _set_patent(patent_id, {"questionnaire_status": computed_status})
    return _questionnaire_payload(get_doc("questionnaires", questionnaire["id"]))


@router.post("/patents/{patent_id}/questionnaire/submit")
def submit_questionnaire(patent_id: str, user: dict = Depends(active_user)):
    patent = require_patent(patent_id, user)
    _assert_basic_info_editable(patent, user, permission="QUESTIONNAIRE_SUBMIT")
    questionnaire = _questionnaire(patent_id)
    missing = [
        field
        for field in REQUIRED_QUESTIONNAIRE_FIELDS
        if questionnaire.get(field) in (None, "", [], False)
    ]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Complete the required questionnaire fields first: "
            + ", ".join(field.replace("_", " ") for field in missing)
            + ".",
        )
    versions = query_docs(
        "questionnaire_versions",
        filters=[("patent_application_id", "==", patent_id)],
    )
    # Two submits racing the old read-max-then-write both minted the same
    # number. The transaction serialises the claims; the floor keeps legacy
    # rows (written before counters existed) from colliding with new claims.
    version_number = allocate_counter(
        "questionnaire_counters",
        patent_id,
        floor=max(
            [int(doc.get("version_number") or 0) for doc in versions] or [0]
        ),
    )
    snapshot = {
        "questionnaire_id": questionnaire["id"],
        "patent_application_id": patent_id,
        "version_number": version_number,
        "version_status": "Completed",
        "change_reason": "Submitted by the applicant",
        "created_by": user["uid"],
        **{field: questionnaire.get(field) for field in QUESTIONNAIRE_FIELDS},
    }
    create_doc("questionnaire_versions", snapshot)
    # The missing-field guard above already proved every
    # REQUIRED_QUESTIONNAIRE_FIELDS entry is filled (same shared predicate as
    # questionnaire_completion), so completion is definitionally 100% here.
    # The hardcoded values stay in one place with the guard instead of
    # round-tripping through questionnaire_completion, which can only ever
    # return "Not Started"/"In Progress" by design.
    patch_doc(
        "questionnaires",
        questionnaire["id"],
        {
            "questionnaire_status": "Completed",
            "completion_percentage": "100.00",
        },
    )
    _set_patent(patent_id, {"questionnaire_status": "Completed"})
    log_activity(user["uid"], "QuestionnaireSubmitted", "PatentApplication", patent_id)
    return _questionnaire_payload(get_doc("questionnaires", questionnaire["id"]))


@router.get("/patents/{patent_id}/questionnaire/versions")
def questionnaire_versions(patent_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    versions = query_docs(
        "questionnaire_versions",
        filters=[("patent_application_id", "==", patent_id)],
    )
    versions = sort_docs(versions, "version_number", reverse=True)
    return [questionnaire_version_out(doc) for doc in versions]


# ---------------------------------------------------------------------------
# AI drafts
# ---------------------------------------------------------------------------


def _draft_outputs(patent_id: str) -> list[dict]:
    return query_docs("drafts", filters=[("patent_application_id", "==", patent_id)])


@router.get("/patents/{patent_id}/draft")
def get_draft(patent_id: str, user: dict = Depends(active_user)):
    patent = require_patent(patent_id, user)
    if not can_review_draft(patent, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can open the drafting workspace.",
        )
    ensure_permission(user, "DRAFTS_VIEW")
    outputs = _draft_outputs(patent_id)
    slots = []
    for section in drafting.SECTION_TYPES:
        section_outputs = [
            doc for doc in outputs if doc.get("section_type") == section
        ]
        latest = max(
            section_outputs,
            key=lambda doc: int(doc.get("version_number") or 0),
            default=None,
        )
        slots.append(
            {
                "section_type": section,
                "latest": ai_output_out(latest) if latest else None,
            }
        )
    return slots


@router.post("/patents/{patent_id}/draft/generate")
def generate_draft(
    patent_id: str, payload: dict | None = None, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    if not (can_review_draft(patent, user)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can generate drafts.",
        )
    ensure_permission(user, "DRAFTS_GENERATE")
    if patent.get("application_status") != "Under Review":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            'Draft generation requires the application to be "Under Review".',
        )
    questionnaire = _questionnaire(patent_id)
    if questionnaire.get("questionnaire_status") != "Completed":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Submit the questionnaire before generating a draft.",
        )
    payload = payload or {}
    requested = payload.get("section_types") or list(drafting.SECTION_TYPES)
    unknown = [section for section in requested if section not in drafting.SECTION_TYPES]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown section type(s): {', '.join(unknown)}.",
        )

    versions = query_docs(
        "questionnaire_versions",
        filters=[("patent_application_id", "==", patent_id)],
    )
    latest_version = max(
        versions, key=lambda doc: int(doc.get("version_number") or 0), default=None
    )
    questionnaire_version_id = (
        latest_version["id"] if latest_version else questionnaire["id"]
    )

    existing = _draft_outputs(patent_id)
    # Uploaded documents are optional evidence. A read failure must degrade to
    # a draft without them, not block the whole batch.
    try:
        context = extraction_store.load_context(
            patent_id, settings.max_context_characters
        )
    except Exception as exc:  # noqa: BLE001 - extraction is supplementary
        log_event(
            logger,
            logging.WARNING,
            "draft_context_unavailable",
            error_type=type(exc).__name__,
        )
        context = ""
    created = []
    started = time.monotonic()
    for section in requested:
        if created and time.monotonic() - started > drafting.BATCH_DEADLINE_SECONDS:
            logger.info(
                "draft_batch_deadline_reached",
                extra={"patent_id": patent_id, "generated": len(created)},
            )
            break
        try:
            text, provider, model = drafting.generate_section(
                patent, questionnaire, section, context=context
            )
        except drafting.AIGenerationError as exc:
            _set_patent(patent_id, {"ai_status": "Failed"})
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Section {section.replace('_', ' ').title()}: {exc}",
            ) from exc
        version_number = allocate_counter(
            "draft_counters",
            f"{patent_id}:{section}",
            floor=max(
                [
                    int(doc.get("version_number") or 0)
                    for doc in existing
                    if doc.get("section_type") == section
                ]
                or [0]
            ),
        )
        created.append(
            create_doc(
                "drafts",
                {
                    "patent_application_id": patent_id,
                    "questionnaire_version_id": questionnaire_version_id,
                    "section_type": section,
                    "version_number": version_number,
                    "ai_provider": provider,
                    "ai_model": model,
                    "ai_response": text,
                    "processing_status": "Completed",
                    "input_tokens": None,
                    "output_tokens": None,
                },
            )
        )
    complete = len(created) == len(requested)
    _set_patent(patent_id, {"ai_status": "Completed" if complete else "Partial"})
    if created:
        notify_many({str(patent.get("created_by"))}, patent_id, "DraftGenerated")
        log_activity(user["uid"], "DraftGenerated", "PatentApplication", patent_id)
    return [ai_output_out(doc) for doc in created]


@router.get("/patents/{patent_id}/draft/{section_type}/versions")
def draft_versions(
    patent_id: str, section_type: str, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    if not can_review_draft(patent, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can view draft history.",
        )
    ensure_permission(user, "DRAFTS_VIEW")
    if section_type not in drafting.SECTION_TYPES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown section type.")
    versions = [
        doc for doc in _draft_outputs(patent_id) if doc.get("section_type") == section_type
    ]
    versions = sort_docs(versions, "version_number", reverse=True)
    return [ai_output_out(doc) for doc in versions]


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@router.get("/patents/{patent_id}/comments")
def list_comments(patent_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    users = _users_by_id()
    comments = query_docs(
        "comments", filters=[("patent_application_id", "==", patent_id)]
    )
    comments = sort_docs(comments, "created_at")
    return [comment_out(doc, users.get(doc.get("user_id"))) for doc in comments]


@router.post("/patents/{patent_id}/comments", status_code=status.HTTP_201_CREATED)
def create_comment(patent_id: str, payload: dict, user: dict = Depends(active_user)):
    patent = require_patent(patent_id, user)
    ensure_permission(user, "COMMENTS_POST")
    text = (payload.get("comment_text") or "").strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "comment_text is required.")
    if len(text) > 5000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Comments are limited to 5,000 characters.",
        )
    if any(
        (ord(char) < 32 or ord(char) == 127) and char not in ("\n", "\r", "\t")
        for char in text
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Comments must not contain control characters.",
        )
    comment = create_doc(
        "comments",
        {
            "patent_application_id": patent_id,
            "user_id": user["uid"],
            "comment_text": text,
        },
    )
    notify_many(
        patent_participants(patent), patent_id, "CommentAdded", exclude=user["uid"]
    )
    log_activity(user["uid"], "CommentAdded", "PatentApplication", patent_id)
    return comment_out(comment, user)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


# 64 KiB bounds memory per read for both uploads and downloads.
CHUNK_SIZE = 64 * 1024


def _read_upload(upload: UploadFile) -> bytes:
    """Read a file with a hard cap, including chunked bodies without a length.

    Sync on purpose: the routes that use this run CPU-bound PDF conversion and
    blocking Firestore writes, so FastAPI must schedule them on the threadpool
    instead of stalling the event loop on a single instance (ADR-003).
    """
    content = bytearray()
    while True:
        chunk = upload.file.read(CHUNK_SIZE)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > settings.upload_limit_bytes:
            raise HTTPException(413, upload_limit_detail())  # Content Too Large
    return bytes(content)


def _validate_upload(
    upload: UploadFile,
    content: bytes,
    *,
    allowed: tuple[str, ...] | None = None,
) -> uploads.ValidatedUpload:
    try:
        return uploads.validate_upload(
            upload.filename or "file",
            content,
            allowed_extensions=allowed or settings.allowed_extensions,
            max_bytes=settings.upload_limit_bytes,
        )
    except uploads.UploadTooLarge as exc:
        raise HTTPException(413, upload_limit_detail()) from exc
    except uploads.UploadValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@dataclass(frozen=True)
class _PreparedUpload:
    """An upload after validation and any PDF→Word conversion."""

    filename: str
    mime_type: str
    content: bytes
    converted_from_pdf: bool
    source_filename: str | None
    # The original bytes when the stored file is a conversion of them. The PDF
    # is never stored, but it is still the best input for text and figure
    # extraction, so the request keeps it alive until ingestion has run.
    source_content: bytes | None = None


def _prepare_upload(upload: UploadFile, content: bytes) -> _PreparedUpload:
    """Validate the upload and convert PDFs to Word before storage.

    PDFs are never stored: the bytes are converted in-process and the
    resulting DOCX is what reaches Firestore. Other allowed attachment types
    are stored unchanged, still compressed (ADR-006).
    """
    validated = _validate_upload(upload, content)
    if validated.extension != ".pdf":
        return _PreparedUpload(
            filename=validated.filename,
            mime_type=validated.mime_type,
            content=content,
            converted_from_pdf=False,
            source_filename=None,
        )
    try:
        converted = docgen.pdf_to_docx(content)
    except docgen.DocumentGenerationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _PreparedUpload(
        filename=uploads.sanitize_filename(
            f"{PurePath(validated.filename).stem}.docx"
        ),
        mime_type=docgen.DOCX_MIME,
        content=converted,
        converted_from_pdf=True,
        source_filename=validated.filename,
        source_content=content,
    )


def _blob_guard(operation):
    try:
        return operation()
    except blobs.BlobTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    except blobs.BlobNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No stored file is available."
        ) from exc
    except blobs.BlobError as exc:
        # Provider errors can carry project ids and upstream status text.
        # Log the detail and show the caller a stable, non-identifying message.
        log_event(
            logger,
            logging.WARNING,
            "blob_operation_failed",
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "File storage is temporarily unavailable. Try again later.",
        ) from exc


def _chunks(stream, chunk_size: int = CHUNK_SIZE):
    try:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        stream.close()


def _download_response(
    blob_id: str | None,
    media_type: str,
    headers: dict,
    *,
    content: bytes | None = None,
) -> StreamingResponse:
    if content is None:
        content = _blob_guard(lambda: blobs.read_blob(blob_id))
    response_headers = dict(headers)
    response_headers.setdefault("Content-Length", str(len(content)))
    return StreamingResponse(
        _chunks(io.BytesIO(content)),
        media_type=media_type,
        headers=response_headers,
    )


@router.get("/patents/{patent_id}/files")
def list_files(patent_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    users = _users_by_id()
    files = query_docs("files", filters=[("patent_application_id", "==", patent_id)])
    files = sort_docs(files, "created_at", reverse=True)
    return [file_out(doc, users.get(doc.get("uploaded_by"))) for doc in files]


@router.post("/patents/{patent_id}/files", status_code=status.HTTP_201_CREATED)
def upload_file(
    patent_id: str,
    upload: UploadFile = File(...),
    user: dict = Depends(active_user),
):
    patent = require_patent(patent_id, user)
    ensure_permission(user, "FILES_UPLOAD")
    content = _read_upload(upload)
    prepared = _prepare_upload(upload, content)
    stored = _blob_guard(
        lambda: blobs.put_blob(prepared.content, prepared.mime_type)
    )
    try:
        record = create_doc(
            "files",
            {
                "patent_application_id": patent_id,
                "uploaded_by": user["uid"],
                "original_file_name": prepared.filename,
                "source_file_name": prepared.source_filename,
                "converted_from_pdf": prepared.converted_from_pdf,
                "blob_id": stored["id"],
                "mime_type": prepared.mime_type,
                "file_size_bytes": stored["size_bytes"],
                "stored_size_bytes": stored["stored_bytes"],
                "extraction_status": "pending",
            },
        )
    except Exception:
        # Do not leave an orphaned blob if the metadata row cannot be written.
        blobs.delete_blob(stored["id"])
        raise
    # The file is safely stored. Extraction runs now, in-process, so the user
    # gets text and figures back from the same upload (ADR-003: one instance,
    # no job queue). It never raises; a failure is recorded on the file row.
    extraction_fields = extraction_store.ingest_upload(
        file_id=record["id"],
        patent_id=patent_id,
        filename=prepared.source_filename or prepared.filename,
        content=prepared.source_content or prepared.content,
    )
    record.update(extraction_fields)
    try:
        write_doc("files", record["id"], extraction_fields)
    except Exception as exc:  # noqa: BLE001 - the upload itself succeeded
        log_event(
            logger,
            logging.WARNING,
            "file_extraction_fields_failed",
            error_type=type(exc).__name__,
        )
    notify_many(
        patent_participants(patent), patent_id, "FileUploaded", exclude=user["uid"]
    )
    log_activity(user["uid"], "FileUploaded", "PatentApplication", patent_id)
    return file_out(record, user)


@router.get("/patents/{patent_id}/files/{file_id}/text")
def download_file_text(
    patent_id: str, file_id: str, user: dict = Depends(active_user)
):
    """Download the text the drafting model reads for this upload."""
    require_patent(patent_id, user)
    record = _file_for_patent(patent_id, file_id)
    try:
        content = extraction_store.read_text(file_id)
    except blobs.BlobTooLarge as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No extracted text is available."
        ) from exc
    except blobs.BlobNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No extracted text is available for this file.",
        ) from exc
    except blobs.BlobError as exc:
        log_event(
            logger,
            logging.WARNING,
            "extraction_read_failed",
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "File storage is temporarily unavailable. Try again later.",
        ) from exc
    stem = PurePath(record.get("original_file_name") or "file").stem
    return _download_response(
        None,
        "text/markdown; charset=utf-8",
        _content_disposition(f"{stem}-extracted.md"),
        content=content,
    )


@router.get("/patents/{patent_id}/files/{file_id}/figures")
def list_file_figures(
    patent_id: str, file_id: str, user: dict = Depends(active_user)
):
    require_patent(patent_id, user)
    _file_for_patent(patent_id, file_id)
    return [
        figure_out(figure)
        for figure in extraction_store.figures_for_file(file_id)
    ]


@router.get("/patents/{patent_id}/files/{file_id}/figures/{figure_id}/image")
def download_figure_image(
    patent_id: str,
    file_id: str,
    figure_id: str,
    user: dict = Depends(active_user),
):
    require_patent(patent_id, user)
    _file_for_patent(patent_id, file_id)
    figure = extraction_store.get_figure(figure_id)
    if figure is None or figure.get("file_id") != file_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Figure not found.")
    content = _blob_guard(lambda: extraction_store.read_figure_image(figure))
    return _download_response(
        None,
        figure.get("content_type") or "image/jpeg",
        _content_disposition(figure.get("label") or "figure"),
        content=content,
    )


@router.patch("/patents/{patent_id}/files/{file_id}/figures/{figure_id}")
def update_figure(
    patent_id: str,
    file_id: str,
    figure_id: str,
    payload: dict,
    user: dict = Depends(active_user),
):
    """Review a figure: caption override, include/exclude, or "use anyway".

    Screening rejects what is clearly not a drawing; the user may override a
    rejection with a recorded reason. The override is stored, not the pixels.

    Deliberately gated on FILES_UPLOAD (not a drafting permission): reviewers
    are the uploaders who own the figures, overrides are reason-recorded in
    the figure row, and every change flows through the same visibility gate
    (`require_patent`) as the file itself.
    """
    require_patent(patent_id, user)
    ensure_permission(user, "FILES_UPLOAD")
    _file_for_patent(patent_id, file_id)
    figure = extraction_store.get_figure(figure_id)
    if figure is None or figure.get("file_id") != file_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Figure not found.")
    patch: dict = {}
    if "caption" in payload:
        caption = payload["caption"]
        if caption is not None and not isinstance(caption, str):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "caption must be a string."
            )
        patch["caption_override"] = (caption or "").strip()[:500] or None
    if "include_in_drawings" in payload:
        include = payload["include_in_drawings"]
        if not isinstance(include, bool):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "include_in_drawings must be a boolean.",
            )
        patch["include_in_drawings"] = include
    if "usable" in payload:
        usable = payload["usable"]
        if usable not in ("usable", "rejected"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "usable must be 'usable' or 'rejected'.",
            )
        patch["usable"] = usable
        patch["reviewed_by_user"] = True
        if usable == "usable" and figure.get("usable") == "rejected":
            patch["reason"] = "approved by user"
    if "display_order" in payload:
        try:
            patch["display_order"] = max(0, int(payload["display_order"]))
        except (TypeError, ValueError):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "display_order must be an integer.",
            ) from None
    if not patch:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to update."
        )
    return figure_out(patch_doc("file_figures", figure_id, patch))


def _file_for_patent(patent_id: str, file_id: str) -> dict:
    record = get_doc("files", file_id)
    if record.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    return record


@router.post("/patents/{patent_id}/figures/classify")
def classify_figures(patent_id: str, user: dict = Depends(active_user)):
    """Vision second opinion over figure candidates (multimodal provider)."""
    patent = require_patent(patent_id, user)
    if not can_review_draft(patent, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can classify figures.",
        )
    ensure_permission(user, "DRAFTS_GENERATE")
    return form_ai.classify_figures(patent_id)


@router.get("/patents/{patent_id}/files/{file_id}/download")
def download_file(patent_id: str, file_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    record = _file_for_patent(patent_id, file_id)
    return _download_response(
        record.get("blob_id"),
        record.get("mime_type") or "application/octet-stream",
        _content_disposition(record.get("original_file_name") or "download"),
    )


@router.delete("/patents/{patent_id}/files/{file_id}")
def delete_file(patent_id: str, file_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    record = _file_for_patent(patent_id, file_id)
    # Uploaders can always remove their own file; the catalogued FILES_DELETE
    # grant (Patent Agent) is what allows deleting someone else's upload.
    if not (
        is_admin(user)
        or record.get("uploaded_by") == user["uid"]
        or has_permission(user, "FILES_DELETE")
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot delete this file."
        )
    # Metadata first: a failure there leaves a retryable, consistent record,
    # while deleting the blob first would leave a row pointing at missing bytes.
    delete_doc("files", file_id)
    blobs.delete_blob(record.get("blob_id"))
    # Text, layout and figure crops are separate documents; leaving them behind
    # would keep the deleted document's content readable for ever.
    extraction_store.delete_for_file(file_id)
    log_activity(user["uid"], "FileDeleted", "PatentFile", file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def _can_manage_calendar(patent: dict, user: dict) -> bool:
    return is_admin(user) or patent.get("assigned_patent_agent_id") == user["uid"]


@router.get("/patents/{patent_id}/calendar-events")
def list_patent_events(patent_id: str, user: dict = Depends(active_user)):
    ensure_permission(user, "CALENDAR_VIEW")
    require_patent(patent_id, user)
    events = query_docs(
        "calendar_events", filters=[("patent_application_id", "==", patent_id)]
    )
    events = sort_docs(events, "event_date")
    return [calendar_event_out(doc) for doc in events]


@router.post(
    "/patents/{patent_id}/calendar-events", status_code=status.HTTP_201_CREATED
)
def create_calendar_event(
    patent_id: str, payload: dict, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    if not _can_manage_calendar(patent, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can add calendar events.",
        )
    ensure_permission(user, "CALENDAR_MANAGE")
    event_type = payload.get("event_type")
    if event_type not in CALENDAR_EVENT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown event_type.")
    event_date = payload.get("event_date")
    if not event_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "event_date is required.")
    event = create_doc(
        "calendar_events",
        {
            "patent_application_id": patent_id,
            "event_type": event_type,
            "event_date": _parse_iso(event_date),
            "created_by": user["uid"],
        },
    )
    return calendar_event_out(event)


@router.delete("/patents/{patent_id}/calendar-events/{event_id}")
def delete_calendar_event(
    patent_id: str, event_id: str, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    if not _can_manage_calendar(patent, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can delete calendar events.",
        )
    ensure_permission(user, "CALENDAR_MANAGE")
    event = get_doc("calendar_events", event_id)
    if event.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Calendar event not found.")
    delete_doc("calendar_events", event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/calendar/events")
def calendar(user: dict = Depends(active_user)):
    ensure_permission(user, "CALENDAR_VIEW")
    patents = {doc["id"]: doc for doc in visible_patents(user)}
    events = [
        doc
        for doc in list_docs("calendar_events")
        if doc.get("patent_application_id") in patents
    ]
    events = sort_docs(events, "event_date")
    return [
        calendar_event_out(
            doc,
            (patents.get(doc.get("patent_application_id")) or {}).get(
                "invention_title"
            ),
        )
        for doc in events
    ]


# ---------------------------------------------------------------------------
# Document generation
# ---------------------------------------------------------------------------


def _sections_for(patent_id: str) -> dict[str, str]:
    outputs = _draft_outputs(patent_id)
    sections: dict[str, str] = {}
    for section in drafting.SECTION_TYPES:
        candidates = [
            doc
            for doc in outputs
            if doc.get("section_type") == section
            and doc.get("processing_status") == "Completed"
            and doc.get("ai_response")
        ]
        latest = max(
            candidates,
            key=lambda doc: int(doc.get("version_number") or 0),
            default=None,
        )
        if latest:
            sections[section] = latest["ai_response"]
    return sections


def _active_template(document_type: str) -> dict | None:
    templates = query_docs(
        "templates", filters=[("document_type", "==", document_type)]
    )
    active = [doc for doc in templates if doc.get("is_active")]
    return active[0] if active else None


def _ensure_format_supported(output_format: str) -> None:
    """Reject formats this deployment cannot store before queueing a job.

    Documents are Word-only (ADR-006): PDF output was retired because the
    bytes now live in Firestore, where a scanned PDF would not fit, and
    every PDF upload is converted to DOCX on the way in.
    """
    if output_format == "PDF":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "PDF output is no longer supported. Documents are generated as "
            "DOCX; open the DOCX in a word processor to export a PDF if you "
            "need one.",
        )
    if output_format != "DOCX":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "output_format must be DOCX."
        )


GENERATION_STATUSES = {"Under Review", "Draft Generated"}
STALE_JOB_AFTER = timedelta(minutes=15)


def _assert_generation_allowed(patent: dict) -> None:
    if patent.get("application_status") not in GENERATION_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Document generation requires the application to be Under Review "
            "or Draft Generated.",
        )


def _timestamp(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _reap_stale_jobs(patent_id: str) -> None:
    """Mark abandoned Processing jobs failed so the UI can retry them.

    Generation runs in-process (ADR-003); if the worker dies or a deploy
    interrupts it, the job would otherwise stay Processing forever.
    """
    cutoff = datetime.now(timezone.utc) - STALE_JOB_AFTER
    jobs = query_docs(
        "document_jobs", filters=[("patent_application_id", "==", patent_id)]
    )
    for job in jobs:
        if job.get("status") != "Processing":
            continue
        started = _timestamp(job.get("started_at") or job.get("created_at"))
        # A job with a missing or garbled timestamp can never prove it is
        # fresh, so treat it as stale instead of skipping it forever.
        if started is not None and started > cutoff:
            continue
        log_event(
            logger,
            logging.WARNING,
            "stale_document_job",
            patent_id=patent_id,
            job_id=job["id"],
        )
        patch_doc(
            "document_jobs",
            job["id"],
            {
                "status": "Failed",
                "error_message": (
                    "Generation did not finish within 15 minutes and was "
                    "marked failed. Retry the job."
                ),
                "completed_at": _now(),
            },
        )


def _job_error_message(exc: Exception) -> str:
    """Keep curated errors; replace unexpected ones with a stable message."""
    if isinstance(exc, docgen.DocumentGenerationError):
        return str(exc)
    return (
        "Document generation failed unexpectedly. Try again, or ask an "
        "administrator to check the server logs."
    )


def _run_generation(
    patent: dict,
    output_format: str,
    user: dict,
    retried_from_job_id: str | None = None,
) -> dict:
    patent_id = patent["id"]
    job = create_doc(
        "document_jobs",
        {
            "patent_application_id": patent_id,
            "status": "Processing",
            "triggered_by": user["uid"],
            "retried_from_job_id": retried_from_job_id,
            "error_message": None,
            "started_at": _now(),
            "completed_at": None,
            "output_format": output_format,
        },
    )
    try:
        sections = _sections_for(patent_id)
        missing = [
            section
            for section in drafting.SECTION_TYPES
            if section not in sections
        ]
        if missing:
            raise docgen.DocumentGenerationError(
                "Generate every AI draft section first. Missing: "
                + ", ".join(missing)
                + "."
            )
        template_doc = _active_template(DOCUMENT_TYPE)
        template_bytes = None
        if template_doc:
            try:
                template_bytes = blobs.read_blob(template_doc.get("file_path"))
            except blobs.BlobNotFound as exc:
                raise docgen.DocumentGenerationError(
                    "The active DOCX template is missing. Ask an administrator "
                    "to re-upload it."
                ) from exc
        if template_bytes is None:
            # No uploaded template yet: use the bundled Form 1 so every patent
            # still gets a real application layout.
            template_bytes = docgen.default_template()
        docx = docgen.render_docx(patent, sections, template_bytes)
        try:
            stored = blobs.put_blob(docx, docgen.DOCX_MIME)
        except blobs.BlobTooLarge as exc:
            raise docgen.DocumentGenerationError(str(exc)) from exc

        documents = query_docs(
            "documents", filters=[("patent_application_id", "==", patent_id)]
        )
        document = next(
            (
                doc
                for doc in documents
                if doc.get("output_format") == output_format
                and doc.get("document_type") == DOCUMENT_TYPE
            ),
            None,
        )
        versions = query_docs(
            "document_versions", filters=[("patent_application_id", "==", patent_id)]
        ) if document else []
        previous_max = max(
            [
                int(doc.get("version_number") or 0)
                for doc in versions
                if doc.get("document_id") == (document or {}).get("id")
            ]
            or [0]
        )
        # The counter document makes concurrent generations serialise on one
        # Firestore transaction instead of both reading the same max version.
        version_number = allocate_counter(
            "document_counters",
            f"{patent_id}:{output_format}:{DOCUMENT_TYPE}",
            floor=previous_max,
        )
        stamp = _now()
        document_fields = {
            "template_id": (template_doc or {}).get("id"),
            "generated_by": user["uid"],
            "generated_at": stamp,
            "stored_path": stored["id"],
            "file_size_bytes": stored["size_bytes"],
            "stored_size_bytes": stored["stored_bytes"],
        }
        if document is None:
            # Deterministic ID: two first-time generations that race would
            # otherwise create two document records for the same format.
            document = create_doc(
                "documents",
                {
                    "patent_application_id": patent_id,
                    "document_type": DOCUMENT_TYPE,
                    "output_format": output_format,
                    "watermark_status": "DRAFT",
                    **document_fields,
                    "latest_version": version_number,
                },
                doc_id=f"{patent_id}:{DOCUMENT_TYPE}:{output_format}",
            )
        else:
            document = set_latest_version(
                "documents", document["id"], version_number, document_fields
            )
        create_doc(
            "document_versions",
            {
                "document_id": document["id"],
                "patent_application_id": patent_id,
                "version_number": version_number,
                "change_summary": f"Generated {output_format}",
                "generated_by": user["uid"],
                "generated_at": stamp,
                "storage_path": stored["id"],
                "file_size_bytes": stored["size_bytes"],
                "stored_size_bytes": stored["stored_bytes"],
            },
        )
        current_status = patent.get("application_status")
        next_status = (
            "Draft Generated"
            if current_status in {"Under Review", "Changes Requested"}
            else current_status
        )
        _set_patent(
            patent_id,
            {"document_status": "Generated", "application_status": next_status},
        )
        notify_many({str(patent.get("created_by"))}, patent_id, "DraftGenerated")
        log_activity(user["uid"], "DocumentGenerated", "PatentApplication", patent_id)
        return patch_doc(
            "document_jobs",
            job["id"],
            {
                "status": "Completed",
                "error_message": None,
                "completed_at": _now(),
            },
        )
    except Exception as exc:
        # Recorded on the job so the UI can show why the document failed.
        if not isinstance(exc, docgen.DocumentGenerationError):
            log_event(
                logger,
                logging.ERROR,
                "document_generation_failed",
                exc_info=True,
                patent_id=patent_id,
                output_format=output_format,
                error_type=type(exc).__name__,
            )
        return patch_doc(
            "document_jobs",
            job["id"],
            {
                "status": "Failed",
                "error_message": _job_error_message(exc),
                "completed_at": _now(),
            },
        )


@router.get("/patents/{patent_id}/documents")
def list_documents(patent_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_VIEW")
    documents = query_docs(
        "documents", filters=[("patent_application_id", "==", patent_id)]
    )
    documents = sort_docs(documents, "generated_at", reverse=True)
    return [document_out(doc) for doc in documents]


@router.get("/patents/{patent_id}/documents/jobs")
def list_document_jobs(patent_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_VIEW")
    _reap_stale_jobs(patent_id)
    jobs = query_docs(
        "document_jobs", filters=[("patent_application_id", "==", patent_id)]
    )
    jobs = sort_docs(jobs, "created_at", reverse=True)
    return [document_job_out(doc) for doc in jobs]


@router.post("/patents/{patent_id}/documents/generate")
def generate_document(
    patent_id: str, payload: dict, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_GENERATE")
    if not (is_admin(user) or patent.get("assigned_patent_agent_id") == user["uid"]):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can generate documents.",
        )
    _assert_generation_allowed(patent)
    output_format = str(payload.get("output_format") or "DOCX").upper()
    _ensure_format_supported(output_format)
    _reap_stale_jobs(patent_id)
    job = _run_generation(patent, output_format, user)
    return document_job_out(job)


@router.post("/patents/{patent_id}/documents/jobs/{job_id}/retry")
def retry_document_job(
    patent_id: str, job_id: str, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_GENERATE")
    if not (is_admin(user) or patent.get("assigned_patent_agent_id") == user["uid"]):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can retry generation.",
        )
    job = get_doc("document_jobs", job_id)
    if job.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation job not found.")
    if job.get("status") != "Failed":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only failed jobs can be retried."
        )
    _assert_generation_allowed(patent)
    output_format = str(job.get("output_format") or "DOCX").upper()
    _ensure_format_supported(output_format)
    retried = _run_generation(patent, output_format, user, retried_from_job_id=job_id)
    return document_job_out(retried)


@router.get("/patents/{patent_id}/documents/{document_id}/versions")
def document_versions(
    patent_id: str, document_id: str, user: dict = Depends(active_user)
):
    require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_VIEW")
    document = get_doc("documents", document_id)
    if document.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    versions = query_docs(
        "document_versions", filters=[("document_id", "==", document_id)]
    )
    versions = sort_docs(versions, "version_number", reverse=True)
    return [document_version_out(doc) for doc in versions]


@router.get("/patents/{patent_id}/documents/{document_id}/download")
def download_document(
    patent_id: str, document_id: str, user: dict = Depends(active_user)
):
    require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_VIEW")
    document = get_doc("documents", document_id)
    if document.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    blob_id = document.get("stored_path")
    if not blob_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No generated file is available.")
    return _download_response(
        blob_id,
        docgen.DOCX_MIME,
        _content_disposition("patent-document.docx"),
    )


@router.get("/patents/{patent_id}/documents/versions/{version_id}/download")
def download_document_version(
    patent_id: str, version_id: str, user: dict = Depends(active_user)
):
    require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_VIEW")
    version = get_doc("document_versions", version_id)
    if version.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document version not found.")
    document = get_doc("documents", version.get("document_id"))
    if document.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document version not found.")
    blob_id = version.get("storage_path")
    if not blob_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No generated file is available.")
    return _download_response(
        blob_id,
        docgen.DOCX_MIME,
        _content_disposition(
            f"patent-document-v{version.get('version_number')}.docx"
        ),
    )


# ---------------------------------------------------------------------------
# Statutory forms
# ---------------------------------------------------------------------------


def _assert_forms_agent(patent: dict, user: dict, action: str) -> None:
    if not (
        is_admin(user) or patent.get("assigned_patent_agent_id") == user["uid"]
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Only the assigned Patent Agent or an Admin can {action}.",
        )


@router.get("/forms/catalog")
def forms_catalog(user: dict = Depends(active_user)):
    from app.services.form_specs import FORMS

    return [
        {
            "form_code": spec.code,
            "label": spec.label,
            "required": list(spec.required),
            "optional": list(spec.optional),
            "supports_figures": spec.supports_figures,
        }
        for spec in FORMS
    ]


@router.post("/patents/{patent_id}/forms/generate")
def generate_forms(
    patent_id: str, payload: dict, user: dict = Depends(active_user)
):
    patent = require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_GENERATE")
    _assert_forms_agent(patent, user, "generate forms")
    _assert_generation_allowed(patent)
    codes = payload.get("codes")
    if codes is not None:
        unknown = [code for code in codes if code not in FORM_BY_CODE]
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Unknown form code(s): " + ", ".join(unknown) + ".",
            )
    counts: dict[str, str] = {}
    for key, value in (payload.get("counts") or {}).items():
        if key not in COUNT_KEYS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown counts field: {key}.",
            )
        if isinstance(value, str):
            value = value.strip()
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        else:
            continue
        if len(value) > MAX_COUNT_CHARS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Counts values are limited to {MAX_COUNT_CHARS} characters.",
            )
        if value:
            counts[key] = value
    _reap_stale_jobs(patent_id)
    return form_generation.generate_form_set(
        patent_id, user, codes=codes, counts=counts
    )


@router.get("/patents/{patent_id}/forms")
def list_forms(patent_id: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_VIEW")
    return form_generation.form_status(patent_id)


@router.get("/patents/{patent_id}/forms/{code}/download")
def download_form(
    patent_id: str, code: str, user: dict = Depends(active_user)
):
    require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_VIEW")
    if code not in FORM_BY_CODE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown form.")
    document = get_doc_or_none("documents", f"{patent_id}:{code}:DOCX")
    if document is None or document.get("patent_application_id") != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not generated yet.")
    return _download_response(
        document.get("stored_path"),
        docgen.DOCX_MIME,
        _content_disposition(
            f"form-{code.lower()}-v{document.get('latest_version') or 1}.docx"
        ),
    )


@router.get("/patents/{patent_id}/forms/{code}/versions")
def form_versions(patent_id: str, code: str, user: dict = Depends(active_user)):
    require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_VIEW")
    if code not in FORM_BY_CODE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown form.")
    versions = query_docs(
        "document_versions",
        filters=[
            ("patent_application_id", "==", patent_id),
            ("document_id", "==", f"{patent_id}:{code}:DOCX"),
        ],
    )
    return [document_version_out(doc) for doc in sort_docs(versions, "version_number", reverse=True)]


@router.post("/patents/{patent_id}/forms/finalize")
def finalize_forms(patent_id: str, user: dict = Depends(active_user)):
    patent = require_patent(patent_id, user)
    ensure_permission(user, "DOCUMENTS_GENERATE")
    _assert_forms_agent(patent, user, "finalize forms")
    try:
        return form_generation.finalize(patent_id, user)
    except form_generation.FinalizeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/patents/{patent_id}/forms/refine")
def refine_form_fields(
    patent_id: str, payload: dict, user: dict = Depends(active_user)
):

    patent = require_patent(patent_id, user)
    if not can_review_draft(patent, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can refine fields.",
        )
    ensure_permission(user, "DRAFTS_GENERATE")
    if patent.get("application_status") != "Under Review":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            'Refinement requires the application to be "Under Review".',
        )
    questionnaire = _questionnaire(patent_id)
    if questionnaire.get("questionnaire_status") != "Completed":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Submit the questionnaire before refining fields.",
        )
    groups = payload.get("groups") or list(form_ai.GROUPS)
    unknown = [group for group in groups if group not in form_ai.GROUPS]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Unknown group(s): " + ", ".join(unknown) + ".",
        )
    profile = form_generation.build_profile(patent_id)
    raw = form_ai.required_raw_values(profile["questionnaire"])
    versions = query_docs(
        "questionnaire_versions",
        filters=[("patent_application_id", "==", patent_id)],
    )
    questionnaire_version_id = (
        max(versions, key=lambda doc: int(doc.get("version_number") or 0), default=None) or {}
    ).get("id", questionnaire["id"])
    existing = query_docs("drafts", filters=[("patent_application_id", "==", patent_id)])
    created = []
    started = time.monotonic()
    shared: dict = {}
    for group in groups:
        if created and time.monotonic() - started > form_ai.BATCH_DEADLINE_SECONDS:
            # A degraded provider must not hold the request past the client
            # timeout; remaining groups keep their previous versions and can
            # be refined individually.
            logger.info(
                "refine_batch_deadline_reached",
                extra={"patent_id": patent_id, "refined": len(created)},
            )
            break
        group_raw = {key: raw.get(key) for key in form_ai.AI_GROUPS[group]}
        result = form_ai.refine_group(
            patent_id, profile, group, raw_values=group_raw, _cache=shared
        )
        # Same race as questionnaire submit and draft generation: claim the
        # version transactionally instead of read-max-then-write.
        version_number = allocate_counter(
            "draft_counters",
            f"{patent_id}:{group}",
            floor=max(
                [
                    int(doc.get("version_number") or 0)
                    for doc in existing
                    if doc.get("section_type") == group
                ]
                or [0]
            ),
        )
        record = create_doc(
            "drafts",
            {
                "patent_application_id": patent_id,
                "questionnaire_version_id": questionnaire_version_id,
                "section_type": group,
                "version_number": version_number,
                "ai_provider": result["provider"],
                "ai_model": result["model"],
                "ai_response": json.dumps(result["fields"], ensure_ascii=False),
                "fields": result["fields"],
                "origin": result["origin"],
                "figure_refs": result["figure_refs"],
                "used_figures": result.get("used_figures") or [],
                "warnings": result["warnings"],
                "edited_by": user["uid"],
                "processing_status": "Completed",
            },
        )
        existing.append(record)
        created.append(refined_group_out(record))
    log_activity(user["uid"], "FieldsRefined", "PatentApplication", patent_id)
    return created


@router.get("/patents/{patent_id}/form-fields")
def get_form_fields(patent_id: str, user: dict = Depends(active_user)):

    require_patent(patent_id, user)
    ensure_permission(user, "DRAFTS_VIEW")
    existing = query_docs("drafts", filters=[("patent_application_id", "==", patent_id)])
    latest: dict[str, dict] = {}
    for doc in existing:
        if doc.get("section_type") not in form_ai.GROUPS:
            continue
        current = latest.get(doc["section_type"])
        if current is None or int(doc.get("version_number") or 0) > int(
            current.get("version_number") or 0
        ):
            latest[doc["section_type"]] = doc
    return {group: refined_group_out(latest[group]) for group in latest}


@router.patch("/patents/{patent_id}/form-fields")
def update_form_fields(
    patent_id: str, payload: dict, user: dict = Depends(active_user)
):
    from app.services.questionnaire_schema import FIELD_BY_KEY

    patent = require_patent(patent_id, user)
    if not can_review_draft(patent, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin can edit refined fields.",
        )
    ensure_permission(user, "DRAFTS_GENERATE")
    group = payload.get("group")
    if group not in form_ai.GROUPS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Unknown group. Expected one of: " + ", ".join(form_ai.GROUPS) + ".",
        )
    fields = payload.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "fields must be a non-empty object."
        )
    allowed = set(form_ai.AI_GROUPS[group])
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unknown field(s) for this group: " + ", ".join(unknown) + ".",
        )
    cleaned: dict[str, str | None] = {}
    for key, value in fields.items():
        if value is None:
            cleaned[key] = None
            continue
        if not isinstance(value, str):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{key} must be a string."
            )
        limit = FIELD_BY_KEY[key].limit
        if len(value.strip()) > limit:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{key} must be at most {limit} characters.",
            )
        cleaned[key] = value.strip() or None
    existing = query_docs("drafts", filters=[("patent_application_id", "==", patent_id)])
    group_rows = [doc for doc in existing if doc.get("section_type") == group]
    base = max(group_rows, key=lambda doc: int(doc.get("version_number") or 0), default=None)
    if base is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Refine this group with AI first, then edit the result.",
        )
    merged = dict(base.get("fields") or {})
    origin = dict(base.get("origin") or {})
    for key, value in cleaned.items():
        merged[key] = value
        origin[key] = "user"
    # Same transactional claim as the refine route: two agents saving edits
    # at once must not fork the version history.
    version_number = allocate_counter(
        "draft_counters",
        f"{patent_id}:{group}",
        floor=max(
            [int(doc.get("version_number") or 0) for doc in group_rows] or [0]
        ),
    )
    record = create_doc(
        "drafts",
        {
            "patent_application_id": patent_id,
            "questionnaire_version_id": base.get("questionnaire_version_id"),
            "section_type": group,
            "version_number": version_number,
            "ai_provider": base.get("ai_provider"),
            "ai_model": base.get("ai_model"),
            "ai_response": json.dumps(merged, ensure_ascii=False),
            "fields": merged,
            "origin": origin,
            "figure_refs": base.get("figure_refs") or {},
            "used_figures": base.get("used_figures") or [],
            "warnings": [],
            "edited_by": user["uid"],
            "processing_status": "Completed",
        },
    )
    return refined_group_out(record)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@router.get("/templates/document-types")
def template_document_types(user: dict = Depends(active_user)):
    ensure_permission(user, "TEMPLATES_VIEW")
    return list(docgen.DOCUMENT_TYPES)


@router.get("/templates")
def list_templates(
    document_type: str | None = Query(default=None), user: dict = Depends(active_user)
):
    ensure_permission(user, "TEMPLATES_VIEW")
    templates = list_docs("templates")
    if document_type:
        templates = [
            doc for doc in templates if doc.get("document_type") == document_type
        ]
    templates = sort_docs(templates, "version_number", reverse=True)
    users = _users_by_id()
    return [
        template_out(doc, users.get(doc.get("edited_by"))) for doc in templates
    ]


@router.post("/templates", status_code=status.HTTP_201_CREATED)
def upload_template(
    document_type: str = Query(...),
    activate: bool = Query(default=True),
    upload: UploadFile = File(...),
    user: dict = Depends(active_user),
):
    ensure_permission(user, "TEMPLATES_MANAGE")
    if document_type not in docgen.DOCUMENT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown document_type.")
    content = _read_upload(upload)
    validated = _validate_upload(
        upload, content, allowed=(".docx", ".pdf", ".doc")
    )
    if validated.extension == ".doc":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Legacy .doc templates cannot be read. Save the file as .docx or "
            "PDF and upload it again.",
        )
    template_name = validated.filename
    if validated.extension == ".pdf":
        # Templates are rendered by python-docx, so a PDF is converted to Word
        # once at upload time; the original PDF is not kept.
        try:
            content = docgen.pdf_to_docx(content)
        except docgen.DocumentGenerationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        template_name = uploads.sanitize_filename(
            f"{PurePath(validated.filename).stem}.docx"
        )
    unknown, unused, parse_error = docgen.inspect_template(content)
    existing = [
        doc
        for doc in list_docs("templates")
        if doc.get("document_type") == document_type
    ]
    version_number = allocate_counter(
        "template_counters",
        document_type,
        floor=max(
            [int(doc.get("version_number") or 0) for doc in existing] or [0]
        ),
    )
    stored = _blob_guard(lambda: blobs.put_blob(content, docgen.DOCX_MIME))
    if unknown or parse_error:
        # A template with unknown placeholders raises at render time
        # (StrictUndefined) and a template that failed to parse cannot render
        # at all. Never let either become the active template on upload.
        activate = False
    if activate:
        for doc in existing:
            if doc.get("is_active"):
                patch_doc("templates", doc["id"], {"is_active": False})
    try:
        record = create_doc(
            "templates",
            {
                "document_type": document_type,
                "version_number": version_number,
                "file_path": stored["id"],
                "original_file_name": template_name,
                "file_size_bytes": stored["size_bytes"],
                "stored_size_bytes": stored["stored_bytes"],
                "is_active": activate,
                "edited_by": user["uid"],
                "unknown_placeholders": unknown,
                "unused_known_placeholders": unused,
                "template_parse_error": parse_error,
            },
        )
    except Exception:
        blobs.delete_blob(stored["id"])
        raise
    log_activity(user["uid"], "TemplateUploaded", "Template", record["id"])
    return template_out(record, user)


@router.post("/templates/{template_id}/activate")
def activate_template(template_id: str, user: dict = Depends(active_user)):
    ensure_permission(user, "TEMPLATES_MANAGE")
    template = get_doc("templates", template_id)
    if template.get("template_parse_error"):
        # Activating it would replace a working template with one that cannot
        # be rendered, and generation would start failing for every document.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This template failed to parse and cannot be activated. "
            "Upload a corrected version instead.",
        )
    if template.get("unknown_placeholders"):
        # Unknown placeholders now raise at render time (StrictUndefined), so
        # activating such a template would break generation for every
        # document of this type. Fix the variable names first.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This template uses unknown placeholder(s): "
            + ", ".join(template.get("unknown_placeholders") or [])
            + ". Upload a corrected version instead.",
        )
    if not template.get("file_path"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This template has no stored file."
        )
    for doc in list_docs("templates"):
        if (
            doc["id"] != template_id
            and doc.get("document_type") == template.get("document_type")
            and doc.get("is_active")
        ):
            patch_doc("templates", doc["id"], {"is_active": False})
    updated = patch_doc("templates", template_id, {"is_active": True})
    log_activity(user["uid"], "TemplateActivated", "Template", template_id)
    return template_out(updated, user)


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, user: dict = Depends(active_user)):
    ensure_permission(user, "TEMPLATES_MANAGE")
    template = get_doc("templates", template_id)
    if template.get("is_active"):
        # Deleting it would silently drop generation back to the built-in
        # layout for every future document of this type.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Activate another version of this document type before deleting "
            "the active template.",
        )
    blobs.delete_blob(template.get("file_path"))
    delete_doc("templates", template_id)
    log_activity(user["uid"], "TemplateDeleted", "Template", template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@router.get("/notifications")
def list_notifications(user: dict = Depends(active_user)):
    ensure_permission(user, "NOTIFICATIONS_VIEW")
    notifications = query_docs(
        "notifications", filters=[("user_id", "==", user["uid"])]
    )
    notifications = sort_docs(notifications, "created_at", reverse=True)[:100]
    titles = _title_map()
    return [
        notification_out(doc, titles.get(doc.get("patent_application_id")))
        for doc in notifications
    ]


@router.get("/notifications/unread-count")
def unread_notification_count(user: dict = Depends(active_user)):
    ensure_permission(user, "NOTIFICATIONS_VIEW")
    count = len(
        [
            doc
            for doc in query_docs(
                "notifications", filters=[("user_id", "==", user["uid"])]
            )
            if not doc.get("is_read")
        ]
    )
    return {"unread_count": count}


@router.patch("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str, user: dict = Depends(active_user)):
    ensure_permission(user, "NOTIFICATIONS_VIEW")
    notification = get_doc("notifications", notification_id)
    if notification.get("user_id") != user["uid"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found.")
    patch_doc("notifications", notification_id, {"is_read": True})
    return {"id": notification_id, "is_read": True}


@router.post("/notifications/read-all")
def mark_all_notifications_read(user: dict = Depends(active_user)):
    ensure_permission(user, "NOTIFICATIONS_VIEW")
    for doc in query_docs(
        "notifications", filters=[("user_id", "==", user["uid"])]
    ):
        if not doc.get("is_read"):
            patch_doc("notifications", doc["id"], {"is_read": True})
    return {"unread_count": 0}


# ---------------------------------------------------------------------------
# Reports & dashboards
# ---------------------------------------------------------------------------


def _status_counts(patents: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for patent in patents:
        label = patent.get("application_status") or "Draft"
        counts[label] = counts.get(label, 0) + 1
    return [
        {"status": status_name, "count": counts[status_name]}
        for status_name in sorted(counts)
    ]


@router.get("/reports/dashboard")
def dashboard(user: dict = Depends(active_user)):
    """Personal dashboard: intentionally available to every approved user.

    Unlike the report catalog/run/export routes this needs no REPORTS_VIEW
    grant — everyone gets their own action counts. No cross-user data leaks
    here: every count is computed over `visible_patents(user)` only.
    """
    patents = visible_patents(user)
    roles = set(user.get("role_codes") or [])
    if {"ADMIN", "SUPER_ADMIN"} & roles:
        action_statuses = {"Submitted", "Awaiting Patent Agent Acceptance"}
        label = "Applications awaiting assignment"
        action_count = len(
            [doc for doc in patents if doc.get("application_status") in action_statuses]
        )
    elif "PATENT_AGENT" in roles:
        label = "Assignments awaiting your decision"
        action_count = len(
            [
                doc
                for doc in patents
                if doc.get("assigned_patent_agent_id") == user["uid"]
                and doc.get("application_status") == "Awaiting Patent Agent Acceptance"
            ]
        )
    else:
        label = "Applications still in Draft"
        action_count = len(
            [
                doc
                for doc in patents
                if doc.get("application_status") == "Draft"
                and doc.get("created_by") == user["uid"]
            ]
        )
    unread = len(
        [
            doc
            for doc in query_docs(
                "notifications", filters=[("user_id", "==", user["uid"])]
            )
            if not doc.get("is_read")
        ]
    )
    recent_activity = None
    if {"ADMIN", "SUPER_ADMIN"} & roles:
        activity = sort_docs(list_docs("activity"), "created_at", reverse=True)[:10]
        recent_activity = [
            {
                "id": doc["id"],
                "user_id": doc.get("user_id"),
                "event_type": doc.get("event_type"),
                "entity_type": doc.get("entity_type"),
                "entity_id": doc.get("entity_id"),
                "created_at": doc.get("created_at"),
            }
            for doc in activity
        ]
    return {
        "total_visible_patents": len(patents),
        "status_counts": _status_counts(patents),
        "action_required_count": action_count,
        "action_required_label": label,
        "unread_notifications": unread,
        "upcoming_events_count": len(upcoming_events(patents)),
        "recent_activity": recent_activity,
    }


def _assert_report_access(report_type: str, user: dict) -> None:
    """The users report exposes every account, so it stays admin-only.

    The grant matrix controls downloads; it must not be able to widen this
    report to Innovators or Patent Agents.
    """
    if report_type == "users" and not is_admin(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Admin access required for the users report."
        )


def _report_rows(report_type: str, user: dict) -> list[dict]:
    _assert_report_access(report_type, user)
    patents = {
        doc["id"]: doc for doc in visible_patents(user)
    }
    users = _users_by_id()
    if report_type == "patent_applications":
        rows = []
        for patent in patents.values():
            agent = users.get(patent.get("assigned_patent_agent_id")) or {}
            rows.append(
                {
                    "id": patent["id"],
                    "invention_title": patent.get("invention_title"),
                    "application_status": patent.get("application_status"),
                    "assigned_patent_agent": agent.get("full_name"),
                    "created_at": patent.get("created_at"),
                }
            )
        return sort_docs(rows, "created_at", reverse=True)
    if report_type == "documents":
        rows = []
        for document in list_docs("documents"):
            patent = patents.get(document.get("patent_application_id"))
            if not patent:
                continue
            rows.append(
                {
                    "id": document["id"],
                    "invention_title": patent.get("invention_title"),
                    "document_type": document.get("document_type"),
                    "output_format": document.get("output_format"),
                    "generated_at": document.get("generated_at"),
                }
            )
        return sort_docs(rows, "generated_at", reverse=True)
    if report_type == "calendar_events":
        rows = []
        for event in list_docs("calendar_events"):
            patent = patents.get(event.get("patent_application_id"))
            if not patent:
                continue
            rows.append(
                {
                    "id": event["id"],
                    "invention_title": patent.get("invention_title"),
                    "event_type": event.get("event_type"),
                    "event_date": event.get("event_date"),
                }
            )
        return sort_docs(rows, "event_date")
    if report_type == "users":
        if not is_admin(user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Admin access required for the users report."
            )
        return [
            {
                "id": doc["id"],
                "full_name": doc.get("full_name"),
                "email": doc.get("email"),
                "account_status": user_out(doc)["account_status"],
                "roles": ", ".join(doc.get("role_codes") or []),
                "created_at": doc.get("created_at"),
            }
            for doc in sort_docs(list_docs("users"), "created_at", reverse=True)
        ]
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report type.")


@router.get("/reports/permissions/matrix")
def report_permission_matrix(user: dict = Depends(active_user)):
    ensure_permission(user, "RBAC_MANAGE")
    return report_matrix()


@router.post("/reports/permissions/toggle")
def report_permission_toggle(
    payload: dict, grant: bool = Query(...), user: dict = Depends(active_user)
):
    ensure_permission(user, "RBAC_MANAGE")
    try:
        role_id = int(payload.get("role_id"))
        report_type = str(payload.get("report_type"))
        result = toggle_report_permission(role_id, report_type, grant)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_activity(user["uid"], "ReportPermissionToggled", "Role", str(role_id))
    return result


@router.get("/reports")
def report_catalog(user: dict = Depends(active_user)):
    ensure_permission(user, "REPORTS_VIEW")
    allowed = has_permission(user, "REPORTS_DOWNLOAD")
    return [
        {
            **row,
            "can_download": can_download_report(
                user, row["report_type"], allowed
            ),
        }
        for row in REPORT_TYPES
        if row["report_type"] != "users" or is_admin(user)
    ]


@router.get("/reports/{report_type}/export")
def export_report(report_type: str, user: dict = Depends(active_user)):
    ensure_permission(user, "REPORTS_VIEW")
    if report_type not in REPORT_TYPE_NAMES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report type.")
    _assert_report_access(report_type, user)
    if not can_download_report(
        user, report_type, has_permission(user, "REPORTS_DOWNLOAD")
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Your role is not permitted to download this report.",
        )
    rows = _report_rows(report_type, user)
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        # Spreadsheet apps treat a leading =, +, -, or @ as a formula. A
        # user-controlled title or name must not execute when an admin opens
        # the exported file.
        writer.writerows(
            {key: _csv_safe(value) for key, value in row.items()} for row in rows
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers=_content_disposition(f"{report_type}.csv"),
    )


@router.get("/reports/{report_type}")
def run_report(report_type: str, user: dict = Depends(active_user)):
    ensure_permission(user, "REPORTS_VIEW")
    if report_type not in REPORT_TYPE_NAMES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report type.")
    _assert_report_access(report_type, user)
    rows = _report_rows(report_type, user)
    meta = next(row for row in REPORT_TYPES if row["report_type"] == report_type)
    return {
        "report_type": report_type,
        "label": meta["label"],
        "generated_at": _now(),
        "row_count": len(rows),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


@router.get("/rbac/matrix")
def rbac_matrix(user: dict = Depends(active_user)):
    ensure_permission(user, "RBAC_MANAGE")
    return matrix()


@router.post("/rbac/toggle")
def rbac_toggle(
    payload: dict, grant: bool = Query(...), user: dict = Depends(active_user)
):
    ensure_permission(user, "RBAC_MANAGE")
    try:
        role_id = int(payload.get("role_id"))
        permission_id = int(payload.get("permission_id"))
        result = toggle_grant(role_id, permission_id, grant)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_activity(user["uid"], "PermissionToggled", "Role", str(role_id))
    return result


@router.get("/rbac/users")
def rbac_users(user: dict = Depends(active_user)):
    ensure_permission(user, "RBAC_MANAGE")
    users = sort_docs(list_docs("users"), "created_at", reverse=True)
    return [
        {
            "id": doc["id"],
            "email": doc.get("email") or "",
            "full_name": doc.get("full_name") or "",
            "account_status": user_out(doc)["account_status"],
            "is_active": doc.get("is_active", True),
            "roles": list(doc.get("role_codes") or []),
            "created_at": doc.get("created_at"),
        }
        for doc in users
    ]


@router.post("/rbac/users/{target_id}/roles")
def assign_role(target_id: str, payload: dict, user: dict = Depends(active_user)):
    ensure_permission(user, "RBAC_MANAGE")
    role_code = str(payload.get("role_code") or "").upper()
    if role_code not in ALL_ROLE_CODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown role code.")
    if role_code == "SUPER_ADMIN" and not is_super_admin(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a Super Admin can grant the Super Admin role.",
        )
    target = get_doc("users", target_id)
    roles = set(target.get("role_codes") or [])
    roles.add(role_code)
    patch_doc("users", target_id, {"role_codes": sorted(roles)})
    log_activity(user["uid"], "RoleAssigned", "User", target_id)
    return user_out(get_doc("users", target_id))


@router.delete("/rbac/users/{target_id}/roles/{role_code}")
def revoke_role(target_id: str, role_code: str, user: dict = Depends(active_user)):
    ensure_permission(user, "RBAC_MANAGE")
    role_code = role_code.upper()
    if role_code not in ALL_ROLE_CODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown role code.")
    target = get_doc("users", target_id)
    roles = set(target.get("role_codes") or [])
    if target_id == user["uid"] and role_code == "SUPER_ADMIN":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "You cannot revoke your own Super Admin role.",
        )
    if role_code == "SUPER_ADMIN" and not is_super_admin(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a Super Admin can revoke the Super Admin role.",
        )
    if role_code not in roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The user does not hold that role.")
    if role_code == "SUPER_ADMIN":
        ensure_super_admin_survives(list_docs("users"), target_id)
    roles.discard(role_code)
    if not roles:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Every user must keep at least one role."
        )
    patch_doc("users", target_id, {"role_codes": sorted(roles)})
    log_activity(user["uid"], "RoleRevoked", "User", target_id)
    return user_out(get_doc("users", target_id))
