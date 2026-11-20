"""SIGN-IN AND SESSIONS (part of layer 5, security).

Each client has its own users. A user belongs to exactly one client and has exactly one role. Signing in returns a
session token: the user's identity, client, role and expiry, signed with HMAC-SHA256 using a server secret. The
server trusts nothing else: the console cannot claim another role or another client, because changing the token
breaks the signature.

Passwords are stored only as salted PBKDF2-SHA256 hashes. Demo users and their shared demo password are listed on
the sign-in page only when DQ_DEMO_LOGINS=1 (for buildathon reviewers); switch it off for real clients.

Production path: Identity Platform (or Google Workspace sign-in) issues the identity; DOS keeps the same role and
client checks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from . import config
from .clients import as_client, list_clients
from .store import audit, get_store, now

DEMO_PASSWORD = os.getenv("DQ_DEMO_PASSWORD", "DOS@2026")
ROLE_TITLES = {"owner": "Business owner / admin", "operator": "Agent operator", "approver": "Approver / supervisor",
               "technician": "Maintenance technician", "auditor": "Auditor (read-only)"}
DEFAULT_USERS = [  # for clients whose file lists no users
    {"username": "owner", "name": "Business Owner", "role": "owner"},
    {"username": "operator", "name": "Operations Manager", "role": "operator"},
    {"username": "approver", "name": "Supervisor", "role": "approver"},
    {"username": "auditor", "name": "Compliance Auditor", "role": "auditor"},
]


def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def _verify(password: str, stored: str) -> bool:
    try:
        salt_b64, _ = stored.split("$", 1)
        return hmac.compare_digest(_hash(password, base64.b64decode(salt_b64)), stored)
    except ValueError:
        return False


def seed_users(client_files: dict[str, list[dict]]) -> int:
    """Create each client's users once. Existing users are never overwritten."""
    n = 0
    for c in list_clients():
        with as_client(c["id"]):
            for u in client_files.get(c["id"]) or DEFAULT_USERS:
                if get_store().get("users", u["username"]):
                    continue
                get_store().put("users", u["username"], {"username": u["username"], "name": u["name"], "role": u["role"],
                                                          "title": u.get("title") or ROLE_TITLES[u["role"]], "technician_id": u.get("technician_id"),
                                                          "approves": u.get("approves") or [],
                                                          "password_hash": _hash(u.get("password") or DEMO_PASSWORD), "created_at": now()})
                n += 1
    return n


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(client_id: str, user: dict) -> str:
    payload = {"c": client_id, "u": user["username"], "r": user["role"], "n": user["name"], "t": user.get("technician_id"),
               "exp": int(time.time()) + config.SESSION_HOURS * 3600}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(config.SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> dict | None:
    """Return the payload if the signature is valid and the token has not expired; otherwise None."""
    try:
        body, sig = token.split(".", 1)
        good = _b64(hmac.new(config.SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(good, sig):
            return None
        payload = json.loads(_unb64(body))
        return payload if payload.get("exp", 0) > time.time() else None
    except Exception:
        return None


def login(client_id: str, username: str, password: str) -> dict | None:
    with as_client(client_id):
        user = get_store().get("users", username.strip().lower())
        if not user or not _verify(password, user["password_hash"]):
            audit(username[:40] or "unknown", "auth.login_failed", client_id, {})
            return None
        audit(user["username"], "auth.login", client_id, {"role": user["role"]})
        return {"token": issue_token(client_id, user), "user": {k: user[k] for k in ("username", "name", "role", "title", "technician_id")}}


def demo_users(client_id: str) -> list[dict]:
    if not config.DEMO_LOGINS:
        return []
    with as_client(client_id):
        order = ["owner", "operator", "approver", "technician", "auditor"]
        rows = [{k: u[k] for k in ("username", "name", "role", "title", "technician_id")} for u in get_store().list("users", limit=50)]
        return sorted(rows, key=lambda u: (order.index(u["role"]), u["username"]))


def designated_approvers(tool: str) -> list[dict]:
    """Users named in the client file as the ONLY people who may decide this action (segregation of duties).
    Empty list: any approver of this client may decide it."""
    return [{"username": u["username"], "name": u["name"], "title": u["title"]} for u in get_store().list("users", limit=200) if tool in (u.get("approves") or [])]
