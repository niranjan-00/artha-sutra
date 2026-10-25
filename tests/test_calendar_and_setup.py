from datetime import date, timedelta

from app.extensions import db
from app.models import Business, Customer, Invoice, RecurringExpense, Supplier, Transaction
from tests.conftest import create_account


def test_setup_form_is_visible_after_registration(client):
    client.post("/register", data={"name": "A", "email": "a@b.co", "password": "cashflow1234", "password_confirm": "cashflow1234"})
    html = client.get("/getting-started").get_data(as_text=True)
    assert "Save business profile" in html
    assert 'name="business_name"' in html
    # Workspace links stay hidden until the business exists.
    assert "Cash flow calendar" not in html


def test_login_without_business_goes_to_setup(client):
    client.post("/register", data={"name": "A", "email": "a@b.co", "password": "cashflow1234", "password_confirm": "cashflow1234"})
    client.post("/logout")
    response = client.post("/login", data={"email": "a@b.co", "password": "cashflow1234"})
    assert response.status_code == 302 and response.headers["Location"].endswith("/getting-started")
    assert client.get("/calendar").status_code == 302


def test_calendar_requires_login(client):
    assert client.get("/calendar").status_code == 302


def test_calendar_shows_receipts_bills_and_recurring(app, client):
    create_account(client)
    day = date.today() + timedelta(days=2)
    with app.app_context():
        business = Business.query.first()
        customer = Customer(business_id=business.id, name="Asha Traders")
        supplier = Supplier(business_id=business.id, name="Metro Wholesale")
        db.session.add_all([customer, supplier])
        db.session.flush()
        db.session.add_all([
            Invoice(business_id=business.id, customer_id=customer.id, invoice_type="receivable", invoice_number="R-1", issue_date=date.today(), due_date=day, total_amount_paise=250000, amount_paid_paise=50000, status="pending"),
            Invoice(business_id=business.id, supplier_id=supplier.id, invoice_type="payable", invoice_number="B-1", issue_date=date.today(), due_date=day, total_amount_paise=80000, status="pending"),
            Invoice(business_id=business.id, supplier_id=supplier.id, invoice_type="payable", invoice_number="B-NODATE", issue_date=date.today(), due_date=None, total_amount_paise=10000, status="pending"),
            RecurringExpense(business_id=business.id, name="Shop rent", amount_paise=120000, frequency="weekly", next_due_date=day),
        ])
        db.session.commit()
    html = client.get(f"/calendar?month={day:%Y-%m}&date={day.isoformat()}").get_data(as_text=True)
    assert "Asha Traders" in html and "Metro Wholesale" in html and "Shop rent" in html
    assert "₹2,000" in html  # outstanding (total minus paid), not total
    assert "B-NODATE" in html and "Needs a due date" in html


def test_calendar_excludes_paid_and_other_business(app, client):
    create_account(client)
    with app.app_context():
        business = Business.query.first()
        db.session.add(Invoice(business_id=business.id, invoice_type="receivable", invoice_number="PAID", issue_date=date.today(), due_date=date.today(), total_amount_paise=1000, amount_paid_paise=1000, status="paid"))
        db.session.commit()
    html = client.get("/calendar").get_data(as_text=True)
    assert "PAID" not in html


def test_calendar_isolated_between_users(app, client):
    create_account(client)
    with app.app_context():
        business = Business.query.first()
        db.session.add(Invoice(business_id=business.id, invoice_type="receivable", invoice_number="SECRET-1", issue_date=date.today(), due_date=date.today(), total_amount_paise=5000, status="pending"))
        db.session.commit()
    client.post("/logout")
    create_account(client, email="other@example.test", business_name="Other")
    assert "SECRET-1" not in client.get("/calendar").get_data(as_text=True)


def test_calendar_handles_bad_month_and_date(client):
    create_account(client)
    for query in ["?month=abc", "?month=2026-13", "?month=1500-01", "?date=nope", "?month=2026-02&date=2026-03-05"]:
        assert client.get("/calendar" + query).status_code == 200


def test_monthly_recurring_keeps_anchor_day_across_short_months(app, client):
    create_account(client)
    start = date(date.today().year + 1, 1, 31)
    with app.app_context():
        business = Business.query.first()
        db.session.add(RecurringExpense(business_id=business.id, name="Loan EMI", amount_paise=100000, frequency="monthly", next_due_date=start))
        db.session.commit()
    feb = client.get(f"/calendar?month={start.year}-02&date={start.year}-02-28").get_data(as_text=True)
    mar = client.get(f"/calendar?month={start.year}-03&date={start.year}-03-31").get_data(as_text=True)
    assert "Loan EMI" in feb and "Loan EMI" in mar
