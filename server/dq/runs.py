"""Run manager: executes agents and owns the run life cycle.

  running -> completed | failed | stopped
        \\-> waiting_approval -> running -> completed      (after a human decision)

One platform run = one ADK session. The session id IS the run id, which lets the plugins attach every
model call and tool call to the right run without any extra plumbing.

Every run carries a RUN CONTEXT (a context variable) for its whole life. It tells the layers underneath
which client and which run they are serving, so a tool that calls policy() or ds() gets this client's
rule and this client's data, and the read lands in this run's trace."""
from __future__ import annotations

import asyncio
import logging
import time

from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from . import config, governance
from .clients import get_client, policy
from .context import current_client, run_var
from .factory import approval_plan, build_agent
from .plugins import GuardrailPlugin, TelemetryPlugin
from .spec import AgentSpec
from .store import audit, get_store, new_id, now
from .trace import preview, write_step

log = logging.getLogger("dq.runs")
CONFIRM = "adk_request_confirmation"  # the function-call name the ADK uses to ask for human confirmation


class RunManager:
    def __init__(self, catalog: dict[str, AgentSpec]):
        self.catalog = catalog
        self.guardrails = GuardrailPlugin()
        self.telemetry = TelemetryPlugin()
        # In-memory sessions are right for a single Cloud Run instance (the demo). For several instances or
        # restarts, switch to VertexAiSessionService (Agent Runtime sessions) or DatabaseSessionService.
        self.sessions = InMemorySessionService()
        self._runners: dict[str, Runner] = {}
        self._tasks: set[asyncio.Task] = set()

    # ----- runner cache: one runner per (client, config version, agent, version, mode) -----
    def _runner(self, spec: AgentSpec, settings: dict, version: int, mode: str) -> Runner:
        client = get_client()
        # The client's rules are written into the instruction, so a new configuration version needs a new agent.
        key = f"{client['id']}:{client['version']}:{spec.id}:{version}:{mode}"
        if key not in self._runners:
            agent = build_agent(spec, settings, mode)
            app = App(name="digiquench", root_agent=agent, plugins=[self.guardrails, self.telemetry])
            self._runners[key] = Runner(app=app, session_service=self.sessions)
        return self._runners[key]

    def invalidate(self, agent_id: str | None = None) -> None:
        for key in [k for k in self._runners if agent_id is None or f":{agent_id}:" in k]:
            self._runners.pop(key)

    def _spawn(self, coro, wait: bool):
        if wait:
            return coro
        task = asyncio.create_task(coro)  # the task copies the current context: client and role travel with it
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return None

    # ----- public API -----
    async def start(self, spec: AgentSpec, text: str, *, settings: dict | None = None, version: int = 0,
                    mode: str | None = None, user: str = "console", purpose: str = "run", wait: bool = False) -> dict:
        mode = mode or config.MODEL_MODE
        client = get_client()
        run_id = new_id("run")
        run = get_store().put("runs", run_id, {
            "agent_id": spec.id, "agent_name": spec.name, "vertical": spec.vertical, "version": version, "mode": mode,
            "purpose": purpose, "user": user, "input": preview(text, 2000), "output": "", "status": "running",
            "config_version": client["version"], "client_name": client["name"],
            "created_at": now(), "ended_at": None, "latency_ms": 0, "input_tokens": 0, "output_tokens": 0,
            "cost_inr": 0.0, "model_calls": 0, "tool_calls": 0, "error": None, "simulated": mode == "mock"})
        write_step(run_id, "config", "configuration", detail=f"Rules of {client['name']} applied to this run", value=f"version {client['version']}",
                   by="platform", status="applied")
        await self.sessions.create_session(app_name="digiquench", user_id=user, session_id=run_id,
                                           state={"dq_agent_id": spec.id, "dq_version": version, "dq_client": client["id"]})
        message = types.Content(role="user", parts=[types.Part(text=text)])
        pending = self._spawn(self._drive(run_id, spec, settings or {}, version, mode, user, message), wait)
        if pending:
            await pending
        return get_store().get("runs", run_id) or run

    async def decide(self, approval_id: str, approved: bool, actor: str, note: str = "", wait: bool = False) -> dict:
        store = get_store()
        ap = store.get("approvals", approval_id)
        if not ap:
            raise KeyError("approval not found")
        if ap["status"] != "pending":
            raise ValueError("approval already decided")
        run = store.get("runs", ap["run_id"])
        if governance.kill_state()["engaged"]:
            raise PermissionError("Emergency stop is engaged. Release it before deciding approvals.")
        if actor != "eval-gate" and policy("governance.four_eyes") and actor == run["user"]:
            raise PermissionError("Four-eyes rule: the person who started this run cannot approve its actions. Ask another approver.")
        store.update("approvals", approval_id, {"status": "approved" if approved else "rejected", "decided_by": actor,
                                                "decided_at": now(), "note": note})
        write_step(run["id"], "approval", ap["tool"], detail=f"{'Approved' if approved else 'Rejected'} by {actor}" + (f": {note}" if note else ""),
                   status="approved" if approved else "rejected", by=actor)
        if ap.get("purpose", "run") != "eval":
            audit(actor, "approval." + ("approved" if approved else "rejected"), ap["run_id"], {"tool": ap["tool"], "args": ap["args"], "note": note})
        spec = self.catalog[run["agent_id"]]
        # The decision goes back to the ADK as the response to its confirmation request. The ADK then
        # executes the original tool (if confirmed) and lets the model finish the task.
        message = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=ap["confirmation_call_id"], name=CONFIRM, response={"confirmed": approved}))])
        store.update("runs", run["id"], {"status": "running"})
        pending = self._spawn(self._drive(run["id"], spec, ap.get("settings", {}), run["version"], run["mode"], run["user"], message), wait)
        if pending:
            await pending
        return store.get("approvals", approval_id)

    # ----- the engine -----
    async def _drive(self, run_id: str, spec: AgentSpec, settings: dict, version: int, mode: str, user: str, message: types.Content) -> None:
        store = get_store()
        t0 = time.perf_counter()
        final_text, pending, error = "", [], None
        prev_purpose = (store.get("runs", run_id) or {}).get("purpose", "run")
        # Evaluation runs are dry runs: every check runs, but effect() and plant changes do nothing.
        token = run_var.set({"run_id": run_id, "agent_id": spec.id, "client": current_client(), "tool": None, "seen": set(),
                             "dry_run": prev_purpose == "eval"})
        try:
            runner = self._runner(spec, settings, version, mode)
            plan = {p["tool"]: p["why"] for p in approval_plan(spec, settings)}
            async for event in runner.run_async(user_id=user, session_id=run_id, new_message=message):
                for part in (event.content.parts if event.content and event.content.parts else []):
                    if part.function_call and part.function_call.name == CONFIRM:
                        original = (part.function_call.args or {}).get("originalFunctionCall", {})
                        tool = original.get("name", "unknown")
                        pending.append(store.put("approvals", new_id("apr"), {
                            "run_id": run_id, "agent_id": spec.id, "agent_name": spec.name, "status": "pending", "purpose": prev_purpose,
                            "tool": tool, "args": original.get("args", {}), "why": plan.get(tool, ""), "requested_by": user,
                            "confirmation_call_id": part.function_call.id, "settings": settings,
                            "created_at": now(), "decided_by": None, "decided_at": None, "note": ""}))
                        write_step(run_id, "approval", tool, detail="Paused for a human decision. " + plan.get(tool, ""), status="pending", by="platform")
                    elif part.text and event.author != "user" and not getattr(part, "thought", False) and not event.partial:
                        final_text = part.text  # the last model text of the turn is the answer
        except Exception as exc:  # a failed run must still be recorded, with its reason
            log.exception("run %s failed", run_id)
            error = f"{type(exc).__name__}: {exc}"[:500]
            write_step(run_id, "guardrail", "run_error", detail=config.explain_error(error), status="error", by="platform")
            if prev_purpose == "run":
                governance.raise_incident("run_failed", "medium", f"{spec.name} run failed: {error[:200]}", run_id, spec.id)
        finally:
            run_var.reset(token)
        steps = store.list("steps", where={"run_id": run_id}, limit=2000)
        prev = store.get("runs", run_id) or {}
        stopped = any(s["kind"] == "guardrail" and s["name"] == "emergency_stop" for s in steps)
        status = "failed" if error else ("stopped" if stopped else ("waiting_approval" if pending else "completed"))
        store.update("runs", run_id, {
            "status": status, "output": final_text or prev.get("output", ""), "error": error,
            "error_hint": config.explain_error(error) if error else None,
            "latency_ms": prev.get("latency_ms", 0) + round((time.perf_counter() - t0) * 1000),
            "ended_at": None if status == "waiting_approval" else now(),
            "input_tokens": sum(s.get("input_tokens", 0) for s in steps), "output_tokens": sum(s.get("output_tokens", 0) for s in steps),
            "cost_inr": round(sum(s.get("cost_inr", 0) for s in steps), 4),
            "model_calls": sum(1 for s in steps if s["kind"] == "model"), "tool_calls": sum(1 for s in steps if s["kind"] in ("tool", "skill")),
            "guardrail_events": sum(1 for s in steps if s["kind"] == "guardrail"),
            "config_reads": sum(1 for s in steps if s["kind"] == "config"), "data_reads": sum(1 for s in steps if s["kind"] == "data")})
        if status != "waiting_approval":
            self.guardrails.forget(run_id)

    async def drain(self) -> None:
        """Wait for background runs (used by tests and by graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
