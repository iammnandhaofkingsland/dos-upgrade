"""Exposes the loanprocess agent to the ADK tools (adk web, adk run, adk eval, agents-cli).
The agent itself is still built from the catalog spec, so there is one source of truth."""
from dq.factory import build_agent
from dq.spec import load_catalog

root_agent = build_agent(load_catalog()["loanprocess"])
