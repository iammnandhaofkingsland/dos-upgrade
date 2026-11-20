"""Request and run context carried in contextvars.

Why contextvars: the five layers must all know WHICH CLIENT and WHICH RUN they are serving, without every
function taking five extra parameters. A context variable set once per request (or per run) is visible to
everything called underneath it, including background tasks and tools that the ADK runs in worker threads."""
from __future__ import annotations

import contextvars
from typing import Any

client_var: contextvars.ContextVar[str] = contextvars.ContextVar("dq_client", default="demo")
role_var: contextvars.ContextVar[str] = contextvars.ContextVar("dq_role", default="owner")
actor_var: contextvars.ContextVar[str] = contextvars.ContextVar("dq_actor", default="console-user")
# Set by the run manager for the duration of one agent run: {"run_id", "agent_id", "tool"}
run_var: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("dq_run", default=None)


def current_client() -> str:
    return client_var.get()


def current_role() -> str:
    return role_var.get()


def current_actor() -> str:
    return actor_var.get()


def current_run() -> dict[str, Any] | None:
    return run_var.get()

# The signed-in user: {"username", "name", "role", "technician_id"} or None when the request is not signed in.
user_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar("dq_user", default=None)


def current_user() -> dict | None:
    return user_var.get()
