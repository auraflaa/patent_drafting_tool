"""Ensure the two foundation accounts exist with the right roles.

This is intentionally the *only* seeding entry point. It creates no patents,
teams, questionnaires, drafts, documents, figures, or notifications — those are
entered manually through the application.

The two accounts must have signed in with Google once so Firebase Auth knows
them. The script resolves the Auth UID, then upserts the Firestore profile.

Usage (from backend/ with the venv active):
    python scripts/bootstrap_foundation.py
    python scripts/bootstrap_foundation.py --check
"""
from __future__ import annotations

import argparse
import sys

from firebase_admin import auth

from app.core.firebase import db, initialize_firebase

FOUNDATION = (
    {
        "email": "priyangshumukherjee07@gmail.com",
        "full_name": "Priyangshu Mukherjee",
        "role_codes": ["SUPER_ADMIN"],
    },
    {
        "email": "mmanishablr@gmail.com",
        "full_name": "M Manisha",
        "role_codes": ["INNOVATOR"],
    },
)


def _resolve_uid(email: str) -> str:
    try:
        return auth.get_user_by_email(email).uid
    except Exception as exc:  # noqa: BLE001 - report the actionable cause
        raise SystemExit(
            f"No Firebase Auth user for {email}. Sign in with Google once, then "
            f"run this script again. ({type(exc).__name__})"
        ) from exc


def ensure_user(profile: dict, *, check_only: bool) -> dict:
    uid = _resolve_uid(profile["email"])
    ref = db().collection("users").document(uid)
    snapshot = ref.get()
    current = snapshot.to_dict() or {}
    if check_only:
        return {"uid": uid, **current}
    patch = {
        "email": profile["email"],
        "role_codes": profile["role_codes"],
        "account_status": "approved",
        "is_active": True,
    }
    # Preserve a name the user has set for themselves.
    if not current.get("full_name"):
        patch["full_name"] = profile["full_name"]
    if not snapshot.exists:
        patch.update(
            {
                "profile_picture": None,
                "phone_number": None,
                "designation": None,
                "organization": None,
                "bio": None,
                "email_verified": True,
            }
        )
    ref.set(patch, merge=True)
    return {"uid": uid, **current, **patch}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="print the current profiles without writing anything",
    )
    args = parser.parse_args()

    initialize_firebase()
    for profile in FOUNDATION:
        result = ensure_user(profile, check_only=args.check)
        print(
            f"{result.get('email')} | {result.get('uid')} | "
            f"{result.get('role_codes')} | {result.get('account_status')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
