from datetime import date, timedelta

from app.extensions import db
from app.models import Business, Customer, Invoice, RecurringExpense, Supplier, Transaction
from app.services.cashflow import _apply_scenario, _next_due, available_cash_paise, calculate_forecast
from app.services.money import format_inr, parse_rupees


def test_money_is_decimal_safe_and_indian_formatted():
    assert parse_rupees("1,234.56") == 123456
    assert format_inr(12345678) == "₹1,23,456.78"
    assert format_inr(-5000) == "−₹50"
    for invalid in ["", "-1", "1.001", "NaN"]:
        try:
            parse_rupees(invalid)
            assert False, f"expected invalid amount: {invalid}"
        except ValueError:
            pass


def test_daily_forecast_reserve_breach_and_overdue_receipt_exclusion(app):
    with app.app_context():
        today = date.today()
        user = __import__("app.models", fromlist=["User"]).User(name="Owner", email="forecast@example.test", password_hash="x")
        db.session.add(user)
        db.session.flush()
        business = Business(owner_id=user.id, name="Shop", business_type="Retail", opening_balance_paise=10_000_000, minimum_cash_reserve_paise=7_000_000, financial_start_date=today - timedelta(days=10))
        db.session.add(business)
        db.session.flush()
        customer = Customer(business_id=business.id, name="Customer")
        supplier = Supplier(business_id=business.id, name="Supplier")
        db.session.add_all([customer, supplier])
        db.session.flush()
        db.session.add_all([
            Transaction(business_id=business.id, transaction_type="income", description="Settled receipt", amount_paise=1_000_000, category="Sales", transaction_date=today, payment_method="UPI", payment_status="settled"),
            Transaction(business_id=business.id, transaction_type="expense", description="Pending expense", amount_paise=250_000, category="Utilities", transaction_date=today + timedelta(days=1), payment_method="Bank transfer", payment_status="pending"),
            Invoice(business_id=business.id, supplier_id=supplier.id, invoice_type="payable", invoice_number="PAY-1", issue_date=today, due_date=today + timedelta(days=2), total_amount_paise=5_000_000, amount_paid_paise=0, status="pending"),
            Invoice(business_id=business.id, customer_id=customer.id, invoice_type="receivable", invoice_number="OLD-1", issue_date=today - timedelta(days=5), due_date=today - timedelta(days=1), total_amount_paise=8_000_000, amount_paid_paise=0, status="overdue"),
            RecurringExpense(business_id=business.id, name="Rent", amount_paise=200_000, category="Rent", frequency="monthly", next_due_date=today + timedelta(days=5), is_active=True),
        ])
        db.session.commit()
        assert available_cash_paise(business, today) == 11_000_000
        result = calculate_forecast(business, 7, today=today)
        assert result["rows"][0]["balance_paise"] == 11_000_000
        assert result["rows"][1]["balance_paise"] == 10_750_000
        assert result["rows"][2]["balance_paise"] == 5_750_000
        assert result["risk"]["date"] == (today + timedelta(days=2)).isoformat()
        assert result["risk"]["shortfall_paise"] == 1_250_000
        assert result["rows"][-1]["balance_paise"] == 5_550_000
        assert result["rows"][1]["inflows_paise"] == 0
        scenario = {"action": "add_expense", "amount_paise": 500_000, "date": today + timedelta(days=3)}
        alternative = calculate_forecast(business, 7, scenario=scenario, today=today)
        assert alternative["rows"][-1]["balance_paise"] == result["rows"][-1]["balance_paise"] - 500_000
        assert Invoice.query.filter_by(invoice_number="PAY-1").one().total_amount_paise == 5_000_000
        assert Transaction.query.filter_by(description="Pending expense").one().amount_paise == 250_000


def test_missing_dates_are_reported(app):
    with app.app_context():
        today = date.today()
        user = __import__("app.models", fromlist=["User"]).User(name="Owner", email="missing@example.test", password_hash="x")
        db.session.add(user)
        db.session.flush()
        business = Business(owner_id=user.id, name="Shop", business_type="Retail", financial_start_date=today, opening_balance_paise=100_000, minimum_cash_reserve_paise=20_000)
        db.session.add(business)
        db.session.flush()
        customer = Customer(business_id=business.id, name="Customer")
        db.session.add(customer)
        db.session.flush()
        db.session.add(Invoice(business_id=business.id, customer_id=customer.id, invoice_type="receivable", invoice_number="NO-DATE", issue_date=today, due_date=None, total_amount_paise=50000, amount_paid_paise=0, status="pending"))
        db.session.commit()
        result = calculate_forecast(business, 7, today=today)
        assert result["missing_dates"] == 1


def test_monthly_recurrence_preserves_original_day_after_february():
    january_31 = date(2025, 1, 31)
    february = _next_due(january_31, "monthly", anchor_day=31)
    assert february == date(2025, 2, 28)
    assert _next_due(february, "monthly", anchor_day=31) == date(2025, 3, 31)


def test_scenario_date_shift_beyond_horizon_is_not_clamped_to_final_day():
    today = date(2025, 1, 1)
    end = today + timedelta(days=30)
    event = {"date": today + timedelta(days=2), "signed_paise": -50000, "label": "Supplier bill", "source_type": "invoice", "record_id": 12}
    shifted_out = _apply_scenario([event], {"action": "delay_supplier", "record_id": 12, "days": 60}, today, end)
    assert shifted_out == []
