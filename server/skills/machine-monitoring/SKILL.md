---
name: machine-monitoring
description: How to read a machine alarm and alert maintenance. Use whenever a machine's vibration, temperature, current, cycle time or pressure is in warning or alarm.
---
# Machine monitoring playbook

## Read the alarm
1. Get the machine status. Note every signal in alarm or warning.
2. For each one, get the trend over the last two minutes. A **slow drift** (steady rise) usually means wear
   (bearing, tool, filter). A **sudden jump** usually means an event (crash, blockage, broken part).
3. Compare with normal and the alarm limit. Say both numbers. Never round a reading into a different meaning.

## Alert
- One WhatsApp message to the maintenance on-call group, three lines: machine and signal; reading against limit and
  trend; the first check from the manual.
- Do not alert customers, suppliers or anyone outside maintenance.

## Never
- Never stop, start or change a machine. If stopping looks wise, say: "the shift supervisor should decide whether
  to stop the machine."
- Never guess the cause. RootCauseIQ does the diagnosis.
