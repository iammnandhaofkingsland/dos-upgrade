"""State store with two interchangeable back ends.

MemoryStore keeps everything in a dict: zero setup, perfect for a laptop and for tests.
FirestoreStore writes to Cloud Firestore: serverless, no schema migrations, free tier is enough for a demo.
Both expose the same five methods, so no other module knows which one is in use.

Collections: activations, deployments, runs, steps, approvals, audit, outbox, config_versions, datasets,
data_access, client_state, batches, custom_specs.

TENANT ISOLATION. Every document belongs to one client (tenant). The store stamps the current client on
every write and filters every read by it, using the context variable set by the API for the request.
No caller can forget the filter, because no caller writes it. Collections in GLOBAL are shared."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from . import config
from .context import current_client

GLOBAL = {"clients"}  # collections that are not tenant-scoped


def _tenant(collection: str) -> str:
    return "*" if collection in GLOBAL else current_client()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now() -> float:
    return time.time()


class MemoryStore:
    def __init__(self):
        self._data: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(collection: str, doc_id: str) -> str:
        return f"{_tenant(collection)}/{doc_id}"

    def put(self, collection: str, doc_id: str, doc: dict) -> dict:
        with self._lock:
            doc = {**doc, "id": doc_id, "tenant": _tenant(collection)}
            self._data.setdefault(collection, {})[self._key(collection, doc_id)] = doc
            return dict(doc)

    def get(self, collection: str, doc_id: str) -> dict | None:
        doc = self._data.get(collection, {}).get(self._key(collection, doc_id))
        return dict(doc) if doc else None

    def update(self, collection: str, doc_id: str, changes: dict) -> dict | None:
        with self._lock:
            doc = self._data.get(collection, {}).get(self._key(collection, doc_id))
            if doc is None:
                return None
            doc.update(changes)
            return dict(doc)

    def list(self, collection: str, where: dict[str, Any] | None = None, order_by: str = "created_at",
             descending: bool = True, limit: int = 200) -> list[dict]:
        tenant = _tenant(collection)
        rows = [dict(d) for d in self._data.get(collection, {}).values()
                if d.get("tenant") == tenant and all(d.get(k) == v for k, v in (where or {}).items())]
        rows.sort(key=lambda d: d.get(order_by, 0), reverse=descending)
        return rows[:limit]

    def delete(self, collection: str, doc_id: str) -> None:
        with self._lock:
            self._data.get(collection, {}).pop(self._key(collection, doc_id), None)


class FirestoreStore:
    """Same interface on Cloud Firestore. Imported lazily so local runs need no Google credentials.
    Document ids are prefixed with the tenant, and every query filters on the tenant field."""

    def __init__(self):
        from google.cloud import firestore  # noqa: PLC0415

        self._fs = firestore
        self._db = firestore.Client(project=config.PROJECT or None)

    def _col(self, collection: str):
        return self._db.collection(f"dq_{collection}")

    @staticmethod
    def _key(collection: str, doc_id: str) -> str:
        return f"{_tenant(collection)}__{doc_id}".replace("/", "_")

    def put(self, collection, doc_id, doc):
        doc = {**doc, "id": doc_id, "tenant": _tenant(collection)}
        self._col(collection).document(self._key(collection, doc_id)).set(doc)
        return doc

    def get(self, collection, doc_id):
        snap = self._col(collection).document(self._key(collection, doc_id)).get()
        return snap.to_dict() if snap.exists else None

    def update(self, collection, doc_id, changes):
        ref = self._col(collection).document(self._key(collection, doc_id))
        ref.set(changes, merge=True)
        return ref.get().to_dict()

    def list(self, collection, where=None, order_by="created_at", descending=True, limit=200):
        q = self._col(collection).where(filter=self._fs.FieldFilter("tenant", "==", _tenant(collection)))
        for k, v in (where or {}).items():
            q = q.where(filter=self._fs.FieldFilter(k, "==", v))
        # Sort in memory: avoids composite indexes, and demo volumes are small.
        rows = [s.to_dict() for s in q.limit(2000).stream()]
        rows.sort(key=lambda d: d.get(order_by, 0), reverse=descending)
        return rows[:limit]

    def delete(self, collection, doc_id):
        self._col(collection).document(self._key(collection, doc_id)).delete()


_store = None


def get_store():
    global _store
    if _store is None:
        _store = FirestoreStore() if config.STORE == "firestore" else MemoryStore()
    return _store


def reset_store():
    """Used by tests."""
    global _store
    _store = MemoryStore()
    return _store


_audit_lock = threading.Lock()


def _audit_hash(prev: str, rec: dict) -> str:
    import hashlib  # noqa: PLC0415
    import json  # noqa: PLC0415

    body = {k: rec[k] for k in ("seq", "actor", "role", "action", "target", "detail", "created_at")}
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()


def audit(actor: str, action: str, target: str, detail: dict | None = None) -> None:
    """Append-only, tamper-evident audit trail. Each record stores the hash of the record before it, so
    editing or deleting any past record breaks the chain and verify_audit() reports where."""
    from .context import current_role  # noqa: PLC0415

    with _audit_lock:
        last = get_store().list("audit", order_by="seq", limit=1)
        prev = last[0]["hash"] if last else "genesis"
        rec = {"seq": (last[0]["seq"] + 1) if last else 1, "actor": actor, "role": current_role(), "action": action,
               "target": target, "detail": detail or {}, "created_at": now()}
        rec["prev_hash"], rec["hash"] = prev, _audit_hash(prev, rec)
        get_store().put("audit", new_id("aud"), rec)


def verify_audit() -> dict:
    """Recompute the whole chain for the current client. Returns the first broken record, if any."""
    rows = get_store().list("audit", order_by="seq", descending=False, limit=100000)
    prev = "genesis"
    for r in rows:
        if r.get("prev_hash") != prev or _audit_hash(prev, r) != r.get("hash"):
            return {"intact": False, "records": len(rows), "broken_at_seq": r.get("seq")}
        prev = r["hash"]
    return {"intact": True, "records": len(rows), "head": prev[:16] if rows else None}
