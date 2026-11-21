"""ONE-CLICK AGENT LAUNCHER (layer 4, working through layers 2, 3 and 5).

Before this module, running an agent took five separate screens: activate it, connect its data, accept its risk,
deploy it through the governance and evaluation gates, and only then run it. The launcher does the same steps,
in the same order, with the same checks, and reports each one as it happens so the app can animate the journey:

    1 Rules      (layer 2)  the agent is switched on for this company with the company's rules
    2 Data       (layer 3)  every data source it needs is connected (sample data in the demo workspaces)
    3 Risk       (layer 5)  a High-risk agent needs the Business Owner's recorded risk acceptance
    4 Gate       (layer 5)  the deployment gate: emergency stop clear, data ready, money tools gated, rules valid
    5 Evaluation (layer 4)  the agent must pass its own test cases before the version goes live
    6 Run        (layer 4)  the agent works the request; every model call, tool call, data read and guardrail
                            decision is streamed; risky actions stop and wait for a person

Nothing is skipped and nothing is weakened: an operator cannot accept risk (only the Business Owner can), the
emergency stop still stops everything, and approvals still wait for a person who did not start the run.

Events are plain dictionaries, sent to the app one JSON object per line (NDJSON):
    {"type": "stage", "agent": id, "stage": "data", "status": "running" | "done" | "skipped" | "blocked" | "failed", "detail": "..."}
    {"type": "step",  "agent": id, "run_id": ..., "step": {...}}       one trace step of the run
    {"type": "run",   "agent": id, "run": {...}}                         the run record when it stops moving
    {"type": "agent", "agent": id, "index": i, "total": n, "name": ...}  bulk runs: which agent is next
    {"type": "done",  "summary": {...}}                                  bulk runs: the totals at the end"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import AsyncIterator

from . import clients, config, data, evalgate, governance
from .context import current_role
from .spec import AgentSpec
from .store import audit, get_store, new_id, now

# Bulk work (prepare everything, run a whole domain) checks each agent's evaluation in simulation by default, so a
# 55-agent sweep does not spend 110 Gemini calls on tests. The deployment records the mode and the app says so.
BULK_EVAL_MODE = os.getenv("DQ_BULK_EVAL_MODE", "mock").lower()
PARALLEL = max(1, min(8, int(os.getenv("DQ_LAUNCH_PARALLEL", "3"))))
RUN_TIMEOUT_S = int(os.getenv("DQ_LAUNCH_TIMEOUT_S", "240"))
RATE_LIMIT_WORDS = ("429", "RESOURCE_EXHAUSTED", "quota", "rate limit", "Rate limit")
STAGES = [("rules", 2, "Company rules"), ("data", 3, "Data connected"), ("risk", 5, "Risk accepted"),
          ("gate", 5, "Governance gate"), ("eval", 4, "Evaluation gate"), ("run", 4, "Agent at work")]


def _ev(kind: str, agent: str, **fields) -> dict:
    return {"type": kind, "agent": agent, "at": time.time(), **fields}


def _stage(agent: str, stage: str, status: str, detail: str = "") -> dict:
    return _ev("stage", agent, stage=stage, status=status, detail=detail)


def live_deployment(agent_id: str) -> dict | None:
    rows = get_store().list("deployments", where={"agent_id": agent_id, "status": "live"})
    return rows[0] if rows else None


async def deploy(manager, spec: AgentSpec, actor: str, eval_mode: str) -> dict:
    """The same deployment the Agents screen performs: governance gate first, then the evaluation gate."""
    store = get_store()
    act = store.get("activations", spec.id)
    history = store.list("deployments", where={"agent_id": spec.id})
    version = max([d["version"] for d in history], default=0) + 1
    gate = governance.deployment_gate(spec, act)
    fingerprint = hashlib.sha256(json.dumps({"spec": spec.model_dump(), "settings": act["settings"], "config": gate["config_version"]},
                                            sort_keys=True).encode()).hexdigest()[:12]
    dep = store.put("deployments", new_id("dep"), {"agent_id": spec.id, "version": version, "status": "evaluating", "settings": act["settings"],
                                                   "fingerprint": fingerprint, "mode": eval_mode, "created_by": actor, "created_at": now(),
                                                   "eval": None, "gate": gate, "config_version": gate["config_version"], "risk": gate["risk"]["tier"],
                                                   "via": "launcher"})
    if not gate["passed"]:
        dep = store.update("deployments", dep["id"], {"status": "blocked"})
        audit(actor, "deployment.blocked", spec.id, {"version": version, "failed": [c["name"] for c in gate["checks"] if not c["passed"]]})
        return dep
    result = await evalgate.run_gate(manager, spec, act["settings"], version, eval_mode)
    gate["checks"].append({"name": "Evaluation gate", "passed": result["passed"], "detail": f"Score {result['score']:.0%}, needed {result['threshold']:.0%}"})
    gate["passed"] = result["passed"]
    if result["passed"]:
        for old in store.list("deployments", where={"agent_id": spec.id, "status": "live"}):
            store.update("deployments", old["id"], {"status": "superseded"})
        dep = store.update("deployments", dep["id"], {"status": "live", "eval": result, "gate": gate, "live_at": now()})
    else:
        dep = store.update("deployments", dep["id"], {"status": "failed", "eval": result, "gate": gate})
    manager.invalidate(spec.id)
    audit(actor, "deployment." + dep["status"], spec.id, {"version": version, "score": result["score"], "eval_mode": eval_mode, "via": "launcher"})
    return dep


async def prepare(manager, spec: AgentSpec, actor: str, eval_mode: str) -> AsyncIterator[dict]:
    """Stages 1 to 5. Yields stage events; the last event says whether the agent is live."""
    store, a = get_store(), spec.id
    # 1 rules (layer 2)
    act = store.get("activations", a)
    if not act:
        if not governance.allowed("agent.configure"):
            yield _stage(a, "rules", "blocked", "Ask the Operations Manager or Business Owner to switch this agent on.")
            return
        act = store.put("activations", a, {"agent_id": a, "settings": {"business_name": "", "language": "", "extra_instructions": "", "extra_approvals": [],
                                                                       "daily_run_limit": None}, "status": "active", "risk_acceptance": None,
                                           "created_at": now(), "updated_at": now()})
        audit(actor, "agent.activated", a, {"via": "launcher"})
    elif act["status"] == "paused":
        yield _stage(a, "rules", "blocked", "This agent is paused for this company. Resume it to run.")
        return
    yield _stage(a, "rules", "done", f"{clients.get_client()['name']} rules, version {clients.get_client()['version']}")
    # 2 data (layer 3)
    ready = data.readiness(spec)
    if not ready["ready"]:
        if not governance.allowed("data.manage"):
            yield _stage(a, "data", "blocked", "Needs data: " + ", ".join(ready["missing_titles"]))
            return
        for name in ready["missing"]:
            data.connect(name, "sample", actor)
        manager.invalidate()
        yield _stage(a, "data", "done", "Connected: " + ", ".join(ready["missing_titles"]))
    else:
        yield _stage(a, "data", "done", f"{len(ready['needs'])} source(s) ready" if ready["needs"] else "No company data needed")
    # 3 risk (layer 5)
    risk = governance.risk_tier(spec)
    needs_acc = risk["tier"] == "High" and clients.policy("governance.risk_acceptance_for_high")
    acc = (store.get("activations", a) or {}).get("risk_acceptance")
    if needs_acc and not (acc and acc.get("tier") == "High"):
        if current_role() != "owner":
            yield _stage(a, "risk", "blocked", "High-risk agent: the Business Owner must accept the risk once (Agent Studio, Prepare all agents).")
            return
        acc = {"by": actor, "note": "Accepted for this workspace by the Business Owner from Agent Studio (sample data).", "at": now(),
               "tier": "High", "factors": risk["factors"]}
        store.update("activations", a, {"risk_acceptance": acc, "updated_at": now()})
        audit(actor, "risk.accepted", a, acc)
        yield _stage(a, "risk", "done", "High risk accepted by the Business Owner: " + "; ".join(risk["factors"][:2]))
    else:
        yield _stage(a, "risk", "done" if needs_acc else "skipped", f"{risk['tier']} risk" + (", already accepted" if needs_acc else ", no acceptance needed"))
    # 4 + 5 gate and evaluation
    live = live_deployment(a)
    if live:
        yield _stage(a, "gate", "done", f"Version {live['version']} already passed the gate")
        yield _stage(a, "eval", "done", f"Version {live['version']} is live (evaluation score {(live.get('eval') or {}).get('score', 1):.0%})")
        return
    if not governance.allowed("agent.deploy"):
        yield _stage(a, "gate", "blocked", "Ask the Operations Manager or Business Owner to deploy this agent.")
        return
    yield _stage(a, "gate", "running", "Checking emergency stop, data, money tools and rules")
    yield _stage(a, "eval", "running", "Running the agent's own test cases" + (" in simulation" if eval_mode == "mock" else " on Gemini"))
    dep = await deploy(manager, spec, actor, eval_mode)
    checks = dep["gate"]["checks"]
    gate_ok = all(c["passed"] for c in checks if c["name"] != "Evaluation gate")
    yield _stage(a, "gate", "done" if gate_ok else "failed", "; ".join(f"{'✓' if c['passed'] else '✗'} {c['name']}" for c in checks if c["name"] != "Evaluation gate"))
    if dep["status"] == "live":
        note = "simulated checks" if eval_mode == "mock" else "Gemini judged"
        yield _stage(a, "eval", "done", f"Version {dep['version']} live, score {dep['eval']['score']:.0%} ({note})")
    else:
        detail = (dep.get("eval") or {}).get("score")
        yield _stage(a, "eval", "failed", f"Not live: {dep['status']}" + (f", score {detail:.0%}" if detail is not None else ""))


async def watch_run(run_id: str, agent: str) -> AsyncIterator[dict]:
    """Stream the steps of a run until it stops moving (completed, failed, stopped or waiting for a person)."""
    store, sent, t0 = get_store(), 0, time.time()
    while True:
        steps = store.list("steps", where={"run_id": run_id}, order_by="seq", descending=False, limit=2000)
        for s in steps[sent:]:
            yield _ev("step", agent, run_id=run_id, step=s)
        sent = len(steps)
        run = store.get("runs", run_id)
        if not run or run["status"] != "running" or time.time() - t0 > RUN_TIMEOUT_S:
            run = dict(run or {})
            run["approvals"] = [x for x in store.list("approvals", where={"run_id": run_id}, descending=False)]
            yield _ev("run", agent, run=run)
            return
        await asyncio.sleep(0.35)


async def launch(manager, spec: AgentSpec, actor: str, text: str = "", mode: str | None = None, eval_mode: str | None = None,
                 fallback: bool = False) -> AsyncIterator[dict]:
    """Prepare (if needed) and run one agent, streaming every stage and step."""
    a = spec.id
    blocked = False
    # The evaluation gate in the launcher runs the agent's test cases in simulation by default (BULK_EVAL_MODE), so
    # preparing never fails on a Gemini quota. The deployment records the mode; the Agents screen can re-evaluate on Gemini.
    async for ev in prepare(manager, spec, actor, eval_mode or BULK_EVAL_MODE):
        blocked = blocked or ev["status"] in ("blocked", "failed")
        yield ev
    if blocked:
        yield _stage(a, "run", "blocked", "Not started: an earlier stage did not pass")
        return
    if governance.kill_state()["engaged"]:
        yield _stage(a, "run", "blocked", "Emergency stop is engaged. No agent can run until it is released.")
        return
    if not governance.allowed("agent.run"):
        yield _stage(a, "run", "blocked", "Your role can watch runs but cannot start them.")
        return
    store = get_store()
    today = [x for x in store.list("runs", where={"agent_id": a}, limit=5000) if x["created_at"] > time.time() - 86400 and x["purpose"] == "run"]
    act_limit = (store.get("activations", a) or {}).get("settings", {}).get("daily_run_limit") or 10**9
    limit = min(act_limit, clients.policy("budgets.daily_run_limit"))
    if len(today) >= limit:
        yield _stage(a, "run", "blocked", f"Daily run limit of {limit} for this agent reached (company rule)")
        return
    month = sum(x["cost_inr"] for x in store.list("runs", limit=20000) if x["created_at"] >= time.time() - 30 * 86400)
    if month >= clients.policy("budgets.monthly_cost_cap_inr"):
        yield _stage(a, "run", "blocked", "Monthly model spend cap reached (company rule). The Business Owner can raise it.")
        return
    live = live_deployment(a)
    run_mode = (mode or config.MODEL_MODE).lower()
    if run_mode != "mock":
        ok, why = config.gemini_ready()
        if not ok:
            yield _stage(a, "run", "blocked", f"Gemini is not set up: {why} Choose Simulation to run now.")
            return
    yield _stage(a, "run", "running", "Simulation (scripted model, real tools and rules)" if run_mode == "mock" else "Gemini is working the request")
    run = await manager.start(spec, text or spec.demo.ask, settings=live["settings"], version=live["version"], mode=run_mode, user=actor, purpose="run")
    final = None
    async for ev in watch_run(run["id"], a):
        if ev["type"] == "run":
            final = ev["run"]
        yield ev
    err = (final or {}).get("error") or ""
    if fallback and run_mode != "mock" and any(w in err for w in RATE_LIMIT_WORDS):
        yield _stage(a, "run", "running", "Gemini rate limit reached: running again in simulation (marked Simulated)")
        run = await manager.start(spec, text or spec.demo.ask, settings=live["settings"], version=live["version"], mode="mock", user=actor, purpose="run")
        async for ev in watch_run(run["id"], a):
            if ev["type"] == "run":
                final = ev["run"]
            yield ev
    status = (final or {}).get("status", "unknown")
    if status == "running":  # still working after the watch window: say so instead of calling it finished
        yield _stage(a, "run", "done", "Still working in the background. Open Runs to follow it.")
        return
    label = {"completed": "done", "waiting_approval": "waiting for a person", "failed": "failed", "stopped": "stopped by the emergency stop"}.get(status, status)
    hint = (final or {}).get("error_hint") if status == "failed" else ""
    yield _stage(a, "run", "failed" if status == "failed" else "done", f"Run {label}" + (f". {hint}" if hint else ""))


async def _merge(gens: list) -> AsyncIterator[dict]:
    """Run several event streams at once (at most PARALLEL) and yield their events as they arrive."""
    queue: asyncio.Queue = asyncio.Queue()
    sem = asyncio.Semaphore(PARALLEL)
    DONE = object()

    async def pump(factory):
        async with sem:
            try:
                async for ev in factory():
                    await queue.put(ev)
            except Exception as exc:  # one agent's failure must not stop the sweep
                await queue.put({"type": "error", "detail": f"{type(exc).__name__}: {exc}"[:300], "at": time.time()})
        await queue.put(DONE)

    tasks = [asyncio.create_task(pump(g)) for g in gens]
    left = len(tasks)
    while left:
        ev = await queue.get()
        if ev is DONE:
            left -= 1
            continue
        yield ev


def _order(specs: list[AgentSpec]) -> list[AgentSpec]:
    return sorted(specs, key=lambda s: (s.vertical, s.tier != "hero", s.name))


async def sweep(manager, specs: list[AgentSpec], actor: str, run: bool, mode: str | None = None) -> AsyncIterator[dict]:
    """Prepare (run=False) or prepare and run (run=True) many agents, a few at a time."""
    specs = _order(specs)
    total, tally = len(specs), {"live": 0, "completed": 0, "waiting_approval": 0, "failed": 0, "blocked": 0, "simulated": 0}

    def one(i: int, spec: AgentSpec):
        async def gen():
            yield _ev("agent", spec.id, index=i + 1, total=total, name=spec.name, vertical=spec.vertical, tier=spec.tier)
            if run:
                stream = launch(manager, spec, actor, mode=mode, eval_mode=BULK_EVAL_MODE, fallback=True)
            else:
                stream = prepare(manager, spec, actor, BULK_EVAL_MODE)
            async for ev in stream:
                yield ev
        return gen

    async for ev in _merge([one(i, s) for i, s in enumerate(specs)]):
        if ev["type"] == "stage" and ev["status"] == "blocked":
            tally["blocked"] += 1
        if ev["type"] == "stage" and ev["stage"] == "eval" and ev["status"] == "done":
            tally["live"] += 1
        if ev["type"] == "run":
            st = ev["run"].get("status")
            if st in tally:
                tally[st] += 1
            tally["simulated"] += bool(ev["run"].get("simulated"))
        yield ev
    yield {"type": "done", "summary": {"agents": total, **tally}, "at": time.time()}
