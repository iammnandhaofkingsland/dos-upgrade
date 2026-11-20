"""Tool registry: tool name in a spec -> Python function. One dictionary is the whole plug-in system.
Adding a tool = write a function in one of the modules; it is registered automatically.

RAW holds the functions as written (used for lineage scanning). REGISTRY holds the same functions wrapped
by _guard, which turns a data-layer refusal (DataError) into a normal tool error the model can read.
PRECHECKS holds the limit checks that must run BEFORE a human is asked to approve an action."""
import functools
import inspect

from . import commerce, common, fintech, manufacturing, services, wholesale

RAW: dict = {}
PRECHECKS: dict = {}
for _mod in (common, fintech, commerce, services, manufacturing, wholesale):
    for _name, _fn in inspect.getmembers(_mod, inspect.isfunction):
        if _fn.__module__ == _mod.__name__ and not _name.startswith("_") and _name not in ("ok", "err", "effect", "spare_order_value"):
            RAW[_name] = _fn
    PRECHECKS.update(getattr(_mod, "PRECHECKS", {}))


def _guard(fn):
    from ..data import DataError  # noqa: PLC0415

    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DataError as exc:
            return common.err(str(exc))

    return inner


REGISTRY = {name: _guard(fn) for name, fn in RAW.items()}


def get_tool(name: str):
    if name not in REGISTRY:
        raise KeyError(f"Unknown tool {name!r}. Known tools: {sorted(REGISTRY)}")
    return REGISTRY[name]
