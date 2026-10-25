from calendar import monthrange
from datetime import date, timedelta

from app.models import Invoice, RecurringExpense, Transaction


IN_TYPES = {"income", "customer_payment"}
OUT_TYPES = {"expense", "supplier_payment", "refund"}


def transaction_cash_delta(transaction: Transaction) -> int:
    if transaction.payment_status != "settled" or transaction.transaction_type == "transfer":
        return 0
    if transaction.transaction_type in IN_TYPES:
        return int(transaction.amount_paise)
    if transaction.transaction_type in OUT_TYPES:
        return -int(transaction.amount_paise)
    return 0


def available_cash_paise(business, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    balance = int(business.opening_balance_paise or 0)
    movements = Transaction.query.filter(
        Transaction.business_id == business.id,
        Transaction.payment_status == "settled",
        Transaction.transaction_date >= business.financial_start_date,
        Transaction.transaction_date <= as_of,
    ).all()
    return balance + sum(transaction_cash_delta(item) for item in movements)


def _add_months(day: date, anchor_day: int | None = None) -> date:
    month_index = day.month - 1 + 1
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(anchor_day or day.day, monthrange(year, month)[1]))


def _next_due(day: date, frequency: str, anchor_day: int | None = None) -> date | None:
    if frequency == "weekly":
        return day + timedelta(days=7)
    if frequency == "biweekly":
        return day + timedelta(days=14)
    if frequency == "monthly":
        return _add_months(day, anchor_day)
    return None


def _new_event(day: date, signed_amount: int, label: str, source_type: str, record_id=None) -> dict:
    return {
        "date": day,
        "signed_paise": int(signed_amount),
        "label": label,
        "source_type": source_type,
        "record_id": record_id,
    }


def _future_events(business, today: date, end: date) -> tuple[list[dict], int]:
    events: list[dict] = []
    missing_dates = 0

    pending_transactions = Transaction.query.filter_by(
        business_id=business.id, payment_status="pending"
    ).all()
    for transaction in pending_transactions:
        if transaction.transaction_date > end:
            continue
        if transaction.transaction_date < today:
            if transaction.transaction_type in OUT_TYPES:
                events.append(_new_event(today, -int(transaction.amount_paise), f"Overdue · {transaction.description}", "transaction", transaction.id))
            elif transaction.transaction_type in IN_TYPES:
                missing_dates += 1
            continue
        signed = transaction_cash_delta(transaction) if transaction.payment_status == "settled" else 0
        if transaction.transaction_type in IN_TYPES:
            signed = int(transaction.amount_paise)
        elif transaction.transaction_type in OUT_TYPES:
            signed = -int(transaction.amount_paise)
        else:
            continue
        events.append(_new_event(transaction.transaction_date, signed, transaction.description, "transaction", transaction.id))

    invoices = Invoice.query.filter_by(business_id=business.id).all()
    for invoice in invoices:
        outstanding = invoice.outstanding_paise
        if outstanding <= 0:
            continue
        due = invoice.due_date
        if due is None:
            missing_dates += 1
            continue
        if invoice.invoice_type == "receivable":
            # Overdue customer receipts are uncertain and excluded until a new future date is recorded.
            if due < today:
                continue
            if due <= end:
                party = invoice.customer.name if invoice.customer else "Customer invoice"
                events.append(_new_event(due, outstanding, f"{party} · {invoice.invoice_number}", "invoice", invoice.id))
        else:
            # Overdue supplier balances are treated as due now rather than as settled cash already paid.
            scheduled = max(due, today)
            if scheduled <= end:
                party = invoice.supplier.name if invoice.supplier else "Supplier bill"
                events.append(_new_event(scheduled, -outstanding, f"{party} · {invoice.invoice_number}", "invoice", invoice.id))

    recurring = RecurringExpense.query.filter_by(business_id=business.id, is_active=True).all()
    for item in recurring:
        if item.next_due_date is None:
            missing_dates += 1
            continue
        scheduled = item.next_due_date
        anchor_day = scheduled.day
        if scheduled < today:
            scheduled = today
        iterations = 0
        while scheduled <= end and iterations < 100:
            events.append(_new_event(scheduled, -int(item.amount_paise), item.name, "recurring", item.id))
            scheduled = _next_due(scheduled, item.frequency, anchor_day)
            if scheduled is None:
                break
            iterations += 1

    return events, missing_dates


def _apply_scenario(events: list[dict], scenario: dict, today: date, end: date) -> list[dict]:
    """Return a copied event list with a validated, non-persistent adjustment applied."""
    adjusted = [dict(event) for event in events]
    action = scenario.get("action")
    record_id = int(scenario.get("record_id") or 0)
    days = int(scenario.get("days") or 0)
    amount = int(scenario.get("amount_paise") or 0)
    target = None
    if action in {"delay_supplier", "shift_receipt", "reduce_expense", "adjust_receipt"}:
        expected_type = "transaction" if action == "reduce_expense" else "invoice"
        for event in adjusted:
            if event["source_type"] == expected_type and event["record_id"] == record_id:
                target = event
                break
        if target is None:
            raise ValueError("That item is not in the selected forecast range.")
        assert target is not None

    if action == "delay_supplier":
        if target["signed_paise"] >= 0 or days < 1 or days > 60:
            raise ValueError("Choose an upcoming supplier payment and a delay from 1 to 60 days.")
        target["date"] = target["date"] + timedelta(days=days)
        target["label"] += " (scenario: delayed)"
    elif action == "shift_receipt":
        if target["signed_paise"] <= 0 or not -30 <= days <= 30 or days == 0:
            raise ValueError("Choose a future customer receipt and move it by 1–30 days.")
        target["date"] = max(today, target["date"] + timedelta(days=days))
        target["label"] += " (scenario: date moved)"
    elif action == "add_expense":
        scenario_date = scenario.get("date")
        if amount <= 0 or not isinstance(scenario_date, date) or not today <= scenario_date <= end:
            raise ValueError("Enter a positive expense and a date inside the forecast range.")
        adjusted.append(_new_event(scenario_date, -amount, "Unexpected scenario expense", "scenario"))
    elif action == "reduce_expense":
        if target["signed_paise"] >= 0 or amount <= 0 or amount > -target["signed_paise"]:
            raise ValueError("The reduction must be positive and no greater than the selected expense.")
        target["signed_paise"] += amount
        target["label"] += " (scenario: reduced)"
    elif action == "adjust_receipt":
        if target["signed_paise"] <= 0 or amount == 0 or target["signed_paise"] + amount <= 0:
            raise ValueError("Choose a future receipt and enter a non-zero adjustment that keeps it positive.")
        target["signed_paise"] += amount
        target["label"] += " (scenario: amount changed)"
    else:
        raise ValueError("Choose a supported scenario adjustment.")

    return [event for event in adjusted if today <= event["date"] <= end]


def calculate_forecast(business, days: int = 30, scenario: dict | None = None, today: date | None = None) -> dict:
    """Calculate a deterministic forecast. Amounts are integer paise throughout."""
    if days not in {7, 30, 90}:
        raise ValueError("Forecast range must be 7, 30, or 90 days.")
    today = today or date.today()
    end = today + timedelta(days=days)
    starting_cash = available_cash_paise(business, today)
    events, missing_dates = _future_events(business, today, end)
    if scenario:
        events = _apply_scenario(events, scenario, today, end)

    by_date: dict[date, list[dict]] = {}
    for event in events:
        by_date.setdefault(event["date"], []).append(event)

    reserve = int(business.minimum_cash_reserve_paise or 0)
    balance = starting_cash
    rows = []
    first_risk = None
    for offset in range(days + 1):
        day = today + timedelta(days=offset)
        inflows = 0
        outflows = 0
        descriptions = []
        for event in by_date.get(day, []):
            signed = int(event["signed_paise"])
            if signed >= 0:
                inflows += signed
            else:
                outflows += -signed
            balance += signed
            descriptions.append(event["label"])
        below_reserve = balance < reserve
        explanation = None
        if below_reserve:
            if descriptions:
                explanation = "After " + ", ".join(descriptions[:3]) + (" and other scheduled movements" if len(descriptions) > 3 else "")
            elif day == today:
                explanation = "Current available cash is already below the desired reserve."
            else:
                explanation = "Projected balance remains below the desired reserve."
            if first_risk is None:
                first_risk = {
                    "date": day.isoformat(),
                    "balance_paise": balance,
                    "reserve_paise": reserve,
                    "shortfall_paise": max(reserve - balance, 0),
                    "negative": balance < 0,
                    "explanation": explanation,
                }
        rows.append({
            "date": day.isoformat(),
            "inflows_paise": inflows,
            "outflows_paise": outflows,
            "balance_paise": balance,
            "reserve_paise": reserve,
            "below_reserve": below_reserve,
            "risk_explanation": explanation,
            "event_labels": descriptions,
        })

    return {
        "days": days,
        "starting_cash_paise": starting_cash,
        "reserve_paise": reserve,
        "rows": rows,
        "risk": first_risk,
        "missing_dates": missing_dates,
        "end_date": end.isoformat(),
        "events": events,
    }
