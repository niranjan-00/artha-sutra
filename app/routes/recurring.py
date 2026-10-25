from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import RecurringExpense
from app.routes.common import amount_paise, business_or_redirect, parse_date

bp = Blueprint("recurring", __name__)
FREQUENCIES = {"weekly", "biweekly", "monthly"}


def _validate(data):
    name = data.get("name", "").strip()
    category = data.get("category", "Operating").strip() or "Operating"
    frequency = data.get("frequency", "monthly").strip()
    amount = amount_paise(data.get("amount", ""))
    due_date = parse_date(data.get("next_due_date"), required=False)
    if not name or len(name) > 160 or len(category) > 80:
        raise ValueError("Enter a name and category within the supported length.")
    if frequency not in FREQUENCIES:
        raise ValueError("Choose weekly, biweekly or monthly frequency.")
    return name, category, frequency, amount, due_date


@bp.route("/recurring", methods=["GET", "POST"])
@login_required
def list_recurring():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    if request.method == "POST":
        try:
            name, category, frequency, amount, due_date = _validate(request.form)
            db.session.add(RecurringExpense(business_id=business.id, name=name, category=category, frequency=frequency, amount_paise=amount, next_due_date=due_date, is_active=True))
            db.session.commit()
            flash("Recurring expense saved and added to future forecasts.", "success")
            return redirect(url_for("recurring.list_recurring"))
        except ValueError as error:
            flash(str(error), "danger")
    expenses = RecurringExpense.query.filter_by(business_id=business.id).order_by(RecurringExpense.is_active.desc(), RecurringExpense.next_due_date.asc()).all()
    return render_template("finance/recurring.html", expenses=expenses, frequencies=sorted(FREQUENCIES))


@bp.route("/recurring/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_recurring(expense_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    expense = RecurringExpense.query.filter_by(id=expense_id, business_id=business.id).first_or_404()
    if request.method == "POST":
        try:
            name, category, frequency, amount, due_date = _validate(request.form)
            expense.name, expense.category, expense.frequency = name, category, frequency
            expense.amount_paise, expense.next_due_date = amount, due_date
            db.session.commit()
            flash("Recurring expense updated; forecast dates were recalculated.", "success")
            return redirect(url_for("recurring.list_recurring"))
        except ValueError as error:
            flash(str(error), "danger")
    return render_template("finance/recurring_edit.html", expense=expense, frequencies=sorted(FREQUENCIES))


@bp.post("/recurring/<int:expense_id>/toggle")
@login_required
def toggle_recurring(expense_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    expense = RecurringExpense.query.filter_by(id=expense_id, business_id=business.id).first_or_404()
    expense.is_active = not expense.is_active
    db.session.commit()
    flash("Recurring expense " + ("included in" if expense.is_active else "removed from") + " future forecasts.", "success")
    return redirect(url_for("recurring.list_recurring"))
