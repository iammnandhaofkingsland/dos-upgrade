"""Wholesale and supply-chain tools: three-way invoice matching, inbound shipments, supplier performance."""
from __future__ import annotations

from .. import plant
from ..clients import policy
from ..data import ds
from .common import effect, err, ok


def match_invoice(invoice_id: str) -> dict:
    """Three-way match a supplier invoice against its purchase order and goods receipt: quantity and price
    per line, and duplicate detection (same supplier and invoice number already on file).

    Args:
        invoice_id: Invoice identifier, for example INV-S-302.
    """
    invs = ds("supplier_invoices")
    inv = invs.get(str(invoice_id).upper())
    if not inv:
        return err(f"No invoice {invoice_id}")
    po = ds("w_purchase_orders").get(inv["po"])
    grn = next((g for g in ds("goods_receipts").values() if g["po"] == inv["po"]), None)
    dup = [k for k, v in invs.items() if k != invoice_id.upper() and v["supplier"] == inv["supplier"] and v["number"] == inv["number"]]
    tol = policy("wholesale.price_tolerance_pct")
    issues = []
    for line in inv["lines"]:
        pl = next((l for l in (po or {}).get("lines", []) if l["sku"] == line["sku"]), None)
        gl = next((l for l in (grn or {}).get("lines", []) if l["sku"] == line["sku"]), None)
        if not pl:
            issues.append(f"{line['sku']}: not on the purchase order")
            continue
        var = (line["price"] - pl["price"]) / pl["price"] * 100
        if abs(var) > tol:
            issues.append(f"{line['sku']}: price {line['price']} vs PO {pl['price']} ({var:+.1f}%, tolerance {tol}%)")
        if not gl:
            issues.append(f"{line['sku']}: no goods receipt")
        elif line["qty"] > gl["qty"]:
            issues.append(f"{line['sku']}: invoiced {line['qty']} but received {gl['qty']}")
    if dup:
        issues.append(f"Possible duplicate of {', '.join(dup)} (same supplier and invoice number)")
    status = "matched" if not issues else "exception"
    return ok(invoice_id=invoice_id.upper(), supplier=inv["supplier"], status=status, issues=issues, duplicate_of=dup,
              summary=f"{invoice_id.upper()} ({inv['supplier']}): {status.upper()}" + (": " + "; ".join(issues) if issues else ", ready for payment."))


def _check_payment_block(invoice_id: str = "", reason: str = "", **_):
    if not ds("supplier_invoices").get(str(invoice_id).upper()):
        return err(f"No invoice {invoice_id}")
    return None


def block_invoice_payment(invoice_id: str, reason: str) -> dict:
    """Block an invoice from payment until a buyer reviews it (duplicates, price or quantity variances).

    Args:
        invoice_id: Invoice identifier.
        reason: The exception found.
    """
    r = _check_payment_block(invoice_id, reason)
    if r:
        return r
    plant.set_overlay("supplier_invoices", invoice_id.upper(), payment="blocked", block_reason=reason[:200])
    effect("payment_block", {"invoice": invoice_id.upper(), "reason": reason[:200]})
    return ok(invoice_id=invoice_id.upper(), summary=f"Payment of {invoice_id.upper()} blocked: {reason[:120]}")


def list_inbound_shipments() -> dict:
    """List inbound shipments with ETA, last tracking update and status, and flag late, stale (no update for more
    than 24 hours) and delivered-but-not-received shipments.
    """
    rows = []
    for sid, s in ds("shipments").items():
        flags = []
        if s["eta_days"] < 0 and s["status"] != "delivered_not_received":
            flags.append(f"late by {-s['eta_days']} day(s)")
        if s["last_update_hours"] > 24:
            flags.append(f"no tracking update for {s['last_update_hours']} h")
        if s["status"] == "delivered_not_received":
            flags.append("delivered but not received in the warehouse")
        rows.append({"shipment_id": sid, "supplier": s["supplier"], "po": s["po"], "status": s["status"], "flags": flags})
    bad = [r for r in rows if r["flags"]]
    return ok(shipments=rows, summary=f"{len(bad)} shipment(s) need action: " + "; ".join(f"{r['shipment_id']} {r['supplier']}: {', '.join(r['flags'])}" for r in bad))


def get_supplier_scorecard(supplier: str = "") -> dict:
    """Supplier performance: on-time-in-full against target, rejects, and master-data checks (GSTIN validity,
    recent bank-detail change, which is a common payment-fraud signal).

    Args:
        supplier: Supplier name, or empty for all suppliers.
    """
    sc = ds("supplier_scores")
    rows = []
    for name, v in sc.items():
        if supplier and supplier.lower() not in name.lower():
            continue
        flags = []
        if v["otif_pct"] < v["target_pct"]:
            flags.append(f"OTIF {v['otif_pct']}% below target {v['target_pct']}%")
        if not v["gstin_valid"]:
            flags.append("GSTIN not valid")
        if v["bank_changed_recently"]:
            flags.append("bank details changed recently: verify by phone before paying")
        rows.append({"supplier": name, **v, "flags": flags})
    return ok(suppliers=rows, summary="; ".join(f"{r['supplier']}: {', '.join(r['flags']) or 'OK'}" for r in rows))


PRECHECKS = {"block_invoice_payment": _check_payment_block}
