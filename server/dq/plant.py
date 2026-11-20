"""LIVE PLANT: machine telemetry, alarm detection and the state that machine agents act on.

In a real plant, readings come from machine controllers and sensors through an edge gateway
(OPC UA or MQTT into Pub/Sub). For the buildathon this module SIMULATES that stream for each manufacturing
client: every machine produces vibration, temperature, current, cycle time (and pressure for hydraulics and
air) every two seconds, with normal noise. A presenter can inject a fault; the signals then drift exactly
the way that fault drifts them on a real machine, and the detection below has to catch it.

Agents never control machines. This module is READ-ONLY towards machines: agents read telemetry through
the data gate (ds("telemetry")) and act only through business tools (work orders, part orders, lot holds).

State that agents change (technician status, stock after an order, lot holds, order moves) is kept as
OVERLAYS on top of the sample data, per client, in the store. The sample data is never edited."""
from __future__ import annotations

import asyncio
import copy
import logging
import math
import random
import time
from collections import deque
from typing import Any, Callable

from . import sample_data as D
from .context import current_client
from .store import get_store, new_id, now

log = logging.getLogger("dq.plant")
TICK_SECONDS = 2.0
RAMP_SECONDS = 30.0          # a fault reaches full strength 30 seconds after it starts
HISTORY = 150                # 5 minutes of readings per machine at one reading every 2 seconds


def _high(limits: tuple) -> bool:
    """Limits are (warning, alarm). For most signals the alarm is ABOVE the warning (high limits).
    For pressure the alarm is BELOW the warning (low limits)."""
    return limits[1] >= limits[0]


class MachineState:
    def __init__(self, mid: str, spec: dict, rng: random.Random):
        self.id, self.spec, self.rng = mid, spec, rng
        self.readings: deque = deque(maxlen=HISTORY)
        self.fault: str | None = None
        self.fault_started: float = 0.0
        self.status = "running"            # running | warning | alarm | maintenance
        self.alarm_streak = 0
        self.alarm_signals: list[str] = []
        self.warn_signals: list[str] = []
        self.anomaly_since: float | None = None  # sim-time when signals first left normal

    def reading(self, sim: float) -> dict:
        b, n = self.spec["baseline"], self.spec["noise"]
        ramp = 0.0
        drift = {}
        if self.fault:
            ramp = min(1.0, max(0.0, (sim - self.fault_started) / RAMP_SECONDS))
            drift = D.FAULT_SIGNATURES[self.fault]["drift"]
        r = {"t": sim}
        for s, base in b.items():
            r[s] = round(base + self.rng.gauss(0, n[s]) + drift.get(s, 0) * ramp, 3)
        return r


class Plant:
    def __init__(self, client_id: str, seed: int = 7):
        self.client_id = client_id
        self.rng = random.Random(seed)
        self.sim = 0.0
        self.started_wall = time.time()
        self.machines = {mid: MachineState(mid, spec, self.rng) for mid, spec in D.MACHINES.items()}
        for _ in range(40):  # some history so charts are not empty at start
            self._step(record_events=False)

    # ------------------------------------------------------------------ simulation
    def wall(self, sim_t: float) -> float:
        return self.started_wall + sim_t

    def _step(self, record_events: bool = True, confirm: int = 3) -> list[dict]:
        self.sim += TICK_SECONDS
        events = []
        for m in self.machines.values():
            r = m.reading(self.sim)
            m.readings.append(r)
            if m.status == "maintenance":
                continue
            alarms, warns = [], []
            for s, lim in m.spec["limits"].items():
                v = r[s]
                hi = _high(lim)
                if (hi and v >= lim[1]) or (not hi and v <= lim[1]):
                    alarms.append(s)
                elif (hi and v >= lim[0]) or (not hi and v <= lim[0]):
                    warns.append(s)
            # "left normal": any signal more than 4 standard deviations from its baseline
            z_out = any(abs(r[s] - m.spec["baseline"][s]) > 4 * m.spec["noise"][s] for s in m.spec["baseline"])
            if z_out and m.anomaly_since is None:
                m.anomaly_since = self.sim
            if not z_out and not alarms and not warns:
                m.anomaly_since = None
            m.warn_signals, m.alarm_signals = warns, alarms
            m.alarm_streak = m.alarm_streak + 1 if alarms else 0
            if alarms and m.alarm_streak >= confirm and m.status != "alarm":
                m.status = "alarm"
                if record_events:
                    events.append({"machine": m.id, "signals": alarms, "reading": r})
            elif not alarms and m.status == "alarm" and not m.fault:
                m.status = "running"
            elif m.status != "alarm":
                m.status = "warning" if (warns or alarms) else "running"
        return events

    def tick(self, steps: int = 1, confirm: int = 3) -> list[dict]:
        out = []
        for _ in range(steps):
            out += self._step(confirm=confirm)
        return out

    def inject(self, machine_id: str, fault: str) -> None:
        m = self.machines[machine_id]
        sig = D.FAULT_SIGNATURES[fault]
        if m.spec["type"] not in sig["types"]:
            raise ValueError(f"{sig['label']} does not apply to a {m.spec['type'].replace('_', ' ')}")
        m.fault, m.fault_started = fault, self.sim

    def clear(self, machine_id: str) -> None:
        m = self.machines[machine_id]
        m.fault, m.status, m.alarm_streak, m.anomaly_since = None, "running", 0, None

    def set_maintenance(self, machine_id: str, on: bool) -> None:
        m = self.machines[machine_id]
        m.status = "maintenance" if on else ("alarm" if m.fault else "running")

    # ------------------------------------------------------------------ views
    def machine_view(self, mid: str, points: int = 60, include_fault: bool = False) -> dict:
        m = self.machines[mid]
        last = m.readings[-1]
        out = {"machine_id": mid, "name": m.spec["name"], "type": m.spec["type"], "line": m.spec["line"], "status": m.status,
               "criticality": m.spec["criticality"], "operation": m.spec["operation"],
               "latest": {s: last[s] for s in m.spec["baseline"]}, "baseline": m.spec["baseline"], "noise": m.spec["noise"],
               "limits": {s: list(v) for s, v in m.spec["limits"].items()},
               "alarm_signals": m.alarm_signals, "warning_signals": m.warn_signals,
               "abnormal_for_seconds": round(self.sim - m.anomaly_since) if m.anomaly_since is not None else 0,
               "recent": [{k: v for k, v in r.items()} for r in list(m.readings)[-points:]]}
        if include_fault:  # only for the presenter's console, never for agents
            out["simulated_fault"] = D.FAULT_SIGNATURES[m.fault]["label"] if m.fault else None
        return out

    def telemetry(self) -> dict:
        """What agents see through ds("telemetry"). No hint of the injected fault: agents must work it out."""
        return {mid: self.machine_view(mid, points=60) for mid in self.machines}


_plants: dict[str, Plant] = {}


def get_plant(client_id: str | None = None) -> Plant:
    cid = client_id or current_client()
    if cid not in _plants:
        _plants[cid] = Plant(cid)
    return _plants[cid]


def reset_plants() -> None:
    _plants.clear()


# ------------------------------------------------------------------ overlays (agent-changed state)
def live_effects() -> bool:
    """False inside evaluation runs and the safety self-test: tools check everything but change nothing."""
    from .context import current_run  # noqa: PLC0415

    run = current_run() or {}
    return not run.get("dry_run")


def overlay(dataset: str, base: dict) -> dict:
    """Apply this client's saved changes on top of a sample dataset (a dict keyed by record id)."""
    data = copy.deepcopy(base)
    for doc in get_store().list(f"ovl_{dataset}", limit=5000):
        rid = doc["record"]
        if rid in data:
            data[rid].update(doc["fields"])
        else:
            data[rid] = doc["fields"]
    return data


def set_overlay(dataset: str, record: str, **fields) -> None:
    if not live_effects():
        return
    key = f"{dataset}:{record}"
    old = get_store().get(f"ovl_{dataset}", key)
    merged = {**(old or {}).get("fields", {}), **fields}
    get_store().put(f"ovl_{dataset}", key, {"record": record, "fields": merged, "created_at": now()})


def learned_repairs() -> list[dict]:
    return [d["case_data"] for d in get_store().list("learned_repairs", limit=1000, descending=False)]


# ------------------------------------------------------------------ incidents (one per machine alarm)
def open_incident(machine_id: str) -> dict | None:
    rows = [i for i in get_store().list("plant_incidents", where={"machine": machine_id}, limit=50) if i["status"] != "resolved"]
    return rows[0] if rows else None


def create_incident(event: dict, plant: Plant) -> dict:
    m = plant.machines[event["machine"]]
    r = event["reading"]
    sig = event["signals"][0]
    lim = m.spec["limits"][sig]
    inc = get_store().put("plant_incidents", new_id("pin"), {
        "machine": m.id, "machine_name": m.spec["name"], "line": m.spec["line"], "signal": sig, "value": r[sig], "limit": lim[1],
        "unit": D.SIGNAL_UNITS[sig], "signals": event["signals"], "status": "detected", "detected_at": now(),
        "abnormal_since_min": round((plant.sim - (m.anomaly_since or plant.sim)) / 60, 1),
        "root_cause": None, "confidence": None, "part": None, "work_order": None, "technician": None,
        "timeline": [{"at": now(), "who": "DOS sensor watch", "what": f"{m.spec['name']}: {sig.replace('_', ' ')} {r[sig]} {D.SIGNAL_UNITS[sig]} beyond alarm limit {lim[1]}"}],
        "created_at": now()})
    return inc


def update_incident(machine_id: str, note: tuple[str, str] | None = None, **fields) -> dict | None:
    if not live_effects():
        return None
    inc = open_incident(machine_id)
    if not inc:
        return None
    if note:
        fields["timeline"] = inc["timeline"] + [{"at": now(), "who": note[0], "what": note[1]}]
    return get_store().update("plant_incidents", inc["id"], fields)


def zscores(view: dict, window: int = 5) -> dict[str, float]:
    """How far each signal's recent average is from its baseline, in standard deviations."""
    recent = view["recent"][-window:]
    out = {}
    for s, base in view["baseline"].items():
        avg = sum(r[s] for r in recent) / len(recent)
        out[s] = round((avg - base) / max(view["noise"][s], 1e-6), 1)
    return out


def trend_per_minute(view: dict, signal: str, window: int = 30) -> float:
    pts = view["recent"][-window:]
    if len(pts) < 3:
        return 0.0
    n = len(pts)
    xs = [p["t"] for p in pts]
    ys = [p[signal] for p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs) or 1
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return round(slope * 60, 3)


# ------------------------------------------------------------------ background loop
async def run_loop(on_alarm: Callable[[str, dict], Any], tick_check: Callable[[str], Any], clients: Callable[[], list[str]]) -> None:
    """Advance every manufacturing client's plant every two seconds; hand confirmed alarms to on_alarm."""
    from .clients import as_client, policy  # noqa: PLC0415

    while True:
        try:
            for cid in clients():
                with as_client(cid):
                    plant = get_plant(cid)
                    for ev in plant.tick(confirm=int(policy("manufacturing.alarm_confirm_samples"))):
                        if not open_incident(ev["machine"]):
                            inc = create_incident(ev, plant)
                            asyncio.create_task(on_alarm(cid, inc))
                    await tick_check(cid)
        except Exception:  # the loop must survive anything
            log.exception("plant loop error")
        await asyncio.sleep(TICK_SECONDS)
