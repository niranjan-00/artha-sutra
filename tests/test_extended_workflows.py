from datetime import date, timedelta

from app.extensions import db
from app.models import Invoice, RecurringExpense


def test_recurring_expense_forecast_and_pause(client, app, make_account):
    make_account(client)
    due = date.today() + timedelta(days=2)
    response = client.post("/recurring", data={
        "name": "Shop rent", "category": "Rent", "frequency": "monthly", "amount": "250",
        "next_due_date": due.isoformat(),
    })
    assert response.status_code == 302
    assert b"Shop rent" in client.get("/dashboard").data
    with app.app_context():
        item = RecurringExpense.query.filter_by(name="Shop rent").one()
        item_id = item.id
    forecast = client.get("/api/forecast?days=7").json
    row = next(row for row in forecast["rows"] if row["date"] == due.isoformat())
    assert row["outflows_paise"] == 25000
    client.post(f"/recurring/{item_id}/toggle")
    forecast = client.get("/api/forecast?days=7").json
    row = next(row for row in forecast["rows"] if row["date"] == due.isoformat())
    assert row["outflows_paise"] == 0


def test_receipt_scenario_and_invoice_due_date_edit_are_non_destructive(client, app, make_account):
    make_account(client)
    due = date.today() + timedelta(days=7)
    client.post("/bills/new", data={
        "invoice_type": "receivable", "invoice_number": "REC-1", "party_name": "Market Cafe",
        "issue_date": date.today().isoformat(), "due_date": due.isoformat(), "total_amount": "500", "amount_paid": "0",
    })
    with app.app_context():
        invoice = Invoice.query.filter_by(invoice_number="REC-1").one()
        invoice_id = invoice.id
        original_date = invoice.due_date
    scenario = client.post("/scenarios", data={"action": "shift_receipt", "record_id": str(invoice_id), "days": "7"})
    assert scenario.status_code == 200
    assert b"comparison" in scenario.data.lower()
    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        assert invoice.due_date == original_date
        assert invoice.amount_paid_paise == 0
    moved_due = due + timedelta(days=4)
    edited = client.post(f"/invoices/{invoice_id}/edit", data={
        "invoice_number": "REC-1", "issue_date": date.today().isoformat(),
        "due_date": moved_due.isoformat(), "customer_id": str(invoice.customer_id), "notes": "Updated expected date",
    })
    assert edited.status_code == 302
    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        assert invoice.due_date == moved_due
        assert invoice.amount_paid_paise == 0


def test_duplicate_invoice_and_public_route_manifest(client, app, make_account):
    make_account(client)
    form = {
        "invoice_type": "payable", "invoice_number": "DUP-1", "party_name": "Vendor A",
        "issue_date": date.today().isoformat(), "total_amount": "100", "amount_paid": "0",
    }
    assert client.post("/bills/new", data=form).status_code == 302
    assert client.post("/bills/new", data=form).status_code == 200
    with app.app_context():
        assert Invoice.query.filter_by(invoice_number="DUP-1").count() == 1
    manifest = client.get("/manus-routes.json")
    assert manifest.status_code == 200
    assert manifest.is_json
    paths = {route["path"] for route in manifest.json["routes"]}
    assert "/dashboard" in paths
    assert "/invoices/:invoice_id/edit" in paths
    assert "/recurring" in paths
    assert "/api/forecast" not in paths
