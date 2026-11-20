"""Retail and e-commerce tools: stock, demand, suppliers, pricing, orders, returns, catalogue."""
import math

from ..clients import policy
from ..data import ds
from .common import effect, err, ok


def _banned(*texts: str) -> list[str]:
    joined = " ".join(str(t) for t in texts).lower()
    return [w for w in policy("marketing.banned_words") if w.lower() in joined]


def get_stock_levels(category: str = "all") -> dict:
    """List stock on hand, average daily sales, days of cover and supplier lead time for each item.

    Args:
        category: Category name, a SKU, or 'all'.
    """
    rows, safety = [], policy("retail.safety_days")
    for sku, s in ds("stock").items():
        if category.lower() in ("all", s["category"].lower(), sku.lower()):
            cover = round(s["on_hand"] / max(s["daily_sales"], 1), 1)
            rows.append({"sku": sku, "name": s["name"], "on_hand": s["on_hand"], "daily_sales": s["daily_sales"],
                         "days_of_cover": cover, "lead_time_days": s["lead_time_days"], "at_risk": cover <= s["lead_time_days"] + safety})
    return ok(items=rows)


def forecast_demand(sku: str, days: int = 14) -> dict:
    """Forecast unit demand for an item. Returns the forecast with a low and high range and the assumptions.

    Args:
        sku: Item identifier such as SKU-110.
        days: Number of days to forecast.
    """
    s = ds("stock").get(sku.upper())
    if not s:
        return err(f"No item {sku}")
    base = s["daily_sales"] * days
    return ok(sku=sku.upper(), days=days, forecast_units=base, low=math.floor(base * 0.85), high=math.ceil(base * 1.2),
              assumptions=["Average of the last 28 days", "No festival uplift applied"], history_days=28)


def get_supplier_quotes(sku: str) -> dict:
    """Get current supplier quotes for an item: unit price, lead time and on-time delivery record.

    Args:
        sku: Item identifier.
    """
    q = ds("suppliers").get(sku.upper())
    return ok(sku=sku.upper(), quotes=q) if q else err(f"No quotes on file for {sku}")


def create_purchase_order(sku: str, quantity: int, supplier: str) -> dict:
    """Create a purchase order. Requires human approval.

    Args:
        sku: Item identifier.
        quantity: Units to order.
        supplier: Supplier name from the quotes.
    """
    quotes = {q["supplier"]: q for q in ds("suppliers").get(sku.upper(), [])}
    if supplier not in quotes:
        return err(f"{supplier} has no quote for {sku}")
    total = quantity * quotes[supplier]["unit_price"]
    return ok(po_id=effect("purchase_order", {"sku": sku.upper(), "quantity": quantity, "supplier": supplier, "total_inr": total}), total_inr=total)


def competitor_prices(sku: str) -> dict:
    """Get competitor prices for an item alongside our price, cost and margin floor.

    Args:
        sku: Item identifier.
    """
    s, c = ds("stock").get(sku.upper()), ds("competitor").get(sku.upper())
    if not s or not c:
        return err(f"No price data for {sku}")
    return ok(sku=sku.upper(), our_price=s["price"], cost=s["cost"], margin_floor_pct=s["margin_floor_pct"],
              competitor_prices=c, competitor_low=min(c), competitor_high=max(c), source="Demo price feed")


def _check_price(sku: str = "", new_price: float = 0, **_) -> dict | None:
    s = ds("stock").get(str(sku).upper())
    if not s:
        return err(f"No item {sku}")
    if new_price <= 0:
        return err("Price must be above zero")
    margin = (new_price - s["cost"]) / new_price * 100
    if margin < s["margin_floor_pct"]:
        return err(f"Rejected: margin would be {margin:.1f}%, below the floor of {s['margin_floor_pct']}%")
    return None


def update_price(sku: str, new_price: float) -> dict:
    """Change the selling price of an item. Requires human approval. Rejects prices below the margin floor.

    Args:
        sku: Item identifier.
        new_price: New selling price in rupees.
    """
    refusal = _check_price(sku=sku, new_price=new_price)
    if refusal:
        return refusal
    s = ds("stock")[sku.upper()]
    margin = (new_price - s["cost"]) / new_price * 100
    return ok(change_id=effect("price_change", {"sku": sku.upper(), "old": s["price"], "new": new_price}), margin_pct=round(margin, 1))


def sales_summary(period: str = "last_week") -> dict:
    """Summarise sales by category for last_week compared with the week before.

    Args:
        period: last_week is the only period in the demo data.
    """
    q = "SELECT category, ROUND(SUM(amount)) FROM orders WHERE order_date {} GROUP BY category"
    last = dict(ds("warehouse").execute(q.format(">= '2026-11-02'")).fetchall())
    prev = dict(ds("warehouse").execute(q.format("< '2026-11-02'")).fetchall())
    rows = [{"category": c, "revenue": last.get(c, 0), "previous": prev.get(c, 0),
             "change_pct": round((last.get(c, 0) - prev.get(c, 0)) / max(prev.get(c, 1), 1) * 100, 1)} for c in sorted(set(last) | set(prev))]
    return ok(period=period, by_category=rows, total=sum(last.values()), previous_total=sum(prev.values()))


def get_order(order_id: str) -> dict:
    """Get an order: item, amount and days since delivery.

    Args:
        order_id: Order identifier such as ORD-3002.
    """
    o = ds("orders").get(order_id.upper())
    return ok(order_id=order_id.upper(), **o) if o else err(f"No order {order_id}")


def check_return_eligibility(order_id: str, reason: str) -> dict:
    """Apply the returns policy to an order. Returns eligible or not, with the rule that decided it.

    Args:
        order_id: Order identifier.
        reason: Customer's reason, for example size, damaged, changed mind.
    """
    o = ds("orders").get(order_id.upper())
    if not o:
        return err(f"No order {order_id}")
    window, limit = policy("commerce.return_window_days"), policy("commerce.auto_refund_limit_inr")
    eligible = o["delivered_days_ago"] <= window
    return ok(order_id=order_id.upper(), eligible=eligible, rule=f"{window}-day return window", days_since_delivery=o["delivered_days_ago"],
              refund_amount=o["amount"] if eligible else 0, needs_approval=o["amount"] > limit, instant_refund_limit=limit, reason=reason)


def _check_refund(order_id: str = "", amount: float = 0, reason: str = "", **_) -> dict | None:
    o = ds("orders").get(str(order_id).upper())
    if not o:
        return err(f"No order {order_id}")
    if amount <= 0:
        return err("Refund amount must be above zero")
    if amount > o["amount"]:
        return err("Refused: a refund cannot exceed the order amount")
    window = policy("commerce.return_window_days")
    if o["delivered_days_ago"] > window:
        return err(f"Refused: the order was delivered {o['delivered_days_ago']} days ago, outside this client's {window}-day return window")
    return None


def issue_refund(order_id: str, amount: float, reason: str) -> dict:
    """Refund an order to the original payment method. Needs human approval above the client's instant-refund limit.
    The platform refuses refunds above the order amount or outside the return window.

    Args:
        order_id: Order identifier.
        amount: Refund amount in rupees. Cannot exceed the order amount.
        reason: Reason for the refund.
    """
    refusal = _check_refund(order_id=order_id, amount=amount, reason=reason)
    if refusal:
        return refusal
    return ok(refund_id=effect("refund", {"order_id": order_id.upper(), "amount": amount, "reason": reason}), settles_in_days=5)


def get_product(sku: str) -> dict:
    """Get a product listing: current title, description and recorded attributes.

    Args:
        sku: Item identifier.
    """
    p = ds("products").get(sku.upper())
    return ok(sku=sku.upper(), **p) if p else err(f"No product {sku}")


def update_product_listing(sku: str, title: str, bullets: list[str], description: str) -> dict:
    """Save a new product listing. Requires human approval before it goes live.

    Args:
        sku: Item identifier.
        title: New title, under 80 characters.
        bullets: Up to five benefit bullets.
        description: New description.
    """
    if len(title) > 80:
        return err("Title must be under 80 characters")
    bad = _banned(title, description, *bullets)
    if bad:
        return err(f"Refused: the listing uses words this client does not allow ({', '.join(bad)}). Rewrite without them.")
    return ok(listing_id=effect("listing_update", {"sku": sku.upper(), "title": title, "bullets": bullets[:5], "description": description}))


def get_reviews(sku: str) -> dict:
    """Get customer reviews for a product. Reviewer names are already removed.

    Args:
        sku: Item identifier.
    """
    r = ds("reviews").get(sku.upper())
    return ok(sku=sku.upper(), count=len(r), reviews=r) if r else err(f"No reviews for {sku}")


def get_customer_history(customer_id: str) -> dict:
    """Get a customer's past purchases.

    Args:
        customer_id: Customer identifier such as CUS-4001.
    """
    c = ds("customers").get(customer_id.upper())
    return ok(customer_id=customer_id.upper(), **c) if c else err(f"No customer {customer_id}")


def recommend_products(customer_id: str) -> dict:
    """Get candidate products for a customer, already filtered to in-stock items not bought recently.

    Args:
        customer_id: Customer identifier.
    """
    c = ds("customers").get(customer_id.upper())
    if not c:
        return err(f"No customer {customer_id}")
    cands = [{"sku": k, "name": v["name"], "price": v["price"]} for k, v in ds("stock").items() if v["name"] not in c["history"] and v["on_hand"] > 0]
    return ok(customer_id=customer_id.upper(), candidates=cands[:3])


def schedule_email(segment: str, subject: str, body: str, send_at: str) -> dict:
    """Schedule a marketing email to a segment. Requires human approval. Refuses opted-out segments.

    Args:
        segment: Segment name.
        subject: Subject line, under 50 characters.
        body: Email body.
        send_at: When to send, for example 'Tomorrow 10:00'.
    """
    seg = next((s for s in ds("segments") if s["name"].lower() == segment.lower()), None)
    if not seg:
        return err(f"No segment {segment}")
    if seg["opted_out"]:
        return err("Refused: this segment has opted out of marketing")
    bad = _banned(subject, body)
    if bad:
        return err(f"Refused: the email uses words this client does not allow ({', '.join(bad)}). Rewrite without them.")
    return ok(email_id=effect("email_schedule", {"segment": segment, "subject": subject, "body": body, "send_at": send_at}), recipients=seg["size"])


PRECHECKS = {"issue_refund": _check_refund, "update_price": _check_price}
