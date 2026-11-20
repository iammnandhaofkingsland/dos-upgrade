"""Voice version of LoanProcess on the Gemini Live API (real-time speech in, speech out).
Try it with:  cd server && PYTHONPATH=. adk web adk_agents   then pick loanprocess_voice and use the microphone.

Design choices for voice
- Only read tools and low-risk write tools. A waiver cannot be approved mid-call, so the voice agent
  creates a task for a human instead of calling offer_settlement.
- The key playbook rules are written into the instruction, because loading a skill adds a pause to a live call.
- No thinking level: the Live model does not accept one."""
from google.adk import Agent

from dq import config
from dq.factory import PLATFORM_RULES
from dq.tools import get_tool

VOICE_INSTRUCTION = """You are LoanProcess on a phone call for a small lender in India. You are calling a borrower about an overdue instalment.
Speak in the borrower's preferred language from the loan account. Short sentences. Warm and respectful.
1. Greet by first name and say who you are calling for.
2. Confirm you are speaking to the borrower before saying anything about the loan. If not, end politely and say nothing about the loan.
3. State the overdue amount and the original due date once.
4. Ask which date this week they can pay. If they give a date, call record_promise_to_pay and repeat it back.
5. If they mention hardship, a dispute, or ask for a waiver, do not negotiate. Say a team member will call back, and call create_task.
6. Never threaten. Never mention legal action. Never call outside 8 am to 7 pm. Keep the call under two minutes.
""" + PLATFORM_RULES

root_agent = Agent(
    name="loanprocess_voice",
    model=config.LIVE_MODEL,
    description="Voice follow-up for overdue EMIs.",
    instruction=VOICE_INSTRUCTION,
    tools=[get_tool(n) for n in ("get_loan_account", "record_promise_to_pay", "create_task", "escalate_to_human")],
)
