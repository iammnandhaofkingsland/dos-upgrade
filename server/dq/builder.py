"""Agent Builder: turns a plain-language brief into a draft AgentSpec using Gemini 4 Argon.

The model may only choose tools and skills that already exist, so a drafted agent is runnable at once.
The draft is validated against the AgentSpec model before it is shown. A human reviews it before saving."""
from __future__ import annotations

import json
import os
import pathlib
import re

import yaml

from . import config
from .spec import VERTICALS, AgentSpec
from .tools import REGISTRY

SKILLS_DIR = pathlib.Path(__file__).resolve().parent.parent / "skills"

BUILDER_PROMPT = """You design AI agents for DOS (DigiQuench OS), an AI agent platform.
Write ONE agent specification as a JSON object for this brief:

BRIEF: {brief}

Rules
- Fields: id (lowercase letters, digits, hyphens), name, vertical (one of {verticals}), tier ("standard"), tagline, problem,
  users, trigger, model ("flash", "lite" or "pro"), thinking ("low", "medium" or "high"), autonomy ("suggest", "approve" or "auto"),
  tools (list), approvals (list, subset of tools), skills (list), instruction (5 to 8 lines), kpis (3 items), guardrails (3 items),
  evals (2 items, each with ask, expect_tool, expect), demo (object with ask).
- tools may ONLY come from this list: {tools}
- skills may ONLY come from this list: {skills}
- Any tool that sends, pays, refunds, orders, changes a price, or writes a record MUST be in approvals.
- The instruction must say what the agent must never do.
- Use plain English. Output only the JSON object."""

SAMPLE = {
    "id": "gst-helper", "name": "GST Helper", "vertical": "Fintech", "tier": "standard",
    "tagline": "Answers GST filing questions from the company's own policy notes.",
    "problem": "Accounts staff lose time searching notes for routine GST questions.", "users": "Accounts team",
    "trigger": "A staff question in chat", "model": "flash", "thinking": "low", "autonomy": "suggest",
    "tools": ["search_knowledge", "create_task"], "approvals": [], "skills": ["escalation-rules"],
    "instruction": "You are GST Helper. Answer only from the policy library using search_knowledge.\nQuote the document and section.\nIf the library has no answer, create a task for the finance lead.\nNever give tax advice beyond the documents.",
    "kpis": ["Questions answered without escalation", "Answer accuracy", "Hours saved"],
    "guardrails": ["Answers must cite a source", "No tax advice", "Unknowns escalated"],
    "evals": [{"ask": "What is our policy on contact hours?", "expect_tool": "search_knowledge", "expect": "Cites the policy section."}],
    "demo": {"ask": "What is our policy on contact hours?"},
}


def draft_spec(brief: str) -> dict:
    """Returns {"spec": dict, "yaml": str, "simulated": bool}. Raises ValueError if the model output is not a valid spec."""
    simulated = config.MODEL_MODE == "mock" or not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_GENAI_USE_VERTEXAI"))
    if simulated:
        raw = dict(SAMPLE)
    else:
        from google import genai  # noqa: PLC0415
        from google.genai import types  # noqa: PLC0415

        skills = sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir())
        prompt = BUILDER_PROMPT.format(brief=brief, verticals=VERTICALS, tools=sorted(REGISTRY), skills=skills)
        resp = genai.Client().models.generate_content(
            model=config.resolve_model("pro"), contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"))
        text = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip(), flags=re.M).strip()
        raw = json.loads(text)
    spec = AgentSpec(**raw)  # validation: unknown vertical, approvals not in tools, bad id -> error
    unknown = [t for t in spec.tools if t not in REGISTRY]
    if unknown:
        raise ValueError(f"Draft uses tools that do not exist: {unknown}")
    return {"spec": spec.model_dump(), "yaml": yaml.safe_dump([spec.model_dump()], sort_keys=False, allow_unicode=True, width=110), "simulated": simulated}
