"""GOLD-LAYER DATA VIEW (layer 3, for the Business Owner and the Operations Manager).

Shows, for any agent, the exact data its tools read through the data gate, laid out as a medallion pipeline:

    Bronze  the raw source as it arrives (connector, sample file or upload)       -> row count, where it comes from
    Silver  typed, validated and de-duplicated                                    -> rows kept, rows rejected, completeness
    Gold    the agent-ready table the tools read through ds()                     -> the rows themselves, PII masked

Personal values are masked for every role in this view (dq/privacy.py). The view reads the data the same way the
gate does but is not an agent read, so it is not written to the agent's data-access log; it is written to the
audit log instead, because looking at Restricted data is itself an event a regulator may ask about."""
from __future__ import annotations

from typing import Any

from . import data, privacy
from .data import DATASETS, SENSITIVITY
from .sample_data import DB
from .store import get_store

MAX_ROWS = 12


def _flatten(row: dict, prefix: str = "", depth: int = 0) -> dict:
    out: dict[str, Any] = {}
    for k, v in row.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and depth < 1:
            out.update(_flatten(v, key + ".", depth + 1))
        elif isinstance(v, dict):
            out[key] = f"{len(v)} fields"
        elif isinstance(v, list):
            out[key] = ", ".join(str(x) for x in v[:4]) + (" …" if len(v) > 4 else "") if all(not isinstance(x, (dict, list)) for x in v) else f"{len(v)} items"
        else:
            out[key] = v
    return out


def _records(name: str, mode: str) -> list[dict]:
    """All rows of a dataset as flat records (never the source objects)."""
    meta = DATASETS[name]
    if name == "warehouse":
        cur = DB.execute("SELECT * FROM customers")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    raw = data._fetch(meta, mode)  # noqa: SLF001  (same reader as the gate, without counting as an agent read)
    if meta.live == "telemetry":
        raw = {k: {"status": v["status"], **v["latest"]} for k, v in raw.items()}
    if isinstance(raw, dict) and meta.key:
        rows = [{meta.key: k, **v} if isinstance(v, dict) else {meta.key: k, "value": v} for k, v in raw.items()]
    elif isinstance(raw, list):
        rows = [r if isinstance(r, dict) else {"value": r} for r in raw]
    elif isinstance(raw, dict):
        rows = [{"field": k, "value": v} for k, v in raw.items()]
    else:
        rows = [{"value": raw}]
    return rows


def dataset_view(name: str, agent_id: str | None = None) -> dict:
    meta, mode = DATASETS[name], data.binding(name)
    base = {"name": name, "title": meta.title, "classification": meta.classification, "owner": meta.owner, "description": meta.description,
            "connector": meta.connector, "status": mode, "personal_fields": list(meta.pii)}
    if mode == "none":
        return base | {"connected": False, "medallion": None, "columns": [], "rows": [], "masked_columns": [],
                       "note": "Not connected for this company. The agent cannot read it; Prepare all agents connects the sample."}
    rows = [privacy.mask(r, meta.pii) for r in _records(name, mode)]
    flat = [_flatten(r) for r in rows]
    cols = list(dict.fromkeys(c for r in flat for c in r))[:14]
    total_cells = len(flat) * max(1, len(cols))
    filled = sum(1 for r in flat for c in cols if r.get(c) not in (None, ""))
    key = meta.key if meta.key in cols else None
    keys = [r.get(key) for r in flat] if key else []
    dupes = len(keys) - len(set(keys)) if key else 0
    missing_key = sum(1 for k in keys if k in (None, "")) if key else 0
    upload = get_store().get("datasets", name) if mode == "upload" else None
    rejected = (upload or {}).get("quality", {}).get("rejected", 0) if upload else 0
    source = {"sample": "Sample data shipped with DOS", "upload": "File uploaded by the company", "live": "Live connector"}.get(mode, mode)
    if meta.live == "telemetry":
        source = "Live machine stream (edge gateway, every 2 seconds)"
    reads = [a for a in get_store().list("data_access", limit=3000) if a["dataset"] == name and (agent_id is None or a.get("agent_id") == agent_id)]
    masked_cols = [c for c in cols if privacy.kind_of(c.split(".")[-1], meta.pii) or c.split(".")[0] in meta.pii]
    return base | {
        "connected": True,
        "medallion": {
            "bronze": {"rows": len(flat) + rejected, "source": source, "connector_in_production": meta.connector},
            "silver": {"rows": len(flat) - dupes - missing_key, "rejected": rejected + dupes + missing_key, "completeness": round(100 * filled / total_cells, 1) if total_cells else 100.0,
                       "checks": ["types", "required fields", f"unique {key}" if key else "no key column", "classification tag"]},
            "gold": {"rows": len(flat), "columns": len(cols), "served_by": "ds() data gate: masked by role, logged per read",
                     "classification": meta.classification},
        },
        "columns": cols, "masked_columns": masked_cols,
        "rows": [[("" if r.get(c) is None else str(r.get(c))[:60]) for c in cols] for r in flat[:MAX_ROWS]],
        "row_count": len(flat), "showing": min(MAX_ROWS, len(flat)),
        "reads": len(reads), "last_read": max((a["created_at"] for a in reads), default=None),
        "note": "Every personal value is masked in this view, for every role.",
    }


def agent_view(spec) -> dict:
    lin = data.agent_lineage(spec)
    sets = [dataset_view(n, spec.id) for n in lin["datasets"]]
    steps = []
    last = next((x for x in get_store().list("runs", where={"agent_id": spec.id}, limit=50) if x.get("purpose") == "run"), None)
    if last:
        steps = [{"dataset": s["name"], "title": s.get("detail"), "rows": s.get("rows"), "by": s.get("by"), "status": s.get("status"),
                  "classification": s.get("classification")} for s in get_store().list("steps", where={"run_id": last["id"]}, order_by="seq", descending=False, limit=500)
                 if s["kind"] == "data"]
    return {"agent": {"id": spec.id, "name": spec.name, "vertical": spec.vertical, "tools": spec.tools},
            "lineage": lin, "datasets": sorted(sets, key=lambda d: -SENSITIVITY[d["classification"]]),
            "last_run": {"id": last["id"], "status": last["status"], "created_at": last["created_at"], "reads": steps} if last else None}


def overview(specs: list) -> list[dict]:
    out = []
    for s in specs:
        lin = data.agent_lineage(s)
        out.append({"id": s.id, "name": s.name, "vertical": s.vertical, "datasets": lin["datasets"],
                    "classification": lin["max_classification"], "personal_data": lin["personal_data"],
                    "titles": [DATASETS[d].title for d in lin["datasets"]]})
    return out
