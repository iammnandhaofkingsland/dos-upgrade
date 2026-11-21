"""EVENT WATCH (layer 4): what each agent is listening for, and the events waiting for it.

Agents in DOS are not chatbots waiting for a prompt. Each one is switched on by an event: a transaction alert from
the rules engine, a customer uploading KYC documents, a machine alarm, a new supplier invoice, a lab result, a
schedule. This module turns every agent's trigger into a visible "listening" state and builds its queue of events
from the company's own data (through the same datasets the agent's tools read), so the app can show

    Listening   radar on, what it waits for, where events come from
    Queued      the next events, each with the record it is about (personal values masked)
    Handling    the event delivered: the launcher streams the run
    Handled     back to listening, with the last event and its result

Manufacturing agents listen to the live plant: when a machine goes into alarm the plant itself raises the event
and MachineWatch starts without anyone pressing a button. With no alarm, the queue says so and points to the
plant floor, where a fault can be simulated."""
from __future__ import annotations

import re
import time

from . import clients, data, privacy
from .data import DATASETS
from .gold import _flatten, _records
from .store import get_store

ID = re.compile(r"\b[A-Z]{2,5}(?:-[A-Z]{1,2})?-\d{3,6}\b")
# (words in the trigger) -> (event label, where events come from, icon)
KINDS = [
    (("alarm", "abnormal", "machine had"), ("Machine alarm", "Machine telemetry through the edge gateway", "factory")),
    (("rootcauseiq", "diagnosis names", "after machinewatch"), ("Confirmed alarm", "Handed over by the agent before it", "git")),
    (("transaction alert", "aml monitoring alert"), ("Transaction alert", "Card and payment rules engine", "bolt")),
    (("uploads identity", "documents"), ("KYC documents uploaded", "Customer onboarding app", "doc")),
    (("supplier invoice",), ("New supplier invoice", "Accounts payable inbox", "doc")),
    (("lab result",), ("Lab result arrived", "Laboratory information system", "pulse")),
    (("claim is ready",), ("Claim ready to submit", "Hospital billing system", "doc")),
    (("return", "customer message", "message on", "chat or whatsapp", "conversation"), ("Customer message", "WhatsApp, email and web chat", "chat")),
    (("booking", "check-in", "transcript"), ("Clinic event", "Clinic management system", "heart")),
    (("loan enquiry", "overdue list", "contact window"), ("Collections work list", "Loan management system", "bank")),
    (("daily", "every morning", "weekly", "monthly", "shift", "schedule", "report run", "calendar"), ("Scheduled run", "DOS scheduler", "clock")),
]
DEFAULT_KIND = ("Request", "Staff request in the app", "chat")


def _kind(spec) -> tuple[str, str, str]:
    t = spec.trigger.lower()
    for words, kind in KINDS:
        if any(w in t for w in words):
            return kind
    return DEFAULT_KIND


def _next_schedule(trigger: str) -> str | None:
    t = trigger.lower()
    if "shift" in t:
        return "Next: 30 minutes before shift end"
    if "every morning" in t or "start of the contact window" in t:
        return "Next: tomorrow 09:00"
    if "daily" in t:
        return "Next: tomorrow 07:00"
    if "weekly" in t:
        return "Next: Monday 08:00"
    if "monthly" in t:
        return "Next: 1st of the month"
    return None


def _record_event(spec, rec_id: str, rows_by_key: dict, meta, sample: bool) -> dict:
    ask = spec.demo.ask
    base_ids = ID.findall(ask)
    text = ask.replace(base_ids[0], rec_id) if base_ids else ask
    row = rows_by_key.get(rec_id) or {}
    fields = _flatten(privacy.mask(row, meta.pii))
    shown = [[k.replace("_", " ").replace(".", " · "), str(v)[:48]] for k, v in fields.items() if k != meta.key and v not in (None, "")][:5]
    return {"id": rec_id, "input": text, "record": rec_id, "dataset": meta.title, "fields": shown, "sample": sample,
            "note": "" if sample else "New record: the simulation does the look-ups; Gemini decides and acts in live mode."}


def agent_watch(spec, plant_alarms: list[dict]) -> dict:
    label, source, icon = _kind(spec)
    lin = data.agent_lineage(spec)
    b = data.bindings()
    events: list[dict] = []
    waiting_for = spec.trigger
    hint = ""
    ids = ID.findall(spec.demo.ask)
    if spec.vertical == "Manufacturing" and spec.demo.generic:
        # listens to the plant: one event per machine in alarm
        for a in plant_alarms[:3]:
            events.append({"id": a["machine"], "input": f"Alarm on {a['machine']}: {a.get('signal', 'vibration')} beyond its limit. Check the machine and alert maintenance."
                           if spec.id == "machinewatch" else spec.demo.ask.replace(ids[0], a["machine"]) if ids else spec.demo.ask,
                           "record": a["machine"], "dataset": "Live machine telemetry", "sample": True,
                           "fields": [["machine", a.get("name", a["machine"])], ["status", a.get("status", "alarm")], ["signal", a.get("signal", "")]], "note": ""})
        if not events:
            hint = "No machine is in alarm. Simulate a fault on the Plant floor and this agent picks it up by itself."
            events.append({"id": "demo", "input": spec.demo.ask, "record": ids[0] if ids else "", "dataset": "Rehearsal event", "sample": True, "rehearsal": True,
                           "fields": [["what", "The sample alarm used in rehearsals"]], "note": "Rehearsal: the same event the plant raises on a real alarm."})
    elif ids:
        # the demo record first, then other records of the same kind from the company's data
        for name in lin["datasets"]:
            meta = DATASETS[name]
            if not meta.key or b.get(name, "none") == "none":
                continue
            try:
                rows = _records(name, b[name])
            except Exception:  # noqa: BLE001  (a missing upload must not break the watch page)
                continue
            by_key = {str(r.get(meta.key)): r for r in rows}
            if ids[0] in by_key:
                events.append(_record_event(spec, ids[0], by_key, meta, True))
                for k in list(by_key)[:6]:
                    if k != ids[0] and len(events) < 3:
                        events.append(_record_event(spec, k, by_key, meta, False))
                break
        if not events:
            events.append({"id": ids[0], "input": spec.demo.ask, "record": ids[0], "dataset": "", "fields": [], "sample": True, "note": ""})
    else:
        sched = _next_schedule(spec.trigger)
        size = 0
        for name in lin["datasets"]:
            if b.get(name, "none") != "none":
                try:
                    size += len(_records(name, b[name]))
                except Exception:  # noqa: BLE001
                    pass
        events.append({"id": "batch", "input": spec.demo.ask, "record": "", "dataset": ", ".join(DATASETS[d].title for d in lin["datasets"][:2]),
                       "sample": True, "note": sched or "", "fields": [["request", spec.demo.ask[:90]], ["records in scope", str(size)]]})
    last = next((x for x in get_store().list("runs", where={"agent_id": spec.id}, limit=30) if x.get("purpose") == "run"), None)
    return {"id": spec.id, "name": spec.name, "vertical": spec.vertical, "tier": spec.tier, "trigger": spec.trigger,
            "event": label, "source": source, "icon": icon, "waiting_for": waiting_for, "hint": hint,
            "schedule": _next_schedule(spec.trigger), "queue": events, "auto": spec.vertical == "Manufacturing" and spec.demo.generic,
            "last": {k: last.get(k) for k in ("id", "status", "created_at", "simulated", "input")} if last else None}


def plant_alarms() -> list[dict]:
    if clients.get_client()["id"] not in clients.manufacturing_clients():
        return []
    from . import plant  # noqa: PLC0415

    out = []
    try:
        tel = plant.get_plant().telemetry()
    except Exception:  # noqa: BLE001
        return []
    for mid, v in tel.items():
        if v.get("status") in ("alarm", "warning"):
            sig = (v.get("alarm_signals") or v.get("warning_signals") or ["vibration"])[0]
            out.append({"machine": mid, "status": v.get("status"), "name": v.get("name", mid), "signal": sig})
    return out


def watch(specs: list) -> dict:
    alarms = plant_alarms()
    agents = [agent_watch(s, alarms) for s in specs]
    return {"agents": agents, "alarms": alarms, "at": time.time(),
            "queued": sum(1 for a in agents for e in a["queue"] if not e.get("rehearsal"))}
