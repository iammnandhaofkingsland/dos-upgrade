"""LAYER 2: CLIENT CONFIGURATION.

One platform, many clients, and every client is different: different language, contact hours, waiver limit,
refund limit, approval rules. This layer holds those differences as DATA, so serving a new client is a
configuration change and never a code change.

Three ideas make it a tight framework rather than a settings page:
  1. A SCHEMA. Every setting is declared once in POLICIES with a type, a default and hard bounds.
     A client can move a value only inside the bounds. Some settings are LOCKED: no client can change them.
  2. ONE ACCESSOR. Code never reads a setting from a dict. It calls policy("lending.max_waiver_pct").
     That call returns the current client's value AND writes the read into the run trace.
  3. VERSIONS. Every change makes a new numbered version with a diff, an author and a note.
     Every run records the version it ran under, so you can always answer: which rules were in force?"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import json
import logging
import os
import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import config
from .context import client_var, current_client, current_run
from .store import audit, get_store, now
from .trace import write_step

log = logging.getLogger("dq.clients")
CLIENTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "clients"
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class P:
    key: str
    label: str
    type: str  # int | float | bool | time | list | choice | text
    default: Any
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()
    locked: bool = False
    unit: str = ""
    help: str = ""
    enforced: str = ""  # where in the code this value is enforced (shown in the console and the evidence pack)
    group: str = field(default="", compare=False)


def _g(group: str, *items: P) -> list[P]:
    return [P(**{**i.__dict__, "group": group}) for i in items]


POLICIES: list[P] = [
    *_g("Messaging",
        P("messaging.language", "Default reply language", "choice", "English", choices=("English", "Hindi", "Tamil", "Kannada", "Telugu", "Marathi", "Bengali"),
          help="Agents reply in this language unless the customer writes in another.", enforced="Agent instruction (factory.build_instruction)"),
        P("messaging.tone", "Tone of voice", "choice", "Warm and simple", choices=("Warm and simple", "Formal", "Friendly and brief"),
          help="Added to every agent's instruction.", enforced="Agent instruction"),
        P("messaging.allowed_channels", "Channels agents may use", "list", ["whatsapp", "sms", "email"], choices=("whatsapp", "sms", "email"),
          help="A message on any other channel is refused by the tool.", enforced="tools/common.send_message"),
        P("messaging.enforce_contact_hours", "Enforce contact hours", "bool", True,
          help="Outside the window, WhatsApp and SMS messages are queued for the next window, not sent.", enforced="tools/common.send_message"),
        P("messaging.contact_start", "Contact window starts", "time", "08:00", help="Local time, 24-hour.", enforced="tools/common.send_message"),
        P("messaging.contact_end", "Contact window ends", "time", "19:00", help="Local time, 24-hour.", enforced="tools/common.send_message"),
        P("messaging.blocked_phrases", "Phrases agents must never send", "list",
          ["legal action", "police", "final warning", "we will come to your house", "inform your employer", "shame"],
          help="An outbound message containing any of these is blocked before it is sent.", enforced="plugins.GuardrailPlugin.before_tool_callback"),
        P("messaging.test_clock", "Test clock (rehearsal only)", "text", "",
          help="Leave empty to use the real time. Set HH:MM to rehearse contact-hour rules at any time of day.", enforced="clients.client_clock")),
    *_g("Lending",
        P("lending.max_waiver_pct", "Maximum late-fee waiver", "float", 10, lo=0, hi=25, unit="%",
          help="An offer above this is refused by the tool, whatever the model says.", enforced="tools/fintech.offer_settlement"),
        P("lending.min_paid_instalments_for_waiver", "Instalments paid before a waiver is allowed", "int", 6, lo=0, hi=36,
          help="Borrowers below this are not eligible for a waiver.", enforced="tools/fintech.offer_settlement"),
        P("lending.min_credit_score", "Minimum credit score", "int", 650, lo=300, hi=900, enforced="tools/fintech.check_loan_eligibility"),
        P("lending.max_foir_pct", "Maximum instalment-to-income", "float", 50, lo=20, hi=70, unit="%", enforced="tools/fintech.check_loan_eligibility"),
        P("lending.max_income_multiple", "Maximum loan as a multiple of monthly income", "float", 8, lo=1, hi=24, unit="x", enforced="tools/fintech.check_loan_eligibility"),
        P("lending.flat_rate_pct", "Annual flat interest rate", "float", 24, lo=6, hi=36, unit="%", enforced="tools/fintech.check_loan_eligibility"),
        P("lending.reporting_threshold_inr", "Cash reporting threshold", "int", 50000, lo=10000, hi=1000000, unit="Rs", enforced="tools/fintech.list_account_transactions")),
    *_g("Retail and e-commerce",
        P("commerce.return_window_days", "Return window", "int", 7, lo=0, hi=60, unit="days", enforced="tools/commerce.check_return_eligibility"),
        P("commerce.auto_refund_limit_inr", "Refund without approval up to", "int", 1500, lo=0, hi=5000, unit="Rs",
          help="A refund above this amount waits for a human approver. The platform caps this at Rs 5,000.", enforced="factory.approval_rule + tools/commerce"),
        P("retail.safety_days", "Stock safety buffer", "int", 2, lo=0, hi=30, unit="days", help="An item is at risk when cover is below lead time plus this.", enforced="tools/commerce.get_stock_levels"),
        P("marketing.banned_words", "Words not allowed in posts and listings", "list", ["cheap", "guaranteed", "best in the world"],
          help="A post, email or listing containing any of these is refused.", enforced="tools/services.schedule_post, tools/commerce")),
    *_g("Manufacturing",
        P("manufacturing.auto_response", "Run the downtime response automatically", "bool", True,
          help="When a machine alarm is confirmed, DOS runs MachineWatch, RootCauseIQ, FixDispatch, SpareSense, PlanSync and LotTrace in order.", enforced="response.respond"),
        P("manufacturing.alarm_confirm_samples", "Readings beyond the limit before an alarm is confirmed", "int", 3, lo=1, hi=10,
          help="Higher values mean fewer false alarms but slower detection. One reading every 2 seconds.", enforced="plant.run_loop"),
        P("manufacturing.ack_minutes", "Minutes a technician has to acknowledge a work order", "int", 10, lo=1, hi=60,
          help="If nobody acknowledges in time, DOS escalates to the maintenance supervisor.", enforced="response.check_escalations"),
        P("manufacturing.spare_auto_limit_inr", "Spare-part order without approval up to", "int", 25000, lo=0, hi=500000, unit="Rs",
          help="A spare-part order above this value waits for the maintenance head.", enforced="factory.approval_plan + tools/manufacturing.order_spare_part"),
        P("manufacturing.min_rootcause_confidence", "Minimum root-cause confidence to dispatch on", "float", 0.5, lo=0.3, hi=0.9,
          help="Below this, RootCauseIQ says the cause is uncertain and a senior technician inspects first.", enforced="tools/manufacturing.rank_root_causes"),
        P("manufacturing.downtime_cost_per_hour_inr", "Cost of one hour of downtime", "int", 150000, lo=1000, hi=100000000, unit="Rs",
          help="Used to show the cost of downtime on the plant floor. Use your own figure.", enforced="api.plant_state"),
        P("manufacturing.machines_read_only", "Agents are read-only on machines", "bool", True, locked=True,
          help="Platform rule. No agent can start, stop or change a machine. Stopping is the shift supervisor's decision.", enforced="tools/manufacturing (no machine-control tool exists)")),
    *_g("Wholesale",
        P("wholesale.price_tolerance_pct", "Invoice price tolerance", "float", 2, lo=0, hi=10, unit="%",
          help="Invoice prices further than this from the purchase order are exceptions.", enforced="tools/wholesale.match_invoice")),
    *_g("Data",
        P("data.sql_row_limit", "Maximum rows an agent may read per query", "int", 50, lo=1, hi=500, enforced="tools/services.run_sql"),
        P("data.block_personal_columns", "Block personal columns in agent SQL", "bool", True,
          help="Queries that select columns marked as personal data are refused.", enforced="tools/services.run_sql")),
    *_g("Safety limits",
        P("safety.mask_identity_numbers", "Mask Aadhaar, PAN and card numbers", "bool", True, locked=True,
          help="Platform rule. Cannot be turned off by any client.", enforced="plugins.GuardrailPlugin"),
        P("safety.screen_untrusted_text", "Neutralise instructions hidden in data", "bool", True, locked=True,
          help="Platform rule. Text that tries to instruct the agent from inside a tool result is removed.", enforced="plugins.GuardrailPlugin.after_tool_callback"),
        P("safety.max_tool_calls", "Maximum tool calls per run", "int", 12, lo=4, hi=20, enforced="plugins.GuardrailPlugin"),
        P("safety.max_llm_calls", "Maximum model calls per run", "int", 15, lo=4, hi=25, enforced="plugins.GuardrailPlugin")),
    *_g("Budgets",
        P("budgets.daily_run_limit", "Runs per agent per day", "int", 200, lo=1, hi=100000, enforced="api.start_run"),
        P("budgets.monthly_cost_cap_inr", "Model spend cap per month", "int", 5000, lo=100, hi=1000000, unit="Rs",
          help="New runs are refused once this month's model cost reaches the cap.", enforced="api.start_run")),
    *_g("Governance",
        P("governance.eval_threshold", "Evaluation score needed to go live", "float", 0.8, lo=0.6, hi=1.0, enforced="evalgate.run_gate"),
        P("governance.four_eyes", "Approver must differ from requester", "bool", False,
          help="The person who started a run cannot approve its actions.", enforced="runs.RunManager.decide"),
        P("governance.risk_acceptance_for_high", "High-risk agents need a named risk owner", "bool", True, locked=True,
          help="Platform rule. A High-risk agent cannot go live until the Owner records a risk acceptance.", enforced="governance.deployment_gate")),
]
SCHEMA: dict[str, P] = {p.key: p for p in POLICIES}
PROFILE_FIELDS = ("name", "industry", "verticals", "accent", "contact")


class ConfigError(ValueError):
    pass


# ---------------------------------------------------------------- validation
def coerce(key: str, value: Any) -> Any:
    """Check one value against the schema. Returns the cleaned value or raises ConfigError with a plain reason."""
    if key not in SCHEMA:
        raise ConfigError(f"{key}: not a known setting. Known settings are listed in the schema.")
    p = SCHEMA[key]
    if p.locked:
        raise ConfigError(f"{p.label}: this is a platform rule and cannot be changed by a client.")
    try:
        if p.type in ("int", "float"):
            v = int(value) if p.type == "int" else float(value)
            if (p.lo is not None and v < p.lo) or (p.hi is not None and v > p.hi):
                raise ConfigError(f"{p.label}: {v} is outside the allowed range {p.lo:g} to {p.hi:g}{' ' + p.unit if p.unit else ''}.")
            return v
        if p.type == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("true", "yes", "1", "on")
            return bool(value)
        if p.type == "time":
            if not HHMM.match(str(value)):
                raise ConfigError(f"{p.label}: use 24-hour HH:MM, for example 08:00.")
            return str(value)
        if p.type == "choice":
            if value not in p.choices:
                raise ConfigError(f"{p.label}: choose one of {', '.join(p.choices)}.")
            return value
        if p.type == "list":
            items = [s.strip() for s in value.split(",")] if isinstance(value, str) else [str(s).strip() for s in value]
            items = [s for s in items if s]
            if p.choices and set(items) - set(p.choices):
                raise ConfigError(f"{p.label}: allowed values are {', '.join(p.choices)}.")
            if len(items) > 40:
                raise ConfigError(f"{p.label}: at most 40 entries.")
            return items
        if key == "messaging.test_clock" and value and not HHMM.match(str(value)):
            raise ConfigError("Test clock: leave empty or use HH:MM.")
        return str(value)[:200]
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"{p.label}: {value!r} is not a valid {p.type}.") from None


def effective(client: dict) -> dict[str, Any]:
    """Every setting with its value for this client (override, or the platform default)."""
    return {p.key: client.get("policies", {}).get(p.key, p.default) for p in POLICIES}


def schema_public() -> list[dict]:
    return [{"key": p.key, "group": p.group, "label": p.label, "type": p.type, "default": p.default, "min": p.lo, "max": p.hi,
             "choices": list(p.choices), "locked": p.locked, "unit": p.unit, "help": p.help, "enforced": p.enforced} for p in POLICIES]


# ---------------------------------------------------------------- reading
_cache: dict[str, tuple[float, dict]] = {}


def get_client(client_id: str | None = None) -> dict:
    cid = client_id or current_client()
    hit = _cache.get(cid)
    if hit and time.time() - hit[0] < 3:
        return hit[1]
    doc = get_store().get("clients", cid)
    if not doc and not get_store().list("clients", limit=1):
        seed_clients()  # first use in a fresh process or a fresh test store
        doc = get_store().get("clients", cid)
    if not doc:
        raise KeyError(f"No client {cid!r}")
    _cache[cid] = (time.time(), doc)
    return doc


def list_clients() -> list[dict]:
    return get_store().list("clients", order_by="name", descending=False, limit=200)


def policy(key: str) -> Any:
    """THE way to read a client setting. Returns the value for the current client and, inside an agent run,
    writes the read into the trace (once per setting per tool call) so the run shows which rule applied."""
    p = SCHEMA[key]  # a KeyError here is a programming mistake: the setting is not declared
    value = get_client().get("policies", {}).get(key, p.default)
    run = current_run()
    if run is not None and not run.get("quiet"):
        # Reads made for a tool are shown once per tool call; reads made by the platform itself once per run.
        seen = run["seen"] if run.get("tool") else run.setdefault("seen_run", set())
        mark = (key, run.get("tool"))
        if mark not in seen:
            seen.add(mark)
            write_step(run["run_id"], "config", key, detail=p.label, value=value, unit=p.unit, by=run.get("tool") or "platform", status="read")
    return value


def client_clock() -> str:
    """Current local time HH:MM for contact-hour rules. India Standard Time; a test clock overrides it."""
    run = current_run() or {}
    fake = run.get("clock") or get_client().get("policies", {}).get("messaging.test_clock", "")
    if fake:
        return fake
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).strftime("%H:%M")


@contextlib.contextmanager
def as_client(client_id: str):
    """Run a block of code as a given client (used by start-up seeding, tests and scripts)."""
    token = client_var.set(client_id)
    try:
        yield
    finally:
        client_var.reset(token)


# ---------------------------------------------------------------- writing
def _diff(old: dict, new: dict) -> list[dict]:
    out = []
    for k in PROFILE_FIELDS + ("extra_approvals", "datasets"):
        if old.get(k) != new.get(k):
            out.append({"key": k, "label": k.replace("_", " ").capitalize(), "old": old.get(k), "new": new.get(k)})
    eo, en = effective(old), effective(new)
    for k in eo:
        if eo[k] != en[k]:
            out.append({"key": k, "label": SCHEMA[k].label, "old": eo[k], "new": en[k]})
    return out


def _snapshot(client: dict, diff: list[dict], actor: str, note: str) -> None:
    with as_client(client["id"]):
        get_store().put("config_versions", f"v{client['version']:05d}", {
            "version": client["version"], "config": copy.deepcopy(client), "diff": diff, "actor": actor, "note": note, "created_at": now()})


def update_client(changes: dict, actor: str, note: str = "", client_id: str | None = None) -> dict:
    """Apply a set of changes as ONE new version. All-or-nothing: if any value is invalid nothing is saved."""
    from .tools import REGISTRY  # noqa: PLC0415

    old = copy.deepcopy(get_store().get("clients", client_id or current_client()))
    if not old:
        raise KeyError("client not found")
    new = copy.deepcopy(old)
    for k in PROFILE_FIELDS:
        if k in changes:
            new[k] = changes[k]
    if "verticals" in changes:
        from .spec import VERTICALS  # noqa: PLC0415

        bad = set(changes["verticals"]) - set(VERTICALS)
        if bad or not changes["verticals"]:
            raise ConfigError(f"Industries must be chosen from {VERTICALS}.")
    if "extra_approvals" in changes:
        unknown = set(changes["extra_approvals"]) - set(REGISTRY)
        if unknown:
            raise ConfigError(f"Unknown tools in approval list: {sorted(unknown)}")
        new["extra_approvals"] = sorted(set(changes["extra_approvals"]))
    if "datasets" in changes:
        new["datasets"] = dict(changes["datasets"])
    for key, value in (changes.get("policies") or {}).items():
        new.setdefault("policies", {})[key] = coerce(key, value)
    pol = effective(new)
    if pol["messaging.contact_start"] >= pol["messaging.contact_end"]:
        raise ConfigError("Contact window: the start time must be before the end time.")
    diff = _diff(old, new)
    if not diff:
        return old
    new.update(version=old["version"] + 1, updated_at=now(), updated_by=actor)
    get_store().put("clients", new["id"], new)
    _cache.pop(new["id"], None)
    _snapshot(new, diff, actor, note)
    with as_client(new["id"]):
        audit(actor, "config.changed", f"config v{new['version']}", {"changes": diff, "note": note})
    return new


def versions(limit: int = 50) -> list[dict]:
    return get_store().list("config_versions", order_by="version", limit=limit)


def rollback(version: int, actor: str) -> dict:
    snap = get_store().get("config_versions", f"v{version:05d}")
    if not snap:
        raise KeyError("no such version")
    target = snap["config"]
    changes = {k: target.get(k) for k in PROFILE_FIELDS}
    changes["extra_approvals"] = target.get("extra_approvals", [])
    current = get_client()
    # restore every non-locked policy to the value it had in the target version
    te = effective(target)
    changes["policies"] = {k: v for k, v in te.items() if not SCHEMA[k].locked and effective(current)[k] != v}
    return update_client(changes, actor, note=f"Rolled back to version {version}")


# ---------------------------------------------------------------- seeding
def _expand(datasets):
    if datasets == "all":
        from .data import DATASETS  # noqa: PLC0415

        return {n: "sample" for n in DATASETS}
    return dict(datasets or {})


def seed_clients(directory: pathlib.Path = CLIENTS_DIR) -> int:
    """Load the client files into the store on first start. Existing clients are never overwritten."""
    n = 0
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if get_store().get("clients", raw["id"]):
            continue
        doc = {"id": raw["id"], "name": raw["name"], "industry": raw.get("industry", ""), "verticals": raw.get("verticals", []),
               "accent": raw.get("accent", "#1A73E8"), "contact": raw.get("contact", ""), "policies": {}, "extra_approvals": [],
               "datasets": _expand(raw.get("datasets", {})), "version": 1, "created_at": now(), "updated_at": now(), "updated_by": "platform-seed"}
        for key, value in (raw.get("policies") or {}).items():
            doc["policies"][key] = coerce(key, value)
        doc["extra_approvals"] = raw.get("extra_approvals", [])
        get_store().put("clients", doc["id"], doc)
        _snapshot(doc, [], "platform-seed", "Initial configuration from onboarding file")
        n += 1
    _cache.clear()
    return n


def client_file_users(directory: pathlib.Path = CLIENTS_DIR) -> dict[str, list[dict]]:
    """Users listed in each client file (sign-in accounts), keyed by client id."""
    out = {}
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw.get("users"):
            out[raw["id"]] = raw["users"]
    return out


def manufacturing_clients() -> list[str]:
    """Clients whose plant is simulated: they see Manufacturing agents and have live telemetry connected."""
    out = []
    for c in list_clients():
        if "Manufacturing" in (c.get("verticals") or []) and (c.get("datasets") or {}).get("telemetry", "none") != "none":
            out.append(c["id"])
    return out


# ---------------------------------------------------------------- requirements -> configuration
REQ_PROMPT = """You convert a client's written requirements into platform settings.
Return JSON only: {{"changes": [{{"key": "<setting key>", "value": <value>, "reason": "<quote the requirement>"}}],
"not_configurable": ["<requirement that no setting covers>"]}}
Use only these settings (key: label, type, allowed range or choices):
{schema}
Rules: never output a key that is not listed. Never exceed a range. Times are 24-hour HH:MM.
Client requirements:
{text}"""


def _rule_based_draft(text: str) -> dict:
    """Offline stand-in used in simulation mode: a few keyword rules, clearly labelled as such."""
    t, changes, missing = text.lower(), [], []

    def num(pattern):
        m = re.search(pattern, t)
        return float(m.group(1)) if m else None

    if (v := num(r"waiver[^.\d]{0,40}?(\d+(?:\.\d+)?)\s*(?:%|percent)")) is not None:
        changes.append({"key": "lending.max_waiver_pct", "value": v, "reason": "Mentions a waiver percentage"})
    m = re.search(r"refund[^.]{0,60}?(?:rs\.?|inr|₹)\s*([\d,]+)", t)
    if m:
        changes.append({"key": "commerce.auto_refund_limit_inr", "value": int(m.group(1).replace(",", "")), "reason": "Mentions a refund amount"})
    if (v := num(r"return[^.\d]{0,40}?(\d+)\s*day")) is not None:
        changes.append({"key": "commerce.return_window_days", "value": int(v), "reason": "Mentions a return window"})
    m = re.search(r"(\d{1,2})\s*(am|:00)?\s*(?:to|and|-)\s*(\d{1,2})\s*pm", t)
    if m:
        changes += [{"key": "messaging.contact_start", "value": f"{int(m.group(1)):02d}:00", "reason": "Mentions contact hours"},
                    {"key": "messaging.contact_end", "value": f"{int(m.group(3)) + 12:02d}:00", "reason": "Mentions contact hours"}]
    for lang in SCHEMA["messaging.language"].choices:
        if lang.lower() in t:
            changes.append({"key": "messaging.language", "value": lang, "reason": f"Mentions {lang}"})
            break
    if (v := num(r"credit score[^.\d]{0,40}?(\d{3})")) is not None:
        changes.append({"key": "lending.min_credit_score", "value": int(v), "reason": "Mentions a credit score"})
    if "two people" in t or "different person" in t or "four eyes" in t or "maker" in t:
        changes.append({"key": "governance.four_eyes", "value": True, "reason": "Asks for a separate approver"})
    if "voice call" in t or "ivr" in t:
        missing.append("Voice calls: no setting covers this yet. It needs a new channel connector.")
    return {"changes": changes, "not_configurable": missing, "source": "Simulation: keyword rules, not a model"}


def draft_from_requirements(text: str) -> dict:
    """Turn a paragraph of client requirements into PROPOSED setting changes. Nothing is applied here:
    every proposed value is validated against the schema and a human reviews and applies the draft."""
    if config.MODEL_MODE == "mock" or not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_GENAI_USE_VERTEXAI")):
        raw = _rule_based_draft(text)
    else:
        from google import genai  # noqa: PLC0415
        from google.genai import types  # noqa: PLC0415

        schema = "\n".join(f"- {p.key}: {p.label}, {p.type}" + (f", {p.lo:g} to {p.hi:g}" if p.lo is not None else "") +
                           (f", one of {list(p.choices)}" if p.choices else "") for p in POLICIES if not p.locked and p.key != "messaging.test_clock")
        out = genai.Client().models.generate_content(
            model=config.resolve_model("pro"), contents=REQ_PROMPT.format(schema=schema, text=text[:4000]),
            config=types.GenerateContentConfig(response_mime_type="application/json"))
        raw = json.loads(out.text or "{}")
        raw["source"] = f"Drafted by {config.resolve_model('pro')}"
    current, accepted, rejected = effective(get_client()), [], []
    for ch in raw.get("changes", []):
        try:
            value = coerce(ch.get("key", ""), ch.get("value"))
            accepted.append({"key": ch["key"], "label": SCHEMA[ch["key"]].label, "current": current[ch["key"]], "proposed": value, "reason": str(ch.get("reason", ""))[:300]})
        except ConfigError as exc:
            rejected.append({"key": ch.get("key"), "value": ch.get("value"), "why": str(exc)})
    return {"proposed": accepted, "rejected_by_schema": rejected, "not_configurable": raw.get("not_configurable", []), "source": raw.get("source", "")}
