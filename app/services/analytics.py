"""Business analytics built only from owner-scoped persisted records."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
from sqlalchemy import func
from app.extensions import db
from app.models import Invoice, Product, StockMovement, Transaction
from app.services.cashflow import available_cash_paise, transaction_cash_delta
from app.services.inventory import demand_map, stock_levels

IN_TYPES = {"income", "customer_payment"}
OUT_TYPES = {"expense", "supplier_payment", "refund"}

def _date_range(start: date | None, end: date | None):
    end = end or date.today()
    start = start or end
    if start > end:
        start, end = end, start
    return start, end

def daily_summary(business, start: date | None = None, end: date | None = None) -> dict:
    start, end = _date_range(start, end)
    txs = Transaction.query.filter(
        Transaction.business_id == business.id,
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end,
    ).order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).all()
    settled = [t for t in txs if t.payment_status == "settled"]
    sales = [t for t in settled if t.transaction_type == "income"]
    expenses = [t for t in settled if t.transaction_type == "expense"]
    refunds = [t for t in settled if t.transaction_type == "refund"]
    collections = [t for t in settled if t.transaction_type == "customer_payment"]
    purchases = [t for t in settled if t.transaction_type == "supplier_payment"]
    payment_breakdown = defaultdict(int)
    for t in collections + sales:
        payment_breakdown[t.payment_method] += int(t.amount_paise)
    # Purchase stock movements are shown separately because they are inventory, not operating expense.
    purchase_movements = StockMovement.query.filter(
        StockMovement.business_id == business.id,
        StockMovement.movement_type == "purchase",
        StockMovement.movement_date >= start,
        StockMovement.movement_date <= end,
    ).all()
    inventory_purchase_cost = sum(int(m.quantity_change) * int(m.unit_cost_paise or 0) for m in purchase_movements)
    open_credit = sum(i.outstanding_paise for i in Invoice.query.filter_by(business_id=business.id, invoice_type="receivable").all())
    product_sales = defaultdict(int)
    for m in StockMovement.query.filter(
        StockMovement.business_id == business.id,
        StockMovement.movement_type == "sale",
        StockMovement.movement_date >= start,
        StockMovement.movement_date <= end,
    ).all():
        product_sales[m.product_id] += abs(int(m.quantity_change))
    products = {p.id: p for p in Product.query.filter_by(business_id=business.id).all()}
    ranked = sorted(product_sales.items(), key=lambda x: (-x[1], products.get(x[0]).name if products.get(x[0]) else ""))
    top_products = [{"name": products[pid].name, "units": units, "product_id": pid} for pid, units in ranked[:5] if pid in products]
    low_products = [{"name": products[pid].name, "units": units, "product_id": pid} for pid, units in sorted(product_sales.items(), key=lambda x: x[1])[:5] if pid in products]
    by_day = defaultdict(lambda: {"sales": 0, "collections": 0, "expenses": 0, "purchases": 0})
    for t in settled:
        key = t.transaction_date.isoformat()
        if t.transaction_type == "income": by_day[key]["sales"] += int(t.amount_paise)
        elif t.transaction_type == "customer_payment": by_day[key]["collections"] += int(t.amount_paise)
        elif t.transaction_type == "expense": by_day[key]["expenses"] += int(t.amount_paise)
        elif t.transaction_type == "supplier_payment": by_day[key]["purchases"] += int(t.amount_paise)
    chart_labels = []
    cursor = start
    while cursor <= end:
        row = by_day[cursor.isoformat()]
        chart_labels.append({"date": cursor.isoformat(), **row})
        cursor += timedelta(days=1)
    revenue = sum(int(t.amount_paise) for t in sales)
    operating_expenses = sum(int(t.amount_paise) for t in expenses)
    estimated_profit = revenue - operating_expenses - sum(int(t.amount_paise) for t in refunds)
    return {
        "start": start, "end": end, "transactions": txs, "chart": chart_labels,
        "sales_paise": revenue, "purchases_paise": sum(int(t.amount_paise) for t in purchases) + inventory_purchase_cost,
        "inventory_purchase_paise": inventory_purchase_cost, "expenses_paise": operating_expenses,
        "collections_paise": sum(int(t.amount_paise) for t in collections),
        "refunds_paise": sum(int(t.amount_paise) for t in refunds), "estimated_profit_paise": estimated_profit,
        "cash_paise": available_cash_paise(business, end), "outstanding_credit_paise": open_credit,
        "payment_breakdown": dict(payment_breakdown), "sales_count": len(sales), "purchase_count": len(purchases) + len(purchase_movements),
        "khata_count": len([t for t in txs if t.customer_id and t.transaction_type in {"customer_payment", "income"}]),
        "top_products": top_products, "low_products": low_products,
        "recent": txs[:8], "profit_is_estimate": True,
    }

def decision_insights(business, summary: dict | None = None) -> list[dict]:
    summary = summary or daily_summary(business, date.today() - timedelta(days=29), date.today())
    stock = stock_levels(business.id)
    demand = demand_map(business.id, date.today())
    products = Product.query.filter_by(business_id=business.id, status="active").all()
    insights = []
    low = [p for p in products if p.min_stock and stock.get(p.id, 0) < p.min_stock]
    if low:
        names = ", ".join(p.name for p in low[:3])
        insights.append({"title": "Protect availability", "recommendation": f"Review reorder quantities for {names}.", "problem": "Stock is below the configured minimum.", "evidence": f"{len(low)} product(s) are below their minimum stock level.", "reasoning": "Low stock can interrupt sales; confirm supplier lead time and cash before approving a purchase.", "benefit": "Fewer avoidable stockouts.", "risk": "Ordering too much can tie up cash.", "confidence": "High", "href": "/inventory/alerts"})
    overdue = [i for i in Invoice.query.filter_by(business_id=business.id, invoice_type="receivable").all() if i.computed_status() == "overdue"]
    if overdue:
        amount = sum(i.outstanding_paise for i in overdue)
        insights.append({"title": "Prioritize collection", "recommendation": "Contact overdue customers before making discretionary purchases.", "problem": "Cash is tied up in overdue Khata balances.", "evidence": f"{len(overdue)} overdue receivable(s), totaling ₹{amount/100:,.2f}.", "reasoning": "Collections can improve cash flow without creating new stock obligations.", "benefit": "Faster cash conversion.", "risk": "Follow up respectfully and keep a record of contact.", "confidence": "High", "href": "/khata"})
    if not insights:
        insights.append({"title": "Keep records current", "recommendation": "Record today’s sales, payments, and expenses before deciding on the next purchase.", "problem": "Recommendations are only as reliable as the latest records.", "evidence": f"{summary['sales_count']} sale transaction(s) are in the selected period.", "reasoning": "Fresh records make stock, cash, and profitability comparisons more useful.", "benefit": "More dependable decisions.", "risk": "Incomplete records can hide obligations.", "confidence": "Moderate", "href": "/transactions/new"})
    return insights
