"""Google OAuth 2.0 sign-in (no external auth library — httpx + the Google
OpenID endpoints).

Reuses the shared GCP OAuth client (set via GOOGLE_CLIENT_ID/SECRET). Access is
limited to an allowlist: any email on an allowed domain, plus explicitly allowed
addresses. The flow is optional — when no client id is configured the login page
just shows the email/password form.
"""

from __future__ import annotations

import os
import secrets

import httpx

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
# Explicit redirect (must be registered in the GCP client). Falls back to the
# request origin + /auth/callback when unset.
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

_DEFAULT_DOMAINS = "predictivelabs.co.uk,predictivelabs.ai"
_DEFAULT_EMAILS = "kaljuvee@gmail.com,julian.kaljuvee@gmail.com,info@predictivelabs.co.uk"


def enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def _allowed_domains() -> set[str]:
    return {d.strip().lower() for d in
            os.environ.get("GOOGLE_ALLOWED_DOMAINS", _DEFAULT_DOMAINS).split(",") if d.strip()}


def _allowed_emails() -> set[str]:
    extra = os.environ.get("GOOGLE_ALLOWED_EMAILS", _DEFAULT_EMAILS)
    emails = {e.strip().lower() for e in extra.split(",") if e.strip()}
    if os.environ.get("ADMIN_EMAIL"):
        emails.add(os.environ["ADMIN_EMAIL"].strip().lower())
    return emails


def is_allowed(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    if email in _allowed_emails():
        return True
    domain = email.rsplit("@", 1)[-1]
    return domain in _allowed_domains()


def redirect_uri(request) -> str:
    if GOOGLE_REDIRECT_URI:
        return GOOGLE_REDIRECT_URI
    # Honour the proxy's forwarded proto so prod builds an https URI.
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    return f"{proto}://{host}/auth/callback"


def authorize_url(request, state: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def new_state() -> str:
    return secrets.token_urlsafe(24)


def exchange_code(request, code: str) -> dict | None:
    """Exchange an authorization code for tokens, then fetch the userinfo.
    Returns {email, name} or None on failure."""
    try:
        with httpx.Client(timeout=20) as c:
            tok = c.post(TOKEN_ENDPOINT, data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri(request),
                "grant_type": "authorization_code",
            })
            tok.raise_for_status()
            access = tok.json().get("access_token")
            if not access:
                return None
            ui = c.get(USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access}"})
            ui.raise_for_status()
            data = ui.json()
            if not data.get("email") or not data.get("email_verified", True):
                return None
            return {"email": data["email"], "name": data.get("name") or data["email"]}
    except Exception:
        return None
