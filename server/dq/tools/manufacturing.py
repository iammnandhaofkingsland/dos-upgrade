"""Manufacturing tools: what the 12 machine and plant agents can read and do.

Rules every tool here follows (see AGENTS.md):
- Data only through ds("name"); client limits only through policy("key").
- READ-ONLY towards machines. No tool starts, stops or changes a machine. Stopping is the shift supervisor's call.
- Every action (work order, part order, lot hold, order move, maintenance change) is recorded with effect(),
  and agent-made changes are saved as overlays on the sample data through plant.set_overlay().
- Every result carries a one-line "summary" so a person (and the simulated model) can read the outcome."""
from __future__ import annotations

import math

from .. import config, plant
from ..clients import policy
from ..data import ds
from ..store import get_store, new_id, now
from .common import effect, err, ok


def _machine(machine_id: str) -> tuple[dict | None, dict | None]:
    mid = str(machine_id).upper().strip()
    return ds("machines").get(mid), ds("telemetry").get(mid)


# ------------------------------------------------------------------ MachineWatch
def get_machine_status(machine_id: str) -> dict:
    """Read the live condition of one machine: status, latest sensor values, normal values, alarm limits,
    signals in warning or alarm, and for how long the signals have been abnormal.

    Args:
        machine_id: Machine identifier, for example LTH-101.
    """
    spec, tv = _machine(machine_id)
    if not spec or not tv:
        return err(f"No machine {machine_id}. Use list_plant_alarms to see machine ids.")
    z = plant.zscores(tv)
    off = {s: z[s] for s in z if abs(z[s]) >= 3}
    latest = ", ".join(f"{s.replace('_', ' ')} {tv['latest'][s]}" for s in tv["latest"])
    summary = (f"{tv['name']} ({tv['machine_id']}) is {tv['status'].upper()}. Alarm: {', '.join(tv['alarm_signals']) or 'none'}. "
               f"Warning: {', '.join(tv['warning_signals']) or 'none'}. Abnormal for {tv['abnormal_for_seconds']} s.")
    return ok(machine_id=tv["machine_id"], name=tv["name"], type=tv["type"], line=tv["line"], status=tv["status"],
              criticality=tv["criticality"], latest=tv["latest"], normal=tv["baseline"], limits=tv["limits"],
              alarm_signals=tv["alarm_signals"], warning_signals=tv["warning_signals"], deviation_sigma=off,
              abnormal_for_seconds=tv["abnormal_for_seconds"], latest_text=latest, summary=summary)


def get_sensor_trend(machine_id: str, signal: str, minutes: int = 2) -> dict:
    """Summarise how one sensor signal has moved over the last few minutes: first, last, min, max and
    the rate of change per minute. Use it to tell a sudden jump from a slow drift.

    Args:
        machine_id: Machine identifier, for example LTH-101.
        signal: One of vibration, temperature, current, cycle_time, pressure.
        minutes: How many minutes to look back (1 to 5).
    """
    spec, tv = _machine(machine_id)
    if not tv:
        return err(f"No machine {machine_id}")
    if signal not in tv["latest"]:
        return err(f"{tv['name']} has no {signal} signal. Signals: {', '.join(tv['latest'])}")
    pts = tv["recent"][-max(3, min(150, int(minutes * 30))):]
    vals = [p[signal] for p in pts]
    slope = plant.trend_per_minute(tv, signal, window=len(pts))
    lim = tv["limits"].get(signal)
    shape = "rising" if slope > 0.05 * max(1, abs(tv["baseline"][signal]) / 10) else "falling" if slope < -0.05 * max(1, abs(tv["baseline"][signal]) / 10) else "steady"
    summary = f"{signal.replace('_', ' ')} on {tv['machine_id']}: {vals[0]} to {vals[-1]} over {len(pts) * 2} s, {shape} at {slope}/min (normal {tv['baseline'][signal]}, alarm limit {lim[1] if lim else 'n/a'})."
    return ok(machine_id=tv["machine_id"], signal=signal, first=vals[0], last=vals[-1], min=min(vals), max=max(vals),
              per_minute=slope, shape=shape, normal=tv["baseline"][signal], limits=lim, points=len(pts), summary=summary)


def list_plant_alarms() -> dict:
    """List every machine that is in alarm or warning right now, with the signals involved.
    """
    tel = ds("telemetry")
    rows = [{"machine_id": k, "name": v["name"], "status": v["status"], "alarm": v["alarm_signals"], "warning": v["warning_signals"]}
            for k, v in tel.items() if v["status"] in ("alarm", "warning", "maintenance")]
    summary = f"{len(rows)} machine(s) need attention: " + "; ".join(f"{r['machine_id']} {r['status']}" for r in rows) if rows else "All machines normal."
    return ok(machines=rows, total_machines=len(tel), summary=summary)


# ------------------------------------------------------------------ RootCauseIQ
def rank_root_causes(machine_id: str) -> dict:
    """Rank the likely root causes of a machine's abnormal condition. Compares how each signal has moved
    (in standard deviations from normal) with the known failure-mode signatures for this machine type,
    and weights each cause by how often it caused similar breakdowns in the repair history.
    Returns causes with confidence, the evidence, similar past cases, the proven fix, the spare part and the skill needed.

    Args:
        machine_id: Machine identifier, for example LTH-101.
    """
    spec, tv = _machine(machine_id)
    if not tv:
        return err(f"No machine {machine_id}")
    z = plant.zscores(tv, window=6)
    moved = {s: (1 if v >= 3 else -1 if v <= -3 else 0) for s, v in z.items()}
    if not any(moved.values()):
        return ok(machine_id=tv["machine_id"], causes=[], summary=f"{tv['machine_id']}: no signal is abnormal, so there is no fault to explain.")
    history = [h for h in ds("repair_history") if h["type"] == tv["type"]]
    sigs = {k: v for k, v in ds("fault_signatures").items() if tv["type"] in v["types"]}
    scored = []
    for key, sig in sigs.items():
        pat = sig["pattern"]
        match, total, evidence = 0.0, 0, []
        for s in tv["baseline"]:
            want = 0 if pat.get(s, 0) == 0 else (1 if pat[s] > 0 else -1)
            weight = abs(pat.get(s, 0)) or 1
            if want == 0 and abs(z[s]) >= 6:
                weight = 2  # a strong movement this fault cannot explain counts double against it
            total += weight
            if moved[s] == want:
                match += weight
                if want != 0:
                    evidence.append(f"{s.replace('_', ' ')} {'up' if want > 0 else 'down'} {abs(z[s])} sigma, as expected for this fault")
            elif want != 0 and moved[s] == 0:
                evidence.append(f"{s.replace('_', ' ')} expected to move but is normal")
            elif want == 0 and moved[s] != 0:
                evidence.append(f"{s.replace('_', ' ')} moved ({z[s]} sigma) but this fault would not move it")
        cases = [h for h in history if h["cause"] == key]
        prior = (len(cases) + 1) / (len(history) + len(sigs))
        scored.append({"cause": key, "label": sig["label"], "fit": match / total, "prior": prior, "evidence": evidence,
                       "similar_cases": [c["case"] for c in cases][:5], "cases_count": len(cases), "fix": sig["fix"],
                       "part": sig["part"], "skill": sig["skill"], "typical_minutes": sig["minutes"]})
    for c in scored:
        c["raw"] = math.exp(6 * c["fit"]) * c["prior"]
    tot = sum(c["raw"] for c in scored) or 1
    for c in scored:
        c["confidence"] = round(c["raw"] / tot, 2)
        del c["raw"]
    scored.sort(key=lambda c: -c["confidence"])
    top = scored[0]
    same_symptom = [h for h in history if moved.get("vibration") and "vibration" in h["symptom"]] if moved.get("vibration") else []
    hist_note = f"{top['cases_count']} of {len(history)} past {tv['type'].replace('_', ' ')} breakdowns had this cause"
    threshold = policy("manufacturing.min_rootcause_confidence")
    certain = top["confidence"] >= threshold
    plant.update_incident(tv["machine_id"], note=("RootCauseIQ", f"Likely cause: {top['label']} ({int(top['confidence'] * 100)}%). Fix: {top['fix'][:90]}"),
                          root_cause=top["label"], confidence=top["confidence"], part=top["part"], skill=top["skill"], status="diagnosed")
    summary = (f"Most likely cause on {tv['machine_id']}: {top['label']} at {int(top['confidence'] * 100)}% confidence "
               f"({hist_note}). Proven fix: {top['fix']} Part {top['part']}, skill {top['skill']}."
               + ("" if certain else f" Confidence is below the client's threshold of {int(threshold * 100)}%: send a senior technician to inspect first."))
    return ok(machine_id=tv["machine_id"], machine_type=tv["type"], deviation_sigma=z, causes=scored[:3], top_cause=top["label"], confidence=top["confidence"],
              confident=certain, recommended_part=top["part"], recommended_skill=top["skill"], recommended_fix=top["fix"],
              similar_cases_with_vibration=len(same_symptom), summary=summary)


def search_repair_history(machine_type: str, symptom: str) -> dict:
    """Find past repairs on the same type of machine with a similar symptom.

    Args:
        machine_type: cnc_lathe, vmc, grinder, induction, hydraulic_press or compressor.
        symptom: Words describing the symptom, for example "vibration high".
    """
    words = {w for w in symptom.lower().split() if len(w) > 2}
    rows = [h for h in ds("repair_history") if h["type"] == machine_type]
    if config.EMBED_SEARCH and config.MODEL_MODE == "live" and rows:
        ranked = _semantic_rank(rows, symptom)
        if ranked is not None:  # meaning-based match with Gemini embeddings; falls back to keywords on any error
            top = ranked[:5]
            summary = f"{len(top)} most similar past repair(s) on {machine_type.replace('_', ' ')} (by meaning): " + "; ".join(f"{h['case']} {h['cause'].replace('_', ' ')} ({h['minutes']} min, similarity {h['similarity']})" for h in top)
            return ok(cases=top, method="embeddings", summary=summary)
    scored = sorted(rows, key=lambda h: -sum(w in h["symptom"].lower() for w in words))
    top = [h for h in scored if sum(w in h["symptom"].lower() for w in words) > 0][:5]
    summary = f"{len(top)} similar past repair(s) on {machine_type.replace('_', ' ')}: " + "; ".join(f"{h['case']} {h['cause'].replace('_', ' ')} ({h['minutes']} min)" for h in top)
    return ok(cases=top, summary=summary) if top else ok(cases=[], summary="No similar past repairs found.")


def search_manuals(query: str) -> dict:
    """Search machine manuals, alarm codes and plant safety rules. Quote what you use.

    Args:
        query: Alarm code or words, for example "AL-2011" or "spindle vibration".
    """
    words = {w for w in query.lower().replace("?", "").split() if len(w) > 2}
    scored = sorted(((sum(w in (k["text"] + k["section"] + k["doc"]).lower() for w in words), k) for k in ds("alarm_manual")), key=lambda t: -t[0])
    hits = [k for sc, k in scored if sc > 0][:3]
    return ok(passages=hits, summary="Found: " + "; ".join(f"{h['doc']} - {h['section']}" for h in hits)) if hits else ok(passages=[], summary="Nothing found in the manuals.")


# ------------------------------------------------------------------ FixDispatch
def find_available_technician(skill: str) -> dict:
    """Find the best available technician on the current shift for a skill. Prefers senior technicians
    for critical machines and technicians who are free right now.

    Args:
        skill: mechanical, electrical, hydraulic or cnc-setup.
    """
    techs = ds("technicians")
    shift = "A"
    pool = [(tid, t) for tid, t in techs.items() if t["shift"] == shift and skill in t["skills"]]
    free = [(tid, t) for tid, t in pool if t["status"] == "available"]
    if not free:
        return ok(technician_id=None, summary=f"No {skill} technician is free on shift {shift}. Escalate to the maintenance supervisor.",
                  busy=[{"technician_id": tid, "name": t["name"], "status": t["status"]} for tid, t in pool])
    free.sort(key=lambda x: 0 if x[1]["level"] == "senior" else 1)
    tid, t = free[0]
    return ok(technician_id=tid, name=t["name"], level=t["level"], skills=t["skills"], phone=t["phone"],
              summary=f"Best free {skill} technician on shift {shift}: {t['name']} ({tid}, {t['level']}).")


def _check_work_order(machine_id: str = "", title: str = "", diagnosis: str = "", priority: str = "high", technician_id: str = "", **_):
    if not ds("machines").get(str(machine_id).upper()):
        return err(f"No machine {machine_id}")
    if priority not in ("critical", "high", "medium", "low"):
        return err("priority must be critical, high, medium or low")
    if technician_id and technician_id != "auto" and technician_id.upper() not in ds("technicians"):
        return err(f"No technician {technician_id}. Use find_available_technician first.")
    return None


def create_work_order(machine_id: str, title: str, diagnosis: str, priority: str, technician_id: str, part_id: str = "") -> dict:
    """Create a maintenance work order, assign it to a technician and send them the diagnosis and parts.
    If the technician does not acknowledge within the client's time limit, DOS escalates to the supervisor.

    Args:
        machine_id: Machine identifier.
        title: Short title, for example "Spindle vibration alarm".
        diagnosis: The likely cause, the evidence and the proven fix, in plain words.
        priority: critical, high, medium or low.
        technician_id: Technician identifier from find_available_technician (for example TEC-11), or "auto".
        part_id: Spare part needed, for example SP-BRG-7014. Empty if none.
    """
    refusal = _check_work_order(machine_id, title, diagnosis, priority, technician_id)
    if refusal:
        return refusal
    mid = machine_id.upper()
    if not technician_id or technician_id == "auto":
        inc = plant.open_incident(mid)
        pick = find_available_technician((inc or {}).get("skill") or "mechanical")
        technician_id = pick.get("technician_id") or ""
    tech = ds("technicians").get(technician_id.upper()) if technician_id else None
    wo_id = new_id("WO").upper().replace("_", "-")[:11]
    if not plant.live_effects():  # evaluation or self-test: check everything, change nothing
        return ok(work_order="dry-run", technician=tech["name"] if tech else None, status="dry-run", summary=f"(test run) Would create a work order for {mid} assigned to {tech['name'] if tech else 'nobody'}.")
    doc = get_store().put("work_orders", wo_id, {
        "machine": mid, "machine_name": ds("machines")[mid]["name"], "title": title[:120], "diagnosis": diagnosis[:1500], "priority": priority,
        "technician_id": technician_id.upper() if tech else None, "technician_name": tech["name"] if tech else None, "part": part_id or None,
        "status": "assigned" if tech else "unassigned", "assigned_at": now(), "acknowledged_at": None, "started_at": None, "resolved_at": None,
        "escalated": False, "incident_id": (plant.open_incident(mid) or {}).get("id"), "created_at": now(), "resolution": None})
    if tech:
        plant.set_overlay("technicians", technician_id.upper(), status="busy")
        effect("message", {"channel": "whatsapp", "to": tech["phone"], "text": f"DOS work order {wo_id} [{priority}] {mid}: {title}. Likely cause: {diagnosis[:160]} Part: {part_id or 'none'}. Please acknowledge in DOS."})
    effect("work_order", {"work_order": wo_id, "machine": mid, "technician": tech["name"] if tech else "unassigned", "priority": priority})
    plant.update_incident(mid, note=("FixDispatch", f"Work order {wo_id} assigned to {tech['name'] if tech else 'nobody (no technician free)'}"),
                          work_order=wo_id, technician=tech["name"] if tech else None, status="dispatched")
    ack = policy("manufacturing.ack_minutes")
    return ok(work_order=wo_id, technician=tech["name"] if tech else None, status=doc["status"],
              summary=f"Work order {wo_id} created for {mid} and sent to {tech['name'] if tech else 'NO technician'}; escalates to the supervisor if not acknowledged in {ack} min.")


# ------------------------------------------------------------------ SpareSense
def check_spare_stock(part_id: str) -> dict:
    """Check stock, minimum level, cost, lead time and supplier for a spare part.

    Args:
        part_id: Spare part identifier, for example SP-BRG-7014.
    """
    p = ds("spare_parts").get(str(part_id).upper())
    if not p:
        return err(f"No spare part {part_id}")
    status = "in stock" if p["stock"] > 0 else "OUT OF STOCK"
    return ok(part_id=part_id.upper(), name=p["name"], stock=p["stock"], min=p["min"], unit_cost=p["unit_cost"], lead_days=p["lead_days"],
              supplier=p["supplier"], summary=f"{p['name']} ({part_id.upper()}): {status} ({p['stock']} on hand, minimum {p['min']}), Rs {p['unit_cost']:,} each, {p['lead_days']} day(s) lead time.")


def spare_order_value(part_id: str = "", qty: int = 1, **_) -> float:
    p = ds("spare_parts").get(str(part_id).upper())
    return float(p["unit_cost"]) * float(qty or 0) if p else float("inf")


def _check_spare_order(part_id: str = "", qty: int = 1, reason: str = "", **_):
    p = ds("spare_parts").get(str(part_id).upper())
    if not p:
        return err(f"No spare part {part_id}")
    if not 1 <= int(qty) <= 20:
        return err("Refused: quantity must be between 1 and 20 for a breakdown order.")
    return None


def order_spare_part(part_id: str, qty: int, reason: str) -> dict:
    """Order or expedite a spare part. Orders above the client's spending limit wait for the maintenance head.

    Args:
        part_id: Spare part identifier, for example SP-BRG-7014.
        qty: Quantity, 1 to 20.
        reason: Why it is needed, for example the work order number.
    """
    refusal = _check_spare_order(part_id, qty, reason)
    if refusal:
        return refusal
    p = ds("spare_parts")[part_id.upper()]
    value = p["unit_cost"] * int(qty)
    oid = effect("spare_order", {"part": part_id.upper(), "name": p["name"], "qty": int(qty), "value_inr": value, "supplier": p["supplier"], "reason": reason[:200], "expedite": p["stock"] == 0})
    plant.set_overlay("spare_parts", part_id.upper(), on_order=int(qty))
    return ok(order_id=oid, value_inr=value, eta_days=p["lead_days"], summary=f"Ordered {qty} x {p['name']} (Rs {value:,}) from {p['supplier']}, ETA {p['lead_days']} day(s).")


# ------------------------------------------------------------------ PlanSync
def get_machine_orders(machine_id: str) -> dict:
    """List open production orders on a machine, with remaining quantity, hours needed, customer due time,
    alternative machines and whether the due time is at risk.

    Args:
        machine_id: Machine identifier.
    """
    mid = str(machine_id).upper()
    orders = ds("production_orders")
    tel = ds("telemetry")
    rows = []
    for oid, o in orders.items():
        if o["machine"] != mid or o["done"] >= o["qty"]:
            continue
        hours = (o["qty"] - o["done"]) / o["rate_per_hour"]
        alts = [a for a in o["alt"] if tel.get(a, {}).get("status") in ("running", "warning")]
        rows.append({"order_id": oid, "customer": o["customer"], "part": o["part"], "remaining": o["qty"] - o["done"], "hours_needed": round(hours, 1),
                     "due_hours": o["due_hours"], "at_risk_if_down_2h": hours + 2 > o["due_hours"], "alternatives_running": alts})
    return ok(machine_id=mid, orders=rows, summary=f"{len(rows)} open order(s) on {mid}: " + "; ".join(f"{r['order_id']} needs {r['hours_needed']} h, due in {r['due_hours']} h, alternatives {r['alternatives_running'] or 'none'}" for r in rows))


def _check_reassign(order_id: str = "", to_machine_id: str = "", reason: str = "", **_):
    o = ds("production_orders").get(str(order_id).upper())
    if not o:
        return err(f"No order {order_id}")
    to = str(to_machine_id).upper()
    if to not in o["alt"]:
        return err(f"Refused: {to} cannot run {o['part']}. Allowed alternatives: {o['alt'] or 'none - the planner must decide'}.")
    if ds("telemetry").get(to, {}).get("status") in ("alarm", "maintenance"):
        return err(f"Refused: {to} is itself in alarm or maintenance.")
    return None


def reassign_order(order_id: str, to_machine_id: str, reason: str) -> dict:
    """Move a production order to an alternative machine that can run the same operation.

    Args:
        order_id: Production order identifier, for example PO-7701.
        to_machine_id: The alternative machine, for example LTH-102.
        reason: Why, for example "LTH-101 in alarm".
    """
    refusal = _check_reassign(order_id, to_machine_id, reason)
    if refusal:
        return refusal
    oid, to = order_id.upper(), to_machine_id.upper()
    o = ds("production_orders")[oid]
    frm = o["machine"]
    plant.set_overlay("production_orders", oid, machine=to)
    effect("order_moved", {"order": oid, "from": frm, "to": to, "reason": reason[:200]})
    plant.update_incident(frm, note=("PlanSync", f"Order {oid} moved from {frm} to {to}"))
    hours = (o["qty"] - o["done"]) / o["rate_per_hour"]
    risk = hours > o["due_hours"]
    return ok(order_id=oid, from_machine=frm, to_machine=to, due_risk=risk,
              summary=f"Moved {oid} ({o['part']}) from {frm} to {to}." + (" Still at risk of missing its due time: planner to decide." if risk else " Due time remains achievable."))


# ------------------------------------------------------------------ LotTrace
def list_suspect_lots(machine_id: str, since_minutes: int) -> dict:
    """List lots produced on a machine since an abnormal condition began, with their status (in process, stored, shipped).

    Args:
        machine_id: Machine identifier.
        since_minutes: Minutes since the condition began. Add a safety margin of 30 minutes.
    """
    mid = str(machine_id).upper()
    rows = []
    for lid, l in ds("lots").items():
        if l["machine"] != mid:
            continue
        end = l["ended_min_ago"] if l["ended_min_ago"] is not None else 0
        if end <= since_minutes:
            rows.append({"lot_id": lid, "order": l["order"], "qty": l["qty"], "status": l["status"]})
    return ok(machine_id=mid, lots=rows, summary=f"{len(rows)} suspect lot(s) on {mid} in the last {since_minutes} min: " + ", ".join(f"{r['lot_id']} ({r['status']})" for r in rows))


def _check_hold(lot_id: str = "", reason: str = "", **_):
    l = ds("lots").get(str(lot_id).upper())
    if not l:
        return err(f"No lot {lot_id}")
    if l["status"] == "shipped":
        return err(f"Refused: lot {lot_id} has already shipped. Customer containment is the quality head's decision: escalate to a human.")
    if l["status"] == "on_hold":
        return err(f"Lot {lot_id} is already on hold.")
    return None


def hold_lot(lot_id: str, reason: str) -> dict:
    """Put a suspect lot on quality hold so it cannot be shipped. Always needs the quality head's approval.

    Args:
        lot_id: Lot identifier, for example LOT-2611-03.
        reason: Why the lot is suspect.
    """
    refusal = _check_hold(lot_id, reason)
    if refusal:
        return refusal
    lid = lot_id.upper()
    plant.set_overlay("lots", lid, status="on_hold", hold_reason=reason[:200])
    effect("lot_hold", {"lot": lid, "reason": reason[:200]})
    plant.update_incident(ds("lots")[lid]["machine"], note=("LotTrace", f"Lot {lid} placed on quality hold"))
    return ok(lot_id=lid, status="on_hold", summary=f"Lot {lid} is on quality hold: {reason[:120]}")


# ------------------------------------------------------------------ OEEPulse, QualityLens, EnergyWatch, MaterialFlow, PredictMaint, ShiftBrief
def compute_oee(machine_id: str = "") -> dict:
    """Calculate OEE (availability x performance x quality) for the shift, per machine or for one machine,
    and list the biggest losses, including stops with no recorded reason.

    Args:
        machine_id: Machine identifier, or empty for all machines.
    """
    perf = ds("shift_performance")
    ids = [machine_id.upper()] if machine_id else list(perf)
    rows = []
    for mid in ids:
        p = perf.get(mid)
        if not p:
            continue
        a = p["run_min"] / p["planned_min"]
        pf = min(1.0, (p["parts"] * p["ideal_cycle_s"] / 60) / p["run_min"])
        q = p["good"] / p["parts"]
        biggest = max(p["stops"].items(), key=lambda kv: kv[1])
        rows.append({"machine_id": mid, "oee": round(a * pf * q, 3), "availability": round(a, 3), "performance": round(pf, 3), "quality": round(q, 3),
                     "biggest_loss": f"{biggest[0]} ({biggest[1]} min)", "unrecorded_stop_min": p["stops"].get("unrecorded", 0)})
    rows.sort(key=lambda r: r["oee"])
    return ok(machines=rows, summary="Lowest OEE: " + "; ".join(f"{r['machine_id']} {int(r['oee'] * 100)}% (loss: {r['biggest_loss']})" for r in rows[:3]))


def get_spc_data(feature: str) -> dict:
    """Check in-process measurements for a feature against tolerance and SPC rules (a run of 6 rising or
    falling points, points beyond tolerance) and calculate Cpk. Catches drift before parts go out of tolerance.

    Args:
        feature: Feature name, for example "SS-22 bearing seat dia". Use an empty string to list features.
    """
    data = ds("spc")
    if feature not in data:
        return ok(features=list(data), summary="Features: " + ", ".join(data))
    f = data[feature]
    x = f["readings"]
    n = len(x)
    mean = sum(x) / n
    sd = (sum((v - mean) ** 2 for v in x) / (n - 1)) ** 0.5 or 1e-9
    cpk = min(f["usl"] - mean, mean - f["lsl"]) / (3 * sd)
    run, best, direction = 1, 1, 0
    for i in range(1, n):
        d = 1 if x[i] > x[i - 1] else -1 if x[i] < x[i - 1] else 0
        run = run + 1 if d != 0 and d == direction else 1
        direction = d
        best = max(best, run)
    out = [v for v in x if v > f["usl"] or v < f["lsl"]]
    drift = best >= 6
    margin = min(f["usl"] - x[-1], x[-1] - f["lsl"])
    return ok(feature=feature, machine=f["machine"], mean=round(mean, 4), cpk=round(cpk, 2), longest_trend=best, drift=drift, out_of_tolerance=len(out),
              last=x[-1], margin_to_limit=round(margin, 4), unit=f["unit"],
              summary=f"{feature} on {f['machine']}: Cpk {cpk:.2f}, {'DRIFT: ' + str(best) + ' points in one direction' if drift else 'no trend'}, last {x[-1]} {f['unit']} ({margin:.3f} from the limit), {len(out)} out of tolerance.")


def get_energy_profile(machine_id: str = "") -> dict:
    """Find energy waste per machine: energy per part above its baseline, and idle running.

    Args:
        machine_id: Machine identifier, or empty for all machines.
    """
    e = ds("energy")
    rows = []
    for mid, v in e.items():
        if machine_id and mid != machine_id.upper():
            continue
        idle_kwh = v["idle_kw"] * v["idle_hours_per_day"]
        excess = (v["kwh_per_part"] - v["baseline_kwh_per_part"]) / v["baseline_kwh_per_part"] if v["baseline_kwh_per_part"] else 0
        rows.append({"machine_id": mid, "idle_kwh_per_day": round(idle_kwh, 1), "energy_per_part_above_baseline_pct": round(excess * 100, 1), "note": v.get("note", "")})
    rows.sort(key=lambda r: -(r["idle_kwh_per_day"] + r["energy_per_part_above_baseline_pct"]))
    return ok(machines=rows, summary="Biggest waste: " + "; ".join(f"{r['machine_id']} idle {r['idle_kwh_per_day']} kWh/day, +{r['energy_per_part_above_baseline_pct']}% per part" for r in rows[:3]))


def check_material_for_orders(hours: int = 48) -> dict:
    """Check raw material stock against the open orders that need it, and flag shortages ahead of time.

    Args:
        hours: Look-ahead window in hours (default 48).
    """
    orders = ds("production_orders")
    rows = []
    for mid, m in ds("materials").items():
        need = sum((orders[o]["qty"] - orders[o]["done"]) * m["kg_per_part"] for o in m["orders"] if o in orders)
        short = need - m["stock_kg"]
        rows.append({"material_id": mid, "name": m["name"], "stock_kg": m["stock_kg"], "needed_kg": round(need), "shortage_kg": round(max(0, short)), "lead_days": m["lead_days"]})
    shortages = [r for r in rows if r["shortage_kg"] > 0]
    return ok(materials=rows, shortages=shortages, summary=(f"{len(shortages)} shortage(s): " + "; ".join(f"{r['name']} short {r['shortage_kg']} kg (lead {r['lead_days']} d)" for r in shortages)) if shortages else "No material shortages for open orders.")


def get_maintenance_plan() -> dict:
    """List planned maintenance tasks with due times and the live condition of each machine, so tasks can be
    brought forward for machines that look worn and delayed for healthy ones.
    """
    plan = ds("maintenance_plan")
    tel = ds("telemetry")
    rows = []
    for tid, t in plan.items():
        tv = tel.get(t["machine"])
        z = plant.zscores(tv) if tv else {}
        worst = max((abs(v) for v in z.values()), default=0)
        rows.append({"task_id": tid, "machine": t["machine"], "task": t["task"], "due_hours": t["due_hours"],
                     "condition": "abnormal" if worst >= 3 else "watch" if worst >= 2 else "healthy", "worst_sigma": worst})
    return ok(tasks=rows, summary="; ".join(f"{r['task_id']} {r['machine']} due {r['due_hours']} h, condition {r['condition']}" for r in rows))


def reschedule_maintenance(task_id: str, new_due_hours: int, reason: str) -> dict:
    """Bring a planned maintenance task forward or push it back, based on machine condition.

    Args:
        task_id: Task identifier, for example PM-301.
        new_due_hours: New due time in hours from now (1 to 2000).
        reason: The condition evidence behind the change.
    """
    t = ds("maintenance_plan").get(str(task_id).upper())
    if not t:
        return err(f"No task {task_id}")
    if not 1 <= int(new_due_hours) <= 2000:
        return err("new_due_hours must be between 1 and 2000")
    plant.set_overlay("maintenance_plan", task_id.upper(), due_hours=int(new_due_hours))
    effect("maintenance_rescheduled", {"task": task_id.upper(), "machine": t["machine"], "from_hours": t["due_hours"], "to_hours": int(new_due_hours), "reason": reason[:200]})
    return ok(task_id=task_id.upper(), summary=f"{task_id.upper()} on {t['machine']} moved from {t['due_hours']} h to {new_due_hours} h: {reason[:100]}")


def get_shift_summary() -> dict:
    """Collect what the next shift needs to know: machines in alarm or maintenance, open and closed work orders,
    lots on hold, open incidents and the lowest-OEE machines.
    """
    tel = ds("telemetry")
    down = [f"{k} {v['status']}" for k, v in tel.items() if v["status"] in ("alarm", "maintenance")]
    wos = get_store().list("work_orders", limit=50)
    holds = [k for k, v in ds("lots").items() if v["status"] == "on_hold"]
    oee = compute_oee()["machines"][:3]
    return ok(machines_down=down, open_work_orders=[f"{w['id']} {w['machine']} {w['status']}" for w in wos if w["status"] != "resolved"],
              closed_work_orders=[f"{w['id']} {w['machine']}" for w in wos if w["status"] == "resolved"], lots_on_hold=holds,
              lowest_oee=[f"{r['machine_id']} {int(r['oee'] * 100)}%" for r in oee],
              summary=f"Down: {', '.join(down) or 'none'}. Open work orders: {sum(w['status'] != 'resolved' for w in wos)}. Lots on hold: {', '.join(holds) or 'none'}.")


PRECHECKS = {"create_work_order": _check_work_order, "order_spare_part": _check_spare_order, "reassign_order": _check_reassign, "hold_lot": _check_hold}

_EMB_CACHE: dict[str, list[float]] = {}


def _semantic_rank(rows: list[dict], symptom: str) -> list[dict] | None:
    """Rank past repairs by meaning: cosine similarity between Gemini embeddings of the symptom and of each case.
    Case embeddings are cached in memory by case id, so each case is embedded once per server start."""
    try:
        from google import genai  # noqa: PLC0415

        client = genai.Client()
        todo = [h for h in rows if h["case"] not in _EMB_CACHE]
        texts = [symptom] + [f"{h['symptom']}. Cause: {h['cause'].replace('_', ' ')}. Fix: {h.get('fix', '')}" for h in todo]
        res = client.models.embed_content(model=config.EMBED_MODEL, contents=texts)
        vecs = [list(e.values) for e in res.embeddings]
        query = vecs[0]
        for h, v in zip(todo, vecs[1:]):
            _EMB_CACHE[h["case"]] = v

        def cos(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(y * y for y in b)) or 1.0
            return dot / (na * nb)

        scored = [{**h, "similarity": round(cos(query, _EMB_CACHE[h["case"]]), 3)} for h in rows]
        return sorted(scored, key=lambda h: -h["similarity"])
    except Exception:  # no key, no network, unknown model: keyword search still works
        return None
