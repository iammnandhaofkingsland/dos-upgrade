"""Trace writer and masking helpers used by every layer.

A STEP is one line of a run's trace. Each step is tagged with the LAYER that produced it, so the console can
show, for any run, which client rule was read (layer 2), which data was touched (layer 3), what the agent
did (layer 4) and which control fired (layer 5). Layer 1, the console, is where you read it."""
from __future__ import annotations

import re
from typing import Any

from .store import get_store, new_id, now

LAYER = {"config": 2, "data": 3, "model": 4, "tool": 4, "skill": 4, "guardrail": 5, "approval": 5, "governance": 5}

# Identity numbers: always masked, in what the model sees and in everything stored.
PII_PATTERNS = [
    (re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"), "[AADHAAR-MASKED]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN-MASKED]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD-MASKED]"),
]
# Contact details: the agent needs them to do its job, but traces and logs do not. Masked in stored previews.
CONTACT_PATTERNS = [
    (re.compile(r"\+91[- ]?\d{5}[- ]?\d(\d{4})\b"), r"+91-*****-*\1"),
    (re.compile(r"\b[\w.+-]+@([\w-]+\.[\w.]+)\b"), r"***@\1"),
]


def mask_pii(text: str) -> tuple[str, int]:
    hits = 0
    for pattern, label in PII_PATTERNS:
        text, n = pattern.subn(label, text)
        hits += n
    return text, hits


def mask_contacts(text: str) -> str:
    for pattern, repl in CONTACT_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def preview(value: Any, limit: int = 600) -> str:
    """Text that is safe to store in a trace: identity numbers and contact details masked, length capped."""
    return mask_contacts(mask_pii(str(value))[0])[:limit]


def write_step(run_id: str, kind: str, name: str, **fields) -> None:
    store = get_store()
    seq = len(store.list("steps", where={"run_id": run_id}, limit=2000)) + 1
    store.put("steps", new_id("stp"), {"run_id": run_id, "seq": seq, "kind": kind, "layer": LAYER.get(kind, 4), "name": name,
                                       "created_at": now(), **fields})
