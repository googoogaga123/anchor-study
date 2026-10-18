"""Who is signed in.

Two ways in, one session:

  WorkOS AuthKit   the ready-made login service (owner's choice, 18 Oct 2026:
                   free up to 1 million users a month; a hosted sign-in page
                   with email codes, passwords and social logins). /login
                   sends the browser to AuthKit; /callback trades the code
                   for the user's verified email. On when WORKOS_API_KEY and
                   WORKOS_CLIENT_ID are set (environment or .env).
  Dev sign-in      /api/dev-login signs anyone in by email - for this Mac and
                   for recording the demo clips, never for the public site.
                   On by default only while WorkOS is not set up; DEV_LOGIN=1
                   turns it on beside WorkOS (the clip recorder needs it).

Either way the app sets its own signed cookie, and the rest of the app only
calls `current_user(request)`. Set SESSION_SECRET (environment or .env) to
keep people signed in across server restarts.

The owner (an Admin who can promote others) is OWNER_EMAIL when set, else the
first account created. Every user gets their own Library id; nothing is
shared (record 0001). A user whose verified email is at smu.edu.sg (or one of
its subdomains) is marked is_smu, for the "free for SMU students" plan.
"""
import base64
import hashlib
import hmac
import json
import os
import pathlib
import secrets

from fastapi import HTTPException, Request

import db

ENV_FILE = pathlib.Path(__file__).resolve().parent.parent / ".env"


def _env(name, default=None):
    """A setting from the environment, else from .env (never printed or logged)."""
    if os.environ.get(name):
        return os.environ[name]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and key.strip() == name:
                return value.strip().strip("'\"")
    return default


COOKIE = "ailodge_session"
SID_COOKIE = "anchor_wos_sid"   # the WorkOS session, so signing out also ends it there
STATE_COOKIE = "anchor_login_state"
# A random secret per run unless set: sessions end when the server restarts.
SECRET = _env("SESSION_SECRET") or secrets.token_hex(32)
OWNER_EMAIL = (_env("OWNER_EMAIL") or "").strip().lower()
WORKOS_API_KEY, WORKOS_CLIENT_ID = _env("WORKOS_API_KEY"), _env("WORKOS_CLIENT_ID")
LOGIN_SERVICE = bool(WORKOS_API_KEY and WORKOS_CLIENT_ID)
DEV_LOGIN = _env("DEV_LOGIN", "0" if LOGIN_SERVICE else "1") == "1"
_workos = None


def _sign(user_id):
    mac = hmac.new(SECRET.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{mac}"


def _verify(token):
    try:
        uid, mac = token.split(".", 1)
    except (AttributeError, ValueError):
        return None
    good = hmac.new(SECRET.encode(), uid.encode(), hashlib.sha256).hexdigest()
    return int(uid) if hmac.compare_digest(mac, good) else None


def is_smu_email(email):
    domain = email.rpartition("@")[2].lower()
    return domain == "smu.edu.sg" or domain.endswith(".smu.edu.sg")


def _find_or_create(email, name=None, verified=False):
    email = email.strip().lower()
    user = db.one("SELECT * FROM users WHERE email = %s", (email,))
    if not user:
        if OWNER_EMAIL:
            owner = email == OWNER_EMAIL
        else:
            owner = db.one("SELECT count(*) AS n FROM users")["n"] == 0
        user = db.one(
            "INSERT INTO users (email, name, role, library_id) VALUES (%s, %s, %s, %s) RETURNING *",
            (email, name or email.split("@")[0], "owner" if owner else "member", "u-" + secrets.token_hex(8)))
    if verified and is_smu_email(email) and not user.get("is_smu"):
        user = db.one("UPDATE users SET is_smu = true WHERE id = %s RETURNING *", (user["id"],))
    return user


def sign_in(email, name=None):
    """Development sign-in: find or create the user; returns (user, cookie value)."""
    if not DEV_LOGIN:
        raise HTTPException(403, "Development sign-in is off.")
    user = _find_or_create(email, name)
    return user, _sign(user["id"])


# ---- WorkOS AuthKit ----------------------------------------------------------

def _client():
    global _workos
    if _workos is None:
        from workos import WorkOSClient
        _workos = WorkOSClient(api_key=WORKOS_API_KEY, client_id=WORKOS_CLIENT_ID)
    return _workos


def redirect_uri(request: Request):
    """Where AuthKit sends the browser back to: WORKOS_REDIRECT_URI, else this site's /callback.
    It must also be listed under Redirects in the WorkOS dashboard."""
    return _env("WORKOS_REDIRECT_URI") or f"{public_origin(request)}/callback"


def public_origin(request: Request):
    # PUBLIC_ORIGIN (set by serve_public.sh): the address the world uses, e.g. https://<mac>.<tailnet>.ts.net.
    if fixed := _env("PUBLIC_ORIGIN"):
        return fixed.rstrip("/")
    # Behind a tunnel the server sees plain http; the tunnel says what the browser used.
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def login_url(request: Request, state):
    return _client().user_management.get_authorization_url(provider="authkit", redirect_uri=redirect_uri(request),
                                                           state=state)


def finish_login(code):
    """The code AuthKit sent back -> (user, cookie value, WorkOS session id)."""
    try:
        auth = _client().user_management.authenticate_with_code(code=code)
    except Exception as e:
        raise HTTPException(400, "That sign-in link has expired or was already used. Please sign in again.") from e
    u = auth.user
    name = u.first_name or u.name or u.email.split("@")[0]
    user = _find_or_create(u.email, name, verified=bool(u.email_verified))
    return user, _sign(user["id"]), _session_id(auth.access_token)


def _session_id(access_token):
    """The WorkOS session id ("sid") inside the access token - read only to sign out there later."""
    try:
        payload = access_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("sid")
    except (IndexError, ValueError, AttributeError):
        return None


def logout_url(sid, return_to):
    if not (LOGIN_SERVICE and sid):
        return None
    return _client().user_management.get_logout_url(session_id=sid, return_to=return_to)


# ---- The session -------------------------------------------------------------

def current_user(request: Request):
    uid = _verify(request.cookies.get(COOKIE, ""))
    user = db.one("SELECT * FROM users WHERE id = %s", (uid,)) if uid else None
    if not user:
        raise HTTPException(401, "Please sign in.")
    return user


def is_admin(user):
    return user["role"] in ("owner", "admin")
