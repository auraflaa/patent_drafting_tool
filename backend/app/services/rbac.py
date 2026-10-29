"""Role/permission catalog and report-download matrix.

The catalog is code-defined (four fixed roles, a small permission set) while
the *overrides* live in Firestore. That keeps a fresh Firebase project usable
without a seed script and still lets a Super Admin edit the matrix at runtime.

Firestore fields used by the user document remain `role_codes` (ADR-002);
the REST projections expose them as `roles`.
"""
from app.core.firebase import FirebaseNotConfigured
from app.services.repository import create_doc, list_docs

SUPER_ADMIN = "SUPER_ADMIN"
ADMIN = "ADMIN"
PATENT_AGENT = "PATENT_AGENT"
INNOVATOR = "INNOVATOR"

ALL_ROLE_CODES = (SUPER_ADMIN, ADMIN, PATENT_AGENT, INNOVATOR)

# (id, role_name, role_code, is_system_role)
ROLES = (
    (1, "Super Admin", SUPER_ADMIN, True),
    (2, "Admin", ADMIN, True),
    (3, "Patent Agent", PATENT_AGENT, True),
    (4, "Innovator", INNOVATOR, True),
)
ROLE_BY_ID = {row[0]: row for row in ROLES}

# (id, permission_name, permission_code, module_name, action)
PERMISSIONS = (
    (1, "View Patent Applications", "PATENTS_VIEW", "Patent Applications", "view"),
    (2, "Create Patent Applications", "PATENTS_CREATE", "Patent Applications", "create"),
    (3, "Edit Patent Applications", "PATENTS_EDIT", "Patent Applications", "edit"),
    (4, "Submit Patent Applications", "PATENTS_SUBMIT", "Patent Applications", "submit"),
    (5, "Assign Patent Agent", "PATENTS_ASSIGN", "Patent Applications", "assign"),
    (6, "Reassign Patent Agent", "PATENTS_REASSIGN", "Patent Applications", "reassign"),
    (7, "Edit Basic Information", "BASIC_INFO_EDIT", "Basic Information", "edit"),
    (8, "Edit Questionnaire", "QUESTIONNAIRE_EDIT", "Questionnaire", "edit"),
    (9, "Submit Questionnaire", "QUESTIONNAIRE_SUBMIT", "Questionnaire", "submit"),
    (10, "View AI Drafts", "DRAFTS_VIEW", "AI Drafting", "view"),
    (11, "Generate AI Drafts", "DRAFTS_GENERATE", "AI Drafting", "generate"),
    (12, "View Documents", "DOCUMENTS_VIEW", "Documents", "view"),
    (13, "Generate Documents", "DOCUMENTS_GENERATE", "Documents", "generate"),
    (14, "Post Comments", "COMMENTS_POST", "Collaboration", "comment"),
    (15, "Upload Files", "FILES_UPLOAD", "Collaboration", "upload"),
    (16, "Delete Files", "FILES_DELETE", "Collaboration", "delete"),
    (17, "View Calendar", "CALENDAR_VIEW", "Calendar", "view"),
    (18, "Manage Calendar", "CALENDAR_MANAGE", "Calendar", "manage"),
    (19, "View Teams", "TEAMS_VIEW", "Teams", "view"),
    (20, "Manage Teams", "TEAMS_MANAGE", "Teams", "manage"),
    (21, "View Templates", "TEMPLATES_VIEW", "Templates", "view"),
    (22, "Manage Templates", "TEMPLATES_MANAGE", "Templates", "manage"),
    (23, "View Notifications", "NOTIFICATIONS_VIEW", "Notifications", "view"),
    (24, "View Reports", "REPORTS_VIEW", "Reports", "view"),
    (25, "Download Reports", "REPORTS_DOWNLOAD", "Reports", "download"),
    (26, "Manage Roles & Permissions", "RBAC_MANAGE", "Administration", "manage"),
    (27, "Approve Users", "USERS_APPROVE", "Administration", "approve"),
)
PERMISSION_BY_ID = {row[0]: row for row in PERMISSIONS}
ALL_PERMISSION_IDS = tuple(row[0] for row in PERMISSIONS)
ALL_PERMISSION_CODES = tuple(row[2] for row in PERMISSIONS)

_ALL_IDS = set(ALL_PERMISSION_IDS)

DEFAULT_GRANTS: dict[int, set[int]] = {
    1: set(_ALL_IDS),
    2: _ALL_IDS - {26, 27},
    3: {1, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 23, 24, 25},
    4: {1, 2, 3, 4, 5, 7, 8, 9, 12, 14, 15, 16, 17, 19, 20, 23, 24, 25},
}

REPORT_TYPES = (
    {
        "report_type": "patent_applications",
        "label": "Patent Applications",
        "description": "Every application visible to you with lifecycle status and assignment.",
    },
    {
        "report_type": "documents",
        "label": "Generated Documents",
        "description": "Generated DOCX/PDF versions with their source application.",
    },
    {
        "report_type": "calendar_events",
        "label": "Calendar Events",
        "description": "Filing deadlines, examinations, hearings, and reminders.",
    },
    {
        "report_type": "users",
        "label": "Users",
        "description": "Accounts, approval status, and granted roles (Admin and Super Admin).",
    },
)
REPORT_TYPE_NAMES = tuple(row["report_type"] for row in REPORT_TYPES)
_DEFAULT_REPORT_GRANTS: dict[int, set[str]] = {
    1: set(REPORT_TYPE_NAMES),
    2: set(REPORT_TYPE_NAMES),
    3: set(),
    4: set(),
}


def is_admin_like(user: dict) -> bool:
    return bool({ADMIN, SUPER_ADMIN} & set(user.get("role_codes") or []))


def role_ids_for(role_codes: list[str]) -> list[int]:
    return sorted(
        row[0] for row in ROLES if row[2] in set(role_codes or [])
    )


def _overrides(collection: str) -> dict[str, bool]:
    """Stored grants, or none at all when no overrides have been written.

    A brand-new Firebase project has no `rbac_overrides` documents; the
    code-defined matrix is then the effective one. Reaching Firestore is
    still required to read any overrides, so this is not a no-op cache.
    """
    try:
        docs = list_docs(collection, limit=1000)
    except FirebaseNotConfigured:
        return {}
    return {
        doc["id"]: bool(doc.get("granted"))
        for doc in docs
    }


def _effective_permission_ids(role_id: int, overrides: dict[str, bool]) -> set[int]:
    granted = set(DEFAULT_GRANTS.get(role_id, set()))
    for permission_id in ALL_PERMISSION_IDS:
        key = f"{role_id}-{permission_id}"
        if key in overrides:
            if overrides[key]:
                granted.add(permission_id)
            else:
                granted.discard(permission_id)
    return granted


def permission_codes(user: dict) -> list[str]:
    role_ids = role_ids_for(user.get("role_codes") or [])
    if 1 in role_ids:
        return list(ALL_PERMISSION_CODES)
    overrides = _overrides("rbac_overrides")
    codes: set[str] = set()
    for role_id in role_ids:
        for permission_id in _effective_permission_ids(role_id, overrides):
            codes.add(PERMISSION_BY_ID[permission_id][2])
    return sorted(codes)


def role_out(row: tuple) -> dict:
    return {
        "id": row[0],
        "role_name": row[1],
        "role_code": row[2],
        "is_system_role": row[3],
    }


def permission_out(row: tuple) -> dict:
    return {
        "id": row[0],
        "permission_name": row[1],
        "permission_code": row[2],
        "module_name": row[3],
        "action": row[4],
    }


def matrix() -> dict:
    overrides = _overrides("rbac_overrides")
    grants = [
        {"role_id": role_id, "permission_id": permission_id}
        for role_id in ROLE_BY_ID
        for permission_id in sorted(_effective_permission_ids(role_id, overrides))
    ]
    return {
        "roles": [role_out(row) for row in ROLES],
        "permissions": [permission_out(row) for row in PERMISSIONS],
        "grants": grants,
    }


def toggle_grant(role_id: int, permission_id: int, grant: bool) -> dict:
    if role_id == 1:
        raise ValueError("Super Admin always has full access.")
    if role_id not in ROLE_BY_ID or permission_id not in PERMISSION_BY_ID:
        raise ValueError("Unknown role or permission.")
    doc_id = f"{role_id}-{permission_id}"
    create_doc(
        "rbac_overrides",
        {"role_id": role_id, "permission_id": permission_id, "granted": bool(grant)},
        doc_id,
    )
    return matrix()


def _effective_report_types(role_id: int, overrides: dict[str, bool]) -> set[str]:
    granted = set(_DEFAULT_REPORT_GRANTS.get(role_id, set()))
    for report_type in REPORT_TYPE_NAMES:
        key = f"{role_id}-{report_type}"
        if key in overrides:
            if overrides[key]:
                granted.add(report_type)
            else:
                granted.discard(report_type)
    return granted


def report_matrix() -> dict:
    overrides = _overrides("report_permission_overrides")
    return {
        "roles": [role_out(row) for row in ROLES],
        "report_types": [
            {
                "report_type": row["report_type"],
                "label": row["label"],
                "description": row["description"],
            }
            for row in REPORT_TYPES
        ],
        "grants": [
            {"role_id": role_id, "report_type": report_type}
            for role_id in ROLE_BY_ID
            for report_type in sorted(_effective_report_types(role_id, overrides))
        ],
    }


def toggle_report_permission(role_id: int, report_type: str, grant: bool) -> dict:
    if role_id in (1, 2):
        raise ValueError("Admin and Super Admin can always download reports.")
    if role_id not in ROLE_BY_ID or report_type not in REPORT_TYPE_NAMES:
        raise ValueError("Unknown role or report type.")
    if report_type == "users":
        raise ValueError(
            "The users report is restricted to Admin and Super Admin roles."
        )
    create_doc(
        "report_permission_overrides",
        {"role_id": role_id, "report_type": report_type, "granted": bool(grant)},
        f"{role_id}-{report_type}",
    )
    return report_matrix()


def report_type_granted(user: dict, report_type: str) -> bool:
    if is_admin_like(user):
        return True
    overrides = _overrides("report_permission_overrides")
    for role_id in role_ids_for(user.get("role_codes") or []):
        if report_type in _effective_report_types(role_id, overrides):
            return True
    return False


def can_download_report(
    user: dict, report_type: str, has_download_permission: bool
) -> bool:
    """Whether the caller may download one report type.

    `has_download_permission` carries the caller's REPORTS_DOWNLOAD decision
    so this module never imports core.security (which would create a cycle).
    """
    if is_admin_like(user) or has_download_permission:
        return report_type_granted(user, report_type)
    return False
