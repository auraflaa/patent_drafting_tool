"""Static-hosting configuration checks.

These do not need Firebase: they read the checked-in frontend policies and
fail when a deploy config drops a header or a Firebase Auth allowance that the
login flow depends on.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _policy(config: dict) -> str:
    for block in config["headers"]:
        for header in block["headers"]:
            if header["key"].lower() == "content-security-policy":
                return header["value"]
    raise AssertionError("no CSP header")


def test_static_hosting_headers_allow_firebase_auth() -> None:
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    root_vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    app_vercel = json.loads(
        (ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8")
    )

    for value in (_policy(root_vercel), _policy(app_vercel)):
        assert "script-src 'self' https://apis.google.com" in value
        assert (
            "frame-src 'self' https://*.firebaseapp.com "
            "https://accounts.google.com"
        ) in value
        assert "frame-ancestors 'none'" in value

    # Both nginx locations must carry the same Firebase Auth allowances.
    assert nginx.count("https://apis.google.com") == 2
    assert nginx.count("https://*.firebaseapp.com") == 2

    assert root_vercel["rewrites"] == app_vercel["rewrites"] == [
        {"source": "/(.*)", "destination": "/index.html"}
    ]
    assert root_vercel["headers"][0] == app_vercel["headers"][0]
    assert root_vercel["headers"][1] == app_vercel["headers"][1]
