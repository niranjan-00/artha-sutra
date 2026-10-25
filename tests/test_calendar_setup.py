from datetime import date, timedelta

from app.extensions import db
from app.models import Business, Customer, Invoice, RecurringExpense, Supplier, Transaction
from tests.conftest import create_account


def test_new_registration_and_login_land_on_visible_authenticated_setup(client, app):
    payload = {"name": "Asha Rao", "email": "asha-setup@example.test", "password": "cashflow1234", "password_confirm": "cashflow1234"}
    response = client.post("/register", data=payload)
    assert response.status_code == 302
    setup = client.get(response.headers["Location"])
    assert setup.status_code == 200
    assert b"Set up your business" in setup.data
    assert b"Set up your business before recording financial activity." in setup.data
    assert b'name="business_name"' in setup.data
    assert b"Save and open workspace" in setup.data
    assert client.get("/dashboard").status_code == 302
    calendar_gate = client.get("/cash-calendar")
    assert calendar_gate.status_code == 302
    assert "/getting-started" in calendar_gate.headers["Location"]
    assert client.get("/transactions").status_code == 302
    with app.app_context():
        user = __import__("app.models", fromlist=["User"]).User.query.filter_by(email=payload["email"]).one()
        assert user.business is None
    assert client.post("/getting-started", data={
        "business_name": "Asha Stores", "business_type": "Grocery", "city": "Pune", "state": "Maharashtra",
        "opening_balance": "12500.50", "minimum_cash_reserve": "2000", "financial_start_date": date.today().isoformat(),
    }).status_code == 302
    assert client.get("/dashboard").status_code == 200
    assert client.get("/cash-calendar").status_code == 200
    client.post("/logout")
    login = client.post("/login", data={"email": payload["email"], "password": payload["password"]})
    assert login.status_code == 302
    assert "/dashboard" in login.headers["Location"]


def test_calendar_lists_expected_receipt_bill_recurring_and_actual_movements(client, app, make_account):
    make_account(client, opening="10000", reserve="3000")
    today = date.today()
    with app.app_context():
        business = Business.query.one()
        business.financial_start_date = today - timedelta(days=3)
        customer = Customer(business_id=business.id, name="Corner Café")
        supplier = Supplier(business_id=business.id, name="Fresh Supply Co")
        db.session.add_all([customer, supplier])
        db.session.flush()
        receipt = Invoice(business_id=business.id, customer_id=customer.id, invoice_type="receivable", invoice_number="REC-CAL-1", issue_date=today, due_date=today + timedelta(days=4), total_amount_paise=250000, amount_paid_paise=0, status="pending")
        bill = Invoice(business_id=business.id, supplier_id=supplier.id, invoice_type="payable", invoice_number="PAY-CAL-1", issue_date=today, due_date=today + timedelta(days=4), total_amount_paise=150000, amount_paid_paise=0, status="pending")
        sale = Transaction(business_id=business.id, transaction_type="income", description="Settled till sale", amount_paise=50000, category="Sales", transaction_date=today, payment_method="Cash", payment_status="settled")
        pending = Transaction(business_id=business.id, transaction_type="expense", description="Scheduled delivery", amount_paise=25000, category="Supplies", transaction_date=today + timedelta(days=4), payment_method="UPI", payment_status="pending")
        rent = RecurringExpense(business_id=business.id, name="Shop rent", amount_paise=100000, category="Rent", frequency="monthly", next_due_date=today + timedelta(days=4), is_active=True)
        db.session.add_all([receipt, bill, sale, pending, rent])
        db.session.commit()
        target = today + timedelta(days=4)
        expected = {"receipt": receipt.total_amount_paise, "bill": bill.total_amount_paise, "tx": pending.amount_paise, "rent": rent.amount_paise}
        day = target.isoformat()
    response = client.get(f"/cash-calendar?month={today:%Y-%m}&day={day}")
    assert response.status_code == 200
    assert b"Cash-flow calendar" in response.data
    assert b"Corner Caf\xc3\xa9" in response.data
    assert b"Fresh Supply Co" in response.data
    assert b"Scheduled delivery" in response.data
    assert b"Shop rent" in response.data
    assert b"Expected receipts" in response.data
    assert b"Settled receipts" in response.data
    actual_day_response = client.get(f"/cash-calendar?month={today:%Y-%m}&day={today.isoformat()}")
    assert b"Settled till sale" in actual_day_response.data
    with app.app_context():
        from app.services.calendar import build_month_calendar
        business = Business.query.one()
        data = build_month_calendar(business, today.year, today.month, today=today)
        cell = data["by_day"][day]
        today_cell = data["by_day"][today.isoformat()]
        assert today_cell["actual_in_paise"] == 50000
        assert today_cell["expected_in_paise"] == 0
        assert cell["expected_in_paise"] == expected["receipt"]
        assert cell["expected_out_paise"] == expected["bill"] + expected["tx"] + expected["rent"]
        assert data["actual_totals"]["in_paise"] == 50000
        assert cell["closing_paise"] == 1000000 + 50000 + expected["receipt"] - expected["bill"] - expected["tx"] - expected["rent"]


def test_calendar_login_business_gate_month_validation_and_record_isolation(client, app, make_account):
    assert client.get("/cash-calendar").status_code == 302
    make_account(client)
    assert client.get("/cash-calendar?month=not-a-month").status_code == 302
    assert client.get("/cash-calendar?month=1900-01").status_code == 302
    response = client.get("/cash-calendar")
    assert response.status_code == 200
    assert b"Cash-flow calendar" in response.data
    stranger = app.test_client()
    create_account(stranger, email="calendar-stranger@example.test", business_name="Another business")
    assert b"Cash-flow calendar" in stranger.get("/cash-calendar").data
    assert b"Test Shop" not in stranger.get("/cash-calendar").data
