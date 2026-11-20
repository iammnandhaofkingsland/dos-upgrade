"""LAYER 3: DATA.

Agents are only as good, and only as safe, as the data they can reach. This layer is the single gate between
agents and data. A tool never imports a dataset; it calls ds("loans"). That one call:
  1. checks the dataset is CONNECTED for the current client (otherwise the tool gets a clear refusal),
  2. returns that client's data and nobody else's (sample data, or the file the client uploaded),
  3. writes the access into the run trace and the data access log, with the dataset's classification.

The registry below is the data inventory: what each dataset is, how sensitive it is, which fields are
personal data, who owns it, and what the production connector will be. Lineage (which tool and which agent
uses which dataset) is not typed by hand: it is read from the tool source code, so it cannot go stale."""
from __future__ import annotations

import copy
import csv
import inspect
import io
import re
from dataclasses import dataclass, field
from typing import Any

from .clients import SCHEMA, get_client, update_client
from .context import current_run
from .store import audit, get_store, new_id, now
from . import sample_data as D
from .trace import write_step


class DataError(Exception):
    """Raised by ds() when data is not available to this client. The tool wrapper turns it into a tool error."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str = "text"  # text | number | int | date | phone
    required: bool = False
    pii: bool = False


@dataclass(frozen=True)
class Dataset:
    name: str
    title: str
    classification: str  # Public | Internal | Confidential | Restricted
    owner: str
    description: str
    connector: str  # how this dataset is reached in production
    const: str = ""  # attribute in sample_data.py holding the sample data
    key: str = ""  # identifier column for record datasets
    pii: tuple = ()
    columns: tuple = field(default=())  # upload schema; empty = not uploadable in the demo
    live: str = ""  # "telemetry" = live machine stream; "overlay" = sample + agent changes; "repair" = sample + learned cases


DATASETS: dict[str, Dataset] = {d.name: d for d in [
    Dataset("loans", "Loan accounts", "Restricted", "Head of Collections", "One row per loan: borrower, instalment, overdue amount, days past due.",
            "Loan management system API or nightly export", "LOANS", "loan_id", ("customer", "phone"),
            (Column("loan_id", required=True), Column("customer", required=True, pii=True), Column("phone", "phone", True, True), Column("language"),
             Column("principal", "number"), Column("emi", "number", True), Column("paid_instalments", "int", True), Column("total_instalments", "int", True),
             Column("next_due", "date"), Column("overdue_amount", "number", True), Column("days_past_due", "int", True))),
    Dataset("transactions", "Card and account transactions", "Restricted", "Head of Risk", "Transactions with device, city and time signals.", "Core banking or payment switch feed", "TRANSACTIONS", "txn_id", ("account",)),
    Dataset("account_txns", "Account statements", "Restricted", "Head of Risk", "Recent transactions per account.", "Core banking API", "ACCOUNT_TXNS", "account_id"),
    Dataset("risk", "Customer risk profiles", "Restricted", "Head of Risk", "Risk band, normal spend and past alerts per customer.", "Risk engine API", "RISK", "account_id", ("customer",)),
    Dataset("kyc_docs", "KYC documents", "Restricted", "Compliance Officer", "Fields extracted from identity and address documents.", "Document store (Cloud Storage) plus Gemini extraction", "KYC_DOCS", "applicant_id", ("name", "dob", "number")),
    Dataset("knowledge", "Policy and procedure library", "Internal", "Operations Head", "Policy passages agents must quote instead of answering from memory.", "Vertex AI Search or RAG Engine over the policy folder", "KNOWLEDGE"),
    Dataset("stock", "Stock and prices", "Internal", "Store Manager", "Stock on hand, daily sales, lead time, price, cost and margin floor per item.", "POS or ERP API", "STOCK", "sku",
            columns=(Column("sku", required=True), Column("name", required=True), Column("category"), Column("on_hand", "int", True), Column("daily_sales", "number", True),
                     Column("lead_time_days", "int", True), Column("price", "number", True), Column("cost", "number", True), Column("margin_floor_pct", "number", True))),
    Dataset("suppliers", "Supplier quotes", "Confidential", "Purchase Manager", "Quotes, lead times and on-time record per supplier.", "Supplier portal or email intake", "SUPPLIERS", "sku"),
    Dataset("competitor", "Competitor prices", "Internal", "Category Manager", "Observed competitor prices per item.", "Price-monitoring feed", "COMPETITOR", "sku"),
    Dataset("orders", "Customer orders", "Confidential", "Head of Customer Service", "Orders with item, amount and delivery age.", "Store platform API (Shopify, WooCommerce or custom)", "ORDERS", "order_id", ("customer",),
            (Column("order_id", required=True), Column("customer", required=True, pii=True), Column("item", required=True), Column("sku"), Column("amount", "number", True),
             Column("delivered_days_ago", "int", True), Column("category"))),
    Dataset("products", "Product catalogue", "Public", "Catalogue Manager", "Titles, attributes and descriptions.", "Store platform API", "PRODUCTS", "sku"),
    Dataset("reviews", "Customer reviews", "Internal", "Head of Customer Service", "Free-text reviews. Untrusted text written by the public.", "Store platform or marketplace reviews API", "REVIEWS", "sku"),
    Dataset("customers", "Customer purchase history", "Confidential", "CRM Manager", "What each customer has bought and when.", "CRM or store platform API", "CUSTOMERS", "customer_id"),
    Dataset("patients", "Patient records", "Restricted", "Clinic Manager", "Demographics, visits and appointments. Health data.", "Clinic management system API (FHIR where available)", "PATIENTS", "patient_id", ("name", "phone", "age", "allergies")),
    Dataset("slots", "Doctor calendars", "Internal", "Front Desk", "Free appointment slots per doctor.", "Clinic calendar API", "SLOTS"),
    Dataset("claims", "Insurance claims", "Restricted", "Billing Head", "Claims with procedure, amount and documents.", "Hospital billing system", "CLAIMS", "claim_id", ("patient",)),
    Dataset("labs", "Lab results", "Restricted", "Lab In-charge", "Test results with reference ranges. Health data.", "Laboratory information system", "LABS", "order_id", ("patient",)),
    Dataset("brand_voice", "Brand voice guide", "Internal", "Marketing Head", "Tone, words to avoid and sign-off.", "Brand guide document", "BRAND_VOICE"),
    Dataset("campaigns", "Campaign results", "Internal", "Marketing Head", "Spend, clicks and orders per campaign.", "Google Ads and Meta Ads reporting APIs", "CAMPAIGNS", "campaign_id"),
    Dataset("segments", "Audience segments", "Confidential", "CRM Manager", "Segment sizes, response rates and opt-out flags.", "CRM or customer data platform", "SEGMENTS"),
    Dataset("leads", "Sales leads", "Confidential", "Sales Head", "Enquiries with consent flags.", "CRM or website forms", "LEADS", "lead_id", ("name",)),
    Dataset("pincodes", "PIN code reference", "Public", "Data Team", "PIN code to city and state.", "India Post reference file", "PINCODES", "pincode"),
    Dataset("data_catalog", "Business glossary", "Internal", "Data Team", "Agreed definitions of business terms.", "Dataplex Universal Catalog", "DATA_CATALOG"),
    # ---------------- manufacturing ----------------
    Dataset("machines", "Machine register", "Internal", "Maintenance Head", "Every machine: type, line, operation, normal values and alarm limits.", "CMMS / asset register export", "MACHINES", "machine_id"),
    Dataset("telemetry", "Live machine telemetry", "Internal", "Maintenance Head", "Vibration, temperature, current, cycle time and pressure every 2 seconds per machine.", "Machine controllers through an edge gateway (OPC UA or MQTT) into Pub/Sub", "", "machine_id", live="telemetry"),
    Dataset("fault_signatures", "Failure-mode library", "Internal", "Reliability Engineer", "How each known fault moves the signals, and its proven fix, part and skill (an FMEA in data form).", "Reliability engineering FMEA sheets", "FAULT_SIGNATURES", "fault"),
    Dataset("repair_history", "Repair history", "Internal", "Maintenance Head", "Past breakdowns with symptom, confirmed cause, fix, part and repair minutes. Grows with every closed work order.", "CMMS work-order history", "REPAIR_HISTORY", live="repair"),
    Dataset("alarm_manual", "Machine manuals and alarm codes", "Internal", "Maintenance Head", "Alarm code passages from machine manuals and plant safety rules.", "OEM manuals indexed with Vertex AI Search", "ALARM_MANUAL"),
    Dataset("technicians", "Maintenance technicians", "Confidential", "Maintenance Head", "Technicians, skills, shift and live availability.", "HR roster and shift system", "TECHNICIANS", "technician_id", ("name", "phone"), live="overlay"),
    Dataset("spare_parts", "Spare parts store", "Internal", "Stores In-charge", "Spare parts stock, minimum, cost, lead time and supplier.", "ERP stores module", "SPARE_PARTS", "part_id", live="overlay"),
    Dataset("production_orders", "Production orders", "Confidential", "Production Planner", "Open orders with machine, quantity done, rate and customer due time.", "ERP / MES production orders", "PRODUCTION_ORDERS", "order_id", live="overlay"),
    Dataset("lots", "Production lots", "Confidential", "Quality Head", "Each lot with its order, machine, time window and status.", "MES lot genealogy", "LOTS", "lot_id", live="overlay"),
    Dataset("spc", "In-process measurements", "Internal", "Quality Head", "Measured dimensions and hardness with tolerances, for statistical process control.", "Gauges and CMM via QMS", "SPC", "feature"),
    Dataset("shift_performance", "Shift performance", "Internal", "Production Head", "Planned time, run time, parts, good parts and stop reasons per machine for the shift.", "MES / machine counters", "SHIFT_PERFORMANCE", "machine_id"),
    Dataset("energy", "Energy meters", "Internal", "Utilities Head", "Energy per part, idle power and idle hours per machine.", "Energy meters via edge gateway", "ENERGY", "machine_id"),
    Dataset("materials", "Raw material stock", "Internal", "Stores In-charge", "Raw material stock and consumption per part.", "ERP inventory", "MATERIALS", "material_id"),
    Dataset("maintenance_plan", "Preventive maintenance plan", "Internal", "Maintenance Head", "Planned maintenance tasks with due times.", "CMMS PM schedule", "MAINTENANCE_PLAN", "task_id", live="overlay"),
    # ---------------- wholesale and supply chain ----------------
    Dataset("w_purchase_orders", "Purchase orders (wholesale)", "Confidential", "Purchase Head", "Purchase orders with lines and prices.", "ERP purchasing", "PURCHASE_ORDERS_W", "po_id"),
    Dataset("goods_receipts", "Goods receipts", "Internal", "Warehouse Head", "Received quantities per purchase order.", "Warehouse management system", "GOODS_RECEIPTS", "grn_id"),
    Dataset("supplier_invoices", "Supplier invoices", "Confidential", "Accounts Payable Head", "Supplier invoices awaiting payment.", "AP inbox and ERP", "SUPPLIER_INVOICES", "invoice_id", live="overlay"),
    Dataset("shipments", "Inbound shipments", "Internal", "Logistics Head", "Inbound shipments with ETA and last tracking update.", "Carrier tracking APIs", "SHIPMENTS", "shipment_id"),
    Dataset("supplier_scores", "Supplier scorecards", "Confidential", "Purchase Head", "On-time-in-full, rejects and master-data checks per supplier.", "ERP vendor master and receipts", "SUPPLIER_SCORES", "supplier"),
    Dataset("warehouse", "Analytics warehouse", "Confidential", "Data Team", "Order and customer tables for analysis. Contains personal columns.", "BigQuery (read-only service account)", "DB", pii=("customers.name", "customers.phone", "customers.email")),
]}
SENSITIVITY = {"Public": 0, "Internal": 1, "Confidential": 2, "Restricted": 3}
PERSONAL_SQL_COLUMNS = ("phone", "email")


# ---------------------------------------------------------------- binding
def bindings(client: dict | None = None) -> dict[str, str]:
    """dataset name -> sample | upload | none, for the current client."""
    raw = (client or get_client()).get("datasets") or {}
    if raw == "all":
        return {n: "sample" for n in DATASETS}
    return {n: raw.get(n, "none") for n in DATASETS}


def binding(name: str) -> str:
    return bindings().get(name, "none")


def ds(name: str) -> Any:
    """THE way a tool reads data. See the module docstring for what this call guarantees."""
    meta = DATASETS[name]  # KeyError = programming mistake: dataset not in the registry
    client = get_client()
    mode = bindings(client).get(name, "none")
    if mode == "none":
        _log_access(meta, "denied", 0)
        raise DataError(f"The data source '{meta.title}' is not connected for {client['name']}. "
                        "Nothing was read. Ask an administrator to connect it under Data sources.")
    data = _fetch(meta, mode)
    _log_access(meta, mode, len(data) if hasattr(data, "__len__") else 0)
    # Tools get a COPY, never the source: nothing a tool or a guardrail does to a result can change the data itself.
    return data if name == "warehouse" else copy.deepcopy(data)


def _fetch(meta: Dataset, mode: str) -> Any:
    """Where the rows come from: the client's upload, the live plant, or the sample (plus overlays)."""
    from . import plant  # noqa: PLC0415

    if meta.live == "telemetry":
        return plant.get_plant().telemetry()
    if mode == "upload":
        doc = get_store().get("datasets", meta.name)
        if not doc:
            raise DataError(f"The uploaded file for '{meta.title}' is missing. Upload it again under Data sources.")
        data = doc["rows"]
    else:
        data = getattr(D, meta.const)
    if meta.live == "overlay":
        data = plant.overlay(meta.name, data)
    elif meta.live == "repair":
        data = list(data) + plant.learned_repairs()
    return data


def _log_access(meta: Dataset, mode: str, rows: int) -> None:
    run = current_run()
    if run is None or run.get("quiet"):
        return
    mark = ("ds", meta.name, run.get("tool"))
    if mark in run["seen"]:
        return
    run["seen"].add(mark)
    status = "denied" if mode == "denied" else "read"
    write_step(run["run_id"], "data", meta.name, detail=meta.title, classification=meta.classification, personal_data=bool(meta.pii),
               source=mode, rows=rows, by=run.get("tool") or "platform", status=status)
    get_store().put("data_access", new_id("acc"), {"run_id": run["run_id"], "agent_id": run.get("agent_id"), "tool": run.get("tool"), "dataset": meta.name,
                                                   "classification": meta.classification, "personal_data": bool(meta.pii), "source": mode, "status": status, "created_at": now()})


# ---------------------------------------------------------------- lineage (read from the code)
_DS_CALL = re.compile(r"""\bds\(\s*["']([a-z_]+)["']\s*\)""")
_POLICY_CALL = re.compile(r"""\bpolicy\(\s*["']([a-z_.]+)["']\s*\)""")
_lineage_cache: dict[str, dict] = {}


def tool_lineage(tool: str) -> dict:
    """Which datasets and which client settings a tool touches, found by scanning its source code
    (including helper functions in the same module that it calls)."""
    if tool in _lineage_cache:
        return _lineage_cache[tool]
    from .tools import RAW  # noqa: PLC0415

    fn = RAW.get(tool)
    out = {"datasets": [], "policies": [], "acts": False}
    if fn:
        src = inspect.getsource(fn)
        module = inspect.getmodule(fn)
        for helper in set(re.findall(r"\b(_[a-z_]+)\(", src)):
            h = getattr(module, helper, None)
            if inspect.isfunction(h):
                src += "\n" + inspect.getsource(h)
        out = {"datasets": sorted(set(_DS_CALL.findall(src))), "policies": sorted(set(_POLICY_CALL.findall(src)) & set(SCHEMA)),
               "acts": "effect(" in src}
    _lineage_cache[tool] = out
    return out


def agent_lineage(spec) -> dict:
    datasets, policies, acting = set(), set(), []
    for t in spec.tools:
        lin = tool_lineage(t)
        datasets |= set(lin["datasets"])
        policies |= set(lin["policies"])
        if lin["acts"]:
            acting.append(t)
    return {"datasets": sorted(datasets), "policies": sorted(policies), "acting_tools": acting,
            "max_classification": max((DATASETS[d].classification for d in datasets), key=lambda c: SENSITIVITY[c], default="Public"),
            "personal_data": any(DATASETS[d].pii for d in datasets)}


def readiness(spec) -> dict:
    """Can this agent run for the current client? Lists the datasets it needs that are not connected."""
    need = agent_lineage(spec)["datasets"]
    b = bindings()
    missing = [d for d in need if b.get(d, "none") == "none"]
    return {"ready": not missing, "needs": need, "missing": missing, "missing_titles": [DATASETS[d].title for d in missing]}


# ---------------------------------------------------------------- inventory for the console
def _size(name: str, mode: str) -> int:
    if mode == "none":
        return 0
    if mode == "upload":
        doc = get_store().get("datasets", name)
        return len(doc["rows"]) if doc else 0
    if DATASETS[name].live:
        return len(_fetch(DATASETS[name], mode))
    data = getattr(D, DATASETS[name].const)
    if name == "warehouse":
        return sum(data.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("orders", "customers", "new_orders"))
    return len(data)


def inventory(catalog: dict, verticals: list[str]) -> list[dict]:
    b = bindings()
    used_by: dict[str, dict] = {n: {"tools": set(), "agents": set()} for n in DATASETS}
    for spec in catalog.values():
        if spec.vertical not in verticals:
            continue
        for t in spec.tools:
            for d in tool_lineage(t)["datasets"]:
                used_by[d]["tools"].add(t)
                used_by[d]["agents"].add(spec.name)
    access = get_store().list("data_access", limit=5000)
    out = []
    for name, meta in DATASETS.items():
        if b[name] == "none" and not used_by[name]["agents"]:
            continue  # not relevant to this client's industries
        mine = [a for a in access if a["dataset"] == name]
        up = get_store().get("datasets", name) if b[name] == "upload" else None
        out.append({"name": name, "title": meta.title, "classification": meta.classification, "owner": meta.owner, "description": meta.description,
                    "connector": meta.connector, "personal_fields": list(meta.pii), "status": b[name], "rows": _size(name, b[name]),
                    "uploadable": bool(meta.columns), "tools": sorted(used_by[name]["tools"]), "agents": sorted(used_by[name]["agents"]),
                    "reads": len(mine), "denied": sum(a["status"] == "denied" for a in mine), "last_read": max((a["created_at"] for a in mine), default=None),
                    "quality": up.get("quality") if up else None})
    return sorted(out, key=lambda d: (-SENSITIVITY[d["classification"]], d["title"]))


def sample_rows(name: str, limit: int = 5) -> dict:
    """A few rows for the console, with personal fields hidden. Never used by agents."""
    meta, mode = DATASETS[name], binding(name)
    if mode == "none":
        return {"columns": [], "rows": [], "note": "Not connected"}
    if name == "warehouse":
        return {"columns": ["table", "rows"], "rows": [[t, D.DB.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]] for t in ("orders", "customers", "new_orders")],
                "note": "Tables in the analytics warehouse"}
    data = _fetch(meta, mode)
    if meta.live == "telemetry":
        data = {k: {"status": v["status"], **v["latest"]} for k, v in data.items()}
    rows = []
    if isinstance(data, dict) and meta.key:
        for k, v in list(data.items())[:limit]:
            rows.append({meta.key: k, **v} if isinstance(v, dict) else {meta.key: k, "value": v})
    elif isinstance(data, list):
        rows = [r if isinstance(r, dict) else {"value": r} for r in data[:limit]]
    else:
        rows = [{"field": k, "value": v} for k, v in list(data.items())[:limit]]
    cols = list(dict.fromkeys(c for r in rows for c in r))
    hide = set(meta.pii)
    return {"columns": cols, "rows": [["••• hidden" if c in hide else (str(r.get(c, ""))[:60]) for c in cols] for r in rows],
            "note": f"First {len(rows)} rows. Personal fields are hidden in this view."}


# ---------------------------------------------------------------- upload with validation and a quality report
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PHONE = re.compile(r"^\+?\d[\d -]{8,16}$")


def _cell(col: Column, raw: str) -> tuple[Any, str | None]:
    v = (raw or "").strip()
    if not v:
        return (None, f"{col.name} is empty") if col.required else ((0 if col.type in ("number", "int") else ""), None)
    try:
        if col.type == "number":
            n = float(v.replace(",", ""))
            return (int(n) if n == int(n) else n), (None if n >= 0 else f"{col.name} is negative")
        if col.type == "int":
            n = int(float(v))
            return n, (None if n >= 0 else f"{col.name} is negative")
        if col.type == "date":
            return v, (None if _DATE.match(v) else f"{col.name} must be YYYY-MM-DD")
        if col.type == "phone":
            return v, (None if _PHONE.match(v) else f"{col.name} is not a phone number")
    except ValueError:
        return None, f"{col.name}: '{v[:20]}' is not a number"
    return v[:200], None


def upload_csv(name: str, text: str, actor: str) -> dict:
    """Validate a CSV against the dataset's schema, store the good rows for THIS client only, return a quality report."""
    meta = DATASETS.get(name)
    if not meta or not meta.columns:
        raise DataError("This data source does not accept file uploads in the demo.")
    if len(text) > 2_000_000:
        raise DataError("File too large for the demo (2 MB limit).")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c.name for c in meta.columns if c.required and c.name not in header]
    if missing:
        raise DataError(f"Missing required column(s): {', '.join(missing)}. Expected columns: {', '.join(c.name for c in meta.columns)}.")
    unknown = [h for h in header if h not in {c.name for c in meta.columns}]
    rows, problems, seen, total = {}, [], set(), 0
    filled = {c.name: 0 for c in meta.columns}
    for line, raw in enumerate(reader, start=2):
        total += 1
        raw = {(k or "").strip().lower(): v for k, v in raw.items()}
        rec, errs = {}, []
        for col in meta.columns:
            value, e = _cell(col, raw.get(col.name, ""))
            if e:
                errs.append(e)
            rec[col.name] = value
            filled[col.name] += bool((raw.get(col.name) or "").strip())
        key = str(rec.get(meta.key) or "").upper()
        if key in seen:
            errs.append(f"duplicate {meta.key} {key}")
        if errs:
            problems.append({"line": line, "key": key, "problems": errs})
            continue
        seen.add(key)
        rec.pop(meta.key)
        rows[key] = rec
    if not rows:
        raise DataError("No valid rows in the file. Nothing was saved. See the expected columns and try again.")
    quality = {"rows_in_file": total, "rows_accepted": len(rows), "rows_rejected": len(problems), "score": round(len(rows) / max(total, 1), 3),
               "problems": problems[:20], "ignored_columns": unknown,
               "completeness": {c: round(n / max(total, 1), 3) for c, n in filled.items()},
               "personal_columns": [c.name for c in meta.columns if c.pii]}
    get_store().put("datasets", name, {"rows": rows, "quality": quality, "uploaded_by": actor, "created_at": now(), "source": "upload"})
    current = dict(bindings())
    current[name] = "upload"
    update_client({"datasets": {k: v for k, v in current.items() if v != "none"}}, actor, note=f"Uploaded {meta.title}: {len(rows)} rows")
    audit(actor, "data.uploaded", name, {"rows": len(rows), "rejected": len(problems)})
    return quality


def connect(name: str, mode: str, actor: str) -> dict:
    """Connect a dataset to sample data, or disconnect it. A versioned configuration change."""
    if name not in DATASETS or mode not in ("sample", "none"):
        raise DataError("Unknown data source or mode")
    current = dict(bindings())
    current[name] = mode
    update_client({"datasets": {k: v for k, v in current.items() if v != "none"}}, actor,
                  note=f"{'Connected' if mode == 'sample' else 'Disconnected'} {DATASETS[name].title}")
    audit(actor, "data.connected" if mode == "sample" else "data.disconnected", name)
    return {"name": name, "status": mode}


def template_csv(name: str) -> str:
    meta = DATASETS[name]
    return ",".join(c.name for c in meta.columns) + "\n"
