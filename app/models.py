from datetime import date, datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    theme = db.Column(db.String(12), nullable=False, default="light", server_default="light")
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    business = db.relationship("Business", back_populates="owner", uselist=False, cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Business(db.Model):
    __tablename__ = "businesses"
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    name = db.Column(db.String(160), nullable=False)
    business_type = db.Column(db.String(80), nullable=False, default="Other")
    address = db.Column(db.String(300))
    city = db.Column(db.String(100), nullable=False, default="")
    state = db.Column(db.String(100), nullable=False, default="")
    currency = db.Column(db.String(3), nullable=False, default="INR")
    opening_balance_paise = db.Column(db.BigInteger, nullable=False, default=0)
    minimum_cash_reserve_paise = db.Column(db.BigInteger, nullable=False, default=0)
    financial_start_date = db.Column(db.Date, nullable=False, default=date.today)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    owner = db.relationship("User", back_populates="business")
    customers = db.relationship("Customer", back_populates="business", cascade="all, delete-orphan")
    suppliers = db.relationship("Supplier", back_populates="business", cascade="all, delete-orphan")
    transactions = db.relationship("Transaction", back_populates="business", cascade="all, delete-orphan")
    invoices = db.relationship("Invoice", back_populates="business", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="business", cascade="all, delete-orphan")
    recurring_expenses = db.relationship("RecurringExpense", back_populates="business", cascade="all, delete-orphan")
    notifications = db.relationship("Notification", back_populates="business", cascade="all, delete-orphan")


class Customer(db.Model):
    __tablename__ = "customers"
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(254))
    address = db.Column(db.String(300))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    business = db.relationship("Business", back_populates="customers")
    invoices = db.relationship("Invoice", back_populates="customer")
    transactions = db.relationship("Transaction", back_populates="customer")


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(254))
    address = db.Column(db.String(300))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    business = db.relationship("Business", back_populates="suppliers")
    invoices = db.relationship("Invoice", back_populates="supplier")
    transactions = db.relationship("Transaction", back_populates="supplier")


class Transaction(db.Model):
    __tablename__ = "transactions"
    __table_args__ = (
        db.CheckConstraint("amount_paise > 0", name="ck_transaction_amount_positive"),
        db.Index("ix_transaction_business_date", "business_id", "transaction_date"),
        db.Index("ix_transaction_business_status", "business_id", "payment_status"),
    )
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    transaction_type = db.Column(db.String(30), nullable=False, index=True)
    description = db.Column(db.String(240), nullable=False)
    amount_paise = db.Column(db.BigInteger, nullable=False)
    category = db.Column(db.String(80), nullable=False, default="General")
    transaction_date = db.Column(db.Date, nullable=False, index=True)
    payment_method = db.Column(db.String(30), nullable=False, default="Other")
    payment_status = db.Column(db.String(20), nullable=False, default="settled", index=True)
    reference = db.Column(db.String(120))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    business = db.relationship("Business", back_populates="transactions")
    customer = db.relationship("Customer", back_populates="transactions")
    supplier = db.relationship("Supplier", back_populates="transactions")
    payment = db.relationship("Payment", back_populates="transaction", uselist=False)


class Invoice(db.Model):
    __tablename__ = "invoices"
    __table_args__ = (
        db.CheckConstraint("total_amount_paise > 0", name="ck_invoice_total_positive"),
        db.CheckConstraint("amount_paid_paise >= 0", name="ck_invoice_paid_nonnegative"),
        db.UniqueConstraint("business_id", "invoice_type", "invoice_number", name="uq_invoice_business_type_number"),
        db.Index("ix_invoice_business_due", "business_id", "due_date"),
    )
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    invoice_type = db.Column(db.String(20), nullable=False, index=True)
    invoice_number = db.Column(db.String(100), nullable=False)
    issue_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    total_amount_paise = db.Column(db.BigInteger, nullable=False)
    amount_paid_paise = db.Column(db.BigInteger, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    document_path = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    business = db.relationship("Business", back_populates="invoices")
    customer = db.relationship("Customer", back_populates="invoices")
    supplier = db.relationship("Supplier", back_populates="invoices")
    payments = db.relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")

    @property
    def outstanding_paise(self) -> int:
        return max(int(self.total_amount_paise or 0) - int(self.amount_paid_paise or 0), 0)

    def computed_status(self, today: date | None = None) -> str:
        today = today or date.today()
        if self.outstanding_paise <= 0:
            return "paid"
        if self.due_date and self.due_date < today:
            return "overdue"
        if self.amount_paid_paise > 0:
            return "partially paid"
        return "pending"


class Payment(db.Model):
    __tablename__ = "payments"
    __table_args__ = (db.CheckConstraint("amount_paise > 0", name="ck_payment_amount_positive"),)
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, unique=True)
    payment_type = db.Column(db.String(20), nullable=False)
    amount_paise = db.Column(db.BigInteger, nullable=False)
    balance_after_paise = db.Column(db.BigInteger, nullable=True)
    payment_date = db.Column(db.Date, nullable=False)
    payment_method = db.Column(db.String(30), nullable=False, default="Other")
    reference = db.Column(db.String(120))
    notes = db.Column(db.Text)
    idempotency_key = db.Column(db.String(80), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    business = db.relationship("Business", back_populates="payments")
    invoice = db.relationship("Invoice", back_populates="payments")
    transaction = db.relationship("Transaction", back_populates="payment")


class RecurringExpense(db.Model):
    __tablename__ = "recurring_expenses"
    __table_args__ = (db.CheckConstraint("amount_paise > 0", name="ck_recurring_amount_positive"),)
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    amount_paise = db.Column(db.BigInteger, nullable=False)
    category = db.Column(db.String(80), nullable=False, default="Operating")
    frequency = db.Column(db.String(20), nullable=False, default="monthly")
    next_due_date = db.Column(db.Date, nullable=True, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    business = db.relationship("Business", back_populates="recurring_expenses")


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (db.UniqueConstraint("business_id", "dedupe_key", name="uq_notification_dedupe"),)
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    notification_type = db.Column(db.String(30), nullable=False, index=True)
    related_record_type = db.Column(db.String(30))
    related_record_id = db.Column(db.Integer)
    dedupe_key = db.Column(db.String(180), nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    business = db.relationship("Business", back_populates="notifications")
