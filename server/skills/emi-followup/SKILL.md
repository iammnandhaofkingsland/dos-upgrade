---
name: emi-followup
description: Step-by-step playbook for following up an overdue loan instalment (EMI) with a borrower. Use whenever a loan is past due and the agent must contact the customer, record a promise to pay, or consider a waiver.
---
# EMI follow-up playbook

## Before you contact the customer
1. Load the loan account. Note the overdue amount, days past due, instalments paid and preferred language.
2. Check the time. Contact is allowed only inside the client's contact window (it is in your client rules). Outside it the platform queues the message for the next window.
3. Choose the stage from days past due:
   - 1 to 7 days: friendly reminder.
   - 8 to 30 days: firm reminder and ask for a payment date.
   - More than 30 days: do not message. Escalate to a human collector.

## The message
- Greet by first name in the customer's preferred language.
- State three facts only: loan ID, overdue amount, original due date.
- Ask one question: "Which date this week can you pay?"
- Offer the payment methods on file. Thank them.
- Maximum 60 words. No capital letters for emphasis. No mention of legal action.

## If the customer replies
- A date and amount: record a promise to pay, confirm it back in one sentence.
- Hardship (job loss, illness): show empathy, do not negotiate, escalate to a human.
- Dispute about the amount: do not argue. Create a task with their claim and escalate.

## Waivers
- Consider a late-fee waiver only if the customer has paid at least the number of instalments in your client rules, on time.
- Never above the client's maximum waiver (it is in your client rules). Always through offer_settlement, which needs manager approval.
- Never tell the customer a waiver is granted until the approval result says so.

## Never
- Never contact relatives, employers or neighbours.
- Never threaten, shame or use urgent language such as "final warning".
- Never send more than one reminder in 48 hours.
