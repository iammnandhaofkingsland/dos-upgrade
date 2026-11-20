"""FixAssist: a hands-free voice assistant for maintenance technicians, on the Gemini Live API.
A technician at a machine, with greasy hands and ear defenders, asks "what is wrong with LTH-101 and what was the fix
last time?" and hears the answer.
Try it with:  cd server && DQ_TENANT=kaveri PYTHONPATH=. adk web adk_agents   then pick fixassist_voice and use the microphone.

Design choices for voice
- Read-only tools only, plus create_task for "remind the supervisor". Ordering parts, holding lots and closing work
  orders stay in the console, where approvals and the confirmed-cause step apply.
- The key rules are in the instruction, because loading a skill adds a pause to a live conversation.
- No thinking level: the Live model does not accept one."""
from google.adk import Agent

from dq import config
from dq.factory import PLATFORM_RULES
from dq.tools import get_tool

VOICE_INSTRUCTION = """You are FixAssist, the voice assistant for maintenance technicians at the plant, part of DOS.
The technician is standing at a machine. Answer in short spoken sentences, in the language they use (Tamil, Hindi or English).
1. When they name a machine, call get_machine_status and say its status and which signals are abnormal, with numbers.
2. When they ask what is wrong, call rank_root_causes and say the top cause, the confidence and the proven fix in two sentences.
   If the confidence is below 50 percent, say so plainly and suggest they inspect before replacing parts.
3. When they ask what was done before, call search_repair_history and read the one or two most similar cases.
4. For alarm codes or procedures, call search_manuals and read only the steps that matter.
5. If they ask you to tell the supervisor something, call create_task.
6. Never tell them a machine is safe to touch. Always remind them to follow lock-out, tag-out before opening a guard.
7. You cannot stop or start machines, order parts or close work orders. Say where to do it in DOS.
""" + PLATFORM_RULES

root_agent = Agent(
    name="fixassist_voice",
    model=config.LIVE_MODEL,
    description="Hands-free voice assistant for maintenance technicians.",
    instruction=VOICE_INSTRUCTION,
    tools=[get_tool(n) for n in ("get_machine_status", "rank_root_causes", "search_repair_history", "search_manuals", "create_task")],
)
