from calendar import Calendar, monthrange
from datetime import date, timedelta

from app.models import Invoice, RecurringExpense, Transaction
from app.services.cashflow import _future_events, available_cash_paise, transaction_cash_delta


def build_month_calendar(business, year: int, month: int, today: date | None = None) -> dict:
    """Return one business's month grid, actual history and dated estimates."""
    today = today or date.today()
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    # Forecast rules start at today. Earlier expected dates are handled by the
    # shared forecast service (overdue outflows become due today; receipts stay uncertain).
    events, missing_dates = _future_events(business, today, max(today, last))
    invoices = {x.id: x for x in Invoice.query.filter_by(business_id=business.id).all()}
    transactions = {x.id: x for x in Transaction.query.filter_by(business_id=business.id).all()}
    recurring = {x.id: x for x in RecurringExpense.query.filter_by(business_id=business.id).all()}
    grouped: dict[date, list[dict]] = {}
    signed_by_date: dict[date, int] = {}
    expected_in = expected_out = 0

    actual_end = min(last, today)
    actual_start = max(first, business.financial_start_date)
    actuals = []
    if actual_start <= actual_end:
        actuals = Transaction.query.filter_by(business_id=business.id, payment_status="settled").filter(
            Transaction.transaction_date >= actual_start,
            Transaction.transaction_date <= actual_end,
        ).order_by(Transaction.transaction_date, Transaction.id).all()
    actual_in = actual_out = 0
    for tx in actuals:
        signed = transaction_cash_delta(tx)
        if not signed:
            continue
        grouped.setdefault(tx.transaction_date, []).append({
            "date": tx.transaction_date, "title": tx.description,
            "detail": f"{tx.category} · {tx.payment_method}",
            "direction": "receipt" if signed > 0 else "bill", "amount_paise": abs(signed),
            "status": "Settled", "source_type": "transaction", "record_id": tx.id,
            "actual": True,
        })
        if signed > 0:
            actual_in += signed
        else:
            actual_out += -signed

    for event in events:
        day = event["date"]
        signed = int(event["signed_paise"])
        signed_by_date[day] = signed_by_date.get(day, 0) + signed
        if not first <= day <= last:
            continue
        kind, record_id = event["source_type"], event["record_id"]
        title, detail, status = event["label"], "Expected movement", "Expected"
        if kind == "invoice":
            invoice = invoices.get(record_id)
            if invoice:
                party = invoice.customer.name if invoice.invoice_type == "receivable" and invoice.customer else invoice.supplier.name if invoice.supplier else ("Customer" if signed > 0 else "Supplier")
                title = party
                due_label = invoice.due_date.isoformat() if invoice.due_date else "date not set"
                detail = f"Invoice {invoice.invoice_number} · Due {due_label}"
                if invoice.due_date and invoice.due_date < today:
                    status = "Overdue · due now"
                    detail += f" · Original due date {invoice.due_date.isoformat()}"
        elif kind == "transaction":
            tx = transactions.get(record_id)
            if tx:
                title = tx.description
                detail = f"{tx.category} · Scheduled movement"
                if tx.transaction_date < today:
                    status = "Overdue · due now"
                    detail += f" · Original date {tx.transaction_date.isoformat()}"
                else:
                    status = "Pending"
        elif kind == "recurring":
            item = recurring.get(record_id)
            if item:
                title = item.name
                detail = f"{item.frequency.title()} recurring expense · {item.category}"
                status = "Scheduled"
        direction = "receipt" if signed > 0 else "bill"
        grouped.setdefault(day, []).append({
            "date": day, "title": title, "detail": detail, "direction": direction,
            "amount_paise": abs(signed), "status": status, "source_type": kind,
            "record_id": record_id, "actual": False,
        })
        if signed > 0:
            expected_in += signed
        else:
            expected_out += -signed

    overdue_receipts = []
    for invoice in invoices.values():
        if invoice.invoice_type == "receivable" and invoice.outstanding_paise > 0 and invoice.due_date and invoice.due_date < today:
            overdue_receipts.append({
                "title": invoice.customer.name if invoice.customer else "Customer",
                "detail": f"Invoice {invoice.invoice_number} · due {invoice.due_date.isoformat()}",
                "amount_paise": invoice.outstanding_paise, "source_type": "invoice",
                "record_id": invoice.id, "due_date": invoice.due_date,
            })
    overdue_receipts.sort(key=lambda item: item["due_date"])

    closing = {}
    if last < today:
        for offset in range((last - first).days + 1):
            day = first + timedelta(days=offset)
            closing[day] = available_cash_paise(business, day) if day >= business.financial_start_date else None
    else:
        running = available_cash_paise(business, today)
        for offset in range((max(last, today) - today).days + 1):
            day = today + timedelta(days=offset)
            running += signed_by_date.get(day, 0)
            if first <= day <= last:
                closing[day] = running
        for offset in range((min(today, last) - first).days + 1):
            day = first + timedelta(days=offset)
            if day < today:
                closing[day] = available_cash_paise(business, day) if day >= business.financial_start_date else None

    weeks = []
    by_day = {}
    reserve = int(business.minimum_cash_reserve_paise or 0)
    for week in Calendar(firstweekday=0).monthdayscalendar(year, month):
        cells = []
        for number in week:
            if number == 0:
                cells.append(None)
                continue
            day = date(year, month, number)
            items = grouped.get(day, [])
            items.sort(key=lambda x: (not x["actual"], x["direction"] != "receipt", x["title"].casefold()))
            def total(actual, direction):
                return sum(x["amount_paise"] for x in items if x["actual"] is actual and x["direction"] == direction)
            close = closing.get(day)
            cell = {
                "date": day, "iso": day.isoformat(), "day": number, "is_today": day == today,
                "is_past": day < today, "events": items,
                "actual_in_paise": total(True, "receipt"), "actual_out_paise": total(True, "bill"),
                "expected_in_paise": total(False, "receipt"), "expected_out_paise": total(False, "bill"),
                "closing_paise": close, "below_reserve": close is not None and close < reserve,
            }
            cells.append(cell)
            by_day[day.isoformat()] = cell
        weeks.append(cells)
    return {
        "year": year, "month": f"{year:04d}-{month:02d}", "label": first.strftime("%B %Y"),
        "weeks": weeks, "by_day": by_day,
        "expected_totals": {"in_paise": expected_in, "out_paise": expected_out},
        "actual_totals": {"in_paise": actual_in, "out_paise": actual_out},
        "missing_dates": missing_dates, "overdue_receipts": overdue_receipts,
    }
