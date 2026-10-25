import secrets
from datetime import date, timedelta

from app.extensions import db
from app.models import Business, Customer, Invoice, RecurringExpense, Supplier, Transaction, User


DEMO_EMAIL = "demo@artha-sutra.example"


def reset_demo_workspace() -> User:
    user = User.query.filter_by(email=DEMO_EMAIL).first()
    if user is not None and not user.is_demo:
        raise RuntimeError("The reserved demo email belongs to a regular account; refusing to use that account as the shared demo.")
    if user is None:
        user = User(name="Artha Sutra Demo", email=DEMO_EMAIL, is_demo=True)
        user.set_password(secrets.token_urlsafe(36))
        db.session.add(user)
        db.session.flush()

    business = user.business
    if business is not None:
        business.invoices.clear()
        business.transactions.clear()
        business.recurring_expenses.clear()
        business.customers.clear()
        business.suppliers.clear()
        business.notifications.clear()
        db.session.flush()
    else:
        business = Business(
            owner_id=user.id,
            name="Meera's Corner Market",
            business_type="Grocery",
            city="Pune",
            state="Maharashtra",
            currency="INR",
            opening_balance_paise=14_000_000,
            minimum_cash_reserve_paise=8_000_000,
            financial_start_date=date.today() - timedelta(days=30),
        )
        db.session.add(business)
        db.session.flush()

    business.name = "Meera's Corner Market"
    business.business_type = "Grocery"
    business.city = "Pune"
    business.state = "Maharashtra"
    business.currency = "INR"
    business.opening_balance_paise = 14_000_000
    business.minimum_cash_reserve_paise = 8_000_000
    business.financial_start_date = date.today() - timedelta(days=30)

    today = date.today()
    customer = Customer(business_id=business.id, name="Aarav Foods Co.", phone="+91 98765 43210", email="accounts@aaravfoods.example")
    supplier = Supplier(business_id=business.id, name="Western Grain Traders", phone="+91 91234 56780")
    produce_supplier = Supplier(business_id=business.id, name="Fresh Route Produce")
    db.session.add_all([customer, supplier, produce_supplier])
    db.session.flush()

    db.session.add_all([
        Transaction(business_id=business.id, transaction_type="income", description="Weekend counter sales", amount_paise=2_850_000, category="Sales", transaction_date=today - timedelta(days=1), payment_method="UPI", payment_status="settled"),
        Transaction(business_id=business.id, transaction_type="expense", description="Daily produce restock", amount_paise=740_000, category="Inventory", transaction_date=today - timedelta(days=1), payment_method="Cash", payment_status="settled", supplier_id=produce_supplier.id),
        Transaction(business_id=business.id, transaction_type="income", description="Wholesale order · Sharma Café", amount_paise=1_250_000, category="Wholesale", transaction_date=today - timedelta(days=4), payment_method="Bank transfer", payment_status="settled"),
    ])

    db.session.add_all([
        Invoice(business_id=business.id, customer_id=customer.id, invoice_type="receivable", invoice_number="AS-2408", issue_date=today - timedelta(days=12), due_date=today - timedelta(days=2), total_amount_paise=2_850_000, amount_paid_paise=0, status="overdue", notes="Weekly grocery supply; follow up with accounts."),
        Invoice(business_id=business.id, customer_id=customer.id, invoice_type="receivable", invoice_number="AS-2416", issue_date=today - timedelta(days=1), due_date=today + timedelta(days=10), total_amount_paise=7_200_000, amount_paid_paise=0, status="pending", notes="Expected payment date is based on the customer’s agreed terms."),
        Invoice(business_id=business.id, supplier_id=supplier.id, invoice_type="payable", invoice_number="WT-915", issue_date=today - timedelta(days=3), due_date=today + timedelta(days=4), total_amount_paise=9_100_000, amount_paid_paise=0, status="pending", notes="Monthly staples delivery."),
        Invoice(business_id=business.id, supplier_id=produce_supplier.id, invoice_type="payable", invoice_number="FR-332", issue_date=today, due_date=today + timedelta(days=12), total_amount_paise=4_900_000, amount_paid_paise=0, status="pending", notes="Produce settlement."),
    ])
    db.session.add(RecurringExpense(
        business_id=business.id,
        name="Shop rent",
        amount_paise=2_200_000,
        category="Rent",
        frequency="monthly",
        next_due_date=today + timedelta(days=7),
        is_active=True,
    ))
    db.session.commit()
    return user
