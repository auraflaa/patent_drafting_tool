"""Firestore document -> REST response projections and access helpers.

The frontend consumes the original camel-free snake_case contract
(`invention_title`, `application_status`, `roles`, Title-Case statuses).
Firestore stores lowercase internal state; everything is normalised here so
routers stay thin and the UI did not need a contract rewrite.
"""
from datetime import datetime, timedelta, timezone
import logging

from app.core.firebase import db
from app.core.logging import log_event
from app.core.security import is_admin
from app.services.repository import create_doc, list_docs, now_iso

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifecycle constants
# ---------------------------------------------------------------------------

TERMINAL_STATUSES = {"Granted", "Rejected", "Withdrawn", "Abandoned"}
PRE_ASSIGNMENT_STATUSES = {"Draft", "Submitted", "Awaiting Patent Agent Acceptance"}
AGENT_ACTIVE_STATUSES = {
    "Under Review",
    "Changes Requested",
    "Ready for Draft Generation",
    "Draft Generated",
    "Ready for Filing",
    "Filed",
    "Examination Requested",
    "FER Received",
    "FER Response Submitted",
    "Hearing Scheduled",
}
CALENDAR_EVENT_TYPES = ("Filing Deadline", "Examination", "Hearing", "Reminder")

ACCOUNT_STATUS_API = {
    "pending": "Pending",
    "approved": "Approved",
    "rejected": "Rejected",
    "suspended": "Suspended",
}


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _timestamp(value) -> float:
    if not value:
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Users & teams
# ---------------------------------------------------------------------------


def user_out(doc: dict) -> dict:
    return {
        "id": doc.get("id") or doc.get("uid"),
        "email": doc.get("email") or "",
        "full_name": doc.get("full_name") or "",
        "phone_number": doc.get("phone_number"),
        "profile_picture": doc.get("profile_picture"),
        "designation": doc.get("designation"),
        "organization": doc.get("organization"),
        "account_status": ACCOUNT_STATUS_API.get(
            doc.get("account_status") or "pending", "Pending"
        ),
        "is_active": doc.get("is_active", True),
        "last_login_at": _iso(doc.get("last_login_at")),
        "created_at": _iso(doc.get("created_at")) or now_iso(),
        "roles": list(doc.get("role_codes") or []),
    }


def member_team_ids(uid: str) -> set[str]:
    """Team IDs the user belongs to, via the `members` collection group."""
    ids: set[str] = set()
    try:
        for snap in (
            db().collection_group("members").where("user_id", "==", uid).stream()
        ):
            parent = snap.reference.parent.parent
            if parent is not None:
                ids.add(parent.id)
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            "member_team_ids_failed",
            error_type=type(exc).__name__,
        )
        return ids
    return ids


def user_team_ids(user: dict) -> set[str]:
    cached = user.get("_team_ids")
    if cached is not None:
        return cached
    ids = member_team_ids(user["uid"])
    user["_team_ids"] = ids
    return ids


def is_team_member(team_id: str | None, uid: str) -> bool:
    if not team_id:
        return False
    snap = (
        db()
        .collection("teams")
        .document(str(team_id))
        .collection("members")
        .document(str(uid))
        .get()
    )
    return snap.exists


def team_members(team_id: str) -> list[dict]:
    out = []
    for snap in (
        db().collection("teams").document(str(team_id)).collection("members").stream()
    ):
        item = snap.to_dict() or {}
        item["id"] = snap.id
        out.append(item)
    return out


def team_out(doc: dict) -> dict:
    team_id = doc["id"]
    return {
        "id": team_id,
        "team_name": doc.get("team_name") or "",
        "team_status": doc.get("team_status") or "Active",
        "created_by": doc.get("created_by"),
        "created_at": _iso(doc.get("created_at")),
        "member_count": len(team_members(team_id)),
        "patent_count": len(
            [p for p in list_docs("patents") if p.get("team_id") == team_id]
        ),
    }


def team_member_out(doc: dict, user: dict | None) -> dict:
    return {
        "id": doc["id"],
        "user_id": doc.get("user_id"),
        "email": (user or {}).get("email", ""),
        "full_name": (user or {}).get("full_name", ""),
        "membership_status": doc.get("membership_status"),
        "added_by": doc.get("added_by"),
    }


def team_detail_out(team: dict) -> dict:
    members: dict[str, dict] = {}
    for member in team_members(team["id"]):
        uid = member.get("user_id")
        if not uid:
            continue
        snap = db().collection("users").document(str(uid)).get()
        members[uid] = team_member_out(member, snap.to_dict() if snap.exists else None)
    base = team_out(team)
    base["members"] = sorted(
        members.values(), key=lambda m: (m.get("full_name") or "").lower()
    )
    return base


# ---------------------------------------------------------------------------
# Patents
# ---------------------------------------------------------------------------


def patent_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "team_id": doc.get("team_id"),
        "invention_title": doc.get("invention_title") or "",
        "application_status": doc.get("application_status") or "Draft",
        "assigned_patent_agent_id": doc.get("assigned_patent_agent_id"),
        "ai_status": doc.get("ai_status"),
        "questionnaire_status": doc.get("questionnaire_status"),
        "document_status": doc.get("document_status"),
        "filing_status": doc.get("filing_status"),
        "official_application_number": doc.get("official_application_number"),
        "filing_date": _iso(doc.get("filing_date")),
        "created_by": doc.get("created_by"),
        "created_at": _iso(doc.get("created_at")),
        "updated_at": _iso(doc.get("updated_at")),
    }


def patent_visible(doc: dict, user: dict) -> bool:
    if is_admin(user):
        return True
    uid = user["uid"]
    if doc.get("created_by") == uid or doc.get("assigned_patent_agent_id") == uid:
        return True
    team_id = doc.get("team_id")
    return bool(team_id and team_id in user_team_ids(user))


def visible_patents(user: dict) -> list[dict]:
    return [doc for doc in list_docs("patents") if patent_visible(doc, user)]


def require_patent(patent_id: str, user: dict) -> dict:
    doc = db().collection("patents").document(str(patent_id)).get()
    if not doc.exists:
        from fastapi import HTTPException

        raise HTTPException(404, "Patent application not found.")
    item = doc.to_dict() or {}
    item["id"] = doc.id
    if not patent_visible(item, user):
        from fastapi import HTTPException

        raise HTTPException(403, "You do not have access to this application.")
    return item


def is_patent_creator(patent: dict, user: dict) -> bool:
    return patent.get("created_by") == user["uid"]


def can_edit_basic_info(patent: dict, user: dict) -> bool:
    return (
        patent.get("application_status") == "Draft"
        and (is_patent_creator(patent, user) or is_admin(user))
    )


def can_review_draft(patent: dict, user: dict) -> bool:
    return is_admin(user) or patent.get("assigned_patent_agent_id") == user["uid"]


def active_assignment_count(agent_uid: str) -> int:
    return len(
        [
            doc
            for doc in list_docs("patents")
            if doc.get("assigned_patent_agent_id") == agent_uid
            and doc.get("application_status") in AGENT_ACTIVE_STATUSES
        ]
    )


def patent_participants(patent: dict) -> set[str]:
    participants = {
        patent.get("created_by"),
        patent.get("assigned_patent_agent_id"),
    }
    team_id = patent.get("team_id")
    if team_id:
        participants.update(m.get("user_id") for m in team_members(str(team_id)))
    return {uid for uid in participants if uid}


# ---------------------------------------------------------------------------
# Basic information / questionnaire / drafts
# ---------------------------------------------------------------------------


def applicant_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "applicant_type": doc.get("applicant_type") or "Individual",
        "full_name_or_org_name": doc.get("full_name_or_org_name") or "",
        "address": doc.get("address"),
        "country": doc.get("country"),
        "postal_code": doc.get("postal_code"),
        "email": doc.get("email"),
        "phone": doc.get("phone"),
        "is_primary": bool(doc.get("is_primary")),
        "display_order": int(doc.get("display_order") or 0),
    }


def inventor_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "user_id": doc.get("user_id"),
        "full_name": doc.get("full_name") or "",
        "address": doc.get("address"),
        "country": doc.get("country"),
        "postal_code": doc.get("postal_code"),
        "email": doc.get("email"),
        "phone": doc.get("phone"),
        "inventor_order": int(doc.get("inventor_order") or 0),
    }


QUESTIONNAIRE_FIELDS = (
    "invention_type",
    "problem_statement",
    "proposed_solution",
    "novelty_description",
    "technical_description",
    "advantages",
    "prior_art",
    "keywords",
    "has_existing_drawings",
)
REQUIRED_QUESTIONNAIRE_FIELDS = (
    "invention_type",
    "problem_statement",
    "proposed_solution",
    "novelty_description",
    "technical_description",
)


def questionnaire_out(doc: dict) -> dict:
    raw = doc.get("completion_percentage")
    try:
        percentage = f"{float(raw or 0):.2f}"
    except (TypeError, ValueError):
        percentage = "0.00"
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "questionnaire_status": doc.get("questionnaire_status") or "Not Started",
        "completion_percentage": percentage,
        "invention_type": doc.get("invention_type"),
        "problem_statement": doc.get("problem_statement"),
        "proposed_solution": doc.get("proposed_solution"),
        "novelty_description": doc.get("novelty_description"),
        "technical_description": doc.get("technical_description"),
        "advantages": doc.get("advantages"),
        "prior_art": doc.get("prior_art"),
        "keywords": doc.get("keywords"),
        "has_existing_drawings": doc.get("has_existing_drawings"),
        "created_at": _iso(doc.get("created_at")),
        "updated_at": _iso(doc.get("updated_at")),
    }


def questionnaire_version_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "questionnaire_id": doc.get("questionnaire_id"),
        "patent_application_id": doc.get("patent_application_id"),
        "version_number": int(doc.get("version_number") or 1),
        "version_status": doc.get("version_status"),
        "invention_type": doc.get("invention_type"),
        "problem_statement": doc.get("problem_statement"),
        "proposed_solution": doc.get("proposed_solution"),
        "novelty_description": doc.get("novelty_description"),
        "technical_description": doc.get("technical_description"),
        "advantages": doc.get("advantages"),
        "prior_art": doc.get("prior_art"),
        "keywords": doc.get("keywords"),
        "change_reason": doc.get("change_reason"),
        "created_by": doc.get("created_by"),
    }


def questionnaire_completion(doc: dict) -> tuple[str, str]:
    filled = sum(
        1
        for field in REQUIRED_QUESTIONNAIRE_FIELDS
        if doc.get(field) not in (None, "", [], False)
    )
    percentage = 100.0 * filled / len(REQUIRED_QUESTIONNAIRE_FIELDS)
    if filled == 0:
        status = "Not Started"
    else:
        status = "In Progress"
    return status, f"{percentage:.2f}"


def ai_output_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "questionnaire_version_id": doc.get("questionnaire_version_id"),
        "section_type": doc.get("section_type"),
        "version_number": int(doc.get("version_number") or 1),
        "ai_provider": doc.get("ai_provider"),
        "ai_model": doc.get("ai_model"),
        "ai_response": doc.get("ai_response"),
        "processing_status": doc.get("processing_status"),
        "input_tokens": doc.get("input_tokens"),
        "output_tokens": doc.get("output_tokens"),
        "created_at": _iso(doc.get("created_at")),
    }


# ---------------------------------------------------------------------------
# Collaboration
# ---------------------------------------------------------------------------


def comment_out(doc: dict, user: dict | None) -> dict:
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "user_id": doc.get("user_id"),
        "user_full_name": (user or {}).get("full_name") or None,
        "comment_text": doc.get("comment_text") or "",
        "created_at": _iso(doc.get("created_at")),
    }


def file_out(doc: dict, user: dict | None) -> dict:
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "uploaded_by": doc.get("uploaded_by"),
        "uploaded_by_name": (user or {}).get("full_name") or None,
        "original_file_name": doc.get("original_file_name"),
        "source_file_name": doc.get("source_file_name"),
        "converted_from_pdf": bool(doc.get("converted_from_pdf")),
        "mime_type": doc.get("mime_type"),
        "file_size_bytes": doc.get("file_size_bytes"),
        "created_at": _iso(doc.get("created_at")),
    }


def calendar_event_out(doc: dict, invention_title: str | None = None) -> dict:
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "invention_title": invention_title,
        "event_type": doc.get("event_type"),
        "event_date": _iso(doc.get("event_date")),
        "created_by": doc.get("created_by"),
    }


def notification_out(doc: dict, invention_title: str | None = None) -> dict:
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "invention_title": invention_title,
        "notification_type": doc.get("notification_type"),
        "is_read": bool(doc.get("is_read")),
        "created_at": _iso(doc.get("created_at")),
    }


# ---------------------------------------------------------------------------
# Documents & templates
# ---------------------------------------------------------------------------


def document_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "template_id": doc.get("template_id"),
        "document_type": doc.get("document_type"),
        "output_format": doc.get("output_format"),
        "watermark_status": doc.get("watermark_status"),
        "generated_by": doc.get("generated_by"),
        "generated_at": _iso(doc.get("generated_at")),
    }


def document_version_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "document_id": doc.get("document_id"),
        "version_number": int(doc.get("version_number") or 1),
        "change_summary": doc.get("change_summary"),
        "generated_by": doc.get("generated_by"),
        "generated_at": _iso(doc.get("generated_at")),
    }


def document_job_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "patent_application_id": doc.get("patent_application_id"),
        "status": doc.get("status") or "Queued",
        "output_format": doc.get("output_format"),
        "triggered_by": doc.get("triggered_by"),
        "retried_from_job_id": doc.get("retried_from_job_id"),
        "error_message": doc.get("error_message"),
        "started_at": _iso(doc.get("started_at")),
        "completed_at": _iso(doc.get("completed_at")),
        "created_at": _iso(doc.get("created_at")),
    }


def template_out(doc: dict, editor: dict | None) -> dict:
    return {
        "id": doc["id"],
        "document_type": doc.get("document_type") or "",
        "version_number": int(doc.get("version_number") or 1),
        "file_path": doc.get("file_path"),
        "original_file_name": doc.get("original_file_name"),
        "is_active": bool(doc.get("is_active")),
        "edited_by": doc.get("edited_by"),
        "edited_by_name": (editor or {}).get("full_name") or None,
        "unknown_placeholders": doc.get("unknown_placeholders"),
        "unused_known_placeholders": doc.get("unused_known_placeholders"),
        "template_parse_error": doc.get("template_parse_error"),
    }


# ---------------------------------------------------------------------------
# Side effects: notifications and activity
# ---------------------------------------------------------------------------


def _best_effort(event: str, operation) -> None:
    """Run a secondary write without failing the mutation it follows.

    Notifications and activity rows are recorded after the primary document is
    already committed. Letting one fail would return a 500 for work that did
    succeed, and the client would repeat the mutation.
    """
    try:
        operation()
    except Exception as exc:
        log_event(logger, logging.WARNING, event, error_type=type(exc).__name__)


def notify_many(
    user_ids: set[str] | list[str],
    patent_id: str | None,
    notification_type: str,
    *,
    exclude: str | None = None,
) -> None:
    for uid in {uid for uid in user_ids if uid and uid != exclude}:
        _best_effort(
            "notification_write_failed",
            lambda uid=uid: create_doc(
                "notifications",
                {
                    "user_id": uid,
                    "patent_application_id": patent_id,
                    "notification_type": notification_type,
                    "is_read": False,
                },
            ),
        )


def notify_admins(patent_id: str | None, notification_type: str) -> None:
    try:
        admins = {
            doc["id"]
            for doc in list_docs("users")
            if {"ADMIN", "SUPER_ADMIN"} & set(doc.get("role_codes") or [])
        }
    except Exception as exc:
        log_event(
            logger, logging.WARNING, "admin_lookup_failed", error_type=type(exc).__name__
        )
        return
    notify_many(admins, patent_id, notification_type)


def log_activity(
    user_id: str, event_type: str, entity_type: str, entity_id: str | None
) -> None:
    _best_effort(
        "activity_write_failed",
        lambda: create_doc(
            "activity",
            {
                "user_id": user_id,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "created_at": now_iso(),
            },
        ),
    )


def upcoming_events(patents: list[dict], days: int = 7) -> list[dict]:
    patent_ids = {doc["id"] for doc in patents}
    horizon = datetime.now(timezone.utc) + timedelta(days=days)
    out = []
    for event in list_docs("calendar_events"):
        if event.get("patent_application_id") not in patent_ids:
            continue
        try:
            when = datetime.fromisoformat(
                str(event.get("event_date")).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) <= when <= horizon:
            out.append(event)
    return out
