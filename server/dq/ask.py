"""ASK DOS: plain-English questions about this company's own operations (layer 1, reading layers 2 to 5).

Ask DOS reads; it never acts. It gathers a small, fresh set of facts from the store (approvals waiting, recent runs,
live agents, the emergency stop, open incidents, the plant, spend), screens the question for instruction-like text
(the same screen layer 5 uses on tool results), and then:
  - on Gemini (live mode): asks Gemini 3.5 Flash-Lite to answer ONLY from those facts, in a few short lines;
  - in simulation, or if Gemini is not reachable: answers from the same facts with simple rules, and says so.

Every answer lists the records it looked at, so a person can check it. Questions that try to give orders
("approve everything", "ignore your rules") are refused and recorded as a governance incident."""
from __future__ import annotations

import json
import logging
import os
import time

from . import clients, config, governance
from .context import current_actor, current_role
from .store import audit, get_store

log = logging.getLogger("dq.ask")

PROMPT = """You are Ask DOS, the read-only assistant inside DOS (DigiQuench OS) for {company}.
The person asking is the {role}. Answer ONLY from the JSON facts below. If the facts do not contain the answer, say so.
Use plain English, at most 6 short lines, numbers exactly as given, Indian rupees as Rs. Never claim to approve, run,
change or stop anything: you can only explain and point to the page where a person can act (Approvals, Agent Studio,
Live runs, Plant floor, Work orders, Safety).

FACTS
{facts}

QUESTION
{question}"""
ORDERS = ("approve all", "approve everything", "ignore", "disable", "turn off", "delete", "release the stop", "override")


def facts() -> dict:
    s, since = get_store(), time.time() - 86400
    runs = [r for r in s.list("runs", limit=400) if r.get("purpose") == "run"]
    today = [r for r in runs if r["created_at"] >= since]
    pend = [a for a in s.list("approvals", where={"status": "pending"}, limit=200) if a.get("purpose", "run") != "eval"]
    live = s.list("deployments", where={"status": "live"}, limit=500)
    inc = s.list("incidents", where={"status": "open"}, limit=50)
    plant = [i for i in s.list("plant_incidents", limit=20) if i.get("status") != "resolved"]
    pol = clients.effective(clients.get_client())
    return {
        "company": clients.get_client()["name"],
        "emergency_stop": governance.kill_state().get("engaged", False),
        "agents_live": sorted({d["agent_id"] for d in live}),
        "runs_last_24h": {"total": len(today), "completed": sum(r["status"] == "completed" for r in today),
                          "waiting_for_people": sum(r["status"] == "waiting_approval" for r in today), "failed": sum(r["status"] == "failed" for r in today),
                          "simulated": sum(bool(r.get("simulated")) for r in today), "cost_inr": round(sum(r["cost_inr"] for r in today), 2)},
        "recent_runs": [{"agent": r["agent_name"], "status": r["status"], "when_min_ago": round((time.time() - r["created_at"]) / 60),
                         "answer": (r.get("output") or r.get("error") or "")[:240]} for r in runs[:8]],
        "approvals_waiting": [{"agent": a["agent_name"], "action": a["tool"], "details": {k: v for k, v in (a.get("args") or {}).items()},
                               "why_it_needs_a_person": a.get("why", "")[:160]} for a in pend[:10]],
        "open_incidents": [{"kind": i["kind"], "severity": i["severity"], "summary": i["summary"][:200]} for i in inc[:8]],
        "plant_open_breakdowns": [{"machine": i["machine"], "status": i["status"], "cause": i.get("root_cause"), "confidence": i.get("confidence"),
                                   "technician": i.get("technician"), "work_order": i.get("work_order")} for i in plant[:6]],
        "key_rules": {k: pol[k] for k in list(pol)[:14]},
    }


def _rules_answer(q: str, f: dict) -> str:
    ql = q.lower()
    if any(w in ql for w in ("approv", "waiting", "pending", "decide")):
        rows = f["approvals_waiting"]
        if not rows:
            return "Nothing is waiting for a person right now."
        return f"{len(rows)} action(s) are waiting for a person:\n" + "\n".join(f"- {a['agent']}: {a['action']} ({a['why_it_needs_a_person'][:80]})" for a in rows[:6]) + "\nOpen Approvals to decide."
    if any(w in ql for w in ("fail", "error", "wrong", "incident")):
        bad = [r for r in f["recent_runs"] if r["status"] == "failed"]
        return (f"{f['runs_last_24h']['failed']} run(s) failed in the last 24 hours. " + (f"Latest: {bad[0]['agent']}: {bad[0]['answer'][:160]}" if bad else "") +
                f"\nOpen incidents: {len(f['open_incidents'])}.")
    if any(w in ql for w in ("machine", "plant", "breakdown", "downtime")):
        rows = f["plant_open_breakdowns"]
        return "No open breakdowns on the plant floor." if not rows else "Open breakdowns:\n" + "\n".join(f"- {r['machine']}: {r['status']}, likely cause {r['cause'] or 'being diagnosed'}" for r in rows)
    if any(w in ql for w in ("stop", "kill", "emergency")):
        return "The emergency stop is ENGAGED: no agent can act." if f["emergency_stop"] else "The emergency stop is clear. Approvers and the Business Owner can pull it from the top bar."
    if any(w in ql for w in ("cost", "spend", "money", "rupee", "rs")):
        return f"Model spend in the last 24 hours: Rs {f['runs_last_24h']['cost_inr']} across {f['runs_last_24h']['total']} runs."
    if any(w in ql for w in ("last run", "latest", "recent", "what happened", "explain")):
        r = f["recent_runs"][:1]
        return "No runs yet. Start one from Agent Studio." if not r else f"The latest run was {r[0]['agent']} ({r[0]['status']}, {r[0]['when_min_ago']} min ago): {r[0]['answer']}"
    rl = f["runs_last_24h"]
    return (f"{f['company']}: {len(f['agents_live'])} agents live. In the last 24 hours {rl['total']} runs: {rl['completed']} done, "
            f"{rl['waiting_for_people']} waiting for people, {rl['failed']} failed. {len(f['approvals_waiting'])} approvals waiting.")


def answer(question: str) -> dict:
    q = (question or "").strip()[:600]
    cleaned, hits = governance.screen_text(q)
    if hits or any(w in q.lower() for w in ORDERS):
        governance.raise_incident("prompt_injection", "low", f"Ask DOS refused an instruction-like question from {current_role()}: {q[:120]}")
        audit(current_actor(), "ask.refused", "ask-dos", {"question": q[:200]})
        return {"answer": "I can explain what happened and what is waiting, but I cannot approve, change, switch off or override anything. "
                          "A person decides those on the Approvals and Safety pages.", "blocked": True, "looked_up": [], "engine": "safety screen"}
    f = facts()
    looked = ["approvals", "runs", "deployments", "incidents", "plant", "rules"]
    engine = "rules"
    text = ""
    has_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_GENAI_USE_VERTEXAI")
    if config.MODEL_MODE == "live" and has_key:
        try:
            from google import genai  # noqa: PLC0415

            out = genai.Client().models.generate_content(
                model=config.resolve_model("lite"),
                contents=PROMPT.format(company=f["company"], role=current_role(), facts=json.dumps(f, default=str)[:12000], question=cleaned))
            text, engine = (out.text or "").strip(), "gemini"
        except Exception as exc:  # never leave the person without an answer
            log.warning("Ask DOS fell back to rules: %s", exc)
    if not text:
        text = _rules_answer(cleaned, f)
    audit(current_actor(), "ask.answered", "ask-dos", {"question": q[:200], "engine": engine})
    return {"answer": text, "blocked": False, "looked_up": looked, "engine": engine}
