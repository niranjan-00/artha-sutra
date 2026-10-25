from datetime import date

from flask import Blueprint, render_template, request, url_for
from flask_login import login_required

from app.routes.common import business_or_redirect
from app.services.calendar import calendar_entries, day_totals, month_bounds, month_grid, shift_month
from app.services.cashflow import available_cash_paise, calculate_forecast

bp = Blueprint("cashcal", __name__)


def _parse_month(raw: str | None, today: date) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in (raw or "").split("-"))
        date(year, month, 1)
        if 2000 <= year <= 2100:
            return year, month
    except ValueError:
        pass
    return today.year, today.month


@bp.get("/calendar")
@login_required
def calendar_page():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    today = date.today()
    year, month = _parse_month(request.args.get("month"), today)
    first, last = month_bounds(year, month)
    entries, undated = calendar_entries(business, first, last, today, url_for)

    try:
        selected = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        selected = None
    if selected is None or not first <= selected <= last:
        selected = today if first <= today <= last else first

    # Projected closing balance is only available inside the 90-day forecast horizon.
    forecast = calculate_forecast(business, days=90, today=today)
    balances = {row["date"]: row["balance_paise"] for row in forecast["rows"]}
    reserve = forecast["reserve_paise"]

    weeks = []
    for week in month_grid(year, month):
        cells = []
        for day in week:
            if day is None:
                cells.append(None)
                continue
            items = entries.get(day, [])
            totals = day_totals(items)
            balance = balances.get(day.isoformat())
            cells.append({
                "date": day, "iso": day.isoformat(), "entries": items, "totals": totals,
                "is_today": day == today, "is_selected": day == selected,
                "has_overdue": any(i["overdue"] for i in items),
                "balance_paise": balance, "below_reserve": balance is not None and balance < reserve,
            })
        weeks.append(cells)

    all_items = [i for items in entries.values() for i in items]
    month_totals = day_totals(all_items)
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    return render_template(
        "finance/calendar.html", business=business, weeks=weeks, year=year, month=month,
        month_label=first.strftime("%B %Y"), month_totals=month_totals, undated=undated,
        selected=selected, selected_entries=entries.get(selected, []),
        selected_totals=day_totals(entries.get(selected, [])), selected_balance=balances.get(selected.isoformat()),
        prev_month=f"{prev_year:04d}-{prev_month:02d}", next_month=f"{next_year:04d}-{next_month:02d}",
        this_month=f"{today.year:04d}-{today.month:02d}", today=today, cash=available_cash_paise(business, today),
        reserve=reserve, overdue_count=sum(1 for i in all_items if i["overdue"]),
    )
