"""Authentication/profile endpoints.

Sign-in itself happens in the browser with the Firebase JS SDK. The API only
verifies the resulting ID token, syncs the Firestore profile, and serves the
Super Admin approval queue. There is no server-minted JWT and no dev login.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.security import (
    active_user,
    current_user,
    ensure_permission,
    is_super_admin,
    permissions_for,
)
from app.services.projections import log_activity, user_out
from app.services.rbac import ALL_ROLE_CODES
from app.services.repository import (
    get_doc,
    list_docs,
    now_iso,
    sort_docs,
    write_doc,
)

router = APIRouter()

PROFILE_FIELDS = (
    "full_name",
    "phone_number",
    "designation",
    "organization",
    "bio",
    "profile_picture",
)

# Firestore caps a document at 1 MiB. These bounds keep a single profile far
# below that and stop a client from writing arbitrary nested values into
# fields the projections assume are short strings.
PROFILE_FIELD_LIMITS = {
    "full_name": 120,
    "phone_number": 32,
    "designation": 120,
    "organization": 160,
    "bio": 2_000,
    "profile_picture": 500,
}


def _profile_patch(payload: dict) -> dict:
    patch: dict[str, str] = {}
    for key in PROFILE_FIELDS:
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            patch[key] = ""
            continue
        if not isinstance(value, str):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{key} must be a string.",
            )
        text = value.strip()
        if len(text) > PROFILE_FIELD_LIMITS[key]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{key} must be at most {PROFILE_FIELD_LIMITS[key]} characters.",
            )
        if key != "bio" and any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{key} must not contain control characters.",
            )
        if key == "profile_picture" and text and not text.startswith(
            "https://"
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "profile_picture must be an http(s) URL.",
            )
        patch[key] = text
    return patch


def _touch_last_login(user: dict) -> None:
    """Record sign-in activity at most once every five minutes."""
    last = user.get("last_login_at")
    try:
        parsed = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        parsed = None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed and datetime.now(timezone.utc) - parsed < timedelta(minutes=5):
        return
    write_doc(
        "users",
        user["uid"],
        {"last_login_at": now_iso(), "updated_at": now_iso()},
        merge=True,
    )
    user["last_login_at"] = now_iso()


@router.get("/me")
def me(user: dict = Depends(current_user)):
    _touch_last_login(user)
    return {"user": user_out(user), "permissions": permissions_for(user)}


@router.post("/sync")
def sync_profile(
    payload: dict | None = None, user: dict = Depends(current_user)
):
    """Upsert the profile fields the client owns and return the full session."""
    payload = payload or {}
    patch = _profile_patch(payload)
    patch["last_login_at"] = now_iso()
    patch["updated_at"] = now_iso()
    write_doc("users", user["uid"], patch, merge=True)
    user.update(patch)
    return {"user": user_out(user), "permissions": permissions_for(user)}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: dict = Depends(current_user)):
    """Firebase sessions are revoked client-side; this endpoint is a no-op ACK."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/pending-users")
def pending_users(user: dict = Depends(active_user)):
    ensure_permission(user, "USERS_APPROVE")
    pending = [
        doc
        for doc in list_docs("users")
        if (doc.get("account_status") or "pending") == "pending"
    ]
    pending = sort_docs(pending, "created_at")
    return [
        {
            "id": doc["id"],
            "email": doc.get("email") or "",
            "full_name": doc.get("full_name") or "",
            "organization": doc.get("organization"),
            "created_at": doc.get("created_at"),
        }
        for doc in pending
    ]


@router.post("/users/{user_id}/approve")
def approve_user(
    user_id: str, payload: dict | None = None, user: dict = Depends(active_user)
):
    ensure_permission(user, "USERS_APPROVE")
    payload = payload or {}
    role_codes = [str(code).upper() for code in payload.get("role_codes") or []]
    if not role_codes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select at least one role.")
    unknown = sorted(set(role_codes) - set(ALL_ROLE_CODES))
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown role code(s): {', '.join(unknown)}.",
        )
    if "SUPER_ADMIN" in role_codes and not is_super_admin(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a Super Admin can grant the Super Admin role.",
        )
    target = get_doc("users", user_id)
    write_doc(
        "users",
        user_id,
        {
            "account_status": "approved",
            "role_codes": sorted(set(role_codes)),
            "is_active": True,
            "approved_by": user["uid"],
            "approved_at": now_iso(),
            "updated_at": now_iso(),
        },
        merge=True,
    )
    target.update(
        {"account_status": "approved", "role_codes": sorted(set(role_codes))}
    )
    log_activity(user["uid"], "UserApproved", "User", user_id)
    return user_out(target)


@router.post("/users/{user_id}/reject")
def reject_user(
    user_id: str, payload: dict | None = None, user: dict = Depends(active_user)
):
    ensure_permission(user, "USERS_APPROVE")
    if user_id == user["uid"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "You cannot reject your own account.",
        )
    target = get_doc("users", user_id)
    if "SUPER_ADMIN" in (target.get("role_codes") or []):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Revoke the Super Admin role before rejecting this account.",
        )
    write_doc(
        "users",
        user_id,
        {
            "account_status": "rejected",
            "rejected_by": user["uid"],
            "rejected_at": now_iso(),
            "updated_at": now_iso(),
        },
        merge=True,
    )
    target.update({"account_status": "rejected"})
    log_activity(user["uid"], "UserRejected", "User", user_id)
    return user_out(target)
