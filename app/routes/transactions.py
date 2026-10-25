import csv
import io
from datetime import date

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Customer, Supplier, Transaction
from app.routes.common import amount_paise, business_or_redirect, parse_date

bp = Blueprint("transactions", __name__)
TYPES = {"income", "expense", "customer_payment", "supplier_payment", "refund", "transfer"}
METHODS = {"Cash", "UPI", "Bank transfer", "Card", "Other"}
STATUSES = {"settled", "pending"}


def _query_for(business):
    query = Transaction.query.filter_by(business_id=business.id)
    search = request.args.get("q", "").strip()
    kind = request.args.get("type", "").strip()
    status = request.args.get("status", "").strip()
    category = request.args.get("category", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()
    if search:
        query = query.filter(Transaction.description.ilike(f"%{search}%"))
    if kind in TYPES:
        query = query.filter_by(transaction_type=kind)
    if status in STATUSES:
        query = query.filter_by(payment_status=status)
    if category:
        query = query.filter_by(category=category)
    if date_from:
        try:
            query = query.filter(Transaction.transaction_date >= date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(Transaction.transaction_date <= date.fromisoformat(date_to))
        except ValueError:
            pass
    sort = request.args.get("sort", "date_desc")
    if sort == "date_asc":
        query = query.order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
    elif sort == "amount_desc":
        query = query.order_by(Transaction.amount_paise.desc())
    elif sort == "amount_asc":
        query = query.order_by(Transaction.amount_paise.asc())
    else:
        query = query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
    return query, search, sort


def _form_context(business, values=None, transaction=None):
    return {
        "business": business,
        "values": values or {},
        "transaction": transaction,
        "customers": Customer.query.filter_by(business_id=business.id).order_by(Customer.name.asc()).all(),
        "suppliers": Supplier.query.filter_by(business_id=business.id).order_by(Supplier.name.asc()).all(),
        "types": sorted(TYPES),
        "methods": sorted(METHODS),
    }


@bp.get("/transactions")
@login_required
def list_transactions():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    query, search, sort = _query_for(business)
    rows = query.all()
    if request.args.get("export") == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Date", "Type", "Description", "Category", "Amount (INR)", "Payment method", "Status", "Reference"])
        for row in rows:
            writer.writerow([row.id, row.transaction_date.isoformat(), row.transaction_type, row.description, row.category, f"{row.amount_paise / 100:.2f}", row.payment_method, row.payment_status, row.reference or ""])
        return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=artha-sutra-transactions.csv"})
    categories = [name for (name,) in db.session.query(Transaction.category).filter_by(business_id=business.id).distinct().order_by(Transaction.category).all()]
    return render_template("finance/transactions.html", rows=rows, search=search, sort=sort, categories=categories)


@bp.route("/transactions/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    values = request.form if request.method == "POST" else {}
    if request.method == "POST":
        try:
            kind = request.form.get("transaction_type", "").strip()
            description = request.form.get("description", "").strip()
            category = request.form.get("category", "General").strip() or "General"
            method = request.form.get("payment_method", "Other").strip()
            status = request.form.get("payment_status", "settled").strip()
            amount = amount_paise(request.form.get("amount", ""))
            tx_date = parse_date(request.form.get("transaction_date"))
            if status == "settled" and tx_date > date.today():
                raise ValueError("A future-dated transaction cannot be marked settled. Save it as pending until the cash movement occurs.")
            if kind not in TYPES or method not in METHODS or status not in STATUSES:
                raise ValueError("Choose a valid transaction type, payment method and status.")
            if not description or len(description) > 240 or len(category) > 80:
                raise ValueError("Enter a description and category within the supported length.")
            customer = None
            supplier = None
            customer_id = request.form.get("customer_id", "").strip()
            supplier_id = request.form.get("supplier_id", "").strip()
            if customer_id:
                customer = Customer.query.filter_by(id=customer_id, business_id=business.id).first()
                if customer is None:
                    raise ValueError("Choose a customer from this business.")
            if supplier_id:
                supplier = Supplier.query.filter_by(id=supplier_id, business_id=business.id).first()
                if supplier is None:
                    raise ValueError("Choose a supplier from this business.")
            transaction = Transaction(
                business_id=business.id,
                customer_id=customer.id if customer else None,
                supplier_id=supplier.id if supplier else None,
                transaction_type=kind,
                description=description,
                amount_paise=amount,
                category=category,
                transaction_date=tx_date,
                payment_method=method,
                payment_status=status,
                reference=request.form.get("reference", "").strip()[:120] or None,
                notes=request.form.get("notes", "").strip() or None,
            )
            db.session.add(transaction)
            db.session.commit()
            flash("Transaction saved.", "success")
            return redirect(url_for("transactions.transaction_detail", transaction_id=transaction.id))
        except ValueError as error:
            flash(str(error), "danger")
        except Exception:
            db.session.rollback()
            flash("The transaction was not saved. Please try again.", "danger")
    return render_template("finance/transaction_form.html", **_form_context(business, values))


@bp.get("/transactions/<int:transaction_id>")
@login_required
def transaction_detail(transaction_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    transaction = Transaction.query.filter_by(id=transaction_id, business_id=business.id).first_or_404()
    return render_template("finance/transaction_detail.html", transaction=transaction, business=business)


@bp.route("/transactions/<int:transaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(transaction_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    transaction = Transaction.query.filter_by(id=transaction_id, business_id=business.id).first_or_404()
    if transaction.payment:
        flash("Invoice-linked payment entries are managed from their invoice to preserve the payment record.", "warning")
        return redirect(url_for("invoices.invoice_detail", invoice_id=transaction.payment.invoice_id))
    if request.method == "POST":
        try:
            kind = request.form.get("transaction_type", "").strip()
            method = request.form.get("payment_method", "Other").strip()
            status = request.form.get("payment_status", "settled").strip()
            description = request.form.get("description", "").strip()
            category = request.form.get("category", "General").strip() or "General"
            amount = amount_paise(request.form.get("amount", ""))
            tx_date = parse_date(request.form.get("transaction_date"))
            if status == "settled" and tx_date > date.today():
                raise ValueError("A future-dated transaction cannot be marked settled. Save it as pending until the cash movement occurs.")
            if kind not in TYPES or method not in METHODS or status not in STATUSES:
                raise ValueError("Choose valid transaction values.")
            if not description or len(description) > 240 or len(category) > 80:
                raise ValueError("Enter a description and category within the supported length.")
            transaction.transaction_type = kind
            transaction.description = description
            transaction.category = category
            transaction.amount_paise = amount
            transaction.transaction_date = tx_date
            transaction.payment_method = method
            transaction.payment_status = status
            transaction.reference = request.form.get("reference", "").strip()[:120] or None
            transaction.notes = request.form.get("notes", "").strip() or None
            db.session.commit()
            flash("Transaction updated; cash totals and forecasts now use the saved values.", "success")
            return redirect(url_for("transactions.transaction_detail", transaction_id=transaction.id))
        except ValueError as error:
            flash(str(error), "danger")
        except Exception:
            db.session.rollback()
            flash("The transaction was not updated.", "danger")
    return render_template("finance/transaction_form.html", **_form_context(business, request.form if request.method == "POST" else {}, transaction))


@bp.post("/transactions/<int:transaction_id>/delete")
@login_required
def delete_transaction(transaction_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    transaction = Transaction.query.filter_by(id=transaction_id, business_id=business.id).first_or_404()
    if transaction.payment:
        flash("Record invoice-linked payments from the invoice so balances remain correct.", "warning")
        return redirect(url_for("invoices.invoice_detail", invoice_id=transaction.payment.invoice_id))
    db.session.delete(transaction)
    db.session.commit()
    flash("Transaction deleted. The dashboard and forecast reflect the change.", "success")
    return redirect(url_for("transactions.list_transactions"))
