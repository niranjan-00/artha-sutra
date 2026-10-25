from datetime import date

import pytest

from app import create_app
from app.extensions import db
from app.models import Business, User


@pytest.fixture
def app(tmp_path):
    upload_folder = tmp_path / "uploads"
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-key-that-is-not-used-in-production",
        "WTF_CSRF_ENABLED": False,
        "SESSION_COOKIE_SECURE": False,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.sqlite3'}",
        "UPLOAD_FOLDER": str(upload_folder),
    })
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def create_account(client, email="owner@example.test", business_name="Test Shop", opening="1000", reserve="500"):
    response = client.post("/register", data={
        "name": "Test Owner",
        "email": email,
        "password": "cashflow1234",
        "password_confirm": "cashflow1234",
    })
    assert response.status_code == 302
    response = client.post("/getting-started", data={
        "business_name": business_name,
        "business_type": "Retail",
        "city": "Pune",
        "state": "Maharashtra",
        "opening_balance": opening,
        "minimum_cash_reserve": reserve,
        "financial_start_date": date.today().isoformat(),
    })
    assert response.status_code == 302
    return response


@pytest.fixture
def make_account():
    return create_account
