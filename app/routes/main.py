from datetime import date, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user

from app.extensions import db
from app.models import Business, Invoice, Transaction, User
from app.routes.common import amount_paise, parse_date
from app.services.cashflow import available_cash_paise, calculate_forecast
from app.services.demo import DEMO_EMAIL, reset_demo_workspace
from app.services.recommendations import recommend_next_action, refresh_notifications

bp = Blueprint("main", __name__)
BUSINESS_TYPES = ["Retail", "Grocery", "Wholesale", "Restaurant / café", "Services", "Manufacturing", "Other"]


@bp.get("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard" if current_user.business else "main.getting_started"))
    return render_template("index.html")


@bp.route("/getting-started", methods=["GET", "POST"])
def getting_started():
    if not current_user.is_authenticated:
        return render_template("getting_started.html", public_mode=True, business_types=BUSINESS_TYPES)
    if current_user.business:
        return render_template("getting_started.html", public_mode=False, business_types=BUSINESS_TYPES, business=current_user.business)
    if request.method == "POST":
        name = request.form.get("business_name", "").strip()
        business_type = request.form.get("business_type", "Other").strip()
        custom_type = request.form.get("custom_type", "").strip()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        address = request.form.get("address", "").strip()
        try:
            opening = amount_paise(request.form.get("opening_balance", "0"), allow_zero=True)
            reserve = amount_paise(request.form.get("minimum_cash_reserve", "0"), allow_zero=True)
            start_date = parse_date(request.form.get("financial_start_date"))
            if not name or len(name) > 160:
                raise ValueError("Enter a business name of 160 characters or fewer.")
            if business_type not in BUSINESS_TYPES:
                raise ValueError("Choose a listed business category.")
            if business_type == "Other":
                if not custom_type or len(custom_type) > 80:
                    raise ValueError("Enter a custom business category.")
                business_type = custom_type
            if not city or not state:
                raise ValueError("Enter your city and state.")
            if len(address) > 300:
                raise ValueError("Address must be 300 characters or fewer.")
            if reserve > 10**14 or opening > 10**14:
                raise ValueError("Enter an amount within the supported range.")
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("getting_started.html", public_mode=False, business_types=BUSINESS_TYPES, values=request.form), 400
        business = Business(
            owner_id=current_user.id,
            name=name,
            business_type=business_type,
            city=city,
            state=state,
            address=address or None,
            currency="INR",
            opening_balance_paise=opening,
            minimum_cash_reserve_paise=reserve,
            financial_start_date=start_date or date.today(),
        )
        db.session.add(business)
        db.session.commit()
        flash("Business profile saved. Your cash view is ready for real entries.", "success")
        return redirect(url_for("main.dashboard"))
    return render_template("getting_started.html", public_mode=False, business_types=BUSINESS_TYPES)


@bp.get("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


@bp.get("/healthz")
def healthz():
    return jsonify(status="ok"), 200


@bp.get("/demo")
def demo_entry():
    user = User.query.filter_by(email=DEMO_EMAIL).first()
    if user is not None and not user.is_demo:
        flash("The sample demo workspace is temporarily unavailable. Your account was not opened.", "warning")
        return redirect(url_for("main.index"))
    if user is None or user.business is None:
        try:
            user = reset_demo_workspace()
        except RuntimeError:
            flash("The sample demo workspace is temporarily unavailable. Your account was not opened.", "warning")
            return redirect(url_for("main.index"))
    login_user(user, remember=False, fresh=True)
    from flask import session
    session.permanent = True
    flash("You’re exploring clearly labelled demo data. It is separate from personal accounts.", "info")
    return redirect(url_for("main.dashboard"))


@bp.get("/dashboard")
@login_required
def dashboard():
    business = current_user.business
    if business is None:
        return redirect(url_for("main.getting_started"))
    days_raw = request.args.get("days", "30")
    days = int(days_raw) if days_raw in {"7", "30", "90"} else 30
    forecast = calculate_forecast(business, days=days)
    refresh_notifications(business, forecast)
    action = recommend_next_action(business, forecast)
    today = date.today()
    cash = available_cash_paise(business, today)
    transactions = Transaction.query.filter_by(business_id=business.id).order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).limit(8).all()
    open_receivables = Invoice.query.filter_by(business_id=business.id, invoice_type="receivable").all()
    open_payables = Invoice.query.filter_by(business_id=business.id, invoice_type="payable").all()
    expected_in = sum(item.outstanding_paise for item in open_receivables if item.due_date and item.due_date >= today)
    forecast_out = sum(row["outflows_paise"] for row in forecast["rows"])
    missing_payable = sum(item.outstanding_paise for item in open_payables if item.outstanding_paise and item.due_date is None)
    upcoming_out = forecast_out + missing_payable
    missing_dates = forecast["missing_dates"]
    has_recent_data = Transaction.query.filter_by(business_id=business.id).filter(Transaction.transaction_date >= today - timedelta(days=30)).count() > 0
    if missing_dates:
        confidence = "Incomplete dates"
        confidence_note = f"{missing_dates} open item(s) have no due date."
    elif forecast["risk"]:
        confidence = "Review required"
        confidence_note = "Rule-based projection follows recorded dates and the reserve threshold."
    elif not has_recent_data and not open_receivables and not open_payables:
        confidence = "Limited data"
        confidence_note = "Record a few cash movements to make the forecast more useful."
    else:
        confidence = "Records up to date"
        confidence_note = "A transparent status—not an AI score or guarantee."

    obligations = []
    for invoice in open_receivables + open_payables:
        if invoice.outstanding_paise <= 0:
            continue
        if invoice.due_date and invoice.due_date > today + timedelta(days=30):
            continue
        party = invoice.customer.name if invoice.customer else invoice.supplier.name if invoice.supplier else "Unassigned"
        status = invoice.computed_status(today)
        direction = "Receipt expected" if invoice.invoice_type == "receivable" else "Payment due"
        subtitle = f"{invoice.invoice_number} · {direction}" + (" · Overdue" if status == "overdue" else "")
        obligations.append({"date": invoice.due_date, "title": party, "subtitle": subtitle, "status": status.title(), "amount_paise": invoice.outstanding_paise, "href": url_for("invoices.invoice_detail", invoice_id=invoice.id)})
    for event in forecast["events"]:
        if event["date"] > today + timedelta(days=30):
            continue
        if event["source_type"] == "recurring":
            obligations.append({"date": event["date"], "title": event["label"], "subtitle": "Recurring commitment", "status": "Planned", "amount_paise": -event["signed_paise"], "href": url_for("recurring.list_recurring")})
        elif event["source_type"] == "transaction":
            item = Transaction.query.filter_by(id=event["record_id"], business_id=business.id, payment_status="pending").first()
            if item:
                incoming = item.transaction_type in {"income", "customer_payment"}
                obligations.append({"date": event["date"], "title": item.description, "subtitle": f"{item.category} · Planned {'receipt' if incoming else 'payment'}", "status": "Pending", "amount_paise": item.amount_paise, "href": url_for("transactions.transaction_detail", transaction_id=item.id)})
    obligations.sort(key=lambda item: (item["date"] or date.max, item["title"]))
    chart = {
        "labels": [row["date"] for row in forecast["rows"]],
        "balance": [round(row["balance_paise"] / 100, 2) for row in forecast["rows"]],
        "reserve": [round(row["reserve_paise"] / 100, 2) for row in forecast["rows"]],
        "risk": [row["date"] for row in forecast["rows"] if row["below_reserve"]],
    }
    return render_template(
        "dashboard/index.html", business=business, days=days, forecast=forecast,
        cash=cash, expected_in=expected_in, upcoming_out=upcoming_out,
        confidence=confidence, confidence_note=confidence_note, action=action,
        transactions=transactions, obligations=obligations[:7], chart=chart,
        demo=current_user.is_demo,
    )
