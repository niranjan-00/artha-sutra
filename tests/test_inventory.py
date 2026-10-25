from datetime import date, timedelta

from app.extensions import db
from app.models import Business, Notification, Product, ProductBatch, StockAlert, StockMovement
from app.services import inventory as inv


def _business(app):
    return Business.query.first()


def make_product(client, **overrides):
    data = {"name": "Biscuits", "sku": "BIS-1", "category": "Snacks", "unit": "packets",
            "purchase_price": "8", "selling_price": "10", "min_stock": "15", "status": "active"}
    data.update(overrides)
    return client.post("/inventory/products/new", data=data)


def add_stock(client, product_id, **overrides):
    data = {"movement_type": "opening", "quantity": "8", "movement_date": date.today().isoformat()}
    data.update(overrides)
    return client.post(f"/inventory/products/{product_id}/stock", data=data, follow_redirects=True)


def test_requires_login(client):
    assert client.get("/inventory").status_code in (302, 401)


def test_stock_is_sum_of_movements_and_never_negative(app, client, make_account):
    make_account(client)
    assert make_product(client).status_code == 302
    with app.app_context():
        pid = Product.query.one().id
    add_stock(client, pid, quantity="8")
    r = add_stock(client, pid, movement_type="adjustment", direction="remove", quantity="9")
    assert b"cannot go below zero" in r.data
    with app.app_context():
        assert inv.stock_levels(_business(app).id)[pid] == 8


def test_expiry_product_requires_expiry_date_and_tracks_batches(app, client, make_account):
    make_account(client)
    make_product(client, tracks_expiry="on")
    with app.app_context():
        pid = Product.query.one().id
    r = add_stock(client, pid, quantity="5")
    assert b"expiry date" in r.data
    with app.app_context():
        assert StockMovement.query.count() == 0
    add_stock(client, pid, quantity="5", batch_number="B1", expiry_date=(date.today() + timedelta(days=5)).isoformat())
    add_stock(client, pid, quantity="3", batch_number="B1", expiry_date=(date.today() + timedelta(days=5)).isoformat())
    with app.app_context():
        assert ProductBatch.query.count() == 1
        assert inv.batch_levels(_business(app).id)[ProductBatch.query.one().id] == 8


def test_expired_batch_is_flagged_and_never_suggested_for_sale(app, client, make_account):
    make_account(client)
    make_product(client, tracks_expiry="on", min_stock="0")
    with app.app_context():
        pid = Product.query.one().id
    add_stock(client, pid, quantity="4", batch_number="OLD", expiry_date=(date.today() - timedelta(days=2)).isoformat())
    page = client.get("/inventory/expiry")
    assert b"Already expired" in page.data and b"Do not sell" in page.data
    with app.app_context():
        item = inv.expiry_items(_business(app))[0]
        assert item["bucket"] == "expired"
        assert item["value_at_risk_paise"] == 4 * 800
        assert "sell" not in item["action"].lower().replace("do not sell", "")


def test_low_stock_alert_created_once_and_acknowledge_persists(app, client, make_account):
    make_account(client)
    make_product(client)
    with app.app_context():
        pid = Product.query.one().id
    add_stock(client, pid, quantity="8")
    client.get("/inventory/alerts")
    client.get("/inventory")
    with app.app_context():
        alerts = StockAlert.query.filter_by(resolved_at=None).all()
        assert len(alerts) == 1 and alerts[0].level == "low"
        assert Notification.query.filter(Notification.dedupe_key.like("inventory-alert-%")).count() == 1
        alert_id = alerts[0].id
    client.post(f"/inventory/alerts/{alert_id}/acknowledge")
    client.get("/inventory/alerts")
    with app.app_context():
        assert StockAlert.query.filter_by(resolved_at=None).count() == 1
        assert StockAlert.query.get(alert_id).is_acknowledged is True


def test_alert_level_change_creates_new_alert_and_restock_resolves(app, client, make_account):
    make_account(client)
    make_product(client)
    with app.app_context():
        pid = Product.query.one().id
    add_stock(client, pid, quantity="10")
    with app.app_context():
        assert [a.level for a in StockAlert.query.filter_by(resolved_at=None)] == ["low"]
    add_stock(client, pid, movement_type="adjustment", direction="remove", quantity="5")  # 5 <= 15/2 -> critical
    with app.app_context():
        assert [a.level for a in StockAlert.query.filter_by(resolved_at=None)] == ["critical"]
        assert StockAlert.query.count() == 2
    add_stock(client, pid, movement_type="purchase", quantity="50")
    with app.app_context():
        assert StockAlert.query.filter_by(resolved_at=None).count() == 0


def test_prediction_requires_enough_history(app, client, make_account):
    make_account(client)
    make_product(client)
    with app.app_context():
        pid = Product.query.one().id
        biz = _business(app)
        today = date.today()
        db.session.add(StockMovement(business_id=biz.id, product_id=pid, movement_type="opening", quantity_change=40, movement_date=today))
        db.session.add(StockMovement(business_id=biz.id, product_id=pid, movement_type="sale", quantity_change=-10, movement_date=today))
        db.session.commit()
        d = inv.demand_map(biz.id, today)[pid]
        assert d["sufficient"] is False and inv.days_until_stockout(30, d) is None
        # Rebuild with 10 days of history and sales on 5 distinct days
        for m in StockMovement.query.all():
            m.movement_date = today - timedelta(days=9)
        for offset in range(5):
            db.session.add(StockMovement(business_id=biz.id, product_id=pid, movement_type="sale", quantity_change=-10, movement_date=today - timedelta(days=offset)))
        db.session.commit()
        d = inv.demand_map(biz.id, today)[pid]
        assert d["sufficient"] is True
        assert d["avg_daily"] == (10 + 50) / 10
        assert round(inv.days_until_stockout(30, d), 1) == 5.0


def test_other_business_cannot_see_or_change_product(app, client, make_account):
    make_account(client)
    make_product(client)
    with app.app_context():
        pid = Product.query.one().id
    other = app.test_client()
    make_account(other, email="two@example.test", business_name="Other Shop")
    assert other.get(f"/inventory/products/{pid}").status_code == 404
    assert other.post(f"/inventory/products/{pid}/stock", data={"movement_type": "opening", "quantity": "5"}).status_code == 404
    assert b"Biscuits" not in other.get("/inventory").data


def test_duplicate_sku_rejected(app, client, make_account):
    make_account(client)
    make_product(client)
    r = make_product(client, name="Other")
    assert r.status_code == 200 and b"SKU" in r.data
    with app.app_context():
        assert Product.query.count() == 1
