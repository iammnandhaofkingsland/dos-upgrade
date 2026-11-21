"""Control-plane REST API. The console (layer 1) talks only to these routes.

Resources by layer
  2 client configuration   /client, /client/versions, /client/requirements
  3 data                   /data, /data/{name}, /data/{name}/upload, /data/access
  4 agents                 /catalog, /agents, /agents/{id}/blueprint, deployments, runs, approvals
  5 governance             /governance/*, /audit, /audit/verify

Every route runs for ONE client (X-DQ-Client header) and ONE role (X-DQ-Role header). The store filters by
client; need() checks the role. Every state change writes an audit record.

Demo note: the role comes from a header so that one presenter can switch hats on stage. In production the
role comes from the signed identity token (Identity Platform or IAP), never from a header the caller sets."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import builder, clients, config, data, evalgate, governance, plant, response
from . import sample_data as D
from .context import current_actor, current_client, current_role, current_user
from .factory import approval_plan, build_instruction
from .runs import RunManager
from .spec import VERTICALS, AgentSpec
from .store import audit, get_store, new_id, now, verify_audit


class Settings(BaseModel):
    business_name: str = ""
    language: str = ""
    extra_instructions: str = Field(default="", max_length=2000)
    extra_approvals: list[str] = Field(default_factory=list)
    daily_run_limit: int | None = Field(default=None, ge=1, le=100000)


class RunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)
    draft: bool = False  # true = test the configured (not yet deployed) agent from the wizard


class Decision(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=500)


class Brief(BaseModel):
    brief: str = Field(min_length=10, max_length=2000)


class SpecBody(BaseModel):
    spec: dict[str, Any]


class ConfigChange(BaseModel):
    policies: dict[str, Any] = Field(default_factory=dict)
    extra_approvals: list[str] | None = None
    name: str | None = Field(default=None, max_length=80)
    verticals: list[str] | None = None
    note: str = Field(default="", max_length=300)


class Text(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)


class Note(BaseModel):
    note: str = Field(default="", max_length=500)


class Kill(BaseModel):
    engaged: bool
    reason: str = Field(default="", max_length=300)


class Connect(BaseModel):
    mode: str


class FaultBody(BaseModel):
    machine: str
    fault: str


class WorkOrderAction(BaseModel):
    notes: str = Field(default="", max_length=800)
    confirmed_cause: str = Field(default="", max_length=60)
    minutes: int | None = Field(default=None, ge=1, le=2000)


def require_key(x_dq_key: str = Header(default="")) -> str:
    """Every /api route except sign-in passes here. In token mode the caller must be signed in (the middleware has
    already checked the token signature and set client, role and user). In header mode (tests only) the shared key
    is checked instead."""
    if config.AUTH_MODE == "token":
        if current_user() is None:
            raise HTTPException(401, "Please sign in")
    elif config.API_KEY and x_dq_key != config.API_KEY:
        raise HTTPException(401, "Missing or wrong X-DQ-Key header")
    if current_role() not in governance.ROLES:
        raise HTTPException(400, f"Unknown role {current_role()!r}")
    try:
        clients.get_client()
    except KeyError:
        raise HTTPException(404, f"Unknown client {current_client()!r}") from None
    return current_actor()


def need(permission: str):
    """Route guard: the caller's role must hold this permission. Returns the actor name for the audit log."""
    def guard() -> str:
        if not governance.allowed(permission):
            raise HTTPException(403, f"Your role ({current_role()}) is not allowed to: {governance.PERMISSION_LABELS[permission].lower()}.")
        return current_actor()
    return guard


def build_router(catalog: dict[str, AgentSpec], manager: RunManager) -> APIRouter:
    r = APIRouter(prefix="/api", dependencies=[Depends(require_key)])
    store = get_store

    def visible() -> dict[str, AgentSpec]:
        """Agents this client can see: its industries only."""
        allowed = set(clients.get_client().get("verticals") or VERTICALS)
        return {k: s for k, s in catalog.items() if s.vertical in allowed}

    def spec_or_404(agent_id: str) -> AgentSpec:
        if agent_id not in visible():
            raise HTTPException(404, f"No agent {agent_id} in this client's catalog")
        return catalog[agent_id]

    def activation_or_404(agent_id: str) -> dict:
        act = store().get("activations", agent_id)
        if not act:
            raise HTTPException(409, "Activate this agent first")
        return act

    def live_deployment(agent_id: str) -> dict | None:
        rows = store().list("deployments", where={"agent_id": agent_id, "status": "live"})
        return rows[0] if rows else None

    def month_cost() -> float:
        start = time.time() - 30 * 86400
        return round(sum(x["cost_inr"] for x in store().list("runs", limit=20000) if x["created_at"] >= start), 2)

    # ---------------- meta (layer 1 needs to know who it is drawing for) ----------------
    @r.get("/meta")
    def meta():
        c = clients.get_client()
        return {"client": {"id": c["id"], "name": c["name"], "industry": c.get("industry", ""), "accent": c.get("accent", "#1A73E8"), "version": c["version"]},
                "tenant": c["id"], "role": current_role(), "actor": current_actor(), "user": _me(), "auth_mode": config.AUTH_MODE,
                "plant": c["id"] in clients.manufacturing_clients(),
                "permissions": [p for p in governance.PERMISSIONS if governance.allowed(p)],
                "mode": config.MODEL_MODE, "store": config.STORE, "models": config.MODEL_ALIASES,
                "agents": len(visible()), "verticals": c.get("verticals") or VERTICALS, "usd_inr": config.USD_INR,
                "kill": governance.kill_state()}

    @r.get("/clients")
    def list_clients():
        return [{"id": c["id"], "name": c["name"], "industry": c.get("industry", ""), "accent": c.get("accent"), "version": c["version"]} for c in clients.list_clients()]

    @r.get("/layers")
    def layers():
        """One line of health per layer, for the Overview page."""
        c, since = clients.get_client(), time.time() - 86400
        pol, vis = clients.effective(c), visible()
        changed = [k for k, v in pol.items() if v != clients.SCHEMA[k].default]
        vers = clients.versions(1)
        inv = data.inventory(catalog, c.get("verticals") or VERTICALS)
        acc = [a for a in store().list("data_access", limit=5000) if a["created_at"] >= since]
        runs = [x for x in store().list("runs", limit=5000) if x["created_at"] >= since and x["purpose"] == "run"]
        steps = [s for s in store().list("steps", limit=20000) if s["created_at"] >= since]
        incidents = store().list("incidents", where={"status": "open"}, limit=500)
        st = store().get("client_state", "selftest")
        return [
            {"layer": 1, "name": "Experience", "status": "ok", "headline": f"Signed in as {current_role()}",
             "facts": [f"{len([p for p in governance.PERMISSIONS if governance.allowed(p)])} of {len(governance.PERMISSIONS)} permissions", "Every screen is drawn from the four layers below"]},
            {"layer": 2, "name": "Client configuration", "status": "ok", "headline": f"Version {c['version']}",
             "facts": [f"{len(changed)} of {len(pol)} settings differ from the platform default", f"Last change by {vers[0]['actor']}" if vers else "No changes yet"]},
            {"layer": 3, "name": "Data", "status": "warn" if any(d["status"] == "none" for d in inv) else "ok",
             "headline": f"{sum(d['status'] != 'none' for d in inv)} of {len(inv)} sources connected",
             "facts": [f"{sum(d['classification'] == 'Restricted' and d['status'] != 'none' for d in inv)} Restricted sources", f"{len(acc)} reads in 24 h, {sum(a['status'] == 'denied' for a in acc)} refused"]},
            {"layer": 4, "name": "AI agents", "status": "ok", "headline": f"{len(store().list('deployments', where={'status': 'live'}))} live of {len(vis)}",
             "facts": [f"{len(runs)} runs in 24 h", f"{sum(x['status'] == 'completed' for x in runs)} completed, {sum(x['status'] == 'failed' for x in runs)} failed"]},
            {"layer": 5, "name": "Safety, security, governance", "status": "stop" if governance.kill_state()["engaged"] else ("warn" if incidents else "ok"),
             "headline": "EMERGENCY STOP ENGAGED" if governance.kill_state()["engaged"] else f"{len(incidents)} open incidents",
             "facts": [f"{sum(s['kind'] == 'guardrail' for s in steps)} guardrail events in 24 h",
                       f"Self-test {st['passed']}/{st['total']}" if st else "Self-test not run yet"]},
        ]

    # ================= LAYER 2: client configuration =================
    @r.get("/client")
    def get_client_config():
        c = clients.get_client()
        return {"client": c, "effective": clients.effective(c), "schema": clients.schema_public(), "all_verticals": VERTICALS,
                "tools": sorted({t for s in visible().values() for t in s.tools}), "month_cost_inr": month_cost()}

    @r.put("/client")
    def change_client_config(body: ConfigChange, actor: str = Depends(need("config.edit"))):
        changes: dict[str, Any] = {"policies": body.policies}
        for k in ("extra_approvals", "name", "verticals"):
            if getattr(body, k) is not None:
                changes[k] = getattr(body, k)
        try:
            new = clients.update_client(changes, actor, body.note)
        except clients.ConfigError as exc:
            raise HTTPException(422, str(exc)) from None
        manager.invalidate()  # agents are rebuilt with the new rules on their next run
        return {"client": new, "effective": clients.effective(new)}

    @r.get("/client/versions")
    def config_versions():
        return [{k: v[k] for k in ("version", "actor", "note", "diff", "created_at")} for v in clients.versions()]

    @r.post("/client/rollback/{version}")
    def config_rollback(version: int, actor: str = Depends(need("config.edit"))):
        try:
            new = clients.rollback(version, actor)
        except KeyError:
            raise HTTPException(404, "No such version") from None
        manager.invalidate()
        return {"client": new}

    @r.post("/client/requirements")
    def config_from_requirements(body: Text, _: str = Depends(need("config.edit"))):
        """Requirements in plain words -> PROPOSED setting changes. Nothing is applied until the Owner reviews and saves."""
        try:
            return clients.draft_from_requirements(body.text)
        except Exception as exc:
            raise HTTPException(422, f"Could not draft settings: {exc}") from None

    # ================= LAYER 3: data =================
    @r.get("/data")
    def data_inventory():
        return data.inventory(catalog, clients.get_client().get("verticals") or VERTICALS)

    @r.get("/data/access")
    def data_access(limit: int = 100):
        runs = {x["id"]: x for x in store().list("runs", limit=5000)}
        out = []
        for a in store().list("data_access", limit=min(limit, 1000)):
            run = runs.get(a["run_id"], {})
            out.append({**a, "title": data.DATASETS[a["dataset"]].title, "agent_name": run.get("agent_name"), "purpose": run.get("purpose")})
        return out

    @r.get("/data/{name}")
    def data_detail(name: str):
        if name not in data.DATASETS:
            raise HTTPException(404, "Unknown data source")
        meta = data.DATASETS[name]
        up = store().get("datasets", name) if data.binding(name) == "upload" else None
        return {"name": name, "title": meta.title, "classification": meta.classification, "owner": meta.owner, "description": meta.description,
                "connector": meta.connector, "status": data.binding(name), "personal_fields": list(meta.pii),
                "columns": [{"name": c.name, "type": c.type, "required": c.required, "personal": c.pii} for c in meta.columns],
                "sample": data.sample_rows(name), "quality": up.get("quality") if up else None, "uploaded_by": up.get("uploaded_by") if up else None}

    @r.get("/data/{name}/template", response_class=PlainTextResponse)
    def data_template(name: str):
        if name not in data.DATASETS or not data.DATASETS[name].columns:
            raise HTTPException(404, "No upload template for this data source")
        return data.template_csv(name)

    @r.post("/data/{name}/upload")
    def data_upload(name: str, body: Text, actor: str = Depends(need("data.manage"))):
        try:
            quality = data.upload_csv(name, body.text, actor)
        except data.DataError as exc:
            raise HTTPException(422, str(exc)) from None
        manager.invalidate()
        return quality

    @r.post("/data/{name}/connect")
    def data_connect(name: str, body: Connect, actor: str = Depends(need("data.manage"))):
        try:
            out = data.connect(name, body.mode, actor)
        except data.DataError as exc:
            raise HTTPException(422, str(exc)) from None
        manager.invalidate()
        return out

    # ================= LAYER 4: agents =================
    @r.get("/catalog")
    def list_catalog(vertical: str | None = None):
        acts = {a["id"]: a for a in store().list("activations", limit=500)}
        out = []
        for s in visible().values():
            if vertical and s.vertical != vertical:
                continue
            live = live_deployment(s.id)
            ready = data.readiness(s)
            out.append({**{k: getattr(s, k) for k in ("id", "name", "vertical", "tier", "tagline", "problem", "autonomy", "model")},
                        "model_id": config.resolve_model(s.model), "tools": len(s.tools), "approvals": len(s.approvals), "skills": s.skills,
                        "risk": governance.risk_tier(s)["tier"], "data_ready": ready["ready"], "missing_data": ready["missing_titles"],
                        "state": "live" if live else ("configured" if s.id in acts else "available"), "version": live["version"] if live else None})
        return out

    @r.get("/catalog/{agent_id}")
    def get_catalog(agent_id: str):
        d = spec_or_404(agent_id).model_dump()
        d["model_id"] = config.resolve_model(d["model"])
        return d

    @r.get("/agents/{agent_id}/blueprint")
    def blueprint(agent_id: str):
        """Everything the five layers know about one agent, in one place: how it is built for THIS client."""
        spec = spec_or_404(agent_id)
        act = store().get("activations", agent_id) or {}
        settings = act.get("settings", {})
        lin, pol = data.agent_lineage(spec), clients.effective(clients.get_client())
        b = data.bindings()
        return {"id": spec.id, "name": spec.name, "model": config.resolve_model(spec.model), "thinking": spec.thinking, "autonomy": spec.autonomy,
                "instruction": build_instruction(spec, settings), "skills": spec.skills,
                "tools": [{**p, "datasets": data.tool_lineage(p["tool"])["datasets"], "settings": data.tool_lineage(p["tool"])["policies"],
                           "acts": data.tool_lineage(p["tool"])["acts"]} for p in approval_plan(spec, settings)],
                "datasets": [{"name": d, "title": data.DATASETS[d].title, "classification": data.DATASETS[d].classification,
                              "personal_data": bool(data.DATASETS[d].pii), "status": b[d]} for d in lin["datasets"]],
                "settings": [{"key": k, "label": clients.SCHEMA[k].label, "value": pol[k], "unit": clients.SCHEMA[k].unit, "enforced": clients.SCHEMA[k].enforced} for k in lin["policies"]],
                "risk": governance.risk_tier(spec), "readiness": data.readiness(spec), "risk_acceptance": act.get("risk_acceptance"),
                "evals": [e.model_dump() for e in spec.evals], "config_version": clients.get_client()["version"]}

    @r.post("/agents/{agent_id}/activate")
    def activate(agent_id: str, settings: Settings, actor: str = Depends(need("agent.configure"))):
        spec = spec_or_404(agent_id)
        bad = set(settings.extra_approvals) - set(spec.tools)
        if bad:
            raise HTTPException(422, f"extra_approvals not in this agent's tools: {sorted(bad)}")
        existing = store().get("activations", agent_id)
        act = store().put("activations", agent_id, {"agent_id": agent_id, "settings": settings.model_dump(), "status": existing["status"] if existing else "active",
                                                    "risk_acceptance": (existing or {}).get("risk_acceptance"),
                                                    "created_at": existing["created_at"] if existing else now(), "updated_at": now()})
        manager.invalidate(agent_id)
        audit(actor, "agent.configured" if existing else "agent.activated", agent_id, settings.model_dump())
        return act

    @r.post("/agents/{agent_id}/risk-acceptance")
    def accept_risk(agent_id: str, body: Note, actor: str = Depends(need("risk.accept"))):
        spec = spec_or_404(agent_id)
        activation_or_404(agent_id)
        risk = governance.risk_tier(spec)
        if len(body.note.strip()) < 10:
            raise HTTPException(422, "Write a short reason (at least 10 characters) for accepting this risk")
        acc = {"by": actor, "note": body.note.strip(), "at": now(), "tier": risk["tier"], "factors": risk["factors"]}
        act = store().update("activations", agent_id, {"risk_acceptance": acc, "updated_at": now()})
        audit(actor, "risk.accepted", agent_id, acc)
        return act

    def _set_status(agent_id: str, status: str, actor: str) -> dict:
        activation_or_404(agent_id)
        act = store().update("activations", agent_id, {"status": status, "updated_at": now()})
        audit(actor, "agent.paused" if status == "paused" else "agent.resumed", agent_id)
        return act

    @r.post("/agents/{agent_id}/pause")
    def pause(agent_id: str, actor: str = Depends(need("agent.configure"))):
        return _set_status(agent_id, "paused", actor)

    @r.post("/agents/{agent_id}/resume")
    def resume(agent_id: str, actor: str = Depends(need("agent.configure"))):
        return _set_status(agent_id, "active", actor)

    @r.get("/agents")
    def my_agents():
        out = []
        runs = store().list("runs", limit=2000)
        for act in store().list("activations", limit=500):
            spec = catalog.get(act["agent_id"])
            if not spec:
                continue
            mine = [x for x in runs if x["agent_id"] == spec.id and x["purpose"] == "run"]
            done = [x for x in mine if x["status"] in ("completed", "failed")]
            live = live_deployment(spec.id)
            out.append({"id": spec.id, "name": spec.name, "vertical": spec.vertical, "tagline": spec.tagline, "status": act["status"],
                        "settings": act["settings"], "live_version": live["version"] if live else None,
                        "eval_score": live["eval"]["score"] if live else None, "runs": len(mine),
                        "risk": governance.risk_tier(spec)["tier"], "data_ready": data.readiness(spec)["ready"],
                        "success_rate": round(sum(x["status"] == "completed" for x in done) / len(done), 3) if done else None,
                        "cost_inr": round(sum(x["cost_inr"] for x in mine), 2),
                        "pending_approvals": len([a for a in store().list("approvals", where={"agent_id": spec.id, "status": "pending"}) if a.get("purpose") != "eval"])})
        return sorted(out, key=lambda a: a["name"])

    # ---------------- deployment: governance gate, then evaluation gate ----------------
    @r.post("/agents/{agent_id}/deployments")
    async def deploy(agent_id: str, actor: str = Depends(need("agent.deploy"))):
        spec, act = spec_or_404(agent_id), activation_or_404(agent_id)
        history = store().list("deployments", where={"agent_id": agent_id})
        version = max([d["version"] for d in history], default=0) + 1
        gate = governance.deployment_gate(spec, act)
        fingerprint = hashlib.sha256(json.dumps({"spec": spec.model_dump(), "settings": act["settings"], "config": gate["config_version"]}, sort_keys=True).encode()).hexdigest()[:12]
        dep = store().put("deployments", new_id("dep"), {"agent_id": agent_id, "version": version, "status": "evaluating", "settings": act["settings"],
                                                         "fingerprint": fingerprint, "mode": config.MODEL_MODE, "created_by": actor, "created_at": now(),
                                                         "eval": None, "gate": gate, "config_version": gate["config_version"], "risk": gate["risk"]["tier"]})
        if not gate["passed"]:
            # Governance checks failed: do not spend model calls on an evaluation that cannot go live.
            dep = store().update("deployments", dep["id"], {"status": "blocked"})
            audit(actor, "deployment.blocked", agent_id, {"version": version, "failed": [c["name"] for c in gate["checks"] if not c["passed"]]})
            return dep
        result = await evalgate.run_gate(manager, spec, act["settings"], version, config.MODEL_MODE)
        gate["checks"].append({"name": "Evaluation gate", "passed": result["passed"], "detail": f"Score {result['score']:.0%}, needed {result['threshold']:.0%}"})
        gate["passed"] = result["passed"]
        if result["passed"]:
            for old in store().list("deployments", where={"agent_id": agent_id, "status": "live"}):
                store().update("deployments", old["id"], {"status": "superseded"})
            dep = store().update("deployments", dep["id"], {"status": "live", "eval": result, "gate": gate, "live_at": now()})
        else:
            dep = store().update("deployments", dep["id"], {"status": "failed", "eval": result, "gate": gate})
        audit(actor, "deployment." + dep["status"], agent_id, {"version": version, "score": result["score"], "risk": gate["risk"]["tier"], "config_version": gate["config_version"]})
        return dep

    @r.get("/agents/{agent_id}/deployments")
    def deployments(agent_id: str):
        return store().list("deployments", where={"agent_id": agent_id})

    @r.post("/agents/{agent_id}/rollback")
    def rollback(agent_id: str, actor: str = Depends(need("agent.deploy"))):
        live = live_deployment(agent_id)
        previous = [d for d in store().list("deployments", where={"agent_id": agent_id, "status": "superseded"})]
        if not live or not previous:
            raise HTTPException(409, "No earlier version to roll back to")
        store().update("deployments", live["id"], {"status": "rolled_back"})
        target = store().update("deployments", previous[0]["id"], {"status": "live", "live_at": now()})
        manager.invalidate(agent_id)
        audit(actor, "deployment.rolled_back", agent_id, {"from": live["version"], "to": target["version"]})
        return target

    # ---------------- runs ----------------
    @r.post("/agents/{agent_id}/runs")
    async def start_run(agent_id: str, body: RunRequest, actor: str = Depends(need("agent.run"))):
        spec, act = spec_or_404(agent_id), activation_or_404(agent_id)
        if governance.kill_state()["engaged"]:
            raise HTTPException(423, "Emergency stop is engaged for this client. No agent can run until it is released.")
        if act["status"] == "paused":
            raise HTTPException(409, "This agent is paused")
        live = live_deployment(agent_id)
        if not live and not body.draft:
            raise HTTPException(409, "Deploy this agent before running it")
        ready = data.readiness(spec)
        if not ready["ready"] and not body.draft:
            raise HTTPException(409, "Connect the data this agent needs first: " + ", ".join(ready["missing_titles"]))
        today = [x for x in store().list("runs", where={"agent_id": agent_id}, limit=5000) if x["created_at"] > time.time() - 86400 and x["purpose"] == "run"]
        limit = min(act["settings"].get("daily_run_limit") or 10**9, clients.policy("budgets.daily_run_limit"))
        if len(today) >= limit:
            raise HTTPException(429, f"Daily run limit of {limit} for this agent reached")
        cap = clients.policy("budgets.monthly_cost_cap_inr")
        if month_cost() >= cap:
            raise HTTPException(429, f"Monthly model spend cap of Rs {cap:,} reached. The Owner can raise it in Client configuration.")
        settings = live["settings"] if live and not body.draft else act["settings"]
        return await manager.start(spec, body.input, settings=settings, version=live["version"] if live and not body.draft else 0,
                                   user=actor, purpose="test" if body.draft else "run")

    @r.get("/runs")
    def list_runs(agent_id: str | None = None, status: str | None = None, purpose: str | None = "run", limit: int = 100):
        where = {k: v for k, v in (("agent_id", agent_id), ("status", status), ("purpose", purpose)) if v}
        return store().list("runs", where=where, limit=min(limit, 500))

    @r.get("/runs/{run_id}")
    def get_run(run_id: str):
        run = store().get("runs", run_id)
        if not run:
            raise HTTPException(404, "No such run")
        return {**run, "steps": store().list("steps", where={"run_id": run_id}, order_by="seq", descending=False, limit=2000),
                "approvals": store().list("approvals", where={"run_id": run_id}, descending=False),
                "actions": store().list("outbox", where={"run_id": run_id}, descending=False)}

    @r.get("/runs/{run_id}/events")
    async def run_events(run_id: str):
        """Server-Sent Events: pushes each new step, then the final run record. The console uses this for the live trace."""
        async def stream():
            sent = 0
            for _ in range(600):  # at most 5 minutes
                steps = store().list("steps", where={"run_id": run_id}, order_by="seq", descending=False, limit=2000)
                for s in steps[sent:]:
                    yield f"event: step\ndata: {json.dumps(s)}\n\n"
                sent = len(steps)
                run = store().get("runs", run_id)
                if not run or run["status"] != "running":
                    yield f"event: run\ndata: {json.dumps(run)}\n\n"
                    return
                await asyncio.sleep(0.5)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------- approvals ----------------
    @r.get("/approvals")
    def approvals(status: str | None = "pending"):
        rows = store().list("approvals", where={"status": status} if status else None)
        from . import auth  # noqa: PLC0415
        out = [a for a in rows if a.get("purpose", "run") != "eval"]  # evaluation runs are auto-rejected and hidden
        for a in out:
            a["designated"] = auth.designated_approvers(a["tool"])
        return out

    @r.post("/approvals/{approval_id}/decision")
    async def decide(approval_id: str, body: Decision, actor: str = Depends(need("approval.decide"))):
        from . import auth  # noqa: PLC0415  (imported here to avoid a cycle at start-up)
        ap = store().get("approvals", approval_id)
        if ap:
            named = auth.designated_approvers(ap["tool"])
            if named and current_role() != "owner" and actor not in [u["username"] for u in named]:
                raise HTTPException(403, f"Only {', '.join(u['name'] + ' (' + u['title'] + ')' for u in named)} may decide {ap['tool']} for this company.")
        try:
            return await manager.decide(approval_id, body.approved, actor, body.note)
        except KeyError:
            raise HTTPException(404, "No such approval") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None

    # ---------------- observability ----------------
    @r.get("/metrics/overview")
    def overview(hours: int = 24):
        since = time.time() - hours * 3600
        runs = [x for x in store().list("runs", limit=5000) if x["created_at"] >= since and x["purpose"] == "run"]
        done = [x for x in runs if x["status"] in ("completed", "failed")]
        lat = sorted(x["latency_ms"] for x in done)
        aps = [a for a in store().list("approvals", limit=2000) if a["created_at"] >= since and a.get("purpose", "run") == "run"]
        buckets: dict[int, dict] = {}
        for x in runs:
            h = int((x["created_at"] - since) // 3600)
            b = buckets.setdefault(h, {"hour": h, "runs": 0, "failed": 0, "cost_inr": 0.0})
            b["runs"] += 1
            b["failed"] += x["status"] == "failed"
            b["cost_inr"] = round(b["cost_inr"] + x["cost_inr"], 4)
        by_agent: dict[str, dict] = {}
        for x in runs:
            a = by_agent.setdefault(x["agent_id"], {"agent_id": x["agent_id"], "name": x["agent_name"], "runs": 0, "completed": 0, "failed": 0, "cost_inr": 0.0, "latency_ms": 0})
            a["runs"] += 1
            a["completed"] += x["status"] == "completed"
            a["failed"] += x["status"] == "failed"
            a["cost_inr"] = round(a["cost_inr"] + x["cost_inr"], 4)
            a["latency_ms"] += x["latency_ms"]
        for a in by_agent.values():
            a["avg_latency_ms"] = round(a.pop("latency_ms") / max(a["runs"], 1))
        steps = [s for s in store().list("steps", limit=20000) if s["created_at"] >= since]
        return {
            "window_hours": hours, "runs": len(runs), "completed": sum(x["status"] == "completed" for x in runs), "failed": sum(x["status"] == "failed" for x in runs),
            "waiting_approval": sum(x["status"] == "waiting_approval" for x in runs),
            "success_rate": round(sum(x["status"] == "completed" for x in done) / len(done), 3) if done else None,
            "p50_latency_ms": lat[len(lat) // 2] if lat else None, "p95_latency_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
            "input_tokens": sum(x["input_tokens"] for x in runs), "output_tokens": sum(x["output_tokens"] for x in runs),
            "cost_inr": round(sum(x["cost_inr"] for x in runs), 2), "avg_cost_inr": round(sum(x["cost_inr"] for x in runs) / len(runs), 3) if runs else None,
            "month_cost_inr": month_cost(), "month_cap_inr": clients.effective(clients.get_client())["budgets.monthly_cost_cap_inr"],
            "approvals": {"pending": sum(a["status"] == "pending" for a in aps), "approved": sum(a["status"] == "approved" for a in aps), "rejected": sum(a["status"] == "rejected" for a in aps)},
            "guardrail_events": sum(s["kind"] == "guardrail" for s in steps), "tool_errors": sum(s["kind"] == "tool" and s["status"] == "error" for s in steps),
            "blocked_actions": sum(s["kind"] == "tool" and s["status"] in ("blocked", "rejected") for s in steps),
            "config_reads": sum(s["kind"] == "config" for s in steps), "data_reads": sum(s["kind"] == "data" for s in steps),
            "simulated_runs": sum(bool(x.get("simulated")) for x in runs),
            "timeline": [buckets[h] for h in sorted(buckets)], "by_agent": sorted(by_agent.values(), key=lambda a: -a["runs"]),
            "agents_live": len(store().list("deployments", where={"status": "live"})), "agents_available": len(visible())}

    @r.get("/outbox")
    def outbox(limit: int = 100):
        """Business actions the agents performed: messages, purchase orders, refunds, drafts, tasks."""
        return store().list("outbox", limit=min(limit, 500))

    # ================= LAYER 5: safety, security, governance =================
    @r.get("/governance/overview")
    def governance_overview():
        acts = {a["id"]: a for a in store().list("activations", limit=500)}
        live = {d["agent_id"]: d for d in store().list("deployments", where={"status": "live"}, limit=500)}
        register = []
        for s in visible().values():
            risk = governance.risk_tier(s)
            if s.id in acts or risk["tier"] == "High":
                act = acts.get(s.id, {})
                register.append({"id": s.id, "name": s.name, "vertical": s.vertical, "tier": risk["tier"], "score": risk["score"], "factors": risk["factors"],
                                 "required_controls": risk["required_controls"], "state": "live" if s.id in live else ("configured" if s.id in acts else "available"),
                                 "risk_acceptance": act.get("risk_acceptance"), "autonomy": s.autonomy})
        since = time.time() - 86400
        steps = [s for s in store().list("steps", limit=20000) if s["created_at"] >= since and s["kind"] == "guardrail"]
        counts: dict[str, int] = {}
        for s in steps:
            counts[s["name"]] = counts.get(s["name"], 0) + 1
        tiers = {t: sum(governance.risk_tier(s)["tier"] == t for s in visible().values()) for t in ("High", "Medium", "Low")}
        return {"kill": governance.kill_state(), "register": sorted(register, key=lambda x: -x["score"]), "tiers": tiers,
                "roles": [{"role": k, "what": v, "permissions": [governance.PERMISSION_LABELS[p] for p, roles in governance.PERMISSIONS.items() if k in roles]} for k, v in governance.ROLES.items()],
                "matrix": [{"permission": governance.PERMISSION_LABELS[p], **{role: role in roles for role in governance.ROLES}} for p, roles in governance.PERMISSIONS.items()],
                "controls": governance.controls(), "guardrail_events": counts,
                "incidents_open": len(store().list("incidents", where={"status": "open"}, limit=1000)),
                "selftest": store().get("client_state", "selftest"), "audit": verify_audit(),
                "approvals_pending": len([a for a in store().list("approvals", where={"status": "pending"}) if a.get("purpose") != "eval"])}

    @r.post("/governance/kill")
    def kill(body: Kill, actor: str = Depends(need("killswitch"))):
        if body.engaged and len(body.reason.strip()) < 5:
            raise HTTPException(422, "Give a short reason for the emergency stop")
        return governance.set_kill(body.engaged, actor, body.reason)

    @r.get("/governance/incidents")
    def incidents(status: str | None = None):
        return store().list("incidents", where={"status": status} if status else None, limit=500)

    @r.post("/governance/incidents/{incident_id}/close")
    def close_incident(incident_id: str, body: Note, actor: str = Depends(need("incident.close"))):
        try:
            return governance.close_incident(incident_id, actor, body.note)
        except KeyError:
            raise HTTPException(404, "No such incident") from None

    @r.post("/governance/selftest")
    def selftest(actor: str = Depends(need("selftest.run"))):
        return governance.selftest(actor)

    @r.get("/governance/evidence")
    def evidence(actor: str = Depends(need("evidence.export"))):
        return governance.evidence(catalog, actor)

    @r.get("/audit")
    def audit_log(limit: int = 200):
        return store().list("audit", order_by="seq", limit=min(limit, 1000))

    @r.get("/audit/verify")
    def audit_verify():
        return verify_audit()

    # ================= MANUFACTURING: live plant floor and work orders =================
    def plant_or_404():
        if current_client() not in clients.manufacturing_clients():
            raise HTTPException(404, "This client has no live plant connected")
        return plant.get_plant()

    @r.get("/plant/state")
    def plant_state():
        pl = plant_or_404()
        show_fault = governance.allowed("plant.simulate")
        machines = [pl.machine_view(mid, points=45, include_fault=show_fault) for mid in pl.machines]
        incidents = store().list("plant_incidents", limit=30)
        for inc in incidents:  # show each step's current status (an approval may have been decided since)
            for step in inc.get("runs", []):
                run = store().get("runs", step["run_id"])
                if run:
                    step["status"] = run["status"]
        wos = store().list("work_orders", limit=50)
        cost_h = clients.policy("manufacturing.downtime_cost_per_hour_inr")
        resolved = [i for i in incidents if i["status"] == "resolved" and i.get("minutes_to_resolve") is not None]
        assigned = []
        for i in incidents:
            wo = next((w for w in wos if w["id"] == i.get("work_order")), None)
            if wo:
                assigned.append((wo["assigned_at"] - i["detected_at"]) / 60)
        acked = [((w["acknowledged_at"] - w["assigned_at"]) / 60) for w in wos if w.get("acknowledged_at")]
        # Downtime stops counting the moment an incident is resolved (by a technician or by a simulation reset).
        down_min = sum(i["minutes_to_resolve"] if i.get("minutes_to_resolve") is not None else ((i.get("resolved_at") or time.time()) - i["detected_at"]) / 60
                       for i in incidents)
        return {"machines": machines, "incidents": incidents, "work_orders": wos,
                "kpis": {"machines": len(machines), "running": sum(m["status"] == "running" for m in machines),
                         "attention": sum(m["status"] in ("warning", "alarm", "maintenance") for m in machines),
                         "open_incidents": sum(i["status"] != "resolved" for i in incidents),
                         "avg_min_to_technician": round(sum(assigned) / len(assigned), 2) if assigned else None,
                         "avg_min_to_acknowledge": round(sum(acked) / len(acked), 2) if acked else None,
                         "avg_min_to_resolve": round(sum(i["minutes_to_resolve"] for i in resolved) / len(resolved), 2) if resolved else None,
                         "downtime_min": round(down_min, 1), "downtime_cost_inr": round(down_min / 60 * cost_h), "cost_per_hour_inr": cost_h,
                         "auto_response": clients.policy("manufacturing.auto_response")},
                "faults": {k: {"label": v["label"], "types": v["types"]} for k, v in D.FAULT_SIGNATURES.items()} if show_fault else {}}

    @r.post("/plant/faults")
    def inject_fault(body: FaultBody, actor: str = Depends(need("plant.simulate"))):
        """DEMO ONLY: make a simulated machine drift the way a real fault would. Agents are not told the fault."""
        pl = plant_or_404()
        if body.machine not in pl.machines or body.fault not in D.FAULT_SIGNATURES:
            raise HTTPException(404, "Unknown machine or fault")
        if plant.open_incident(body.machine):
            raise HTTPException(409, "This machine already has an open incident")
        try:
            pl.inject(body.machine, body.fault)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        audit(actor, "plant.fault_simulated", body.machine, {"fault": body.fault})
        return {"ok": True, "machine": body.machine, "note": "Simulated fault started. Signals drift over about 30 seconds; DOS must detect and diagnose it on its own."}

    @r.post("/plant/clear/{machine_id}")
    def clear_fault(machine_id: str, actor: str = Depends(need("plant.simulate"))):
        pl = plant_or_404()
        if machine_id not in pl.machines:
            raise HTTPException(404, "Unknown machine")
        pl.clear(machine_id)
        inc = plant.open_incident(machine_id)
        if inc:
            now_t = time.time()
            store().update("plant_incidents", inc["id"], {"status": "resolved", "resolved_at": now_t, "minutes_to_resolve": round((now_t - inc["detected_at"]) / 60, 1),
                                                          "root_cause_confirmed": "simulation_reset",
                                                          "timeline": inc["timeline"] + [{"at": now_t, "who": actor, "what": "Simulation reset by presenter"}]})
            for w in store().list("work_orders", limit=200):   # the repair job is no longer needed
                if w.get("incident_id") == inc["id"] and w["status"] != "resolved":
                    store().update("work_orders", w["id"], {"status": "cancelled", "cancelled_at": now_t, "cancel_reason": "Simulation reset by presenter"})
                    if w.get("technician_id"):  # the technician is free again for the next breakdown
                        plant.set_overlay("technicians", w["technician_id"], status="available")
        audit(actor, "plant.simulation_reset", machine_id)
        return {"ok": True}

    @r.post("/plant/respond/{incident_id}")
    async def respond_now(incident_id: str, actor: str = Depends(need("agent.run"))):
        inc = store().get("plant_incidents", incident_id)
        if not inc:
            raise HTTPException(404, "No such incident")
        asyncio.create_task(response.respond(manager, current_client(), inc))
        audit(actor, "plant.response_started", inc["machine"], {"incident": incident_id})
        return {"ok": True}

    @r.get("/workorders")
    def work_orders(mine: bool = False):
        rows = store().list("work_orders", limit=200)
        u = current_user() or {}
        if mine or current_role() == "technician":
            rows = [w for w in rows if w.get("technician_id") and w["technician_id"] == u.get("technician_id")]
        return rows

    @r.post("/workorders/{wo_id}/{action}")
    def work_order_action(wo_id: str, action: str, body: WorkOrderAction, actor: str = Depends(need("workorder.update"))):
        if action not in response.TRANSITIONS:
            raise HTTPException(404, "Unknown action")
        wo = store().get("work_orders", wo_id)
        if not wo:
            raise HTTPException(404, "No such work order")
        u = current_user() or {}
        if current_role() == "technician" and wo.get("technician_id") != u.get("technician_id"):
            raise HTTPException(403, "This work order is assigned to another technician")
        try:
            return response.advance_work_order(wo_id, action, actor, body.notes, body.confirmed_cause, body.minutes)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @r.get("/plant/causes")
    def cause_options():
        return [{"key": k, "label": v["label"]} for k, v in D.FAULT_SIGNATURES.items()] + [{"key": "other", "label": "Other (describe in notes)"}]

    # ---------------- demo support (simulation mode only) ----------------
    if config.MODEL_MODE == "mock":
        @r.post("/dev/backdate/{run_id}")
        def backdate(run_id: str, minutes: int):
            """Move a simulated run back in time so rehearsal dashboards show a spread of activity.
            This route does not exist in live mode."""
            run = store().get("runs", run_id)
            if not run or not run.get("simulated"):
                raise HTTPException(404, "Only simulated runs can be backdated")
            shift = minutes * 60
            store().update("runs", run_id, {"created_at": run["created_at"] - shift, "ended_at": (run["ended_at"] or now()) - shift})
            for s in store().list("steps", where={"run_id": run_id}, limit=2000):
                store().update("steps", s["id"], {"created_at": s["created_at"] - shift})
            return {"ok": True}

    # ---------------- agent builder ----------------
    @r.post("/builder/draft")
    def builder_draft(body: Brief, _: str = Depends(need("builder.use"))):
        try:
            return builder.draft_spec(body.brief)
        except Exception as exc:
            raise HTTPException(422, f"Could not produce a valid spec: {exc}") from None

    @r.post("/builder/save")
    def builder_save(body: SpecBody, actor: str = Depends(need("builder.use"))):
        try:
            spec = AgentSpec(**body.spec)
        except Exception as exc:
            raise HTTPException(422, str(exc)) from None
        if spec.id in catalog:
            raise HTTPException(409, "An agent with this id already exists")
        from .tools import REGISTRY  # noqa: PLC0415

        unknown = [t for t in spec.tools if t not in REGISTRY]
        if unknown:
            raise HTTPException(422, f"Unknown tools: {unknown}")
        ungated = sorted(governance.MONEY_TOOLS & set(spec.tools) - set(spec.approvals))
        if ungated:
            raise HTTPException(422, f"Money-moving tools must be approval-gated: add {ungated} to approvals")
        catalog[spec.id] = spec
        store().put("custom_specs", spec.id, {"spec": spec.model_dump(), "created_at": now(), "created_by": actor})
        audit(actor, "catalog.agent_added", spec.id, {"risk": governance.risk_tier(spec)["tier"]})
        d = spec.model_dump()
        d["model_id"] = config.resolve_model(spec.model)
        return d

    return r


class LoginBody(BaseModel):
    client: str = Field(min_length=1, max_length=40)
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


def _me() -> dict | None:
    """The signed-in user, with the job title from the client's user list (the token carries only the essentials)."""
    u = current_user()
    if not u:
        return None
    rec = get_store().get("users", u["username"]) or {}
    return {**u, "title": rec.get("title", "")}


def build_auth_router() -> APIRouter:
    """Routes that work before sign-in: the client list, reviewer demo users and sign-in itself."""
    from . import auth  # noqa: PLC0415

    r = APIRouter(prefix="/api")

    @r.get("/clients")
    def public_clients():
        return [{"id": c["id"], "name": c["name"], "industry": c.get("industry", ""), "accent": c.get("accent"), "version": c["version"]} for c in clients.list_clients()]

    @r.get("/auth/demo-users")
    def demo_users(client: str):
        return {"enabled": config.DEMO_LOGINS, "password": auth.DEMO_PASSWORD if config.DEMO_LOGINS else None, "users": auth.demo_users(client)}

    @r.post("/auth/login")
    def do_login(body: LoginBody):
        if body.client not in {c["id"] for c in clients.list_clients()}:
            raise HTTPException(404, "Unknown company")
        out = auth.login(body.client, body.username, body.password)
        if not out:
            raise HTTPException(401, "Wrong username or password")
        return out

    return r
