from app.extensions import db
from app.models import Transaction, User
from tests.conftest import create_account


def test_registration_duplicate_login_logout_and_protection(client, app):
    assert client.get("/dashboard").status_code == 302
    data = {"name": "Nisha Rao", "email": "nisha@example.test", "password": "securecash123", "password_confirm": "securecash123"}
    response = client.post("/register", data=data)
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(email="nisha@example.test").first()
        assert user is not None
        assert user.password_hash != data["password"]
        assert user.check_password(data["password"])
    assert client.post("/logout").status_code == 302
    assert client.post("/register", data=data).status_code == 400
    assert client.post("/login", data={"email": data["email"], "password": "wrong-password"}).status_code == 401
    assert client.post("/login", data={"email": data["email"], "password": data["password"]}).status_code == 302
    assert client.post("/logout").status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_transaction_crud_and_csv(client, app, make_account):
    make_account(client)
    response = client.post("/transactions/new", data={
        "transaction_type": "income", "description": "Counter sales", "amount": "250.50",
        "category": "Sales", "transaction_date": "2026-10-25", "payment_method": "UPI", "payment_status": "settled",
    })
    assert response.status_code == 302
    with app.app_context():
        row = Transaction.query.filter_by(description="Counter sales").one()
        assert row.amount_paise == 25050
        assert row.payment_status == "settled"
        transaction_id = row.id
    assert client.get(f"/transactions/{transaction_id}").status_code == 200
    response = client.post(f"/transactions/{transaction_id}/edit", data={
        "transaction_type": "expense", "description": "Corrected sales entry", "amount": "100.25",
        "category": "Supplies", "transaction_date": "2026-10-25", "payment_method": "Cash", "payment_status": "pending",
    })
    assert response.status_code == 302
    with app.app_context():
        row = db.session.get(Transaction, transaction_id)
        assert row.description == "Corrected sales entry"
        assert row.amount_paise == 10025
        assert row.payment_status == "pending"
    csv_response = client.get("/transactions?export=csv")
    assert csv_response.status_code == 200
    assert b"Corrected sales entry" in csv_response.data
    assert client.post(f"/transactions/{transaction_id}/delete").status_code == 302
    with app.app_context():
        assert db.session.get(Transaction, transaction_id) is None


def test_invalid_transaction_amount_and_user_isolation(client, app, make_account):
    make_account(client)
    response = client.post("/transactions/new", data={
        "transaction_type": "income", "description": "Bad amount", "amount": "-100",
        "category": "Sales", "transaction_date": "2026-10-25", "payment_method": "Cash", "payment_status": "settled",
    })
    assert response.status_code == 200
    with app.app_context():
        assert Transaction.query.filter_by(description="Bad amount").first() is None
    response = client.post("/transactions/new", data={
        "transaction_type": "income", "description": "Private entry", "amount": "100",
        "category": "Sales", "transaction_date": "2026-10-25", "payment_method": "Cash", "payment_status": "settled",
    })
    with app.app_context():
        transaction_id = Transaction.query.filter_by(description="Private entry").one().id
    stranger = app.test_client()
    create_account(stranger, email="other@example.test", business_name="Other Shop")
    assert stranger.get(f"/transactions/{transaction_id}").status_code == 404


def test_dashboard_and_forecast_route_use_business_data(client, make_account):
    make_account(client)
    assert client.get("/dashboard?days=7").status_code == 200
    assert client.get("/forecast?days=90").status_code == 200
    response = client.get("/api/forecast?days=7")
    assert response.status_code == 200
    assert response.json["days"] == 7
    assert len(response.json["rows"]) == 8
    assert client.get("/api/forecast?days=12").status_code == 400
