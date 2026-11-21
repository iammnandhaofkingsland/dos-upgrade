"""THE DOS APP API: the routes the new app (layer 1) uses, on top of the existing /api routes.

Two routers:
  build_public_router()      works before sign-in: the company list with its role cards, and sign-in with a code
  build_app_router(...)      /api/app/*, signed in only: the role-aware home, Agent Studio, the one-click launcher
                             (streams), live activity, Ask DOS, and the five-layer view (Business Owner and
                             Operations Manager only)

Nothing here bypasses a lower layer. The launcher calls the same gates as the Agents screen; the five-layer view is
refused (403) for roles that should not see it, so hiding it in the app is backed by the server."""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import access, ask, clients, config, data, events, gold, governance, launcher
from .api import need, require_key
from .context import current_actor, current_client, current_role, current_user
from .spec import VERTICALS, AgentSpec
from .store import audit, get_store, verify_audit

DOMAIN_ICONS = {"Fintech": "bank", "Manufacturing": "factory", "Wholesale": "truck", "Retail": "store", "E-commerce": "cart",
                "Healthcare": "heart", "Digital Marketing": "megaphone", "Data Automation": "database"}
ACTIONS = {  # audit action -> (kind, plain-English verb)
    "auth.login": ("people", "signed in"), "auth.login_code": ("people", "signed in with a login code"), "auth.login_code_failed": ("bad", "entered a wrong login code"),
    "agent.activated": ("agent", "switched on"), "agent.configured": ("agent", "reconfigured"), "agent.paused": ("bad", "paused"), "agent.resumed": ("agent", "resumed"),
    "deployment.live": ("ok", "went live"), "deployment.failed": ("bad", "failed its evaluation"), "deployment.blocked": ("bad", "was blocked by the governance gate"),
    "deployment.rolled_back": ("warn", "was rolled back"), "risk.accepted": ("warn", "risk accepted"), "data.connected": ("data", "data connected"),
    "data.disconnected": ("data", "data disconnected"), "data.uploaded": ("data", "data uploaded"), "approval.approved": ("ok", "approved"),
    "approval.rejected": ("bad", "rejected"), "config.changed": ("rules", "rules changed"), "config.rolled_back": ("rules", "rules rolled back"),
    "killswitch.engaged": ("bad", "EMERGENCY STOP engaged"), "killswitch.released": ("ok", "emergency stop released"),
    "incident.closed": ("ok", "incident closed"), "plant.fault_simulated": ("warn", "machine fault simulated"), "plant.response_started": ("agent", "breakdown response started"),
    "plant.response_completed": ("ok", "breakdown response finished"), "plant.simulation_reset": ("ok", "machine reset"), "work_order.ack": ("people", "work order acknowledged"),
    "work_order.start": ("people", "repair started"), "work_order.resolve": ("ok", "repair closed"), "selftest.run": ("ok", "safety self-test run"),
    "evidence.exported": ("ok", "evidence pack exported"), "catalog.agent_added": ("agent", "new agent added"), "auth.code_locked": ("bad", "sign-in paused after wrong codes"),
    "auth.login_failed": ("bad", "sign-in failed"),
    "ask.answered": ("people", "asked DOS a question"), "data.gold_viewed": ("data", "gold-layer data viewed (masked)"), "ask.refused": ("bad", "Ask DOS refused an instruction"),
}


class CodeBody(BaseModel):
    client: str = Field(min_length=1, max_length=60)
    code: str = Field(min_length=4, max_length=12)


class LaunchBody(BaseModel):
    input: str = Field(default="", max_length=4000)
    mode: str | None = Field(default=None, pattern="^(live|mock)$")


class SweepBody(BaseModel):
    vertical: str = "all"
    mode: str | None = Field(default=None, pattern="^(live|mock)$")


class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=600)


def ndjson(gen) -> StreamingResponse:
    """Send events one JSON object per line. The app reads them as they arrive (fetch + ReadableStream)."""
    async def body():
        async for ev in gen:
            yield json.dumps(ev, default=str) + "\n"
    return StreamingResponse(body(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def build_public_router() -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/auth/roster")
    def roster(client: str):
        if client not in {c["id"] for c in clients.list_clients()}:
            raise HTTPException(404, "Unknown company")
        return {"demo": config.DEMO_LOGINS, "people": access.roster(client)}

    @r.get("/auth/companies")
    def companies():
        out = []
        for c in clients.list_clients():
            out.append({"id": c["id"], "name": c["name"], "industry": c.get("industry", ""), "accent": c.get("accent") or "#3F86FF",
                        "verticals": c.get("verticals") or VERTICALS, "plant": c["id"] in clients.manufacturing_clients()})
        return sorted(out, key=lambda c: (c["id"] != "demo", c["name"]))

    @r.post("/auth/code")
    def sign_in(body: CodeBody):
        try:
            return access.sign_in(body.client, body.code)
        except ValueError as exc:
            raise HTTPException(401, str(exc)) from None

    return r


def build_app_router(catalog: dict[str, AgentSpec], manager) -> APIRouter:
    r = APIRouter(prefix="/api/app", dependencies=[Depends(require_key)])
    store = get_store

    def visible() -> dict[str, AgentSpec]:
        allowed = set(clients.get_client().get("verticals") or VERTICALS)
        return {k: s for k, s in catalog.items() if s.vertical in allowed}

    def spec_or_404(agent_id: str) -> AgentSpec:
        if agent_id not in visible():
            raise HTTPException(404, f"No agent {agent_id} for this company")
        return catalog[agent_id]

    def layers_only():
        if current_role() not in access.LAYER_ROLES:
            raise HTTPException(403, "The five-layer view is for the Business Owner and the Operations Manager.")

    def pending_approvals() -> list[dict]:
        return [a for a in store().list("approvals", where={"status": "pending"}, limit=500) if a.get("purpose", "run") != "eval"]

    # ------------------------------------------------------------------ who am I
    @r.get("/me")
    def me():
        c, u = clients.get_client(), current_user() or {}
        role = current_role()
        return {"client": {"id": c["id"], "name": c["name"], "industry": c.get("industry", ""), "accent": c.get("accent") or "#3F86FF",
                           "verticals": c.get("verticals") or VERTICALS, "version": c["version"]},
                "user": {"name": u.get("name") or access.ROLE_NAMES.get(role, role), "role": role, "role_name": access.ROLE_NAMES.get(role, role),
                         "technician_id": u.get("technician_id")},
                "layers": role in access.LAYER_ROLES, "plant": c["id"] in clients.manufacturing_clients(),
                "permissions": [p for p in governance.PERMISSIONS if governance.allowed(p)], "mode": config.MODEL_MODE,
                "demo": config.DEMO_LOGINS, "kill": governance.kill_state(), "pending": len(pending_approvals()),
                "agents": len(visible())}

    # ------------------------------------------------------------------ home
    @r.get("/home")
    def home():
        now_t, since = time.time(), time.time() - 86400
        runs = [x for x in store().list("runs", limit=3000) if x.get("purpose") == "run"]
        today = [x for x in runs if x["created_at"] >= since]
        live = {d["agent_id"]: d for d in store().list("deployments", where={"status": "live"}, limit=500)}
        vis = visible()
        hours = [{"h": h, "runs": 0, "done": 0} for h in range(12)]
        for x in today:
            h = int((now_t - x["created_at"]) // 3600)
            if h < 12:
                hours[11 - h]["runs"] += 1
                hours[11 - h]["done"] += x["status"] == "completed"
        domains = {}
        for s in vis.values():
            d = domains.setdefault(s.vertical, {"vertical": s.vertical, "icon": DOMAIN_ICONS.get(s.vertical, "spark"), "agents": 0, "live": 0, "runs": 0})
            d["agents"] += 1
            d["live"] += s.id in live
        for x in today:
            if x["vertical"] in domains:
                domains[x["vertical"]]["runs"] += 1
        pend = pending_approvals()
        done = sum(x["status"] == "completed" for x in today)
        minutes = clients.policy("report.minutes_per_manual_task") if "report.minutes_per_manual_task" in clients.SCHEMA else 12
        out: dict[str, Any] = {
            "kpis": {"agents_live": len(live), "agents_total": len(vis), "runs_today": len(today), "completed_today": done,
                     "waiting": sum(x["status"] == "waiting_approval" for x in today), "failed_today": sum(x["status"] == "failed" for x in today),
                     "pending_approvals": len(pend), "incidents_open": len(store().list("incidents", where={"status": "open"}, limit=500)),
                     "hours_saved": round(done * minutes / 60, 1), "minutes_per_task": minutes,
                     "simulated_today": sum(bool(x.get("simulated")) for x in today),
                     "cost_today_inr": round(sum(x["cost_inr"] for x in today), 2)},
            "hours": hours, "domains": sorted(domains.values(), key=lambda d: VERTICALS.index(d["vertical"]) if d["vertical"] in VERTICALS else 99),
            "recent": [{k: x.get(k) for k in ("id", "agent_id", "agent_name", "vertical", "status", "created_at", "latency_ms", "simulated", "cost_inr")} | {"output": (x.get("output") or x.get("error") or "")[:200]}
                       for x in runs[:8]],
            "approvals": [{k: a.get(k) for k in ("id", "agent_name", "tool", "args", "why", "created_at", "run_id")} for a in pend[:6]],
            "kill": governance.kill_state(),
        }
        if current_client() in clients.manufacturing_clients():
            incs = store().list("plant_incidents", limit=20)
            out["plant"] = {"open": [{k: i.get(k) for k in ("id", "machine", "machine_name", "status", "root_cause", "confidence", "technician", "work_order", "detected_at")}
                                     for i in incs if i["status"] != "resolved"][:5],
                            "resolved": sum(i["status"] == "resolved" for i in incs)}
        if current_role() == "technician":
            tid = (current_user() or {}).get("technician_id")
            out["my_work_orders"] = [w for w in store().list("work_orders", limit=100) if w.get("technician_id") and w["technician_id"] == tid][:8]
        return out

    # ------------------------------------------------------------------ Agent Studio
    @r.get("/studio")
    def studio():
        live = {d["agent_id"]: d for d in store().list("deployments", where={"status": "live"}, limit=500)}
        acts = {a["id"]: a for a in store().list("activations", limit=500)}
        last: dict[str, dict] = {}
        for x in store().list("runs", limit=3000):
            if x.get("purpose") == "run" and x["agent_id"] not in last:
                last[x["agent_id"]] = x
        groups: dict[str, dict] = {}
        for s in sorted(visible().values(), key=lambda s: (s.tier != "hero", s.name)):
            g = groups.setdefault(s.vertical, {"vertical": s.vertical, "icon": DOMAIN_ICONS.get(s.vertical, "spark"), "agents": []})
            risk = governance.risk_tier(s)
            lr = last.get(s.id)
            g["agents"].append({"id": s.id, "name": s.name, "tier": s.tier, "tagline": s.tagline, "problem": s.problem, "users": s.users,
                                "trigger": s.trigger, "autonomy": s.autonomy, "model": config.resolve_model(s.model), "risk": risk["tier"],
                                "tools": s.tools, "approvals": s.approvals, "kpis": s.kpis, "guardrails": s.guardrails, "ask": s.demo.ask,
                                "state": "live" if s.id in live else ("configured" if s.id in acts else "available"),
                                "version": live[s.id]["version"] if s.id in live else None,
                                "data_ready": data.readiness(s)["ready"], "risk_accepted": bool((acts.get(s.id) or {}).get("risk_acceptance")),
                                "last_run": {k: lr.get(k) for k in ("id", "status", "created_at", "simulated")} if lr else None})
        order = {v: i for i, v in enumerate(VERTICALS)}
        return {"domains": sorted(groups.values(), key=lambda g: order.get(g["vertical"], 99)), "mode": config.MODEL_MODE,
                "bulk_eval_mode": launcher.BULK_EVAL_MODE, "parallel": launcher.PARALLEL,
                "can_run": governance.allowed("agent.run"), "can_prepare": governance.allowed("agent.deploy"), "owner": current_role() == "owner"}

    @r.post("/launch/{agent_id}")
    async def launch_one(agent_id: str, body: LaunchBody, actor: str = Depends(need("agent.run"))):
        spec = spec_or_404(agent_id)
        return ndjson(launcher.launch(manager, spec, actor, body.input.strip(), mode=body.mode, fallback=False))

    @r.post("/sweep")
    async def sweep(body: SweepBody, actor: str = Depends(need("agent.run"))):
        specs = [s for s in visible().values() if body.vertical in ("all", s.vertical)]
        if not specs:
            raise HTTPException(404, "No agents in that domain for this company")
        return ndjson(launcher.sweep(manager, specs, actor, run=True, mode=body.mode))

    @r.post("/prepare")
    async def prepare_all(body: SweepBody, actor: str = Depends(need("agent.deploy"))):
        specs = [s for s in visible().values() if body.vertical in ("all", s.vertical)]
        return ndjson(launcher.sweep(manager, specs, actor, run=False))

    # ------------------------------------------------------------------ live activity
    @r.get("/activity")
    def activity(limit: int = 60):
        rows = []
        for a in store().list("audit", order_by="seq", limit=min(limit, 300)):
            kind, verb = ACTIONS.get(a["action"], ("info", a["action"].replace(".", " ").replace("_", " ")))
            target = a["target"]
            if target in catalog:
                target = catalog[target].name
            who = a["actor"]
            rows.append({"id": a.get("id") or a["seq"], "seq": a["seq"], "at": a["created_at"], "kind": kind, "who": who, "role": a.get("role"),
                         "text": f"{target}: {verb}" if a["action"].split(".")[0] in ("agent", "deployment", "risk", "data", "plant", "work_order") else f"{verb} · {target}",
                         "action": a["action"]})
        for x in store().list("runs", limit=40):
            if x.get("purpose") != "run":
                continue
            label = {"completed": ("ok", "finished"), "waiting_approval": ("warn", "is waiting for a person"), "failed": ("bad", "failed"),
                     "running": ("agent", "is working"), "stopped": ("bad", "was stopped")}.get(x["status"], ("info", x["status"]))
            rows.append({"id": x["id"], "seq": 0, "at": x["created_at"], "kind": label[0], "who": x.get("user"), "role": None,
                         "text": f"{x['agent_name']} {label[1]}" + (" (simulated)" if x.get("simulated") else ""), "action": "run." + x["status"], "run_id": x["id"]})
        return sorted(rows, key=lambda e: -e["at"])[:limit]

    # ------------------------------------------------------------------ Ask DOS
    @r.post("/ask")
    def ask_dos(body: AskBody):
        return ask.answer(body.question)

    # ------------------------------------------------------------------ the five layers (owner and ops manager only)
    @r.get("/layers")
    def layers():
        layers_only()
        c, since = clients.get_client(), time.time() - 86400
        pol, vis = clients.effective(c), visible()
        changed = [k for k, v in pol.items() if v != clients.SCHEMA[k].default]
        inv = data.inventory(catalog, c.get("verticals") or VERTICALS)
        acc = [a for a in store().list("data_access", limit=5000) if a["created_at"] >= since]
        runs = [x for x in store().list("runs", limit=5000) if x["created_at"] >= since and x.get("purpose") == "run"]
        steps = [s for s in store().list("steps", limit=20000) if s["created_at"] >= since]
        live = store().list("deployments", where={"status": "live"}, limit=500)
        st = store().get("client_state", "selftest")
        kill = governance.kill_state()
        audit_state = verify_audit()
        by_layer = {n: sum(1 for s in steps if s.get("layer") == n) for n in range(1, 6)}
        return {"layers": [
            {"n": 1, "name": "Experience", "what": "The DOS app every role uses. Each role sees only the pages its work needs.",
             "facts": [f"5 roles, {len(governance.PERMISSIONS)} permissions", f"Signed in as {access.ROLE_NAMES.get(current_role())}",
                       "Login codes, no passwords on screen"], "status": "ok", "page": "home", "trace_steps": by_layer[1]},
            {"n": 2, "name": "Client configuration", "what": "This company's rules: limits, approvals, hours, budgets. Rules are data, not code.",
             "facts": [f"Version {c['version']}", f"{len(changed)} of {len(pol)} settings tuned for {c['name']}", f"{sum(s['kind'] == 'config' for s in steps)} rule reads in 24 h"],
             "status": "ok", "page": "rules", "trace_steps": by_layer[2]},
            {"n": 3, "name": "Data", "what": "One gate for every read: classified, masked by role, logged.",
             "facts": [f"{sum(d['status'] != 'none' for d in inv)} of {len(inv)} sources connected", f"{len(acc)} reads in 24 h",
                       f"{sum(a['status'] == 'denied' for a in acc)} reads refused"], "status": "warn" if any(d["status"] == "none" for d in inv) else "ok",
             "page": "data", "trace_steps": by_layer[3]},
            {"n": 4, "name": "AI agents", "what": f"{len(vis)} agents on Gemini and the Google ADK, each with its own tools, skills and tests.",
             "facts": [f"{len(live)} live of {len(vis)}", f"{len(runs)} runs in 24 h", f"{sum(x['status'] == 'completed' for x in runs)} done, {sum(x['status'] == 'waiting_approval' for x in runs)} waiting for people"],
             "status": "ok", "page": "studio", "trace_steps": by_layer[4]},
            {"n": 5, "name": "Safety, security and governance", "what": "Every action checked before it happens, risky ones wait for a person, everything recorded.",
             "facts": ["EMERGENCY STOP ENGAGED" if kill.get("engaged") else "Emergency stop clear", f"{sum(s['kind'] == 'guardrail' for s in steps)} guardrail decisions in 24 h",
                       f"Audit chain {'intact' if audit_state['intact'] else 'BROKEN'} ({audit_state['records']} records)",
                       f"Self-test {st['passed']}/{st['total']}" if st else "Self-test not run yet"],
             "status": "stop" if kill.get("engaged") else "ok", "page": "safety", "trace_steps": by_layer[5]},
        ], "client": c["name"], "mode": config.MODEL_MODE}

    # ------------------------------------------------------------------ gold-layer data (owner and ops manager), PII masked
    @r.get("/gold")
    def gold_overview():
        layers_only()
        return {"agents": gold.overview(sorted(visible().values(), key=lambda s: (VERTICALS.index(s.vertical) if s.vertical in VERTICALS else 99, s.name))),
                "verticals": [v for v in VERTICALS if v in {s.vertical for s in visible().values()}]}

    @r.get("/gold/{agent_id}")
    def gold_agent(agent_id: str):
        layers_only()
        spec = spec_or_404(agent_id)
        out = gold.agent_view(spec)
        audit(current_actor(), "data.gold_viewed", spec.id, {"datasets": out["lineage"]["datasets"], "masked": True})
        return out

    # ------------------------------------------------------------------ event watch: what each agent is waiting for
    @r.get("/events")
    def event_watch(vertical: str = "all"):
        specs = [s for s in visible().values() if vertical in ("all", s.vertical)]
        specs.sort(key=lambda s: (VERTICALS.index(s.vertical) if s.vertical in VERTICALS else 99, s.tier != "hero", s.name))
        out = events.watch(specs)
        out["can_run"] = governance.allowed("agent.run")
        out["mode"] = config.MODEL_MODE
        return out

    # ------------------------------------------------------------------ Gemini connection check (owner and ops manager)
    _check_cache: dict = {}

    @r.get("/gemini-check")
    def gemini_check(fresh: bool = False):
        """One tiny call per model alias, so a reviewer (or the presenter, before the demo) knows live mode works."""
        layers_only()
        ok, why = config.gemini_ready()
        if not ok:
            return {"ready": False, "reason": why, "models": [], "mode": config.MODEL_MODE}
        if not fresh and _check_cache.get("at", 0) > time.time() - 120:
            return _check_cache["result"]
        from google import genai  # noqa: PLC0415
        from google.genai import types as gt  # noqa: PLC0415
        client = genai.Client(http_options=gt.HttpOptions(timeout=30_000))
        models = []
        for alias in ("flash", "lite", "pro"):
            mid, t0 = config.resolve_model(alias), time.perf_counter()
            try:
                txt = client.models.generate_content(model=mid, contents="Reply with the single word OK.").text or ""
                models.append({"alias": alias, "model": mid, "ok": True, "ms": round((time.perf_counter() - t0) * 1000), "reply": txt.strip()[:20]})
            except Exception as exc:  # report, never crash the page
                err = f"{type(exc).__name__}: {exc}"[:300]
                models.append({"alias": alias, "model": mid, "ok": False, "ms": round((time.perf_counter() - t0) * 1000), "error": err, "hint": config.explain_error(err)})
        result = {"ready": all(m["ok"] for m in models), "reason": why, "models": models, "mode": config.MODEL_MODE, "checked_at": time.time()}
        _check_cache.update(at=time.time(), result=result)
        return result

    @r.get("/versions")
    def versions():
        layers_only()
        rows = []
        for d in store().list("deployments", limit=500):
            s = catalog.get(d["agent_id"])
            rows.append({k: d.get(k) for k in ("id", "agent_id", "version", "status", "mode", "created_by", "created_at", "risk", "config_version", "via")}
                        | {"name": s.name if s else d["agent_id"], "vertical": s.vertical if s else "", "score": (d.get("eval") or {}).get("score")})
        return rows

    return r
