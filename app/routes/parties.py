from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Customer, Invoice, Supplier, Transaction
from app.routes.common import business_or_redirect

bp = Blueprint("parties", __name__)


def _party_model(kind: str):
    return Customer if kind == "customers" else Supplier


def _list(kind: str):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    model = _party_model(kind)
    search = request.args.get("q", "").strip()
    query = model.query.filter_by(business_id=business.id)
    if search:
        query = query.filter(model.name.ilike(f"%{search}%"))
    parties = query.order_by(model.name.asc()).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        notes = request.form.get("notes", "").strip()
        if not name or len(name) > 160 or len(email) > 254 or len(phone) > 40 or len(address) > 300:
            flash("Enter a valid name and contact details within the field limits.", "danger")
        else:
            party = model(business_id=business.id, name=name, email=email or None, phone=phone or None, address=address or None, notes=notes or None)
            db.session.add(party)
            db.session.commit()
            flash(f"{kind[:-1].title()} saved.", "success")
            return redirect(url_for(f"parties.{kind}_list"))
    return render_template("parties/list.html", parties=parties, kind=kind, search=search)


@bp.route("/customers", methods=["GET", "POST"])
@login_required
def customers_list():
    return _list("customers")


@bp.route("/suppliers", methods=["GET", "POST"])
@login_required
def suppliers_list():
    return _list("suppliers")


def _detail(kind: str, party_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    model = _party_model(kind)
    party = model.query.filter_by(id=party_id, business_id=business.id).first_or_404()
    invoices = Invoice.query.filter_by(business_id=business.id, **({"customer_id": party.id} if kind == "customers" else {"supplier_id": party.id})).order_by(Invoice.issue_date.desc()).all()
    transactions = Transaction.query.filter_by(business_id=business.id, **({"customer_id": party.id} if kind == "customers" else {"supplier_id": party.id})).order_by(Transaction.transaction_date.desc()).limit(20).all()
    outstanding = sum(invoice.outstanding_paise for invoice in invoices)
    return render_template("parties/detail.html", party=party, kind=kind, invoices=invoices, transactions=transactions, outstanding=outstanding)


@bp.get("/customers/<int:party_id>")
@login_required
def customer_detail(party_id: int):
    return _detail("customers", party_id)


@bp.get("/suppliers/<int:party_id>")
@login_required
def supplier_detail(party_id: int):
    return _detail("suppliers", party_id)


def _edit(kind: str, party_id: int):
    business, redirect_response = business_or_redirect()
    if redirect_response:
        return redirect_response
    model = _party_model(kind)
    party = model.query.filter_by(id=party_id, business_id=business.id).first_or_404()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        if not name or len(name) > 160 or len(email) > 254 or len(phone) > 40 or len(address) > 300:
            flash("Enter valid contact details within the field limits.", "danger")
        else:
            party.name = name
            party.email = email or None
            party.phone = phone or None
            party.address = address or None
            party.notes = request.form.get("notes", "").strip() or None
            db.session.commit()
            flash("Contact details updated.", "success")
            return redirect(url_for(f"parties.{kind[:-1]}_detail", party_id=party.id))
    return render_template("parties/edit.html", party=party, kind=kind)


@bp.route("/customers/<int:party_id>/edit", methods=["GET", "POST"])
@login_required
def edit_customer(party_id: int):
    return _edit("customers", party_id)


@bp.route("/suppliers/<int:party_id>/edit", methods=["GET", "POST"])
@login_required
def edit_supplier(party_id: int):
    return _edit("suppliers", party_id)
