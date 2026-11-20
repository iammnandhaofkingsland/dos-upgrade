---
name: kyc-checklist
description: Checklist for verifying Know Your Customer documents for an individual applicant in India. Use when extracting, validating or summarising KYC documents.
---
# KYC checklist (individual)

Produce this table for every applicant. Status is PASS, FAIL or MISSING.

| Item | How to check |
|---|---|
| PAN present | A PAN document was extracted |
| PAN format | verify_id_format with id_type pan |
| Identity proof present | Aadhaar (masked) or passport or voter ID extracted |
| Name match | Names on PAN and identity proof match. Initial-versus-full-name differences are FAIL with note "needs declaration" |
| Date of birth match | Same date on both documents |
| Address proof present | A separate address document, not older than 3 months if a utility bill |

Rules
- Show only the last four characters of any ID number.
- A single FAIL or MISSING means overall status "Incomplete". List what the applicant must provide.
- Save the checklist with save_draft (kind kyc_checklist). A compliance officer gives the final status.
