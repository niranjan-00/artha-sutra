from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user

from app.extensions import db
from app.models import Business, Invoice, Notification, Transaction, User
from app.routes.common import amount_paise, business_or_redirect, parse_date
from app.services.cashflow import calculate_forecast
from app.services.demo import reset_demo_workspace
from app.services.money import parse_rupees
from app.services.recommendations import recommend_next_action, refresh_notifications

bp = Blueprint("finance", __name__)
BUSINESS_TYPES = ["Retail", "Grocery", "Wholesale", "Restaurant / café", "Services", "Manufacturing", "Other"]


def _days_from_request():
    raw = request.args.get("days", "30")
    return int(raw) if raw in {"7", "30", "90"} else 30


def _chart(forecast):
    return {
        "labels": [row["date"] for row in forecast["rows"]],
        "balance": [round(row["balance_paise"] / 100, 2) for row in forecast["rows"]],
        "reserve": [round(row["reserve_paise"] / 100, 2) for row in forecast["rows"]],
        "risk": [row["date"] for row in forecast["rows"] if row["below_reserve"]],
    }


@bp.get("/forecast")
@login_required
def forecast_page():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    days = _days_from_request()
    forecast = calculate_forecast(business, days=days)
    refresh_notifications(business, forecast)
    action = recommend_next_action(business, forecast)
    chart = _chart(forecast)
    return render_template("finance/forecast.html", forecast=forecast, days=days, chart=chart, action=action)


@bp.get("/api/forecast")
@login_required
def forecast_api():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return jsonify(error="Business setup required"), 409
    assert business is not None
    try:
        days = int(request.args.get("days", "30"))
        if days not in {7, 30, 90}:
            raise ValueError
    except ValueError:
        return jsonify(error="days must be 7, 30, or 90"), 400
    forecast = calculate_forecast(business, days=days)
    return jsonify({
        "days": forecast["days"],
        "starting_cash_paise": forecast["starting_cash_paise"],
        "reserve_paise": forecast["reserve_paise"],
        "missing_dates": forecast["missing_dates"],
        "risk": forecast["risk"],
        "rows": [{key: row[key] for key in ("date", "inflows_paise", "outflows_paise", "balance_paise", "reserve_paise", "below_reserve", "risk_explanation")} for row in forecast["rows"]],
    })


def _signed_rupees(value: str) -> int:
    raw = (value or "").strip().replace("₹", "").replace(",", "")
    try:
        decimal_value = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError("Enter a valid adjustment amount.") from error
    if not decimal_value.is_finite() or decimal_value == 0:
        raise ValueError("Adjustment must be a non-zero amount.")
    negative = decimal_value < 0
    paise = parse_rupees(str(abs(decimal_value)))
    return -paise if negative else paise


@bp.route("/scenarios", methods=["GET", "POST"])
@login_required
def scenarios():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    today = date.today()
    days = 90
    baseline = calculate_forecast(business, days=days)
    candidates_receivable = Invoice.query.filter_by(business_id=business.id, invoice_type="receivable").all()
    candidates_payable = Invoice.query.filter_by(business_id=business.id, invoice_type="payable").all()
    invoices = [invoice for invoice in candidates_receivable + candidates_payable if invoice.outstanding_paise and invoice.due_date and today <= invoice.due_date <= today + timedelta(days=days)]
    pending_expenses = Transaction.query.filter_by(business_id=business.id, payment_status="pending", transaction_type="expense").filter(Transaction.transaction_date >= today, Transaction.transaction_date <= today + timedelta(days=days)).all()
    comparison = None
    scenario = None
    if request.method == "POST":
        try:
            action = request.form.get("action", "").strip()
            record_id_raw = request.form.get("record_id", "0").strip()
            record_id = int(record_id_raw or 0)
            days_shift = int(request.form.get("days", "0"))
            amount_value = request.form.get("amount", "").strip()
            amount = 0
            scenario_date = None
            if action == "add_expense":
                amount = amount_paise(amount_value)
                scenario_date = parse_date(request.form.get("scenario_date"))
            elif action in {"reduce_expense", "delay_supplier", "shift_receipt"}:
                if action == "reduce_expense":
                    amount = amount_paise(amount_value)
            elif action == "adjust_receipt":
                amount = _signed_rupees(amount_value)
            else:
                raise ValueError("Choose one of the listed scenario adjustments.")
            scenario = {
                "action": action,
                "record_id": record_id,
                "days": days_shift,
                "amount_paise": amount,
                "date": scenario_date,
            }
            alternative = calculate_forecast(business, days=days, scenario=scenario)
            baseline_risk = baseline["risk"]["date"] if baseline["risk"] else None
            alternative_risk = alternative["risk"]["date"] if alternative["risk"] else None
            baseline_end = baseline["rows"][-1]["balance_paise"]
            alternative_end = alternative["rows"][-1]["balance_paise"]
            comparison = {
                "baseline": baseline,
                "alternative": alternative,
                "difference_paise": alternative_end - baseline_end,
                "baseline_risk": baseline_risk,
                "alternative_risk": alternative_risk,
                "description": {
                    "delay_supplier": f"Move supplier payment by {days_shift} days",
                    "shift_receipt": f"Move customer receipt by {days_shift} days",
                    "add_expense": "Add an unexpected expense",
                    "reduce_expense": "Reduce a planned expense",
                    "adjust_receipt": "Change an expected customer receipt amount",
                }[action],
                "chart": _chart(alternative),
            }
        except (ValueError, TypeError) as error:
            flash(str(error), "danger")
        except Exception:
            flash("The scenario could not be calculated. No actual records were changed.", "danger")
    return render_template("finance/scenarios.html", baseline=baseline, comparison=comparison, scenario=scenario, invoices=invoices, pending_expenses=pending_expenses, today=today, end_date=today + timedelta(days=days))


@bp.get("/notifications")
@login_required
def notifications_page():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    items = Notification.query.filter_by(business_id=business.id).order_by(Notification.created_at.desc()).limit(100).all()
    return render_template("finance/notifications.html", notifications=items)


@bp.post("/notifications/<int:notification_id>/read")
@login_required
def mark_notification_read(notification_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    item = Notification.query.filter_by(id=notification_id, business_id=business.id).first_or_404()
    item.is_read = True
    db.session.commit()
    flash("Notification marked as read.", "success")
    target = request.form.get("next", "").strip()
    if target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(url_for("finance.notifications_page"))


@bp.post("/notifications/read-all")
@login_required
def mark_all_notifications_read():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    Notification.query.filter_by(business_id=business.id, is_read=False).update({"is_read": True})
    db.session.commit()
    flash("All notifications marked as read.", "success")
    return redirect(url_for("finance.notifications_page"))


@bp.get("/api/notifications")
@login_required
def notifications_api():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return jsonify(error="Business setup required"), 409
    assert business is not None
    items = Notification.query.filter_by(business_id=business.id).order_by(Notification.created_at.desc()).limit(50).all()
    return jsonify(notifications=[{"id": item.id, "title": item.title, "message": item.message, "type": item.notification_type, "read": item.is_read} for item in items])


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    if request.method == "POST":
        try:
            name = request.form.get("business_name", "").strip()
            kind = request.form.get("business_type", "Other").strip()
            custom = request.form.get("custom_type", "").strip()
            city = request.form.get("city", "").strip()
            state = request.form.get("state", "").strip()
            address = request.form.get("address", "").strip()
            opening = amount_paise(request.form.get("opening_balance", ""), allow_zero=True)
            reserve = amount_paise(request.form.get("minimum_cash_reserve", ""), allow_zero=True)
            start = parse_date(request.form.get("financial_start_date"))
            profile_name = request.form.get("profile_name", "").strip()
            profile_email = request.form.get("profile_email", "").strip().lower()
            theme = request.form.get("theme", current_user.theme).strip().lower()
            language = request.form.get("language", current_user.language).strip().lower()
            if not name or len(name) > 160 or not city or not state or len(address) > 300:
                raise ValueError("Enter a valid business name, city, state and address.")
            if kind not in BUSINESS_TYPES:
                raise ValueError("Choose a valid business category.")
            if kind == "Other":
                if not custom or len(custom) > 80:
                    raise ValueError("Enter the custom business category.")
                kind = custom
            if not profile_name or len(profile_name) > 120 or len(profile_email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", profile_email):
                raise ValueError("Enter a valid profile name and email address.")
            if theme not in {"light", "dark"}:
                raise ValueError("Choose either light or dark appearance.")
            if language not in {"en", "kn", "hi", "mr"}:
                raise ValueError("Choose a supported language preference.")
            duplicate = User.query.filter(User.email == profile_email, User.id != current_user.id).first()
            if duplicate:
                raise ValueError("That email address is already used by another account.")
            business.name = name
            business.business_type = kind
            business.city = city
            business.state = state
            business.address = address or None
            business.currency = "INR"
            business.opening_balance_paise = opening
            business.minimum_cash_reserve_paise = reserve
            business.financial_start_date = start
            current_user.name = profile_name
            current_user.email = profile_email
            current_user.theme = theme
            current_user.language = language
            db.session.commit()
            flash("Settings saved. Historical transaction records were not rewritten.", "success")
            return redirect(url_for("finance.settings"))
        except ValueError as error:
            flash(str(error), "danger")
        except Exception:
            db.session.rollback()
            flash("Settings were not saved. Please review the form and try again.", "danger")
    return render_template("finance/settings.html", business=business, business_types=BUSINESS_TYPES)


@bp.post("/profile/theme")
@login_required
def set_theme():
    desired = request.form.get("theme", "").strip().lower()
    if desired not in {"light", "dark"}:
        flash("Choose either light or dark appearance.", "danger")
        desired = "light" if current_user.theme == "dark" else "dark"
    current_user.theme = desired
    db.session.commit()
    target = request.form.get("next", "").strip()
    if not target.startswith("/") or target.startswith("//"):
        target = url_for("main.dashboard")
    return redirect(target)


@bp.post("/demo/reset")
@login_required
def demo_reset():
    if not current_user.is_demo:
        abort(404)
    user = reset_demo_workspace()
    login_user(user, remember=False, fresh=True)
    flash("The fictional demo workspace has been reset. Personal businesses are unaffected.", "success")
    return redirect(url_for("main.dashboard"))
