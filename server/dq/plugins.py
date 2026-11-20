"""Two ADK plugins that run around EVERY model call and tool call of EVERY agent.

Plugins are registered once on the App, so a new agent gets the safety layer and telemetry for free.
- GuardrailPlugin (layer 5): emergency stop, identity-number masking, step budgets, limit checks BEFORE approval,
  and the untrusted-text screen on everything a tool returns.
- TelemetryPlugin: writes one step record per model call and tool call (latency, tokens, cost).
The ADK also emits OpenTelemetry spans to Cloud Trace; these step records are the product-level trace
that business users see in the console.

Order matters. The ADK calls before_tool_callback BEFORE it asks a human to confirm a gated tool, so a request
that breaks a hard limit is refused here and never reaches the approver's queue."""
from __future__ import annotations

import time
from typing import Any, Optional

from google.adk.plugins import BasePlugin
from google.genai import types

from . import governance, pricing
from .clients import policy
from .context import current_run
from .tools import PRECHECKS
from .trace import mask_pii, preview, write_step  # noqa: F401  (mask_pii re-exported for callers and tests)

SKILL_TOOLS = ("load_skill", "list_skills", "load_skill_resource", "run_skill_script")
STOPPED = "The emergency stop is engaged for this client, so I have stopped. No further action was taken."


def _run_id(ctx) -> str:
    return ctx.session.id  # one ADK session per platform run


# ---------- guardrails ----------
class GuardrailPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="dq_guardrails")
        self._llm_calls: dict[str, int] = {}
        self._tool_calls: dict[str, int] = {}

    async def on_user_message_callback(self, *, invocation_context, user_message: types.Content) -> Optional[types.Content]:
        """Mask ID numbers before they reach the model, the logs or the trace."""
        changed, parts = 0, []
        for p in user_message.parts or []:
            if p.text:
                masked, n = mask_pii(p.text)
                changed += n
                parts.append(types.Part(text=masked))
            else:
                parts.append(p)
        if changed:
            write_step(invocation_context.session.id, "guardrail", "identity_number_masked", detail=f"{changed} ID number(s) masked in the user message before the model saw it", status="applied")
            return types.Content(role=user_message.role, parts=parts)
        return None

    async def before_model_callback(self, *, callback_context, llm_request):
        from google.adk.models import LlmResponse  # noqa: PLC0415

        rid = _run_id(callback_context)
        if governance.kill_state()["engaged"]:
            write_step(rid, "guardrail", "emergency_stop", detail="Run halted: emergency stop is engaged", status="blocked")
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=STOPPED)]))
        self._llm_calls[rid] = self._llm_calls.get(rid, 0) + 1
        limit = policy("safety.max_llm_calls")
        if self._llm_calls[rid] > limit:
            write_step(rid, "guardrail", "model_call_budget", detail=f"Model-call budget of {limit} for this run is used up", status="blocked")
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(
                text="I have reached the step limit for this task, so I am stopping here. A team member can continue from the trace.")]))
        return None

    async def before_tool_callback(self, *, tool, tool_args: dict[str, Any], tool_context) -> Optional[dict]:
        rid = _run_id(tool_context)
        run = current_run()
        limit = policy("safety.max_tool_calls")  # read before the tool label is set: a platform read, traced once per run
        if run is not None:  # label config and data reads with the tool that caused them
            run["tool"], run["seen"] = tool.name, set()
        refusal = None
        if governance.kill_state()["engaged"]:
            write_step(rid, "guardrail", "emergency_stop", detail=f"{tool.name} not executed: emergency stop is engaged", status="blocked")
            refusal = {"status": "error", "error_message": "Emergency stop is engaged. Do not retry. Tell the user that all agent activity is paused."}
        if refusal is None:
            self._tool_calls[rid] = self._tool_calls.get(rid, 0) + 1
            if self._tool_calls[rid] > limit:
                write_step(rid, "guardrail", "tool_call_budget", detail=f"Tool-call budget of {limit} used up at {tool.name}", status="blocked")
                refusal = {"status": "error", "error_message": "Tool budget for this run is used up. Summarise what is done and stop."}
        if refusal is None and tool.name in PRECHECKS:
            # Hard limits are checked here, before the ADK asks a human to approve. A human is never asked
            # to approve something the platform would refuse anyway.
            try:
                refusal = PRECHECKS[tool.name](**tool_args)
            except Exception as exc:  # a data-gate refusal, or bad arguments from the model
                refusal = {"status": "error", "error_message": str(exc)}
            if refusal:
                name = "message_check" if tool.name == "send_message" else "limit_check"
                write_step(rid, "guardrail", name, detail=f"{tool.name} refused before approval: {refusal['error_message']}", status="blocked")
                if tool.name == "send_message" and "fair-practice" in refusal["error_message"]:
                    governance.raise_incident("blocked_message", "medium", "An agent drafted a message with a blocked phrase. It was not sent.", rid, (run or {}).get("agent_id"))
        if refusal:
            # The tool will not run, so record the attempt as a tool step here.
            write_step(rid, "tool", tool.name, input=preview(tool_args, 400), output=preview(refusal, 500), status="blocked", latency_ms=0)
            if run is not None:
                run["tool"] = None
        return refusal

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
        """Screen everything a data tool returns. Text that tries to instruct the agent is neutralised IN PLACE
        (returning None keeps the other plugins running)."""
        if tool.name not in SKILL_TOOLS and isinstance(result, (dict, list)):
            hits = governance.screen_in_place(result)
            if hits:
                rid = _run_id(tool_context)
                write_step(rid, "guardrail", "untrusted_text_removed", detail=f"{hits} instruction-like passage(s) removed from the result of {tool.name} before the model read it", status="applied")
                governance.raise_incident("prompt_injection", "medium", f"Instruction-like text was found in data returned by {tool.name} and removed.", rid, (current_run() or {}).get("agent_id"))
        return None

    async def after_model_callback(self, *, callback_context, llm_response):
        """Mask ID numbers in model text before it is shown or stored."""
        if llm_response.content and llm_response.content.parts:
            for p in llm_response.content.parts:
                if p.text:
                    masked, n = mask_pii(p.text)
                    if n:
                        p.text = masked
                        write_step(_run_id(callback_context), "guardrail", "identity_number_masked", detail=f"{n} ID number(s) masked in the reply", status="applied")
        return None

    def forget(self, run_id: str) -> None:
        self._llm_calls.pop(run_id, None)
        self._tool_calls.pop(run_id, None)


# ---------- telemetry ----------
class TelemetryPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="dq_telemetry")
        self._t0: dict[str, float] = {}

    async def before_model_callback(self, *, callback_context, llm_request):
        self._t0["m:" + callback_context.invocation_id] = time.perf_counter()
        return None

    async def after_model_callback(self, *, callback_context, llm_response):
        t0 = self._t0.pop("m:" + callback_context.invocation_id, time.perf_counter())
        usage = llm_response.usage_metadata
        tin = (usage.prompt_token_count or 0) if usage else 0
        tout = ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0
        model = llm_response.model_version or "unknown"
        parts = llm_response.content.parts if llm_response.content and llm_response.content.parts else []
        calls = [p.function_call.name for p in parts if p.function_call]
        text = " ".join(p.text for p in parts if p.text and not getattr(p, "thought", False))
        write_step(_run_id(callback_context), "model", model, latency_ms=round((time.perf_counter() - t0) * 1000),
                   input_tokens=tin, output_tokens=tout, cost_inr=pricing.cost_inr(model, tin, tout),
                   decision=("calls " + ", ".join(calls)) if calls else "replies to user", output=preview(text, 400), status="ok")
        return None

    async def on_model_error_callback(self, *, callback_context, llm_request, error: Exception):
        write_step(_run_id(callback_context), "model", str(llm_request.model or "model"), status="error", output=preview(f"{type(error).__name__}: {error}", 400))
        return None

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        self._t0["t:" + str(tool_context.function_call_id)] = time.perf_counter()
        return None

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
        t0 = self._t0.pop("t:" + str(tool_context.function_call_id), time.perf_counter())
        status = "ok"
        if isinstance(result, dict) and (result.get("status") == "error" or "error" in result):
            text = str(result).lower()
            # The ADK answers an approval-gated call with a placeholder until a human decides.
            status = "awaiting_approval" if "requires confirmation" in text else ("rejected" if "reject" in text else "error")
        elif isinstance(result, dict) and result.get("scheduled_for"):
            status = "scheduled"
        kind = "skill" if tool.name in SKILL_TOOLS else "tool"
        write_step(_run_id(tool_context), kind, tool.name, latency_ms=round((time.perf_counter() - t0) * 1000),
                   input=preview(tool_args, 400), output=preview(result, 500), status=status)
        run = current_run()
        if run is not None:
            run["tool"] = None
        return None

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error: Exception):
        write_step(_run_id(tool_context), "tool", tool.name, input=preview(tool_args, 400), status="error", output=preview(f"{type(error).__name__}: {error}", 400))
        return None
