"""Healthcare, marketing and data tools."""
import os
import re

from .. import config
from ..clients import policy
from ..data import PERSONAL_SQL_COLUMNS, ds
from .common import effect, err, ok

# ---------------- healthcare (administration only: no tool gives clinical advice) ----------------


def find_slots(doctor: str = "", day: str = "") -> dict:
    """Find free appointment slots, optionally for one doctor or one day.

    Args:
        doctor: Doctor's name, or empty for any doctor.
        day: Day of the week, or empty for any day.
    """
    out = [{"doctor": doc, "day": d, "time": t} for doc, days in ds("slots").items() if not doctor or doctor.lower() in doc.lower()
           for d, times in days.items() if not day or day.lower() == d.lower() for t in times]
    return ok(slots=out) if out else ok(slots=[], note="No free slots match. Offer other days.")


def book_appointment(patient_id: str, doctor: str, slot: str) -> dict:
    """Book an appointment slot for a patient.

    Args:
        patient_id: Patient identifier, or 'new' for a new patient.
        doctor: Doctor's name.
        slot: Day and time, for example 'Friday 10:30'.
    """
    return ok(booking_id=effect("appointment", {"patient_id": patient_id, "doctor": doctor, "slot": slot, "action": "book"}))


def reschedule_appointment(patient_id: str, new_slot: str) -> dict:
    """Move a patient's existing appointment to a new slot and release the old one to the waiting list.

    Args:
        patient_id: Patient identifier.
        new_slot: New day and time.
    """
    p = ds("patients").get(patient_id.upper())
    if not p or "next_appointment" not in p:
        return err(f"No existing appointment for {patient_id}")
    return ok(booking_id=effect("appointment", {"patient_id": patient_id.upper(), "old": p["next_appointment"], "slot": new_slot, "action": "reschedule"}),
              released_slot=p["next_appointment"])


def get_patient_summary(patient_id: str) -> dict:
    """Get a patient's administrative summary: name, age, last or next visit and recorded allergies.

    Args:
        patient_id: Patient identifier such as PT-5001.
    """
    p = ds("patients").get(patient_id.upper())
    return ok(patient_id=patient_id.upper(), **p) if p else err(f"No patient {patient_id}")


def check_claim(claim_id: str) -> dict:
    """Run the payer checklist on an insurance claim and list the problems found.

    Args:
        claim_id: Claim identifier such as CLM-6001.
    """
    c = ds("claims").get(claim_id.upper())
    if not c:
        return err(f"No claim {claim_id}")
    problems = []
    if c["planned"] and not c["pre_auth_number"]:
        problems.append("Pre-authorisation number missing for a planned procedure")
    if "Investigation reports" not in c["documents"]:
        problems.append("Investigation reports not attached")
    return ok(claim_id=claim_id.upper(), procedure=c["procedure"], amount=c["amount"], problems=problems, ready=not problems)


def get_lab_result(order_id: str) -> dict:
    """Get a lab result with the reference range printed on the report.

    Args:
        order_id: Lab order identifier such as LAB-8001.
    """
    r = ds("labs").get(order_id.upper())
    if not r:
        return err(f"No lab order {order_id}")
    lo, hi = (float(x) for x in r["reference_range"].split(" - "))
    return ok(order_id=order_id.upper(), **r, outside_reference_range=not lo <= r["value"] <= hi)


# ---------------- marketing ----------------


def get_brand_voice() -> dict:
    """Get the brand voice rules: tone, words to avoid, emoji rule and sign-off."""
    return ok(**ds("brand_voice"))


def keyword_ideas(topic: str) -> dict:
    """Get keyword ideas for a topic with search intent. Volumes are estimates.

    Args:
        topic: Topic or product to research.
    """
    base = topic.lower().split()[:3]
    ideas = [{"keyword": " ".join(base), "intent": "buy", "est_volume": 5400}, {"keyword": " ".join(base) + " online", "intent": "buy", "est_volume": 2900},
             {"keyword": "how to style " + base[-1], "intent": "learn", "est_volume": 1300}, {"keyword": "best " + " ".join(base[-2:]), "intent": "compare", "est_volume": 880}]
    return ok(topic=topic, ideas=ideas, hashtags=["#" + "".join(w.capitalize() for w in base[:2]), "#" + base[-1].capitalize()], note="Volumes are estimates")


def generate_image(prompt: str) -> dict:
    """Generate a marketing image from a prompt using Google's image model. Returns a reference to the image.

    Args:
        prompt: Concrete description of the image: subject, setting, light, style. Say 'no text' unless text is needed.
    """
    if config.MODEL_MODE == "live" and (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        try:  # real call: Nano Banana returns the image as inline bytes in the response parts
            from google import genai  # noqa: PLC0415

            resp = genai.Client().models.generate_content(model=config.IMAGE_MODEL, contents=prompt)
            for part in resp.candidates[0].content.parts:
                if part.inline_data:
                    return ok(image_id=effect("image", {"prompt": prompt, "mime": part.inline_data.mime_type, "bytes": len(part.inline_data.data)}), model=config.IMAGE_MODEL)
        except Exception as exc:  # the demo must not die because an image failed
            return ok(image_id=effect("image", {"prompt": prompt, "placeholder": True}), note=f"Image model unavailable ({type(exc).__name__}); placeholder stored")
    return ok(image_id=effect("image", {"prompt": prompt, "placeholder": True}), note="Simulation mode: placeholder image stored")


def schedule_post(channel: str, text: str, when: str) -> dict:
    """Schedule a social media post. Requires human approval.

    Args:
        channel: instagram, linkedin, facebook or x.
        text: The post text.
        when: When to publish.
    """
    limits = {"instagram": 2200, "linkedin": 3000, "facebook": 2000, "x": 280}
    if channel.lower() not in limits:
        return err("Unknown channel")
    if len(text) > limits[channel.lower()]:
        return err(f"Text is over the {limits[channel.lower()]} character limit for {channel}")
    bad = [w for w in policy("marketing.banned_words") if w.lower() in text.lower()]
    if bad:
        return err(f"Refused: the post uses words this client does not allow ({', '.join(bad)}). Rewrite without them.")
    return ok(post_id=effect("social_post", {"channel": channel.lower(), "text": text, "when": when}))


def campaign_metrics(campaign_id: str = "CMP-01") -> dict:
    """Get campaign results for this week and last week, the best creative and the best posting times.

    Args:
        campaign_id: Campaign identifier.
    """
    c = ds("campaigns").get(campaign_id.upper())
    if not c:
        return err(f"No campaign {campaign_id}")
    return ok(campaign_id=campaign_id.upper(), **c, cost_per_order=round(c["spend_inr"] / c["orders"], 1),
              last_week_cost_per_order=round(c["last_week"]["spend_inr"] / c["last_week"]["orders"], 1))


def audience_segments() -> dict:
    """List customer segments with size, past response rate and opt-out status."""
    return ok(segments=ds("segments"))


def get_lead(lead_id: str) -> dict:
    """Get a sales lead: name, company, enquiry text and consent status.

    Args:
        lead_id: Lead identifier such as LEAD-01.
    """
    lead = ds("leads").get(lead_id.upper())
    return ok(lead_id=lead_id.upper(), **lead) if lead else err(f"No lead {lead_id}")


# ---------------- data ----------------
PII_COLUMNS = {"name", "phone", "email"}


def list_tables() -> dict:
    """List the tables available for analysis."""
    return ok(tables=[r[0] for r in ds("warehouse").execute("SELECT name FROM sqlite_master WHERE type='table'")])


def describe_table(table: str) -> dict:
    """Describe a table: column names, types and row count.

    Args:
        table: Table name.
    """
    if not re.fullmatch(r"[A-Za-z_]+", table):
        return err("Invalid table name")
    cols = ds("warehouse").execute(f"PRAGMA table_info({table})").fetchall()
    if not cols:
        return err(f"No table {table}")
    return ok(table=table, columns=[{"name": c[1], "type": c[2], "personal_data": c[1] in PII_COLUMNS} for c in cols],
              rows=ds("warehouse").execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def run_sql(query: str) -> dict:
    """Run a read-only SQL query on the analytics database (SQLite dialect). SELECT only. A row limit is enforced.

    Args:
        query: One SELECT statement.
    """
    q = query.strip().rstrip(";")
    if not re.match(r"(?is)^\s*select\b", q) or re.search(r"(?i)\b(insert|update|delete|drop|alter|create|attach|pragma)\b", q) or ";" in q:
        return err("Refused: only a single SELECT statement is allowed")
    if policy("data.block_personal_columns") and re.search(r"(?i)\b(" + "|".join(PERSONAL_SQL_COLUMNS) + r")\b", q):
        return err("Refused: personal data columns (phone, email) cannot be queried by this agent")
    if policy("data.block_personal_columns") and re.search(r"(?is)select\s+\*.*\bcustomers\b", q):
        return err("Refused: SELECT * on the customers table would return personal columns. Name the columns you need.")
    limit = policy("data.sql_row_limit")
    m = re.search(r"(?i)\blimit\s+(\d+)", q)
    if not m:
        q += f" LIMIT {limit}"
    elif int(m.group(1)) > limit:
        q = re.sub(r"(?i)\blimit\s+\d+", f"LIMIT {limit}", q)
    try:
        cur = ds("warehouse").execute(q)
        return ok(columns=[c[0] for c in cur.description], rows=[list(r) for r in cur.fetchmany(limit)], sql=q)
    except Exception as exc:
        return err(f"SQL error: {exc}")


def profile_dataset(table: str) -> dict:
    """Profile a table: row count, blanks per column and duplicate keys.

    Args:
        table: Table name.
    """
    d = describe_table(table)
    if d["status"] != "success":
        return d
    blanks = {c["name"]: ds("warehouse").execute(f"SELECT COUNT(*) FROM {table} WHERE {c['name']} IS NULL OR {c['name']}=''").fetchone()[0] for c in d["columns"]}
    dup = ds("warehouse").execute("SELECT COUNT(*) FROM (SELECT phone FROM customers GROUP BY phone HAVING COUNT(*)>1)").fetchone()[0] if table == "customers" else 0
    bad = ds("warehouse").execute("SELECT COUNT(*) FROM new_orders WHERE CAST(amt AS REAL)=0 OR dt NOT LIKE '____-__-__'").fetchone()[0] if table == "new_orders" else 0
    return ok(table=table, rows=d["rows"], blanks={k: v for k, v in blanks.items() if v}, duplicate_phone_groups=dup, rows_failing_type_checks=bad)


def apply_cleaning_rule(table: str, rule: str, rows_affected: int) -> dict:
    """Apply a cleaning or enrichment rule to a table. Requires human approval. Rows are marked, never deleted.

    Args:
        table: Table name.
        rule: The rule in plain words, for example 'fill city from pincode'.
        rows_affected: How many rows the rule will change.
    """
    return ok(rule_id=effect("cleaning_rule", {"table": table, "rule": rule, "rows_affected": rows_affected}))


def lookup_reference(pincode: str) -> dict:
    """Look up city and state for an Indian PIN code from reference data.

    Args:
        pincode: Six-digit PIN code.
    """
    r = ds("pincodes").get(pincode.strip())
    return ok(pincode=pincode, **r) if r else ok(pincode=pincode, matched=False, note="Not in reference data. Do not guess.")


def catalog_lookup(term: str) -> dict:
    """Look up a business term in the data catalog: definition and owner.

    Args:
        term: Business term, for example revenue.
    """
    hit = ds("data_catalog").get(term.lower())
    return ok(term=term, definition=hit) if hit else ok(term=term, definition=None, note="No definition recorded")


def tag_column(table: str, column: str, tag: str, reason: str) -> dict:
    """Set a sensitivity tag on a column. Requires human approval.

    Args:
        table: Table name.
        column: Column name.
        tag: One of public, internal, personal, sensitive.
        reason: Why this tag applies.
    """
    if tag not in ("public", "internal", "personal", "sensitive"):
        return err("tag must be public, internal, personal or sensitive")
    return ok(tag_id=effect("column_tag", {"table": table, "column": column, "tag": tag, "reason": reason}))
