from datetime import date, timedelta
import io

from app.extensions import db
from app.models import Invoice, Payment, Transaction, User
from app.services.demo import DEMO_EMAIL


def _make_invoice(client, invoice_type="payable", number="BILL-001", amount="1000"):
    return client.post("/bills/new", data={
        "invoice_type": invoice_type,
        "invoice_number": number,
        "party_name": "Test Vendor" if invoice_type == "payable" else "Test Customer",
        "issue_date": date.today().isoformat(),
        "due_date": (date.today() + timedelta(days=7)).isoformat(),
        "total_amount": amount,
        "amount_paid": "0",
        "payment_method": "Cash",
        "payment_date": date.today().isoformat(),
        "notes": "Test invoice",
    })


def test_partial_payment_exact_once_and_overpayment_rejected(client, app, make_account):
    make_account(client)
    assert _make_invoice(client).status_code == 302
    with app.app_context():
        invoice = Invoice.query.filter_by(invoice_number="BILL-001").one()
        invoice_id = invoice.id
    payment_data = {"idempotency_key": "same-submission-token", "amount": "400", "payment_date": date.today().isoformat(), "payment_method": "UPI", "reference": "UPI-1"}
    client.post(f"/invoices/{invoice_id}/payment", data=payment_data)
    client.post(f"/invoices/{invoice_id}/payment", data=payment_data)
    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        assert invoice.amount_paid_paise == 40000
        assert invoice.computed_status() == "partially paid"
        assert Payment.query.filter_by(invoice_id=invoice_id).count() == 1
        assert Transaction.query.filter_by(transaction_type="supplier_payment").count() == 1
    overpayment = {"idempotency_key": "overpay-token", "amount": "700", "payment_date": date.today().isoformat(), "payment_method": "Cash"}
    client.post(f"/invoices/{invoice_id}/payment", data=overpayment)
    with app.app_context():
        assert db.session.get(Invoice, invoice_id).amount_paid_paise == 40000
        assert Payment.query.filter_by(invoice_id=invoice_id).count() == 1


def test_upload_signature_validation_and_private_download(client, app, make_account):
    make_account(client)
    response = client.post("/bills/upload?invoice_type=payable", data={
        "invoice_type": "payable", "invoice_number": "UPLOAD-1", "party_name": "Paper Supply",
        "issue_date": date.today().isoformat(), "due_date": (date.today() + timedelta(days=5)).isoformat(),
        "total_amount": "200", "amount_paid": "0", "document": (io.BytesIO(b"%PDF-1.7\nvalid test body"), "bill.pdf"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    with app.app_context():
        invoice = Invoice.query.filter_by(invoice_number="UPLOAD-1").one()
        invoice_id = invoice.id
        assert invoice.document_path
    assert client.get(f"/bills/{invoice_id}/document").status_code == 200
    bad = client.post("/bills/upload?invoice_type=payable", data={
        "invoice_type": "payable", "invoice_number": "UPLOAD-BAD", "party_name": "Paper Supply",
        "issue_date": date.today().isoformat(), "total_amount": "200", "amount_paid": "0",
        "document": (io.BytesIO(b"not really a PDF"), "bill.pdf"),
    }, content_type="multipart/form-data")
    assert bad.status_code == 200
    with app.app_context():
        assert Invoice.query.filter_by(invoice_number="UPLOAD-BAD").first() is None


def test_document_download_is_business_scoped(client, app, make_account):
    make_account(client)
    _make_invoice(client, number="OWNED-1")
    with app.app_context():
        invoice_id = Invoice.query.filter_by(invoice_number="OWNED-1").one().id
    stranger = app.test_client()
    make_account(stranger, email="reader@example.test", business_name="Another shop")
    assert stranger.get(f"/invoices/{invoice_id}").status_code == 404


def test_future_settled_transaction_must_remain_pending(client, app, make_account):
    make_account(client)
    future = (date.today() + timedelta(days=1)).isoformat()
    fields = {"transaction_type": "expense", "description": "Future rent", "category": "Rent", "amount": "25.50", "transaction_date": future, "payment_method": "Bank transfer"}
    settled = client.post("/transactions/new", data={**fields, "payment_status": "settled"})
    assert settled.status_code == 200
    assert b"cannot be marked settled" in settled.data
    with app.app_context():
        assert Transaction.query.filter_by(description="Future rent").first() is None
    pending = client.post("/transactions/new", data={**fields, "payment_status": "pending"})
    assert pending.status_code == 302
    with app.app_context():
        transaction = Transaction.query.filter_by(description="Future rent").one()
        assert transaction.payment_status == "pending"
        assert transaction.transaction_date == date.today() + timedelta(days=1)


def test_future_invoice_payment_is_rejected_and_initial_payment_needs_settlement_date(client, app, make_account):
    make_account(client)
    assert _make_invoice(client, number="FUTURE-PAY").status_code == 302
    with app.app_context():
        invoice = Invoice.query.filter_by(invoice_number="FUTURE-PAY").one()
        invoice_id = invoice.id
    future = (date.today() + timedelta(days=2)).isoformat()
    client.post(f"/invoices/{invoice_id}/payment", data={"idempotency_key": "future-payment", "amount": "100", "payment_date": future, "payment_method": "Cash"})
    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        assert invoice.amount_paid_paise == 0
        assert Payment.query.filter_by(invoice_id=invoice_id).count() == 0

    initial = {"invoice_type": "payable", "invoice_number": "INITIAL-PAID", "party_name": "Test Vendor", "issue_date": date.today().isoformat(), "due_date": future, "total_amount": "100", "amount_paid": "25", "payment_method": "Cash"}
    missing_date = client.post("/bills/new", data=initial)
    assert missing_date.status_code == 200
    assert b"Enter the date the initial payment was settled" in missing_date.data
    future_initial = client.post("/bills/new", data={**initial, "payment_date": future})
    assert future_initial.status_code == 200
    assert b"cannot be marked settled on a future date" in future_initial.data
    with app.app_context():
        assert Invoice.query.filter_by(invoice_number="INITIAL-PAID").first() is None
    saved = client.post("/bills/new", data={**initial, "payment_date": date.today().isoformat()})
    assert saved.status_code == 302
    with app.app_context():
        invoice = Invoice.query.filter_by(invoice_number="INITIAL-PAID").one()
        payment = Payment.query.filter_by(invoice_id=invoice.id).one()
        movement = Transaction.query.filter_by(id=payment.transaction_id).one()
        assert invoice.amount_paid_paise == 2500
        assert payment.payment_date == movement.transaction_date == date.today()


def test_reserved_demo_email_and_shared_demo_upload_protections(client, app):
    blocked = client.post("/register", data={"name": "Demo Alias", "email": DEMO_EMAIL, "password": "StrongPass123", "password_confirm": "StrongPass123"})
    assert blocked.status_code == 400
    with app.app_context():
        assert User.query.filter_by(email=DEMO_EMAIL).first() is None
    demo_client = app.test_client()
    assert demo_client.get("/demo").status_code == 302
    upload = demo_client.get("/bills/upload?invoice_type=payable")
    assert upload.status_code == 302
    assert upload.headers["Location"].endswith("/bills")
    bills = demo_client.get("/bills")
    assert b"/bills/upload" not in bills.data


def test_demo_entry_never_authenticates_as_a_regular_account_with_reserved_email(client, app):
    with app.app_context():
        user = User(name="Ordinary user", email=DEMO_EMAIL, password_hash="not-used", is_demo=False)
        db.session.add(user)
        db.session.commit()
    response = client.get("/demo")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert client.get("/dashboard").status_code == 302
