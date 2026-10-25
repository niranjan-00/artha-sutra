"""Inventory calculations. Stock is always derived from StockMovement rows (single source of truth)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import ceil

from sqlalchemy import func

from app.extensions import db
from app.models import Notification, Product, ProductBatch, StockAlert, StockMovement

SALES_WINDOW_DAYS = 30
MIN_HISTORY_DAYS = 7      # below this, no stockout prediction is made
MIN_SALE_DAYS = 3         # distinct selling days required for a prediction
COVER_DAYS = 14           # target days of stock when suggesting a reorder quantity
IRREGULAR_RATIO = 0.3     # sold on fewer than 30% of days => demand is irregular

# (key, max days until expiry, label). Order matters: first match wins.
EXPIRY_BUCKETS = (
    ("expired", -1, "Already expired"),
    ("today", 0, "Expires today"),
    ("d3", 3, "Within 3 days"),
    ("d7", 7, "Within 7 days"),
    ("d14", 14, "Within 14 days"),
    ("d30", 30, "Within 30 days"),
)

EXPIRY_ACTIONS = {
    "expired": "Do not sell. Remove this stock from the shelf, record a write-off, and ask the supplier about a return. Follow food, medicine or other product-safety rules that apply to you.",
    "today": "Do not sell after today's expiry. Remove it at close of business and ask the supplier about a return.",
    "d3": "Move to the front and sell only while it is still in date. Avoid reordering this product until it clears.",
    "d7": "Sell older batches first and review your next order quantity. Ask the supplier whether a return is possible.",
    "d14": "Rotate stock so this batch is sold first, and reduce the next order if sales are slow.",
    "d30": "Keep an eye on it and rotate stock. Do not over-order this product.",
}


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def stock_levels(business_id: int) -> dict[int, int]:
    rows = (
        db.session.query(StockMovement.product_id, func.coalesce(func.sum(StockMovement.quantity_change), 0))
        .filter(StockMovement.business_id == business_id)
        .group_by(StockMovement.product_id)
        .all()
    )
    return {pid: int(total) for pid, total in rows}


def batch_levels(business_id: int, product_id: int | None = None) -> dict[int, int]:
    query = (
        db.session.query(StockMovement.batch_id, func.coalesce(func.sum(StockMovement.quantity_change), 0))
        .filter(StockMovement.business_id == business_id, StockMovement.batch_id.isnot(None))
    )
    if product_id is not None:
        query = query.filter(StockMovement.product_id == product_id)
    return {bid: int(total) for bid, total in query.group_by(StockMovement.batch_id).all()}


def demand_map(business_id: int, today: date | None = None) -> dict[int, dict]:
    """Per-product demand from recorded sales only. Returns sufficient=False rather than guessing."""
    today = today or date.today()
    window_start = today - timedelta(days=SALES_WINDOW_DAYS - 1)
    first_dates = dict(
        db.session.query(StockMovement.product_id, func.min(StockMovement.movement_date))
        .filter(StockMovement.business_id == business_id)
        .group_by(StockMovement.product_id)
        .all()
    )
    sales = {
        pid: (int(units), int(days))
        for pid, units, days in db.session.query(
            StockMovement.product_id,
            func.coalesce(func.sum(-StockMovement.quantity_change), 0),
            func.count(func.distinct(StockMovement.movement_date)),
        )
        .filter(
            StockMovement.business_id == business_id,
            StockMovement.movement_type == "sale",
            StockMovement.movement_date >= window_start,
            StockMovement.movement_date <= today,
        )
        .group_by(StockMovement.product_id)
        .all()
    }
    result = {}
    for pid, first in first_dates.items():
        history_days = (today - first).days + 1
        units, sale_days = sales.get(pid, (0, 0))
        window = min(SALES_WINDOW_DAYS, max(history_days, 1))
        sufficient = history_days >= MIN_HISTORY_DAYS and sale_days >= MIN_SALE_DAYS
        avg = (units / window) if sufficient else None
        result[pid] = {
            "sufficient": sufficient,
            "avg_daily": avg,
            "units_sold": units,
            "window_days": window,
            "irregular": bool(sufficient and sale_days / window < IRREGULAR_RATIO),
        }
    return result


def days_until_stockout(stock: int, demand: dict | None) -> float | None:
    if not demand or not demand["sufficient"] or not demand["avg_daily"]:
        return None
    return max(stock, 0) / demand["avg_daily"]


def suggested_reorder_qty(stock: int, min_stock: int, lead_time_days: int | None, demand: dict | None) -> int | None:
    if not demand or not demand["sufficient"] or demand["avg_daily"] is None:
        return None
    target = ceil(demand["avg_daily"] * (COVER_DAYS + (lead_time_days or 0)))
    return max(max(target, min_stock) - stock, 0)


def stock_level_label(stock: int, min_stock: int) -> str | None:
    if min_stock <= 0 or stock >= min_stock:
        return None
    if stock <= 0:
        return "out"
    if stock * 2 <= min_stock:
        return "critical"
    return "low"


def expiry_bucket(expiry: date | None, today: date) -> str | None:
    if expiry is None:
        return None
    days = (expiry - today).days
    for key, limit, _label in EXPIRY_BUCKETS:
        if days <= limit:
            return key
    return None


def bucket_label(key: str) -> str:
    return next(label for k, _l, label in EXPIRY_BUCKETS if k == key)


def low_stock_items(business, today: date | None = None) -> list[dict]:
    today = today or date.today()
    levels = stock_levels(business.id)
    demand = demand_map(business.id, today)
    items = []
    for product in Product.query.filter_by(business_id=business.id, status="active").all():
        stock = levels.get(product.id, 0)
        level = stock_level_label(stock, product.min_stock)
        if not level:
            continue
        d = demand.get(product.id)
        items.append({
            "product": product, "stock": stock, "level": level, "demand": d,
            "days_left": days_until_stockout(stock, d),
            "reorder_qty": suggested_reorder_qty(stock, product.min_stock, product.lead_time_days, d),
        })
    order = {"out": 0, "critical": 1, "low": 2}
    items.sort(key=lambda i: (order[i["level"]], i["product"].name.lower()))
    return items


def expiry_items(business, today: date | None = None) -> list[dict]:
    today = today or date.today()
    remaining = batch_levels(business.id)
    items = []
    batches = (
        ProductBatch.query.filter(ProductBatch.business_id == business.id, ProductBatch.expiry_date.isnot(None))
        .order_by(ProductBatch.expiry_date.asc()).all()
    )
    for batch in batches:
        qty = remaining.get(batch.id, 0)
        bucket = expiry_bucket(batch.expiry_date, today)
        if qty <= 0 or bucket is None:
            continue
        product = batch.product
        items.append({
            "batch": batch, "product": product, "quantity": qty, "bucket": bucket,
            "label": bucket_label(bucket), "days": (batch.expiry_date - today).days,
            "value_at_risk_paise": qty * (batch.unit_cost_paise or product.purchase_price_paise or 0),
            "action": EXPIRY_ACTIONS[bucket],
        })
    return items


def _current_conditions(business, today: date) -> dict[tuple, dict]:
    conditions = {}
    for item in low_stock_items(business, today):
        p, level = item["product"], item["level"]
        unit = p.unit
        if level == "out":
            message = f"{p.name} is out of stock (minimum {p.min_stock} {unit})."
        else:
            message = f"Only {item['stock']} {unit} of {p.name} remain (minimum {p.min_stock})."
            if item["days_left"] is not None:
                message += f" At recent sales this lasts about {item['days_left']:.1f} days."
        conditions[(p.id, 0, "low_stock", level)] = {
            "product_id": p.id, "batch_id": None, "alert_type": "low_stock", "level": level,
            "title": "Out of stock" if level == "out" else "Low stock", "message": message[:500],
        }
    for item in expiry_items(business, today):
        p, b = item["product"], item["batch"]
        if item["bucket"] == "expired":
            message = f"{item['quantity']} {p.unit} of {p.name} (batch {b.batch_number}) expired on {b.expiry_date.isoformat()}. Do not sell."
        else:
            message = f"{item['quantity']} {p.unit} of {p.name} (batch {b.batch_number}) {item['label'].lower()} — expiry {b.expiry_date.isoformat()}."
        conditions[(p.id, b.id, "expiry", item["bucket"])] = {
            "product_id": p.id, "batch_id": b.id, "alert_type": "expiry", "level": item["bucket"],
            "title": "Expired stock" if item["bucket"] == "expired" else "Expiry approaching", "message": message[:500],
        }
    return conditions


def sync_alerts(business, today: date | None = None) -> int:
    """Open alerts for new conditions, resolve cleared ones. Unchanged conditions never create a second alert."""
    today = today or date.today()
    current = _current_conditions(business, today)
    open_alerts = StockAlert.query.filter_by(business_id=business.id, resolved_at=None).all()
    open_keys = set()
    changed = False
    for alert in open_alerts:
        key = (alert.product_id, alert.batch_id or 0, alert.alert_type, alert.level)
        if key in current:
            open_keys.add(key)
        else:
            alert.resolved_at = _utcnow()
            changed = True
    created = 0
    for key, data in current.items():
        if key in open_keys:
            continue
        alert = StockAlert(business_id=business.id, **data)
        db.session.add(alert)
        db.session.flush()
        db.session.add(Notification(
            business_id=business.id, title=data["title"], message=data["message"],
            notification_type="risk" if data["level"] in ("out", "expired", "today") else "upcoming",
            related_record_type="stock_alert", related_record_id=alert.id,
            dedupe_key=f"inventory-alert-{alert.id}",
        ))
        created += 1
        changed = True
    if changed:
        db.session.commit()
    return created
