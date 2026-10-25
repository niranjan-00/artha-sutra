import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import User
from app.services.demo import DEMO_EMAIL

bp = Blueprint("auth", __name__)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard" if current_user.business else "main.getting_started"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirm", "")
        errors = []
        if not name:
            errors.append("Enter your full name.")
        if len(name) > 120:
            errors.append("Name must be 120 characters or fewer.")
        if not EMAIL_RE.match(email) or len(email) > 254:
            errors.append("Enter a valid email address.")
        if email == DEMO_EMAIL:
            errors.append("That email address is reserved for the sample demo workspace.")
        if User.query.filter_by(email=email).first():
            errors.append("An account with this email already exists.")
        if len(password) < 10 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            errors.append("Use at least 10 characters, including a letter and a number.")
        if password != confirmation:
            errors.append("The password confirmation does not match.")
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("auth/register.html", name=name, email=email), 400
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("An account with this email already exists.", "danger")
            return render_template("auth/register.html", name=name, email=email), 400
        login_user(user, remember=False, fresh=True)
        flash("Account created. Add your business details to begin.", "success")
        return redirect(url_for("main.getting_started"))
    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard" if current_user.business else "main.getting_started"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Email or password is incorrect.", "danger")
            return render_template("auth/login.html", email=email), 401
        login_user(user, remember=False, fresh=True)
        from flask import session
        session.permanent = True
        flash("You’re signed in. Your business workspace is ready." if user.business else "You’re signed in. Set up your business to start using your workspace.", "success")
        return redirect(url_for("main.dashboard" if user.business else "main.getting_started"))
    return render_template("auth/login.html")


@bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("main.index"))
