---
name: dq-add-agent
description: Adds a new agent to the DOS catalog. Use when the user asks to create, add or define a new agent, or to change an existing agent's tools, approvals, skills or instructions.
---
# Add an agent to the catalog

An agent is one YAML entry plus, optionally, one run-time skill. Do not write agent-specific Python.

## Steps
1. Read `server/dq/spec.py` to see the required fields and validation rules.
2. Choose tools from `server/dq/tools/` only. Run `python -c "from dq.tools import REGISTRY; print(sorted(REGISTRY))"` in `server/` to list them.
   If a needed tool does not exist, stop and use the `dq-add-tool` skill first.
3. Add the entry to the right file in `server/catalog/`. Follow the style of the existing entries:
   - `instruction`: 5 to 8 lines. Say what to do, what the output looks like, and what never to do.
   - `approvals`: every tool that changes something outside the platform.
   - `autonomy`: `suggest`, `approve` or `auto`. Choose the lowest that still solves the problem.
   - `evals`: at least one case with `expect_tool` and a one-sentence `expect`.
   - `demo.ask`: a realistic request that works with the demo data.
4. If the agent needs domain rules (policy, tone, steps), write them as a run-time skill in `server/skills/<skill-name>/SKILL.md`
   and list the skill under `skills`. The folder name must equal the `name` in the frontmatter.
5. Run `make test`. The catalog test fails if a tool or skill name is wrong.
6. Start the server in simulation mode, activate and deploy the agent in the console, and run its demo request.

7. Open the agent in the console, tab Blueprint. Check the tools, the data it reads, the client rules it obeys and
   the risk tier are what you intended. A High tier needs a risk acceptance by the Owner before deployment.

## Checklist before you finish
- [ ] No client-specific number (limit, hour, percentage) is typed in the instruction or the skill. Refer to "your client rules".
- [ ] Every money-moving tool is in `approvals` (the governance gate and the Agent Builder both refuse otherwise).
- [ ] No tool that acts on the outside world is missing from `approvals`.
- [ ] The instruction contains at least one "never" rule.
- [ ] `make test` passes.
