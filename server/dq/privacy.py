"""PERSONAL DATA MASKING (layer 3). One place that decides how a personal value looks on a screen.

Used by the gold-layer data view, the event watch and the simulated model's closing answer, so a name, phone number,
document number, date of birth or health detail is never shown in full outside the agent's own tool call.

Masking keeps just enough to be useful to a supervisor (the shape of the value and its last characters), never
enough to identify the person:
    name           "Suresh Babu Raman"   -> "S••••• B. R."
    phone          "+91-90000-01002"     -> "+91 •••••• 1002"
    email          "anita@example.com"   -> "a••••@example.com"
    id number      "ABCPB1234K"          -> "••••••234K"
    date of birth  "1988-04-12"          -> "1988-••-••"
    age            54                    -> "50-59"
    health detail  "None recorded"       -> "[health data hidden]"
"""
from __future__ import annotations

import re
from typing import Any

# Column or key names that hold personal data, matched as whole words inside the key ("customer_name", "phone").
_KINDS = [
    ("health", re.compile(r"(allerg|diagnos|condition|medication|result_value|symptom)")),
    ("email", re.compile(r"(^|_)e?mail($|_)")),
    ("phone", re.compile(r"(^|_)(phone|mobile|whatsapp|contact_no|to)($|_)")),
    ("dob", re.compile(r"(^|_)(dob|date_of_birth|birth_date)($|_)")),
    ("age", re.compile(r"(^|_)age($|_)")),
    ("idnum", re.compile(r"(^|_)(number|pan|aadhaar|passport|account_no|card|ssn|national_id)($|_)")),
    ("address", re.compile(r"(^|_)(address|street|house)($|_)")),
    ("name", re.compile(r"(^|_)(name|customer|borrower|patient_name|applicant_name|full_name|technician_name|contact)($|_)")),
]
# Keys that look personal by the rules above but are not (catalogue titles, segment names, machine names).
_NOT_PERSONAL = {"machine_name", "segment", "brand_name", "business_name", "product_name", "campaign_name", "skill_name", "table_name",
                 "client_name", "agent_name", "role_name", "file_name", "item_name", "supplier", "supplier_name", "title"}


def kind_of(key: str, extra: tuple | list = ()) -> str | None:
    """Which kind of personal value a key holds, or None. `extra` = the dataset's own list of personal fields."""
    k = str(key).lower()
    if k in _NOT_PERSONAL:
        return None
    for kind, rx in _KINDS:
        if rx.search(k):
            return kind
    if k in {str(e).lower() for e in extra}:
        return "name"
    return None


def mask_value(kind: str, v: Any) -> Any:
    if v in (None, ""):
        return v
    s = str(v)
    if kind == "health":
        return "[health data hidden]"
    if kind == "email":
        user, _, dom = s.partition("@")
        return f"{user[:1]}••••@{dom}" if dom else "••••"
    if kind == "phone":
        digits = re.sub(r"\D", "", s)
        cc = "+91 " if s.startswith("+91") else ("+" + digits[:2] + " " if s.startswith("+") else "")
        return f"{cc}•••••• {digits[-4:]}" if len(digits) >= 6 else "••••••"
    if kind == "dob":
        return s[:4] + "-••-••" if re.match(r"^\d{4}-", s) else "••-••-••••"
    if kind == "age":
        try:
            n = int(float(s))
            return f"{n // 10 * 10}-{n // 10 * 10 + 9}"
        except ValueError:
            return "••"
    if kind == "idnum":
        tail = re.sub(r"[^A-Za-z0-9]", "", s)[-4:]
        return "••••••" + tail if len(s) > 4 else "••••"
    if kind == "address":
        return "[address hidden]"
    # names: initial of the first word, initials of the rest
    words = [w for w in re.split(r"\s+", s.strip()) if w]
    if not words:
        return s
    if re.fullmatch(r"[A-Z]{2,5}-\d{3,6}", s):  # an ID such as CUS-4001 in a "customer" column is not a name
        return s
    first = words[0][:1] + "•" * max(3, min(6, len(words[0]) - 1))
    return " ".join([first] + [w[:1] + "." for w in words[1:]])


def mask(obj: Any, extra: tuple | list = (), key: str = "") -> Any:
    """Mask every personal value inside a record, a list of records or a nested structure."""
    kind = kind_of(key, extra) if key else None
    if isinstance(obj, dict):
        if kind == "health":
            return "[health data hidden]"
        return {k: mask(v, extra, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v, extra, key) for v in obj]
    return mask_value(kind, obj) if kind else obj


def masked_fields(rows: list[dict], extra: tuple | list = ()) -> list[str]:
    """Which columns of these rows were masked (for the 'PII masked' badges)."""
    cols = list(dict.fromkeys(c for r in rows if isinstance(r, dict) for c in r))
    return [c for c in cols if kind_of(c, extra)]
