---
name: dq-add-tool
description: Adds or changes a tool function that DOS agents can call. Use when an agent needs a capability that is not in the tool registry, or when connecting a tool to a real external system.
---
# Add a tool

## Conventions
- One plain Python function in the matching module under `server/dq/tools/`. It is registered automatically by name.
- Type-hint every parameter. Write a docstring: first line says what the tool does, then an `Args:` section.
  The model reads this text, so be exact about formats and units.
- No client, tenant or user id parameter. Those come from context.
- Read data only with `ds("name")` (string literal). If the dataset is new, declare it first in `DATASETS`
  in `server/dq/data.py` with a classification, an owner and its personal fields, and add the sample to `sample_data.py`.
- Read every client-specific limit with `policy("group.key")` (string literal). If the setting is new, add one
  `P(...)` entry to `POLICIES` in `server/dq/clients.py` with bounds and an `enforced` string naming this tool.
- Return `ok(...)` or `err("message")` from `common.py`. Never raise for an expected failure. Refusals start with "Refused:".
- Anything that changes the outside world must call `effect(kind, payload)` so it appears under "Actions taken".
- If the tool moves money or has a hard limit: put the checks in `_check_<name>(**args)` returning `err(...)` or `None`,
  call it first inside the tool, and register it in the module's `PRECHECKS` so it runs before a human is asked to approve.
- Never return secrets or full ID numbers. Return only the fields the task needs.

## Steps
1. Write the function (and `_check_` function) and its docstring.
2. Add a unit test in `server/tests/` for the happy path and for each limit, under two different clients.
3. If the tool moves money, add it to `approvals` in every spec that uses it and to `MONEY_TOOLS` in `governance.py`.
   If it acts outside the business in another way, add it to `EXTERNAL_TOOLS`.
4. Add a probe for the limit to `governance.selftest()`.
5. Run `make test`. Open an agent that uses the tool, tab Blueprint, and check the tool shows the right data and client rules.

## Connecting a real system later
Keep the signature. Replace the `ds()` source and the body of `effect()` for this kind with the API call.
Read credentials from environment variables that Cloud Run fills from Secret Manager, per client.
Add a timeout, an idempotency key and return `err(...)` on failure.
