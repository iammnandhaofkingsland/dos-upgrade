# Rules for AI coding agents working in this repository

You are helping build DOS (DigiQuench OS), the AI agent platform. Read this file before changing anything.

## Running tasks

Run every task through the task runner from the repository root: `python dos.py setup | test | check <stage> | faults | run | run-live | seed | doctor`.
Never call pytest, uvicorn or adk directly: `dos.py` sets PYTHONPATH and UTF-8 (needed on Windows) and uses the private `.venv`.
A task is done only when `python dos.py test` passes and the step's `python dos.py check <stage>` prints only PASS lines.

## What this project is
One framework of five layers. Every agent, for every client, can act only through all five.
1. EXPERIENCE  the DOS app: `server/console/index.html`, `css/dos.css`, `js/*.js` (one file per page), served at /; `server/dq/app_api.py` and `server/dq/api.py` (the only ways in). The old console stays at `console/classic.html`.
2. CLIENT CONFIGURATION  `server/dq/clients.py` (settings schema, `policy()`, versions) and `server/clients/*.yaml`.
3. DATA  `server/dq/data.py` (registry, `ds()`, upload, lineage), `server/dq/sample_data.py`, `server/dq/store.py`.
4. AI AGENTS  `server/catalog/*.yaml` (55 specs: an agent is data), `server/skills/<name>/SKILL.md`,
   `server/dq/tools/`, `server/dq/factory.py`, `server/dq/runs.py`, `server/dq/evalgate.py`.
5. SAFETY, SECURITY, GOVERNANCE  `server/dq/plugins.py` (around every model and tool call) and
   `server/dq/governance.py` (roles, risk, deployment gate, emergency stop, incidents, self-test, evidence).
`server/dq/context.py` carries the current client, role, user and run in context variables.
Sign-in: `server/dq/auth.py` (users, hashes, signed tokens). Live plant: `server/dq/plant.py` (simulator, incidents,
overlays), `server/dq/response.py` (six-agent downtime chain, escalation, work-order states), `server/dq/tools/manufacturing.py`.

## Hard rules
1. Run `make test` before you say a task is done. All tests must pass with no network.
2. Never put a secret in code, YAML, tests or commit messages. Secrets come from environment variables.
3. Never weaken a guardrail, a limit or a test to make something pass. Fix the cause.
4. A tool reads data ONLY through `ds("name")` with a string literal. Never import `sample_data` in a tool.
5. A tool or guardrail reads a client rule ONLY through `policy("group.key")` with a string literal.
   Never type a client-specific number (a limit, an hour, a percentage) in a tool, a spec or a skill.
6. A new setting is one `P(...)` entry in `POLICIES` with bounds and an `enforced` string, added in the same
   change as the code that reads it. Platform rules are `locked=True`.
7. No tool takes a client, tenant or user id as a parameter. Those come from context.
8. Any tool that sends, pays, refunds, orders, changes a price or writes a record must record the action with
   `effect()`. If it moves money it must be listed under `approvals` in every spec that uses it, and its limit
   checks must be a `_check_<name>` function registered in that module's `PRECHECKS`.
9. Tool functions return `ok(...)` or `err("...")` and never raise for expected failures. Refusals start with "Refused:".
10. Every API route that changes state takes `actor: str = Depends(need("<permission>"))` and calls `audit(...)`.
11. A new control is finished only when it writes a trace step when it fires, has a row in `governance.CONTROLS`
    and has a probe in `governance.selftest()`.
12. Do not rename fields in `AgentSpec` or API responses without updating the console and the tests in the same change.
13. Model IDs live only in `server/dq/config.py`. Do not hard-code a model name anywhere else.
14. Use the current Google Gen AI SDK (`from google import genai`) and ADK 2.x imports (`from google.adk import Agent`).
    Check the installed version before using an API you are not sure exists.
15. The console holds no business rules. It draws what the API returns and escapes everything with `esc()`.
16. Keep answers and comments in plain English. No marketing language in code or docs.

## How to work
- Plan first for anything that touches more than two files. Say which LAYER each file belongs to and list the tests you will add.
- Small commits with a clear message: what changed and why.
- When you add an agent or a tool, use the skills in `.agents/skills/`.
- If a Google API behaves differently from what you expect, read the official docs with the Google Developer Knowledge skill or MCP server before guessing.

## The DOS app (added at the buildathon)
- Sign-in is by company + six-digit login code (`dq/access.py`). Never show personal names; show role names and job titles.
- Only the Business Owner (`owner`) and Operations Manager (`operator`) see the five-layer pages; `/api/app/layers` refuses others.
- Agents are launched through `dq/launcher.py`, which calls the same gates as the Agents screen. Never skip a gate in the launcher.
- Every page is one file in `server/console/js/`, registered as `DOS.pages.<name>`; the menu per role is `DOS.NAV` in `core.js`.
- Simulated output is always labelled (Simulation chip, "Simulated model" steps). Never present it as Gemini output.
