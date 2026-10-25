from datetime import date, timedelta

from app.extensions import db
from app.models import Invoice, Notification


def recommend_next_action(business, forecast: dict) -> dict:
    today = date.today()
    overdue_receivable = Invoice.query.filter(
        Invoice.business_id == business.id,
        Invoice.invoice_type == "receivable",
        Invoice.due_date < today,
        Invoice.total_amount_paise > Invoice.amount_paid_paise,
    ).order_by(Invoice.due_date.asc()).first()
    if overdue_receivable:
        party = overdue_receivable.customer.name if overdue_receivable.customer else "your customer"
        return {
            "eyebrow": "Receivable follow-up",
            "title": f"Follow up with {party}",
            "reason": f"Invoice {overdue_receivable.invoice_number} is overdue; ₹{overdue_receivable.outstanding_paise / 100:,.2f} remains outstanding.",
            "href": f"/invoices/{overdue_receivable.id}",
            "cta": "Review invoice",
        }
    if forecast.get("risk"):
        risk = forecast["risk"]
        return {
            "eyebrow": "Reserve protection",
            "title": "Review the first projected cash shortfall",
            "reason": f"On {risk['date']}, projected cash is below your reserve. {risk['explanation']}",
            "href": "/forecast",
            "cta": "Investigate forecast",
        }
    upcoming = Invoice.query.filter(
        Invoice.business_id == business.id,
        Invoice.invoice_type == "payable",
        Invoice.due_date >= today,
        Invoice.total_amount_paise > Invoice.amount_paid_paise,
    ).order_by(Invoice.due_date.asc()).first()
    if upcoming:
        party = upcoming.supplier.name if upcoming.supplier else "your supplier"
        return {
            "eyebrow": "Upcoming payment",
            "title": f"Prepare for {party}",
            "reason": f"Bill {upcoming.invoice_number} is due {upcoming.due_date.isoformat()} with ₹{upcoming.outstanding_paise / 100:,.2f} remaining.",
            "href": f"/invoices/{upcoming.id}",
            "cta": "Review bill",
        }
    if forecast.get("missing_dates"):
        return {
            "eyebrow": "Forecast completeness",
            "title": "Add missing payment dates",
            "reason": f"{forecast['missing_dates']} open item(s) have no due date and are excluded from the dated forecast.",
            "href": "/bills",
            "cta": "Review bills",
        }
    return {
        "eyebrow": "Keep your forecast useful",
        "title": "Record today’s cash movement",
        "reason": "Recent settled entries help the daily forecast reflect how money actually moves through your business.",
        "href": "/transactions/new",
        "cta": "Add transaction",
    }


def refresh_notifications(business, forecast: dict) -> None:
    today = date.today()
    existing_keys = {
        item.dedupe_key
        for item in Notification.query.filter_by(business_id=business.id).all()
    }
    changed = False
    open_invoices = Invoice.query.filter(
        Invoice.business_id == business.id,
        Invoice.total_amount_paise > Invoice.amount_paid_paise,
    ).all()
    for invoice in open_invoices:
        if invoice.invoice_type == "receivable" and invoice.due_date and invoice.due_date < today:
            key = f"overdue-invoice-{invoice.id}"
            title = "Customer invoice overdue"
            message = f"Invoice {invoice.invoice_number} is overdue; ₹{invoice.outstanding_paise / 100:,.2f} remains outstanding."
            kind = "overdue"
        elif invoice.invoice_type == "payable" and invoice.due_date and today <= invoice.due_date <= today + timedelta(days=3):
            key = f"upcoming-payable-{invoice.id}"
            title = "Supplier payment coming up"
            message = f"Bill {invoice.invoice_number} is due {invoice.due_date.isoformat()}; ₹{invoice.outstanding_paise / 100:,.2f} remains."
            kind = "upcoming"
        else:
            continue
        if key not in existing_keys:
            db.session.add(Notification(
                business_id=business.id,
                title=title,
                message=message,
                notification_type=kind,
                related_record_type="invoice",
                related_record_id=invoice.id,
                dedupe_key=key,
            ))
            existing_keys.add(key)
            changed = True

    risk = forecast.get("risk")
    if risk:
        key = f"forecast-risk-{risk['date']}"
        if key not in existing_keys:
            db.session.add(Notification(
                business_id=business.id,
                title="Projected reserve breach",
                message=f"Projected cash on {risk['date']} is ₹{risk['shortfall_paise'] / 100:,.2f} below your reserve.",
                notification_type="critical" if risk["negative"] else "risk",
                related_record_type="forecast",
                related_record_id=None,
                dedupe_key=key,
            ))
            changed = True
    if changed:
        db.session.commit()
