from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Customer, Invoice, Payment, Supplier
from app.routes.common import amount_paise, business_or_redirect, parse_date

bp = Blueprint("khata", __name__)


@bp.get("/khata")
@login_required
def ledger():
    business, response = business_or_redirect()
    if response:
        return response
    assert business is not None
    invoices = Invoice.query.filter_by(business_id=business.id).order_by(Invoice.due_date.asc(), Invoice.issue_date.desc()).all()
    open_items = [item for item in invoices if item.outstanding_paise > 0]
    receivables = [item for item in open_items if item.invoice_type == "receivable"]
    payables = [item for item in open_items if item.invoice_type == "payable"]
    payments = Payment.query.filter_by(business_id=business.id).order_by(Payment.payment_date.desc(), Payment.id.desc()).limit(40).all()
    return render_template(
        "finance/khata.html", business=business, receivables=receivables, payables=payables,
        payments=payments, receivable_total=sum(x.outstanding_paise for x in receivables),
        payable_total=sum(x.outstanding_paise for x in payables), invoice_count=len(open_items),
    )


@bp.post("/khata/new")
@login_required
def add_manual_entry():
    business, response = business_or_redirect()
    if response:
        return response
    assert business is not None
    invoice_type = request.form.get("invoice_type", "").strip()
    party_name = request.form.get("party_name", "").strip()
    invoice_number = request.form.get("invoice_number", "").strip()
    try:
        if invoice_type not in {"receivable", "payable"}:
            raise ValueError("Choose whether this is money a customer owes or money you owe a supplier.")
        if not party_name or len(party_name) > 160:
            raise ValueError("Enter a customer or supplier name of 160 characters or fewer.")
        if not invoice_number or len(invoice_number) > 100:
            raise ValueError("Enter a reference or bill number of 100 characters or fewer.")
        amount = amount_paise(request.form.get("amount", ""))
        issue_date = parse_date(request.form.get("issue_date"))
        due_date = parse_date(request.form.get("due_date"), required=False)
        notes = request.form.get("notes", "").strip()
        if len(notes) > 4000:
            raise ValueError("Notes must be 4,000 characters or fewer.")
        duplicate = Invoice.query.filter_by(business_id=business.id, invoice_type=invoice_type, invoice_number=invoice_number).first()
        if duplicate:
            raise ValueError("This Khata reference already exists for this type of entry.")

        invoice = Invoice()
        invoice.business_id = business.id
        invoice.invoice_type = invoice_type
        invoice.invoice_number = invoice_number
        invoice.issue_date = issue_date
        invoice.due_date = due_date
        invoice.total_amount_paise = amount
        invoice.amount_paid_paise = 0
        invoice.status = "pending"
        invoice.notes = notes or None
        if invoice_type == "receivable":
            party = Customer.query.filter_by(business_id=business.id, name=party_name).first()
            if party is None:
                party = Customer()
                party.business_id = business.id
                party.name = party_name
                db.session.add(party)
                db.session.flush()
            assert party is not None
            invoice.customer_id = party.id
        else:
            party = Supplier.query.filter_by(business_id=business.id, name=party_name).first()
            if party is None:
                party = Supplier()
                party.business_id = business.id
                party.name = party_name
                db.session.add(party)
                db.session.flush()
            assert party is not None
            invoice.supplier_id = party.id
        db.session.add(invoice)
        db.session.commit()
        flash("Manual Khata entry saved. It appears as an expected balance, not settled cash.", "success")
        return redirect(url_for("invoices.invoice_detail", invoice_id=invoice.id))
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "danger")
    except Exception:
        db.session.rollback()
        flash("Khata entry was not saved. Check the reference and try again.", "danger")
    return redirect(url_for("khata.ledger"))
