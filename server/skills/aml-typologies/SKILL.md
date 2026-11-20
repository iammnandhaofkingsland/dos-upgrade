---
name: aml-typologies
description: Reference list of common money-laundering and fraud patterns with the evidence that supports each. Use when triaging a fraud alert or writing an AML investigation narrative.
---
# Typologies and the evidence to look for

| Pattern | What it looks like | Evidence to cite |
|---|---|---|
| Structuring | Several deposits just under the reporting threshold | Count, amounts, dates, threshold |
| Rapid movement | Money in and out within hours with no business reason | Timestamps, counterparties |
| Account takeover | New device, new city, unusual hour, amount far above normal | Device flag, city versus home city, hour, multiple of average spend |
| Round-tripping | Funds return to the origin through other accounts | The chain of transfers |

Decision guide for fraud triage
- CLEAR: zero or one weak signal.
- REVIEW: one strong signal or two weak ones. Create a task.
- HOLD: two or more strong, independent signals. Request a hold (needs approval).

Writing rules
- Facts first, opinion last, each fact traceable to a tool result.
- Never state that a customer committed a crime. Write "activity consistent with".
- Never draft any message that would tell the customer they are under review.
