"""SIGN-IN WITH A LOGIN CODE (part of layer 5, security).

The new DOS app signs people in with a company and a six-digit login code. No usernames, no passwords on screen,
and no personal names anywhere: every person is shown by their ROLE (Business Owner, Operations Manager,
Approver, Technician, Auditor) or by their job title.

How a code is found
  1. A user in a client file may carry its own `code:` (use this for real clients).
  2. Otherwise the code is built from the role and the user's position within that role:
       Business Owner 2601xx, Operations Manager 2602xx, Approver 2603xx, Technician 2604xx, Auditor 2605xx
     where xx is 01 for the first person in that role, 02 for the second, and so on.
     DQ_CODE_PREFIX changes the first four digits (default 26), so a new event gets new codes without code changes.

What protects it
  - The code only works for the company that was chosen, and it signs the person in as exactly one user.
  - After 5 wrong codes for a company within 5 minutes, that company's sign-in pauses for 5 minutes.
  - Every attempt, right or wrong, is written to the tamper-evident audit chain.
  - The session token is the same signed token the rest of DOS already trusts (auth.issue_token).

Production path: replace the shared demo codes with one-time codes sent by SMS or email (or Google sign-in);
nothing else in DOS changes, because everything downstream reads the signed token."""
from __future__ import annotations

import os
import re
import time

from . import config
from .auth import issue_token
from .clients import as_client, list_clients
from .store import audit, get_store

ROLE_ORDER = ["owner", "operator", "approver", "technician", "auditor"]
ROLE_NAMES = {"owner": "Business Owner", "operator": "Operations Manager", "approver": "Approver",
              "technician": "Technician", "auditor": "Auditor"}
ROLE_DIGIT = {"owner": "01", "operator": "02", "approver": "03", "technician": "04", "auditor": "05"}
ROLE_SEES = {
    "owner": "Everything: operations, every agent, approvals and the five DOS layers.",
    "operator": "Runs agents end to end, watches live runs and the five DOS layers.",
    "approver": "Decides what agents may not do alone. Can pull the emergency stop.",
    "technician": "Plant floor and their own repair jobs. Acknowledge, start and close.",
    "auditor": "Read-only. Every run, the audit trail and the evidence pack.",
}
# Roles that see the five-layer platform pages. Everyone else sees only the pages their work needs.
LAYER_ROLES = ("owner", "operator")
PREFIX = re.sub(r"\D", "", os.getenv("DQ_CODE_PREFIX", "26"))[:2] or "26"
MAX_TRIES, WINDOW_S = 5, 300
_failures: dict[str, list[float]] = {}


def display_name(user: dict) -> str:
    """What the app shows for a person: the job title without brackets, or the role name. Never a personal name."""
    title = re.sub(r"\s*\(.*?\)\s*", " ", user.get("title") or "").strip()
    generic = {"Business owner / admin", "Agent operator", "Approver / supervisor", "Maintenance technician", "Auditor (read-only)"}
    if not title or (user.get("title") in generic):
        return ROLE_NAMES.get(user["role"], user["role"].title())
    return title


def _sorted_users() -> list[dict]:
    users = get_store().list("users", limit=200)
    return sorted(users, key=lambda u: (ROLE_ORDER.index(u["role"]) if u["role"] in ROLE_ORDER else 9, u["username"]))


def code_for(user: dict, position: int) -> str:
    return str(user.get("code") or f"{PREFIX}{ROLE_DIGIT.get(user['role'], '09')}{position:02d}")


def roster(client_id: str) -> list[dict]:
    """The sign-in cards for one company: one card per person, shown by role and title, with its code in demo mode."""
    with as_client(client_id):
        seen: dict[str, int] = {}
        out = []
        for u in _sorted_users():
            seen[u["role"]] = seen.get(u["role"], 0) + 1
            out.append({"role": u["role"], "role_name": ROLE_NAMES.get(u["role"], u["role"]), "name": display_name(u),
                        "sees": ROLE_SEES.get(u["role"], ""), "layers": u["role"] in LAYER_ROLES,
                        "code": code_for(u, seen[u["role"]]) if config.DEMO_LOGINS else None})
        return out


def _locked(client_id: str) -> bool:
    recent = [t for t in _failures.get(client_id, []) if t > time.time() - WINDOW_S]
    _failures[client_id] = recent
    return len(recent) >= MAX_TRIES


def sign_in(client_id: str, code: str) -> dict:
    """Return {"token", "user"} or raise ValueError with a message that is safe to show."""
    if client_id not in {c["id"] for c in list_clients()}:
        raise ValueError("Unknown company")
    code = re.sub(r"\s", "", code or "")
    with as_client(client_id):
        if _locked(client_id):
            audit("unknown", "auth.code_locked", client_id, {})
            raise ValueError("Too many wrong codes. Sign-in for this company is paused for 5 minutes.")
        seen: dict[str, int] = {}
        for u in _sorted_users():
            seen[u["role"]] = seen.get(u["role"], 0) + 1
            if code and code == code_for(u, seen[u["role"]]):
                shown = {**u, "name": display_name(u)}
                audit(u["username"], "auth.login_code", client_id, {"role": u["role"]})
                return {"token": issue_token(client_id, shown),
                        "user": {"username": u["username"], "name": shown["name"], "role": u["role"], "role_name": ROLE_NAMES.get(u["role"]),
                                 "title": u.get("title"), "technician_id": u.get("technician_id"), "layers": u["role"] in LAYER_ROLES}}
        _failures.setdefault(client_id, []).append(time.time())
        audit("unknown", "auth.login_code_failed", client_id, {})
        raise ValueError("That code is not right for this company.")
