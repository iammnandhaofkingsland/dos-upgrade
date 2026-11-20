"""THE DOWNTIME RESPONSE: six agents in a row, started by a confirmed machine alarm.

    sensor alarm confirmed
        -> MachineWatch   reads the machine and alerts maintenance
        -> RootCauseIQ    ranks likely causes with evidence and past cases
        -> FixDispatch    assigns the best free technician with diagnosis and part
        -> SpareSense     checks the part; orders it (above the limit: maintenance head approves)
        -> PlanSync       moves orders off the machine
        -> LotTrace       finds suspect lots; proposes holds (quality head approves)
    technician acknowledges, repairs, confirms the cause -> repair history grows -> next diagnosis is better

Each step is a normal DOS run: same agents, same five layers, same trace, same approvals. A step runs only if
the agent is activated and live for this client. The incident record keeps a timeline a person can read."""
from __future__ import annotations

import logging

from . import plant
from . import sample_data as D
from .clients import as_client, policy
from .context import role_var, actor_var
from .governance import kill_state, raise_incident
from .store import audit, get_store, now

log = logging.getLogger("dq.response")
AUTOPILOT = "dos-autopilot"


def _steps(inc: dict) -> list[tuple[str, str]]:
    m, sig = inc["machine"], inc["signal"]
    mins = max(1, round(inc.get("abnormal_since_min") or 1)) + 30
    i = get_store().get("plant_incidents", inc["id"]) or inc
    cause = i.get("root_cause") or "not yet known"
    part = i.get("part") or ""
    skill = i.get("skill") or "mechanical"
    return [
        ("machinewatch", f"Alarm on {m}: {sig} {inc['value']} {inc['unit']} beyond the alarm limit {inc['limit']}. Check the machine and alert maintenance."),
        ("rootcauseiq", f"Find the root cause of the alarm on {m} ({sig})."),
        ("fixdispatch", f"Dispatch a technician to {m}. Likely cause: {cause}. skill: {skill}. Part {part}."),
        ("sparesense", f"Arrange spare part {part} for the repair on {m}." if part else f"Check spare parts needed for the repair on {m}."),
        ("plansync", f"Machine {m} is down. Move its open orders to an alternative machine."),
        ("lottrace", f"Machine {m} has had an abnormal condition for {mins} min. Find and contain suspect lots."),
    ]


async def respond(manager, client_id: str, incident: dict) -> None:
    """Run the response chain for one incident. Safe to call as a background task."""
    with as_client(client_id):
        role_var.set("operator")
        actor_var.set(AUTOPILOT)
        if not policy("manufacturing.auto_response") or kill_state()["engaged"]:
            plant.update_incident(incident["machine"], note=("DOS", "Automatic response is off or the emergency stop is engaged. Waiting for a person."))
            return
        live = {d["agent_id"]: d for d in get_store().list("deployments", where={"status": "live"}, limit=500)}
        acts = {a["id"]: a for a in get_store().list("activations", limit=500)}
        for i, (agent_id, _text) in enumerate(_steps(incident)):
            text = _steps(incident)[i][1]  # rebuilt each time: later steps use what earlier steps found
            spec = manager.catalog.get(agent_id)
            if not spec or agent_id not in live or acts.get(agent_id, {}).get("status") == "paused":
                plant.update_incident(incident["machine"], note=("DOS", f"{spec.name if spec else agent_id} skipped: not live for this client."))
                continue
            try:
                run = await manager.start(spec, text, settings=live[agent_id]["settings"], version=live[agent_id]["version"],
                                          user=AUTOPILOT, purpose="run", wait=True)
            except Exception as exc:  # one failed step must not stop the others
                log.exception("response step %s failed", agent_id)
                plant.update_incident(incident["machine"], note=(spec.name, f"Step failed: {exc}"))
                continue
            label = {"completed": "done", "waiting_approval": "waiting for approval", "failed": "failed", "stopped": "stopped"}.get(run["status"], run["status"])
            inc = plant.open_incident(incident["machine"])
            if inc:
                steps = inc.get("runs", []) + [{"agent": spec.name, "agent_id": agent_id, "run_id": run["id"], "status": run["status"], "at": now()}]
                get_store().update("plant_incidents", inc["id"], {"runs": steps})
            waiting = [a["tool"] for a in get_store().list("approvals", where={"run_id": run["id"], "status": "pending"})]
            extra = f" Waiting for approval: {', '.join(waiting)}." if waiting else ""
            plant.update_incident(incident["machine"], note=(spec.name, f"Run {label}.{extra} " + (run.get("output") or "")[:220]))
        audit(AUTOPILOT, "plant.response_completed", incident["machine"], {"incident": incident["id"]})


async def check_escalations(client_id: str) -> None:
    """Escalate work orders that nobody acknowledged in time."""
    limit_s = policy("manufacturing.ack_minutes") * 60
    for wo in get_store().list("work_orders", where={"status": "assigned"}, limit=200):
        if wo.get("escalated") or now() - wo["assigned_at"] < limit_s:
            continue
        get_store().update("work_orders", wo["id"], {"escalated": True, "escalated_at": now()})
        get_store().put("outbox", f"esc-{wo['id']}", {"kind": "message", "status": "done", "run_id": None, "agent_id": "fixdispatch", "created_at": now(),
                                                       "payload": {"channel": "whatsapp", "to": "maintenance supervisor", "text": f"ESCALATION: {wo['technician_name']} has not acknowledged work order {wo['id']} on {wo['machine']} within {int(limit_s / 60)} min."}})
        raise_incident("work_order_not_acknowledged", "high", f"Work order {wo['id']} on {wo['machine']} not acknowledged by {wo['technician_name']} in {int(limit_s / 60)} min. Supervisor alerted.", None, "fixdispatch")
        plant.update_incident(wo["machine"], note=("FixDispatch", f"Escalated: {wo['technician_name']} did not acknowledge in {int(limit_s / 60)} min. Supervisor alerted."), status="escalated")


# ------------------------------------------------------------------ technician actions (work-order life cycle)
TRANSITIONS = {"ack": ("assigned", "acknowledged"), "start": ("acknowledged", "in_progress"), "resolve": ("in_progress", "resolved")}


def advance_work_order(wo_id: str, action: str, actor: str, notes: str = "", confirmed_cause: str = "", minutes: int | None = None) -> dict:
    wo = get_store().get("work_orders", wo_id)
    if not wo:
        raise KeyError("no such work order")
    frm, to = TRANSITIONS[action]
    if wo["status"] != frm and not (action == "ack" and wo["status"] == "assigned"):
        raise ValueError(f"Work order is {wo['status']}; it must be {frm} to {action}.")
    stamp = {"ack": "acknowledged_at", "start": "started_at", "resolve": "resolved_at"}[action]
    fields = {"status": to, stamp: now()}
    mid = wo["machine"]
    if action == "ack":
        plant.update_incident(mid, note=(wo["technician_name"] or actor, f"Acknowledged work order {wo_id}"), status="acknowledged")
    if action == "start":
        plant.get_plant().set_maintenance(mid, True)
        plant.update_incident(mid, note=(wo["technician_name"] or actor, "Repair started; machine locked out for maintenance"), status="repairing")
    if action == "resolve":
        cause = confirmed_cause or "unconfirmed"
        mins = int(minutes) if minutes else round((now() - (wo.get("started_at") or wo["assigned_at"])) / 60) or 1
        fields.update(resolution={"notes": notes[:800], "confirmed_cause": cause, "minutes": mins})
        mtype = D.MACHINES[mid]["type"]
        if cause in D.FAULT_SIGNATURES or cause == "other":
            # The learning loop: the confirmed cause joins the repair history that RootCauseIQ weighs next time.
            case = {"case": f"RC-L{len(plant.learned_repairs()) + 1:03d}", "machine": mid, "type": mtype, "days_ago": 0,
                    "symptom": wo["title"].lower(), "cause": cause, "fix": notes[:200] or "see work order", "part": wo.get("part") or "", "minutes": mins}
            get_store().put("learned_repairs", case["case"], {"case_data": case, "created_at": now()})
        pl = plant.get_plant()
        pl.clear(mid)
        if wo.get("technician_id"):
            plant.set_overlay("technicians", wo["technician_id"], status="available")
        inc = plant.open_incident(mid)
        if inc:
            ttr = round((now() - inc["detected_at"]) / 60, 2)
            plant.update_incident(mid, note=(wo["technician_name"] or actor, f"Resolved in {mins} min. Confirmed cause: {cause.replace('_', ' ')}. {notes[:120]}"),
                                  status="resolved", resolved_at=now(), minutes_to_resolve=ttr, confirmed_cause=cause)
    wo = get_store().update("work_orders", wo_id, fields)
    audit(actor, f"work_order.{action}", wo_id, {"machine": mid, "notes": notes[:200], "cause": confirmed_cause})
    return wo
