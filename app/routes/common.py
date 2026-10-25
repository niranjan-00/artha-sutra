from datetime import date

from flask import flash, redirect, url_for
from flask_login import current_user

from app.services.money import parse_rupees


def business_or_redirect():
    business = current_user.business
    if business is None:
        flash("Set up your business before recording financial activity.", "info")
        return None, redirect(url_for("main.getting_started"))
    return business, None


def parse_date(value: str | None, required: bool = True) -> date | None:
    raw = (value or "").strip()
    if not raw:
        if required:
            raise ValueError("Choose a date.")
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Enter a valid date.") from exc


def amount_paise(value: str | None, allow_zero: bool = False) -> int:
    amount = parse_rupees(value or "")
    if amount <= 0 and not allow_zero:
        raise ValueError("Amount must be greater than zero.")
    return amount
