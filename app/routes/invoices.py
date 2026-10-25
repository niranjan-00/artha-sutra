import secrets
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, send_from_directory, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Customer, Invoice, Payment, Supplier, Transaction
from app.routes.common import amount_paise, business_or_redirect, parse_date
from app.services.receipts import build_payment_receipt

bp = Blueprint("invoices", __name__)
METHODS = {"Cash", "UPI", "Bank transfer", "Card", "Other"}


def _list_invoices(invoice_type: str | None = None):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    query = Invoice.query.filter_by(business_id=business.id)
    if invoice_type:
        query = query.filter_by(invoice_type=invoice_type)
    rows = query.order_by(Invoice.due_date.asc(), Invoice.issue_date.desc()).all()
    rows = [invoice for invoice in rows if invoice.outstanding_paise > 0]
    return render_template("finance/invoices.html", invoices=rows, invoice_type=invoice_type)


@bp.get("/bills")
@login_required
def bills_list():
    return _list_invoices()


@bp.get("/receivables")
@login_required
def receivables_list():
    return _list_invoices("receivable")


@bp.get("/payables")
@login_required
def payables_list():
    return _list_invoices("payable")


def _valid_upload(file_storage):
    if file_storage is None or not file_storage.filename:
        return None, None
    filename = secure_filename(file_storage.filename)
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in current_app.config["UPLOAD_EXTENSIONS"]:
        raise ValueError("Choose a PDF, PNG, JPG or JPEG file.")
    content = file_storage.read(current_app.config["MAX_CONTENT_LENGTH"] + 1)
    file_storage.stream.seek(0)
    if not content or len(content) > current_app.config["MAX_CONTENT_LENGTH"]:
        raise ValueError("The file is empty or larger than the 10 MB limit.")
    valid_signature = (
        (ext == "pdf" and content.startswith(b"%PDF-"))
        or (ext == "png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (ext in {"jpg", "jpeg"} and content.startswith(b"\xff\xd8\xff"))
    )
    if not valid_signature:
        raise ValueError("The file content does not match its extension. Choose a valid PDF or image.")
    return ext, content


@bp.route("/bills/new", methods=["GET", "POST"], endpoint="new_invoice")
@bp.route("/bills/upload", methods=["GET", "POST"], defaults={"upload_page": True}, endpoint="upload_invoice")
@login_required
def new_invoice(upload_page: bool = False):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    if upload_page and current_user.is_demo:
        flash("Document uploads are disabled in the shared sample workspace. Add only fictional review details.", "warning")
        return redirect(url_for("invoices.bills_list"))
    invoice_type = request.values.get("invoice_type", "payable").strip()
    if invoice_type not in {"receivable", "payable"}:
        invoice_type = "payable"
    customers = Customer.query.filter_by(business_id=business.id).order_by(Customer.name.asc()).all()
    suppliers = Supplier.query.filter_by(business_id=business.id).order_by(Supplier.name.asc()).all()
    values = request.form if request.method == "POST" else {}
    if request.method == "POST":
        document_path = None
        saved_path = None
        try:
            invoice_number = request.form.get("invoice_number", "").strip()
            issue_date = parse_date(request.form.get("issue_date"))
            due_date = parse_date(request.form.get("due_date"), required=False)
            total = amount_paise(request.form.get("total_amount", ""))
            paid = amount_paise(request.form.get("amount_paid", "0"), allow_zero=True)
            paid_date = parse_date(request.form.get("payment_date"), required=False)
            if paid > total:
                raise ValueError("Amount paid cannot exceed the invoice total.")
            if paid and paid_date is None:
                raise ValueError("Enter the date the initial payment was settled.")
            if paid and paid_date and paid_date > date.today():
                raise ValueError("A payment cannot be marked settled on a future date.")
            if not invoice_number or len(invoice_number) > 100:
                raise ValueError("Enter an invoice number of 100 characters or fewer.")
            duplicate = Invoice.query.filter_by(business_id=business.id, invoice_type=invoice_type, invoice_number=invoice_number).first()
            if duplicate:
                raise ValueError("An invoice with this number and type already exists for this business.")
            notes = request.form.get("notes", "").strip()
            if len(notes) > 4000:
                raise ValueError("Notes must be 4,000 characters or fewer.")

            customer = None
            supplier = None
            if invoice_type == "receivable":
                customer_id = request.form.get("customer_id", "").strip()
                party_name = request.form.get("party_name", "").strip()
                if customer_id:
                    customer = Customer.query.filter_by(id=customer_id, business_id=business.id).first()
                    if customer is None:
                        raise ValueError("Choose a customer from this business.")
                elif party_name:
                    customer = Customer.query.filter_by(business_id=business.id, name=party_name).first()
                    if customer is None:
                        customer = Customer()
                        customer.business_id = business.id
                        customer.name = party_name
                        db.session.add(customer)
                        db.session.flush()
                else:
                    raise ValueError("Choose a customer or enter a customer name.")
            else:
                supplier_id = request.form.get("supplier_id", "").strip()
                party_name = request.form.get("party_name", "").strip()
                if supplier_id:
                    supplier = Supplier.query.filter_by(id=supplier_id, business_id=business.id).first()
                    if supplier is None:
                        raise ValueError("Choose a supplier from this business.")
                elif party_name:
                    supplier = Supplier.query.filter_by(business_id=business.id, name=party_name).first()
                    if supplier is None:
                        supplier = Supplier()
                        supplier.business_id = business.id
                        supplier.name = party_name
                        db.session.add(supplier)
                        db.session.flush()
                else:
                    raise ValueError("Choose a supplier or enter a supplier name.")

            if invoice_type == "receivable":
                assert customer is not None
            else:
                assert supplier is not None
            uploaded_file = request.files.get("document")
            if upload_page and (uploaded_file is None or not uploaded_file.filename):
                raise ValueError("Choose the bill or invoice document to upload.")
            ext, content = _valid_upload(uploaded_file)
            if ext and content:
                document_path = f"{uuid.uuid4().hex}.{ext}"
                saved_path = Path(current_app.config["UPLOAD_FOLDER"], document_path)
                saved_path.write_bytes(content)

            invoice = Invoice()
            invoice.business_id = business.id
            customer_record_id = customer.id if customer is not None else None
            supplier_record_id = supplier.id if supplier is not None else None
            invoice.customer_id = customer_record_id
            invoice.supplier_id = supplier_record_id
            invoice.invoice_type = invoice_type
            invoice.invoice_number = invoice_number
            invoice.issue_date = issue_date
            invoice.due_date = due_date
            invoice.total_amount_paise = total
            invoice.amount_paid_paise = paid
            invoice.status = "paid" if paid == total else "partially paid" if paid else "pending"
            invoice.document_path = document_path
            invoice.notes = notes or None
            db.session.add(invoice)
            db.session.flush()
            if paid and paid_date is not None:
                party_label = customer.name if customer else supplier.name if supplier else "Invoice payment"
                transaction_type = "customer_payment" if invoice_type == "receivable" else "supplier_payment"
                payment_type = "receipt" if invoice_type == "receivable" else "payment"
                movement = Transaction()
                movement.business_id = business.id
                movement.customer_id = customer.id if customer else None
                movement.supplier_id = supplier.id if supplier else None
                movement.transaction_type = transaction_type
                movement.description = f"Initial payment · {invoice_number} · {party_label}"
                movement.amount_paise = paid
                movement.category = "Customer receipt" if invoice_type == "receivable" else "Supplier payment"
                movement.transaction_date = paid_date
                requested_method = request.form.get("payment_method", "Other")
                movement.payment_method = requested_method if requested_method in METHODS else "Other"
                movement.payment_status = "settled"
                db.session.add(movement)
                db.session.flush()
                payment = Payment()
                payment.business_id = business.id
                payment.invoice_id = invoice.id
                payment.transaction_id = movement.id
                payment.payment_type = payment_type
                payment.amount_paise = paid
                payment.balance_after_paise = invoice.outstanding_paise
                payment.payment_date = paid_date
                payment.payment_method = movement.payment_method
                payment.idempotency_key = f"initial-{secrets.token_hex(24)}"
                db.session.add(payment)
            db.session.commit()
            flash("Invoice saved. Forecasts use only the outstanding balance and expected date.", "success")
            return redirect(url_for("invoices.invoice_detail", invoice_id=invoice.id))
        except ValueError as error:
            db.session.rollback()
            if saved_path and saved_path.exists():
                saved_path.unlink()
            flash(str(error), "danger")
        except Exception:
            db.session.rollback()
            if saved_path and saved_path.exists():
                saved_path.unlink()
            flash("The invoice was not saved. Check the invoice number and try again.", "danger")
    return render_template("finance/invoice_form.html", invoice_type=invoice_type, customers=customers, suppliers=suppliers, values=values, upload_page=upload_page, payment_methods=sorted(METHODS))


@bp.get("/invoices/<int:invoice_id>")
@login_required
def invoice_detail(invoice_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    invoice = Invoice.query.filter_by(id=invoice_id, business_id=business.id).first_or_404()
    payments = Payment.query.filter_by(business_id=business.id, invoice_id=invoice.id).order_by(Payment.payment_date.desc()).all()
    return render_template("finance/invoice_detail.html", invoice=invoice, payments=payments, idempotency_key=secrets.token_urlsafe(32))


@bp.post("/invoices/<int:invoice_id>/payment")
@login_required
def record_payment(invoice_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    invoice = Invoice.query.filter_by(id=invoice_id, business_id=business.id).first_or_404()
    key = request.form.get("idempotency_key", "").strip()
    if not key or len(key) > 80:
        flash("Refresh the invoice page and retry the payment form.", "danger")
        return redirect(url_for("invoices.invoice_detail", invoice_id=invoice.id))
    previous = Payment.query.filter_by(idempotency_key=key).first()
    if previous:
        if previous.business_id == business.id:
            flash("This payment submission was already recorded; no duplicate movement was added.", "info")
            return redirect(url_for("invoices.invoice_detail", invoice_id=invoice.id))
        abort(404)
    try:
        amount = amount_paise(request.form.get("amount", ""))
        payment_date = parse_date(request.form.get("payment_date"))
        if payment_date > date.today():
            raise ValueError("A payment cannot be marked settled on a future date.")
        method = request.form.get("payment_method", "Other").strip()
        if method not in METHODS:
            raise ValueError("Choose a valid payment method.")
        if amount > invoice.outstanding_paise:
            raise ValueError("Payment cannot exceed the remaining balance.")
        reference = request.form.get("reference", "").strip()[:120] or None
        party = invoice.customer if invoice.invoice_type == "receivable" else invoice.supplier
        party_name = party.name if party else "Invoice payment"
        receipt = invoice.invoice_type == "receivable"
        movement = Transaction()
        movement.business_id = business.id
        movement.customer_id = invoice.customer_id
        movement.supplier_id = invoice.supplier_id
        movement.transaction_type = "customer_payment" if receipt else "supplier_payment"
        movement.description = f"{'Receipt' if receipt else 'Payment'} · {invoice.invoice_number} · {party_name}"
        movement.amount_paise = amount
        movement.category = "Customer receipt" if receipt else "Supplier payment"
        movement.transaction_date = payment_date
        movement.payment_method = method
        movement.payment_status = "settled"
        movement.reference = reference
        db.session.add(movement)
        db.session.flush()
        invoice.amount_paid_paise += amount
        invoice.status = invoice.computed_status(payment_date)
        payment = Payment()
        payment.business_id = business.id
        payment.invoice_id = invoice.id
        payment.transaction_id = movement.id
        payment.payment_type = "receipt" if receipt else "payment"
        payment.amount_paise = amount
        payment.balance_after_paise = invoice.outstanding_paise
        payment.payment_date = payment_date
        payment.payment_method = method
        payment.reference = reference
        payment.notes = request.form.get("notes", "").strip() or None
        payment.idempotency_key = key
        db.session.add(payment)
        db.session.commit()
        flash("Payment recorded. The invoice balance and cash forecast have been updated.", "success")
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "danger")
    except Exception:
        db.session.rollback()
        flash("Payment was not confirmed as saved. Please review the invoice and retry.", "danger")
    return redirect(url_for("invoices.invoice_detail", invoice_id=invoice.id))


@bp.get("/payments/<int:payment_id>/receipt.pdf")
@login_required
def download_payment_receipt(payment_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    payment = Payment.query.filter_by(id=payment_id, business_id=business.id).first_or_404()
    if payment.invoice_id is None:
        abort(404)
    invoice = Invoice.query.filter_by(id=payment.invoice_id, business_id=business.id).first_or_404()
    party = invoice.customer if invoice.invoice_type == "receivable" else invoice.supplier
    data = build_payment_receipt(business=business, payment=payment, invoice=invoice, party=party)
    prefix = "khata-receipt" if payment.payment_type == "receipt" else "supplier-payment-voucher"
    return send_file(BytesIO(data), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{prefix}-{payment.id}.pdf", max_age=0)


@bp.get("/bills/<int:invoice_id>/document")
@login_required
def download_document(invoice_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    invoice = Invoice.query.filter_by(id=invoice_id, business_id=business.id).first_or_404()
    if not invoice.document_path:
        abort(404)
    filename = Path(invoice.document_path).name
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, as_attachment=True, download_name=f"invoice-{invoice.invoice_number}{Path(filename).suffix}")


@bp.route("/invoices/<int:invoice_id>/edit", methods=["GET", "POST"])
@login_required
def edit_invoice(invoice_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    assert business is not None
    invoice = Invoice.query.filter_by(id=invoice_id, business_id=business.id).first_or_404()
    if request.method == "POST":
        try:
            invoice_number = request.form.get("invoice_number", "").strip()
            issue_date = parse_date(request.form.get("issue_date"))
            due_date = parse_date(request.form.get("due_date"), required=False)
            notes = request.form.get("notes", "").strip()
            if not invoice_number or len(invoice_number) > 100 or len(notes) > 4000:
                raise ValueError("Enter a valid invoice number and notes within the supported length.")
            duplicate = Invoice.query.filter(
                Invoice.business_id == business.id,
                Invoice.invoice_type == invoice.invoice_type,
                Invoice.invoice_number == invoice_number,
                Invoice.id != invoice.id,
            ).first()
            if duplicate:
                raise ValueError("Another invoice already uses this number.")
            if invoice.invoice_type == "receivable":
                party_id = request.form.get("customer_id", "").strip()
                if party_id:
                    party = Customer.query.filter_by(id=party_id, business_id=business.id).first()
                    if party is None:
                        raise ValueError("Choose a customer from this business.")
                    invoice.customer_id = party.id
            else:
                party_id = request.form.get("supplier_id", "").strip()
                if party_id:
                    party = Supplier.query.filter_by(id=party_id, business_id=business.id).first()
                    if party is None:
                        raise ValueError("Choose a supplier from this business.")
                    invoice.supplier_id = party.id
            invoice.invoice_number = invoice_number
            invoice.issue_date = issue_date
            invoice.due_date = due_date
            invoice.notes = notes or None
            db.session.commit()
            flash("Invoice details updated. Existing payment history and cash movements were preserved.", "success")
            return redirect(url_for("invoices.invoice_detail", invoice_id=invoice.id))
        except ValueError as error:
            flash(str(error), "danger")
        except Exception:
            db.session.rollback()
            flash("Invoice details were not updated.", "danger")
    parties = Customer.query.filter_by(business_id=business.id).order_by(Customer.name.asc()).all() if invoice.invoice_type == "receivable" else Supplier.query.filter_by(business_id=business.id).order_by(Supplier.name.asc()).all()
    return render_template("finance/invoice_edit.html", invoice=invoice, parties=parties)
