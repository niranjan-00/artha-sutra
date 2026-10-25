from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.routes.common import business_or_redirect
from app.services.calendar import build_month_calendar

bp = Blueprint("calendar", __name__)


def _month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


def _entry_url(entry: dict) -> str:
    if entry["source_type"] == "invoice":
        return url_for("invoices.invoice_detail", invoice_id=entry["record_id"])
    if entry["source_type"] == "transaction":
        return url_for("transactions.transaction_detail", transaction_id=entry["record_id"])
    if entry["source_type"] == "recurring":
        return url_for("recurring.list_recurring")
    return url_for("calendar.cash_calendar")


@bp.get("/cash-calendar")
@login_required
def cash_calendar():
    business, response = business_or_redirect()
    if response:
        return response
    today = date.today()
    raw_month = request.args.get("month", today.strftime("%Y-%m"))
    try:
        selected_month = date.fromisoformat(raw_month + "-01")
    except ValueError:
        flash("Choose a valid calendar month.", "warning")
        return redirect(url_for("calendar.cash_calendar"))
    offset = (selected_month.year - today.year) * 12 + selected_month.month - today.month
    if abs(offset) > 12:
        flash("The cash calendar shows up to twelve months in either direction.", "info")
        return redirect(url_for("calendar.cash_calendar"))
    data = build_month_calendar(business, selected_month.year, selected_month.month, today=today)
    for cell in data["by_day"].values():
        for entry in cell["events"]:
            entry["href"] = _entry_url(entry)
    for entry in data["overdue_receipts"]:
        entry["href"] = _entry_url(entry)
    fallback_day = today if offset == 0 else selected_month
    raw_day = request.args.get("day", "")
    try:
        selected_day = date.fromisoformat(raw_day) if raw_day else fallback_day
    except ValueError:
        selected_day = fallback_day
    if selected_day.year != selected_month.year or selected_day.month != selected_month.month:
        selected_day = fallback_day
    data["selected_day"] = data["by_day"].get(selected_day.isoformat())
    py, pm = _month_shift(selected_month.year, selected_month.month, -1)
    ny, nm = _month_shift(selected_month.year, selected_month.month, 1)
    return render_template(
        "finance/calendar.html", calendar=data, business=business, selected_day=selected_day,
        today=today, today_month=today.strftime("%Y-%m"),
        previous_month=f"{py:04d}-{pm:02d}", next_month=f"{ny:04d}-{nm:02d}",
        can_previous=offset > -12, can_next=offset < 12,
    )
