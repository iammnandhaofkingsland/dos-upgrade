# DOS: DigiQuench OS

The AI agent platform that runs your operations.

One tight framework of five layers for running AI agents in a business. Built on Google ADK 2.x and Gemini, deployed on Cloud Run.

| Layer | What it does | Code |
|---|---|---|
| 1 Experience | The DOS app: sign-in with login codes, role-based pages, Agent Studio, live runs, approvals, plant floor, Ask DOS | `server/console/` (index.html, css/, js/), `server/dq/app_api.py`, `server/dq/api.py` |
| 2 Client configuration | Each client's rules as bounded, versioned settings | `server/dq/clients.py`, `server/clients/` |
| 3 Data | One gate between agents and data: classify, isolate, log | `server/dq/data.py`, `server/dq/store.py` |
| 4 AI agents | 55 agents across 8 industries as data; factory, runs, approvals, evaluation gate | `server/catalog/`, `server/skills/`, `server/dq/tools/`, `factory.py`, `runs.py` |
| 5 Safety, security, governance | Limits before approval, roles, risk gate, emergency stop, audit chain, self-test, evidence | `server/dq/plugins.py`, `server/dq/governance.py` |

## Run it in two minutes (no key, no cost)
```
make setup
make test      # 42 offline tests (33 platform + 9 for the DOS app)
make check STEP=all   # 31 plain-English PASS/FAIL checks (platform stages, then access, launcher, app, console)
make run       # http://localhost:8080 in simulation mode
make seed      # in a second terminal: a day of activity for five clients, including the plant
```
Open http://localhost:8080 and sign in: pick a company, pick a role, enter the six-digit login code (in demo mode each
role card shows its code; Business Owner 260101, Operations Manager 260201, Approver 260301, Technician 260401, Auditor 260501).
People are shown by role and job title only. As the Business Owner of DOS Sandbox: Agent Studio, Prepare all agents, then
Run every agent (55 agents, 8 domains). Approvers decide what waits; only the Business Owner and Operations Manager see the
five-layer pages. On Kaveri Precision Components, Plant floor, Simulate a fault, and watch six agents respond.
The old console is kept at /assets/classic.html.
Simulation mode uses a scripted offline model. Client rules, the data gate, tool calls, limit checks, approvals,
guardrails, both deployment gates and traces are the real platform code. The model text is scripted.
The console labels every simulated run.

## Run it with Gemini
```
cp server/.env.example server/.env    # paste your Google AI Studio key
make run-live
```

## Deploy to Google Cloud
```
PROJECT_ID=<your-project> bash infra/bootstrap.sh   # once
PROJECT_ID=<your-project> bash infra/deploy.sh
```

## What was and was not tested
- Tested offline with google-adk 2.14.0: catalog validation; all 38 agents build and deploy in simulation;
  bounded, locked and versioned client settings; a rule change that changes agent behaviour; contact-hours queueing;
  per-client refund thresholds; client isolation; the data gate, upload validation and lineage; a trace with steps
  from every layer; roles; risk acceptance for High-risk agents; the four-eyes rule; the emergency stop; the
  untrusted-text screen; the safety self-test for all five clients; the audit hash chain; the evidence pack;
  and `adk eval` on LoanProcess. Added for DOS: sign-in and signed sessions (a forged token is refused); every simulated fault on
  every machine type it applies to (22 combinations, 10 random seeds each: 220 runs) detected in 16 to 34 s and diagnosed
  correctly in 220 of 220 (`make faults`); the six-agent downtime chain;
  escalation when a technician does not acknowledge; spare-order limits from client settings; designated approvers;
  the technician closing a work order and the repair joining the history.
- Not executed by the author: live Gemini calls (including the requirements-to-settings draft and the Agent Builder
  with a real model), Firestore, Cloud Trace export, image generation, and the Cloud Run scripts.
  They follow the public documentation as of 11 November 2026. Run the smoke tests in the guide the first time you use each.
- Sign-in: per-company users, salted PBKDF2 password hashes, HMAC-signed session tokens; the role comes only from the token.
  Production path: Identity Platform. Live plant: a simulator stands in for the machine gateway (OPC UA / MQTT).
- Demo-grade on purpose: the injection screen is pattern-based, sessions are
  in memory, outbound actions are recorded and not sent. The guide lists the Google Cloud service that replaces each.

## Layout
See `AGENTS.md`.
