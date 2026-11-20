---
name: returns-policy
description: The store's return and refund rules and the wording to use with customers. Use for any return, exchange or refund request.
---
# Returns and refunds

1. Always call check_return_eligibility. The tool is the source of truth for the window and the amount.
2. Eligible: confirm in one sentence, explain pickup (within 2 working days) and refund time (5 working days
   after pickup). Prepare the refund with issue_refund.
3. Not eligible: say which rule applied, kindly. Offer an exchange or store credit if the item is unused.
4. Damaged or wrong item: apologise once, ask for a photo, and escalate to a human. Do not decide yourself.
5. Refunds above the instant-refund limit wait for approval. Tell the customer it is "with our team for a
   quick approval". Never say it is refunded until the tool result says so.
