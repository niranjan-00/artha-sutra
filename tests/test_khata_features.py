from datetime import date, timedelta

from app.extensions import db
from app.models import Business, Invoice, Payment, Transaction, User
from tests.conftest import create_account


def _manual_entry(client, invoice_type="receivable", invoice_number="KH-001", amount="375.25"):
    return client.post("/khata/new", data={
        "invoice_type": invoice_type,
        "party_name": "Corner Shop" if invoice_type == "receivable" else "Fresh Supplier",
        "invoice_number": invoice_number,
        "amount": amount,
        "issue_date": date.today().isoformat(),
        "due_date": (date.today() + timedelta(days=6)).isoformat(),
        "notes": "manual test entry",
    })


def _receivable(client, number="REC-KH-100", amount="500"):
    return client.post("/bills/new", data={
        "invoice_type": "receivable", "invoice_number": number, "party_name": "Corner Shop",
        "issue_date": date.today().isoformat(), "due_date": (date.today() + timedelta(days=5)).isoformat(),
        "total_amount": amount, "amount_paid": "0", "payment_date": "", "payment_method": "Cash",
    })


def test_khata_manual_customer_and_supplier_entries_remain_expected_only(client, app, make_account):
    make_account(client)
    assert client.get("/khata").status_code == 200
    customer = _manual_entry(client)
    supplier = _manual_entry(client, "payable", "KH-002", "240")
    assert customer.status_code == supplier.status_code == 302
    ledger = client.get("/khata")
    assert ledger.status_code == 200
    assert b"Customers owe you" in ledger.data
    assert b"You owe suppliers" in ledger.data
    assert b"Corner Shop" in ledger.data and b"Fresh Supplier" in ledger.data
    with app.app_context():
        entries = Invoice.query.order_by(Invoice.id).all()
        assert [(x.invoice_type, x.outstanding_paise, x.amount_paid_paise) for x in entries] == [
            ("receivable", 37525, 0), ("payable", 24000, 0)
        ]
        assert Transaction.query.count() == 0
        assert sum(x.outstanding_paise for x in entries if x.invoice_type == "receivable") == 37525
        assert sum(x.outstanding_paise for x in entries if x.invoice_type == "payable") == 24000

    duplicate = _manual_entry(client, invoice_number="KH-001")
    invalid = _manual_entry(client, invoice_number="KH-ZERO", amount="0")
    assert duplicate.status_code == invalid.status_code == 302
    with app.app_context():
        assert Invoice.query.count() == 2
        assert Invoice.query.filter_by(invoice_number="KH-ZERO").first() is None


def test_payment_receipt_pdf_contains_record_and_is_business_scoped(client, app, make_account):
    make_account(client)
    assert _receivable(client).status_code == 302
    with app.app_context():
        invoice_id = Invoice.query.filter_by(invoice_number="REC-KH-100").one().id
    response = client.post(f"/invoices/{invoice_id}/payment", data={
        "idempotency_key": "khata-receipt-once", "amount": "200", "payment_date": date.today().isoformat(),
        "payment_method": "UPI", "reference": "UPI-REC-77",
    })
    assert response.status_code == 302
    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        assert invoice is not None
        payment = Payment.query.filter_by(invoice_id=invoice_id).one()
        payment_id = payment.id
        assert payment.balance_after_paise == 30000
        assert invoice.outstanding_paise == 30000
    pdf = client.get(f"/payments/{payment_id}/receipt.pdf")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert "khata-receipt" in pdf.headers["Content-Disposition"]
    assert pdf.data.startswith(b"%PDF-")
    assert b"KHATA RECEIPT" in pdf.data
    assert b"INR 200.00" in pdf.data
    assert b"Balance remaining after this entry: INR 300.00" in pdf.data

    stranger = app.test_client()
    create_account(stranger, email="khata-reader@example.test", business_name="Other Store")
    assert stranger.get(f"/payments/{payment_id}/receipt.pdf").status_code == 404


def test_theme_toggle_and_settings_persist_user_profile_and_business(client, app, make_account):
    make_account(client)
    response = client.post("/profile/theme", data={"theme": "dark", "next": "/settings"})
    assert response.status_code == 302
    settings = client.get("/settings")
    assert settings.status_code == 200
    assert b"Dark mode" in settings.data
    assert b'data-theme="dark"' in client.get("/dashboard").data
    with app.app_context():
        user = User.query.filter_by(email="owner@example.test").one()
        assert user.theme == "dark"
        business = Business.query.filter_by(owner_id=user.id).one()
        start = business.financial_start_date.isoformat()
    saved = client.post("/settings", data={
        "business_name": "Updated Corner Store", "business_type": "Retail", "custom_type": "",
        "city": "Pune", "state": "Maharashtra", "address": "Market Road", "currency": "INR",
        "financial_start_date": start, "opening_balance": "1000", "minimum_cash_reserve": "500",
        "profile_name": "Updated Owner", "profile_email": "updated-owner@example.test", "theme": "light",
    })
    assert saved.status_code == 302
    with app.app_context():
        user = User.query.filter_by(email="updated-owner@example.test").one()
        assert user.name == "Updated Owner" and user.theme == "light"
        assert user.business.name == "Updated Corner Store"
    assert b'data-theme="light"' in client.get("/dashboard").data


def test_voice_controls_and_bill_image_review_have_manual_fallback(client, make_account):
    make_account(client)
    transaction_form = client.get("/transactions/new")
    assert transaction_form.status_code == 200
    assert b"data-voice-target=\"description\"" in transaction_form.data
    assert b"Voice input is not supported in this browser" not in transaction_form.data
    bill_form = client.get("/bills/upload?invoice_type=payable")
    assert bill_form.status_code == 200
    assert b"startBillOcr" in bill_form.data
    assert b"tesseract" in bill_form.data.lower()
    assert b"Review each value before saving" in bill_form.data
    assert b"Review extracted text" in bill_form.data
    assert b"PDFs can be entered manually" in bill_form.data
    from pathlib import Path
    js = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "app.js"
    source = js.read_text()
    assert "window.SpeechRecognition || window.webkitSpeechRecognition" in source
    assert "if (!SpeechRecognition)" in source
    assert "You can type instead" in source
    assert "window.Tesseract?.recognize" in source
    assert "enter the details manually" in source.lower()
    assert "you can still review and enter all fields manually" in source.lower()
