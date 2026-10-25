from datetime import date, datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Product, ProductBatch, StockAlert, StockMovement, Supplier
from app.routes.common import amount_paise, business_or_redirect, parse_date
from app.services import inventory as inv

bp = Blueprint("inventory", __name__, url_prefix="/inventory")

MAX_QTY = 10_000_000


def _int(value: str | None, label: str, minimum: int = 0, maximum: int = MAX_QTY, required: bool = True) -> int | None:
    raw = (value or "").strip()
    if not raw:
        if required:
            raise ValueError(f"Enter {label}.")
        return None
    try:
        number = int(raw)
    except ValueError as exc:
        raise ValueError(f"{label.capitalize()} must be a whole number.") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{label.capitalize()} must be between {minimum} and {maximum}.")
    return number


def _product_or_404(business, product_id: int) -> Product:
    return Product.query.filter_by(id=product_id, business_id=business.id).first_or_404()


def _parse_product(business, form, product: Product | None) -> dict:
    name = form.get("name", "").strip()
    if not name or len(name) > 160:
        raise ValueError("Enter a product name of up to 160 characters.")
    sku = form.get("sku", "").strip() or None
    if sku and len(sku) > 60:
        raise ValueError("SKU must be 60 characters or fewer.")
    if sku:
        clash = Product.query.filter(Product.business_id == business.id, Product.sku == sku)
        if product is not None:
            clash = clash.filter(Product.id != product.id)
        if clash.first():
            raise ValueError("Another product already uses that SKU.")
    category = form.get("category", "").strip() or "General"
    unit = form.get("unit", "").strip() or "units"
    if len(category) > 80 or len(unit) > 20:
        raise ValueError("Category or unit is too long.")
    supplier_id = None
    if form.get("supplier_id"):
        supplier = Supplier.query.filter_by(id=_int(form.get("supplier_id"), "supplier", 1), business_id=business.id).first()
        if supplier is None:
            raise ValueError("Choose one of your suppliers.")
        supplier_id = supplier.id
    status = form.get("status", "active")
    if status not in ("active", "inactive"):
        raise ValueError("Choose a valid status.")
    return {
        "name": name, "sku": sku, "category": category, "unit": unit, "supplier_id": supplier_id,
        "purchase_price_paise": amount_paise(form.get("purchase_price") or "0", allow_zero=True),
        "selling_price_paise": amount_paise(form.get("selling_price")),
        "min_stock": _int(form.get("min_stock") or "0", "minimum stock"),
        "lead_time_days": _int(form.get("lead_time_days"), "lead time", 0, 365, required=False),
        "tracks_expiry": form.get("tracks_expiry") == "on",
        "status": status,
    }


def _form_page(business, product=None, values=None):
    suppliers = Supplier.query.filter_by(business_id=business.id).order_by(Supplier.name).all()
    return render_template("inventory/product_form.html", product=product, suppliers=suppliers, values=values or {})


@bp.get("")
@login_required
def product_list():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    today = date.today()
    inv.sync_alerts(business, today)
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "active")
    only_low = request.args.get("low") == "1"
    query = Product.query.filter_by(business_id=business.id)
    if status in ("active", "inactive"):
        query = query.filter_by(status=status)
    if search:
        query = query.filter(db.or_(Product.name.ilike(f"%{search}%"), Product.sku.ilike(f"%{search}%")))
    levels = inv.stock_levels(business.id)
    demand = inv.demand_map(business.id, today)
    rows = []
    for product in query.order_by(Product.name.asc()).all():
        stock = levels.get(product.id, 0)
        level = inv.stock_level_label(stock, product.min_stock)
        if only_low and not level:
            continue
        d = demand.get(product.id)
        rows.append({"product": product, "stock": stock, "level": level, "demand": d,
                     "days_left": inv.days_until_stockout(stock, d)})
    open_alerts = StockAlert.query.filter_by(business_id=business.id, resolved_at=None, is_acknowledged=False).count()
    return render_template("inventory/list.html", rows=rows, search=search, status=status, only_low=only_low, open_alerts=open_alerts)


@bp.route("/products/new", methods=["GET", "POST"])
@login_required
def product_new():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    if request.method == "POST":
        try:
            product = Product(business_id=business.id, **_parse_product(business, request.form, None))
        except ValueError as exc:
            flash(str(exc), "danger")
            return _form_page(business, values=request.form)
        db.session.add(product)
        db.session.commit()
        flash("Product saved. Add opening stock to start tracking quantity.", "success")
        return redirect(url_for("inventory.product_detail", product_id=product.id))
    return _form_page(business)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def product_edit(product_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    product = _product_or_404(business, product_id)
    if request.method == "POST":
        try:
            data = _parse_product(business, request.form, product)
        except ValueError as exc:
            flash(str(exc), "danger")
            return _form_page(business, product, request.form)
        for key, value in data.items():
            setattr(product, key, value)
        db.session.commit()
        inv.sync_alerts(business)
        flash("Product updated.", "success")
        return redirect(url_for("inventory.product_detail", product_id=product.id))
    return _form_page(business, product)


@bp.get("/products/<int:product_id>")
@login_required
def product_detail(product_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    product = _product_or_404(business, product_id)
    today = date.today()
    stock = inv.stock_levels(business.id).get(product.id, 0)
    demand = inv.demand_map(business.id, today).get(product.id)
    remaining = inv.batch_levels(business.id, product.id)
    batches = [(b, remaining.get(b.id, 0)) for b in sorted(product.batches, key=lambda b: (b.expiry_date or date.max, b.id))]
    movements = StockMovement.query.filter_by(product_id=product.id, business_id=business.id).order_by(
        StockMovement.movement_date.desc(), StockMovement.id.desc()).limit(50).all()
    return render_template(
        "inventory/product_detail.html", product=product, stock=stock, demand=demand,
        level=inv.stock_level_label(stock, product.min_stock), days_left=inv.days_until_stockout(stock, demand),
        reorder_qty=inv.suggested_reorder_qty(stock, product.min_stock, product.lead_time_days, demand),
        batches=[(b, q) for b, q in batches], movements=movements, today_iso=today.isoformat(),
        bucket_for=lambda b: inv.expiry_bucket(b.expiry_date, today),
    )


@bp.post("/products/<int:product_id>/stock")
@login_required
def record_stock(product_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    product = _product_or_404(business, product_id)
    form = request.form
    back = redirect(url_for("inventory.product_detail", product_id=product.id))
    try:
        kind = form.get("movement_type", "")
        if kind not in ("opening", "purchase", "adjustment", "writeoff"):
            raise ValueError("Choose a stock movement type.")
        qty = _int(form.get("quantity"), "quantity", 1)
        direction = form.get("direction", "add")
        if kind in ("opening", "purchase"):
            sign = 1
        elif kind == "writeoff":
            sign = -1
        else:
            if direction not in ("add", "remove"):
                raise ValueError("Choose whether to add or remove stock.")
            sign = 1 if direction == "add" else -1
        moved = parse_date(form.get("movement_date") or date.today().isoformat())
        if moved > date.today():
            raise ValueError("Stock movements cannot be dated in the future.")
        notes = form.get("notes", "").strip()[:300] or None
        unit_cost = None
        if sign > 0:
            cost_raw = form.get("unit_cost", "").strip()
            unit_cost = amount_paise(cost_raw, allow_zero=True) if cost_raw else product.purchase_price_paise
        batch = None
        if product.tracks_expiry:
            if sign > 0:
                expiry = parse_date(form.get("expiry_date"), required=False)
                if expiry is None:
                    raise ValueError("Enter an expiry date for this product.")
                number = form.get("batch_number", "").strip()[:60] or "UNBATCHED"
                batch = ProductBatch.query.filter_by(product_id=product.id, batch_number=number, expiry_date=expiry).first()
                if batch is None:
                    batch = ProductBatch(business_id=business.id, product_id=product.id, batch_number=number,
                                         expiry_date=expiry, unit_cost_paise=unit_cost or 0)
                    db.session.add(batch)
                    db.session.flush()
            else:
                batch = ProductBatch.query.filter_by(id=_int(form.get("batch_id"), "batch", 1), product_id=product.id,
                                                     business_id=business.id).first()
                if batch is None:
                    raise ValueError("Choose the batch to remove stock from.")
                if inv.batch_levels(business.id, product.id).get(batch.id, 0) < qty:
                    raise ValueError("That batch does not have enough stock.")
        if sign < 0 and inv.stock_levels(business.id).get(product.id, 0) < qty:
            raise ValueError("Stock cannot go below zero.")
        db.session.add(StockMovement(
            business_id=business.id, product_id=product.id, batch_id=batch.id if batch else None,
            movement_type=kind, quantity_change=sign * qty, unit_cost_paise=unit_cost, movement_date=moved,
            notes=notes, created_by_id=current_user.id,
        ))
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return back
    inv.sync_alerts(business)
    flash("Stock updated. This records quantity only; record any payment separately.", "success")
    return back


@bp.get("/alerts")
@login_required
def alerts():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    inv.sync_alerts(business)
    open_alerts = StockAlert.query.filter_by(business_id=business.id, resolved_at=None).order_by(
        StockAlert.is_acknowledged.asc(), StockAlert.created_at.desc()).all()
    low = {item["product"].id: item for item in inv.low_stock_items(business)}
    return render_template("inventory/alerts.html", alerts=open_alerts, low=low)


@bp.post("/alerts/<int:alert_id>/acknowledge")
@login_required
def acknowledge_alert(alert_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    alert = StockAlert.query.filter_by(id=alert_id, business_id=business.id).first_or_404()
    if alert.resolved_at is None and not alert.is_acknowledged:
        alert.is_acknowledged = True
        alert.acknowledged_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
    flash("Alert acknowledged. You will be told again if the condition changes.", "success")
    return redirect(url_for("inventory.alerts"))


@bp.get("/expiry")
@login_required
def expiry():
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    inv.sync_alerts(business)
    items = inv.expiry_items(business)
    total_risk = sum(i["value_at_risk_paise"] for i in items)
    return render_template("inventory/expiry.html", items=items, total_risk=total_risk)
