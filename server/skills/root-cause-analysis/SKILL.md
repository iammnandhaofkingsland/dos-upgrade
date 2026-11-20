---
name: root-cause-analysis
description: How to find and present the likely root cause of a machine fault with evidence. Use after a machine alarm or when a technician asks why a machine is behaving abnormally.
---
# Root-cause analysis playbook

## Method
1. Rank causes with rank_root_causes. It compares the signal pattern with known failure signatures and weights each
   cause by the repair history.
2. Check the repair history for the same machine type and symptom. Quote case ids.
3. Check the manual for the alarm. Quote the first recommended check.

## Presenting
- Lead with: likely cause, confidence (percent), the two strongest pieces of evidence, how many past cases agree.
- Then: proven fix, spare part id, skill needed, typical repair minutes.
- If the second cause is within 15 points of the first, name both and say what check tells them apart.
- If confidence is below the client's threshold: "Cause uncertain. A senior technician should inspect before a part is fitted."

## Never
- Never present a likely cause as certain. Technicians confirm causes; their confirmation teaches DOS.
