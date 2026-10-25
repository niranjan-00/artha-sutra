from __future__ import annotations
from datetime import date
from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import login_required
from app.extensions import db
from app.models import GstRecord, Invoice, Payment, Transaction
from app.routes.common import amount_paise, business_or_redirect, parse_date
from app.services.receipts import build_transaction_receipt

bp = Blueprint("business_tools", __name__)

@bp.get("/ledger")
@login_required
def ledger():
    return redirect(url_for("transactions.list_transactions"))

@bp.get("/transactions/<int:transaction_id>/receipt.pdf")
@login_required
def transaction_receipt(transaction_id: int):
    business, response = business_or_redirect()
    if response:
        return response
    transaction = Transaction.query.filter_by(id=transaction_id, business_id=business.id).first_or_404()
    if transaction.payment_status != "settled":
        flash("A receipt is available only after the transaction is settled.", "warning")
        return redirect(url_for("transactions.transaction_detail", transaction_id=transaction.id))
    data = build_transaction_receipt(business=business, transaction=transaction)
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename=artha-sutra-transaction-{transaction.id}.pdf"})

@bp.get("/transactions/<int:transaction_id>/share")
@login_required
def receipt_share(transaction_id: int):
    business, response = business_or_redirect()
    if response:
        return response
    transaction = Transaction.query.filter_by(id=transaction_id, business_id=business.id).first_or_404()
    if transaction.payment_status != "settled":
        flash("Only settled transactions can be shared as receipts.", "warning")
        return redirect(url_for("transactions.transaction_detail", transaction_id=transaction.id))
    message = f"{business.name}: {transaction.description} — ₹{transaction.amount_paise / 100:,.2f}. Receipt TX-{transaction.id}."
    return render_template("finance/receipt_share.html", transaction=transaction, business=business, message=message)

@bp.get("/khata/prioritizer")
@login_required
def khata_prioritizer():
    business, response = business_or_redirect()
    if response:
        return response
    today = date.today()
    ranked = []
    invoices = Invoice.query.filter_by(business_id=business.id, invoice_type="receivable").all()
    for invoice in invoices:
        if invoice.outstanding_paise <= 0:
            continue
        overdue_days = max((today - invoice.due_date).days, 0) if invoice.due_date else 0
        payments = Payment.query.filter_by(business_id=business.id, invoice_id=invoice.id).all()
        customer = invoice.customer
        name = customer.name if customer else "Customer"
        score = invoice.outstanding_paise + overdue_days * 500 + len(payments) * 100
        ranked.append({"invoice": invoice, "name": name, "overdue_days": overdue_days, "paid_count": len(payments), "score": score, "message": f"Hello {name}, this is a polite reminder from {business.name}. An outstanding balance of ₹{invoice.outstanding_paise / 100:,.2f} for reference {invoice.invoice_number} is pending. Please let us know your expected payment date. Thank you."})
    ranked.sort(key=lambda item: (-item["score"], item["invoice"].due_date or date.max))
    return render_template("finance/khata_prioritizer.html", ranked=ranked)

@bp.get("/reminders")
@login_required
def reminders():
    return redirect(url_for("recurring.list_recurring"))

@bp.route("/gst", methods=["GET", "POST"])
@login_required
def gst_tracker():
    business, response = business_or_redirect()
    if response:
        return response
    if request.method == "POST":
        try:
            period = request.form.get("filing_period", "").strip()
            record_type = request.form.get("record_type", "GST filing").strip()
            due = parse_date(request.form.get("due_date"), required=False)
            if not period or len(period) > 40:
                raise ValueError("Enter a filing period.")
            status = request.form.get("status", "upcoming").strip()
            if status not in {"upcoming", "paid", "filed", "overdue"}:
                raise ValueError("Choose a valid GST record status.")
            record = GstRecord(business_id=business.id, filing_period=period, record_type=record_type[:40] or "GST filing", due_date=due, amount_paise=amount_paise(request.form.get("amount") or "0", allow_zero=True), status=status, reference=request.form.get("reference", "").strip()[:120] or None, notes=request.form.get("notes", "").strip()[:500] or None, deadline_source="Owner-entered deadline; verify against the applicable official GST notice.")
            db.session.add(record)
            db.session.commit()
            flash("GST record saved. Verify the deadline against the official GST source before relying on it.", "success")
            return redirect(url_for("business_tools.gst_tracker"))
        except ValueError as error:
            flash(str(error), "danger")
    records = GstRecord.query.filter_by(business_id=business.id).order_by(GstRecord.due_date.asc().nullslast(), GstRecord.id.desc()).all()
    return render_template("finance/gst.html", records=records)
