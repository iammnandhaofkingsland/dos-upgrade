---
name: loan-eligibility
description: Rules for explaining a loan eligibility result to an applicant in plain language. Use when an applicant asks whether they qualify or why they were declined.
---
# Loan eligibility explanation

1. Collect four numbers before calling the tool: net monthly income, existing EMIs, credit score, amount wanted.
   If one is missing, ask for it. Do not estimate.
2. Call check_loan_eligibility. The tool applies the lender's rules. You never override it.
3. Explain the result:
   - Eligible: say "you meet our basic checks", give the proposed EMI and the amount they would receive after
     upfront interest. Add: "Final approval needs document verification."
   - Not eligible: give the single most important reason in simple words and one thing that would help
     (a smaller amount, a longer period, a co-applicant).
4. Never say "approved" or "guaranteed". Never comment on the applicant's financial habits.
5. Do not ask for or store full ID numbers in chat.
