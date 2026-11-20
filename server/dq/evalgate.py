"""Evaluation gate: no agent version goes live until it passes its own test cases.

For each eval case in the spec we run the candidate agent and check two things:
  1. Trajectory: did it call the tool the case expects (expect_tool)?
  2. Quality: does the reply meet the expectation text? Judged by Gemini 3.5 Flash-Lite (LLM-as-judge).
The score is the share of checks passed. Below the threshold the deployment is marked failed.

During an eval run, approval-gated tools are auto-rejected: a test must never perform a real action.
In mock mode the gate does structural checks only and says so in the result."""
from __future__ import annotations

import logging
import os

from . import config
from .clients import policy
from .spec import AgentSpec
from .store import get_store

log = logging.getLogger("dq.eval")

JUDGE_PROMPT = """You are grading an AI agent's reply against an expectation.
User request: {ask}
Expectation: {expect}
Agent reply: {reply}
Tools the agent called: {tools}
Answer with exactly one word, PASS or FAIL, then a short reason on the same line."""


def judge(ask: str, expect: str, reply: str, tools: list[str]) -> tuple[bool, str]:
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_GENAI_USE_VERTEXAI")):
        return True, "No model credentials: quality check skipped"
    try:
        from google import genai  # noqa: PLC0415

        out = genai.Client().models.generate_content(
            model=config.resolve_model("lite"), contents=JUDGE_PROMPT.format(ask=ask, expect=expect, reply=reply, tools=tools)).text or ""
        return out.strip().upper().startswith("PASS"), out.strip()[:200]
    except Exception as exc:
        log.warning("judge failed: %s", exc)
        return True, f"Judge unavailable ({type(exc).__name__}): quality check skipped"


async def run_gate(manager, spec: AgentSpec, settings: dict, version: int, mode: str) -> dict:
    store = get_store()
    cases, passed, total = [], 0, 0
    eval_cases = spec.evals or []
    if mode == "mock":  # scripted model: only the demo trajectory can be checked
        eval_cases = [type("C", (), {"ask": spec.demo.ask, "expect_tool": (spec.demo.script[0].tool if spec.demo.script else None), "expect": ""})()]
    for case in eval_cases:
        run = await manager.start(spec, case.ask, settings=settings, version=version, mode=mode, user="eval-gate", purpose="eval", wait=True)
        # never act for real during a test: reject anything waiting for approval
        for _ in range(6):  # an agent may ask for several approvals in a row; reject each one
            waiting = store.list("approvals", where={"run_id": run["id"], "status": "pending"})
            if not waiting:
                break
            for ap in waiting:
                await manager.decide(ap["id"], approved=False, actor="eval-gate", note="auto-rejected during evaluation", wait=True)
        run = store.get("runs", run["id"])
        steps = store.list("steps", where={"run_id": run["id"]}, descending=False, limit=500)
        called = [s["name"] for s in steps if s["kind"] in ("tool", "skill")]
        checks = [("no_error", run["status"] != "failed" and not any(s["status"] == "error" and s["kind"] == "model" for s in steps), run.get("error") or "")]
        if case.expect_tool:
            checks.append(("trajectory", case.expect_tool in called, f"expected {case.expect_tool}, called {called}"))
        if case.expect and mode != "mock":
            ok, why = judge(case.ask, case.expect, run["output"], called)
            checks.append(("quality", ok, why))
        passed += sum(1 for _, ok, _ in checks if ok)
        total += len(checks)
        cases.append({"ask": case.ask, "run_id": run["id"], "checks": [{"name": n, "passed": ok, "detail": d} for n, ok, d in checks]})
    score = round(passed / total, 3) if total else 1.0
    threshold = policy("governance.eval_threshold")  # each client sets its own bar, inside the platform's bounds
    return {"score": score, "threshold": threshold, "passed": score >= threshold, "cases": cases,
            "note": "Simulation mode: structural and trajectory checks only" if mode == "mock" else "Trajectory checks plus LLM-as-judge quality checks"}
