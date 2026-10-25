from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_rupees(value: str) -> int:
    """Convert a user-entered rupee amount to integer paise without float arithmetic."""
    cleaned = (value or "").strip().replace("₹", "").replace(",", "")
    if not cleaned:
        raise ValueError("Enter an amount.")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Enter a valid amount.") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("Amount must be a non-negative number.")
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount != quantized:
        raise ValueError("Use no more than two decimal places.")
    return int(quantized * 100)


def format_inr(amount_paise: int | None, currency: str = "INR") -> str:
    paise = int(amount_paise or 0)
    sign = "−" if paise < 0 else ""
    absolute = abs(paise)
    rupees, cents = divmod(absolute, 100)
    digits = str(rupees)
    if len(digits) > 3:
        last = digits[-3:]
        head = digits[:-3]
        groups = []
        while head:
            groups.insert(0, head[-2:])
            head = head[:-2]
        digits = ",".join(groups + [last])
    prefix = "₹" if currency == "INR" else f"{currency} "
    fraction = f".{cents:02d}" if cents else ""
    return f"{sign}{prefix}{digits}{fraction}"
