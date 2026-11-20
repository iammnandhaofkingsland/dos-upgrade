---
name: maintenance-dispatch
description: How to assign a breakdown to a technician and escalate. Use when a diagnosed machine fault needs a technician.
---
# Maintenance dispatch playbook

1. Find a free technician on the current shift with the skill the diagnosis needs. Prefer senior technicians for
   criticality A machines.
2. Create the work order with: machine, short title, the diagnosis in plain words (cause, evidence, proven fix),
   priority (critical for criticality A machines in alarm, otherwise high), technician, spare part.
3. The technician must acknowledge within the client's time limit. DOS escalates to the maintenance supervisor
   automatically if not.
4. If nobody with the skill is free, create the work order unassigned and escalate to the supervisor now.

Never assign a technician who is off shift. Repairs need lock-out tag-out by the assigned technician.
