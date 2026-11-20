"""MockGemini: a scripted, offline stand-in for Gemini.

Why it exists
- Tests and rehearsals must run with no network, no API key and no cost.
- If the venue Wi-Fi fails during a demo you can still show the platform mechanics.

What it is NOT: it is not a model and its replies are scripted in the catalog (demo.script and demo.reply).
The console labels every mock run as "Simulation". Never present a simulated run as real model output."""
from __future__ import annotations

import json
import re
from typing import AsyncGenerator

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

from .spec import AgentSpec


ID = re.compile(r"\b[A-Z]{2,5}-\d{3,6}\b")
TEXT_SLOTS = {"machine": re.compile(r"\b[A-Z]{3}-\d{3}\b"), "part": re.compile(r"\bSP-[A-Z]{3,4}-[A-Z0-9]{3,5}\b"),
              "minutes": re.compile(r"(\d+)\s*min"), "signal": re.compile(r"\b(vibration|temperature|current|cycle_time|pressure)\b"),
              "invoice": re.compile(r"\bINV-S-\d{3}\b"), "lot": re.compile(r"\bLOT-\d{4}-\d{2}\b"), "order": re.compile(r"\bPO-\d{4}\b"),
              "skill": re.compile(r"skill:\s*([a-z-]+)"), "cause": re.compile(r"Likely cause:\s*([^.]+)")}
SLOT = re.compile(r"\{(r:[a-z_.0-9]+|[a-z_]+)\}")


def _dig(obj, path):
    for key in path:
        if isinstance(obj, list):
            obj = obj[int(key)] if key.isdigit() and int(key) < len(obj) else None
        elif isinstance(obj, dict):
            obj = obj.get(key)
        if obj is None:
            return None
    return obj


def fill_slots(args, user_text: str, results: list[dict]):
    """Fill {machine}, {part}, {r:key.path} ... placeholders in a scripted step from the request and earlier tool results."""
    def value(name: str):
        if name.startswith("r:"):
            path = name[2:].split(".")
            for res in reversed(results):
                v = _dig(res, path)
                if v not in (None, "", []):
                    return v
            return None
        m = TEXT_SLOTS.get(name, re.compile("x^")).search(user_text)
        if m:
            return m.group(1) if m.groups() else m.group(0)
        fallback = {"part": "r:recommended_part", "minutes": None}
        if fallback.get(name):
            return value(fallback[name])
        return {"minutes": 60, "signal": "vibration"}.get(name)

    def sub(v):
        if isinstance(v, str):
            whole = SLOT.fullmatch(v)
            if whole:
                got = value(whole.group(1))
                if got is not None and str(got).isdigit():
                    return int(got)
                return got if got is not None else ""
            return SLOT.sub(lambda m: str(value(m.group(1)) or ""), v)
        if isinstance(v, dict):
            return {k: sub(x) for k, x in v.items()}
        if isinstance(v, list):
            return [sub(x) for x in v]
        return v

    return sub(args)


class MockGemini(BaseLlm):
    model: str = "mock-gemini"
    spec: AgentSpec

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"mock-.*"]

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents or []
        # Find the latest user text turn; count the tool results that came after it.
        last_user = max((i for i, c in enumerate(contents) if c.role == "user" and any(p.text for p in c.parts or [])), default=0)
        done = sum(1 for c in contents[last_user:] for p in (c.parts or [])
                   if p.function_response and p.function_response.name != "adk_request_confirmation")
        rejected = any("reject" in str(p.function_response.response).lower() for c in contents[last_user:] for p in (c.parts or [])
                       if p.function_response and p.function_response.name in self.spec.approvals)
        script = self.spec.demo.script
        responses = [p.function_response for c in contents[last_user:] for p in (c.parts or [])
                     if p.function_response and p.function_response.name != "adk_request_confirmation"]
        last = (responses[-1].response or {}) if responses else {}
        last_text = str(last).lower()
        refused = last.get("status") == "error" and "requires confirmation" not in last_text and "reject" not in last_text
        scheduled = next((r.response.get("scheduled_for") for r in responses if isinstance(r.response, dict) and r.response.get("scheduled_for")), None)
        # If the user names a different record than the sample request, only the look-up step is simulated.
        user_text = " ".join(p.text or "" for p in (contents[last_user].parts or [])) if contents else ""
        ask_ids, msg_ids = ID.findall(self.spec.demo.ask), ID.findall(user_text)
        other = msg_ids[0] if msg_ids and ask_ids and msg_ids[0] not in ask_ids and not self.spec.demo.generic else None
        results = [r.response for r in responses if isinstance(r.response, dict)]
        chars = sum(len(p.text or "") for c in contents for p in (c.parts or [])) + len(str(llm_request.config.system_instruction or ""))
        if rejected:
            part = types.Part(text="[Simulation] The approver rejected the action, so I have not carried it out. Everything else I did is listed in the trace.")
            out_tokens = 30
        elif refused:
            part = types.Part(text="[Simulation] The platform refused that step: " + str(last.get("error_message", "not allowed")) +
                              " I have stopped there and done nothing further.")
            out_tokens = 40
        elif other and done >= 1:
            part = types.Part(text=f"[Simulation] I looked up {other}; the trace shows what the platform returned. The scripted model only plays the full "
                                   "conversation for the sample request. Switch to live mode to see Gemini handle this record end to end.")
            out_tokens = 45
        elif done < len(script):
            step = script[done]
            if self.spec.demo.generic:
                args = fill_slots(step.args, user_text, results)
            else:
                args = json.loads(json.dumps(step.args).replace(ask_ids[0], other)) if other else step.args
            part = types.Part(function_call=types.FunctionCall(name=step.tool, args=args))
            out_tokens = 40
        elif self.spec.demo.generic:
            notes = [r.get("summary") for r in results if r.get("summary")]
            text = "[Simulation] " + (" ".join(notes) if notes else "No findings.")
            if any("requires confirmation" in str(r).lower() for r in results):
                text += " One action is waiting for human approval in DOS."
            part = types.Part(text=text)
            out_tokens = max(20, len(text) // 4)
        else:
            text = self.spec.demo.reply or (f"[Simulation] {self.spec.name} would now use its tools ({', '.join(self.spec.tools[:3])}) "
                                            f"to handle: \"{self.spec.demo.ask}\". Switch to live mode to see Gemini do it.")
            if scheduled:
                text += f" Note: it is outside the client's contact window, so the message is scheduled for {scheduled}, not sent yet."
            part = types.Part(text=text)
            out_tokens = max(20, len(text) // 4)
        in_tokens = 600 + chars // 4  # rough but stable, so cost dashboards behave in rehearsal
        yield LlmResponse(
            content=types.Content(role="model", parts=[part]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=in_tokens, candidates_token_count=out_tokens, total_token_count=in_tokens + out_tokens),
            model_version="mock-gemini",
        )
