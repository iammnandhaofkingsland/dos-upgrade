"""Tools shared by many agents. A tool is a plain Python function: the ADK reads its name, type hints and
docstring and tells Gemini how to call it. Keep docstrings precise: they are part of the prompt."""
from ..clients import client_clock, policy
from ..context import current_run
from ..data import ds
from ..store import get_store, new_id, now


def effect(kind: str, payload: dict, status: str = "done") -> str:
    """Record a business action in the outbox so the console can show exactly what an agent did.
    In production this is where the real API call (WhatsApp provider, ERP, store platform) happens.
    During a safety self-test (dry run) nothing is recorded: the checks run, the action does not."""
    run = current_run() or {}
    eid = new_id("fx")
    if run.get("dry_run"):
        return "dry-run"
    get_store().put("outbox", eid, {"kind": kind, "payload": payload, "status": status, "run_id": run.get("run_id"),
                                    "agent_id": run.get("agent_id"), "created_at": now()})
    return eid


def ok(**data) -> dict:
    return {"status": "success", **data}


def err(message: str) -> dict:
    return {"status": "error", "error_message": message}


def search_knowledge(query: str) -> dict:
    """Search the company's policy and procedure library. Returns matching passages with document and section.

    Args:
        query: What to look for, in plain words.
    """
    words = {w for w in query.lower().replace("?", "").split() if len(w) > 2}
    scored = sorted(((sum(w in (k["text"] + k["section"] + k["doc"]).lower() for w in words), k) for k in ds("knowledge")), key=lambda t: -t[0])
    # Policy passages carry {setting} placeholders, so the library always quotes THIS client's current numbers.
    hits = [{**k, "text": _fill(k["text"])} for s, k in scored if s > 0][:3]
    return ok(results=hits) if hits else ok(results=[], note="No policy passage found. Do not answer from memory.")


def _fill(text: str) -> str:
    import re  # noqa: PLC0415

    return re.sub(r"\{([a-z_.]+)\}", lambda m: f"{policy(m.group(1))}", text)


def _check_message(channel: str = "", to: str = "", text: str = "", **_) -> dict | None:
    """Rules checked BEFORE a message is approved or sent."""
    allowed = policy("messaging.allowed_channels")
    if channel not in allowed:
        return err(f"Channel '{channel}' is not allowed for this client. Allowed: {', '.join(allowed)}.")
    bad = [p for p in policy("messaging.blocked_phrases") if p.lower() in text.lower()]
    if bad:
        return err(f"Message blocked by fair-practice rules (found: {', '.join(bad)}). Rewrite politely.")
    return None


def send_message(channel: str, to: str, text: str) -> dict:
    """Send a message to a customer, patient or supplier.

    Args:
        channel: One of whatsapp, sms, email.
        to: Phone number or email address of the recipient.
        text: The message body. Keep it short and polite.
    """
    refusal = _check_message(channel=channel, to=to, text=text)
    if refusal:
        return refusal
    if channel in ("whatsapp", "sms") and policy("messaging.enforce_contact_hours"):
        start, end, clock = policy("messaging.contact_start"), policy("messaging.contact_end"), client_clock()
        if not start <= clock < end:
            # Outside the permitted window the message is QUEUED, never sent and never dropped.
            mid = effect("message", {"channel": channel, "to": to, "text": text, "send_at": start}, status="scheduled")
            return ok(message_id=mid, delivered=False, scheduled_for=start,
                      note=f"It is {clock}, outside the permitted contact window ({start} to {end}). The message is queued and will go at {start}. "
                           "Tell the user it is scheduled, not sent.")
    return ok(message_id=effect("message", {"channel": channel, "to": to, "text": text}), delivered=True)


def create_task(title: str, details: str, assignee: str = "operations") -> dict:
    """Create a follow-up task, ticket or case for a human team.

    Args:
        title: Short title of the task.
        details: What needs to be done and why.
        assignee: Team or role that should pick it up.
    """
    return ok(task_id=effect("task", {"title": title, "details": details, "assignee": assignee}))


def save_draft(kind: str, title: str, body: str) -> dict:
    """Save a document as a draft for human review. Nothing is sent or filed.

    Args:
        kind: Type of document, for example kyc_checklist, soap_note, report, sql, narrative.
        title: Title of the draft.
        body: Full text of the draft.
    """
    return ok(draft_id=effect("draft", {"kind": kind, "title": title, "body": body}))


def escalate_to_human(reason: str, summary: str) -> dict:
    """Hand the conversation to a human and stop. Use for complaints, disputes, hardship, abuse or emergencies.

    Args:
        reason: Why a human is needed.
        summary: Two-line summary so the human does not have to read the whole conversation.
    """
    return ok(handover_id=effect("handover", {"reason": reason, "summary": summary}), note="A human will take over. Tell the user this politely.")


PRECHECKS = {"send_message": _check_message}
