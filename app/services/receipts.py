from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def _pdf_text(value: object) -> str:
    text = str(value or "—")
    return text.encode("latin-1", "replace").decode("latin-1")


def _inr(amount_paise: int) -> str:
    rupees = Decimal(int(amount_paise)) / Decimal(100)
    return f"INR {rupees:,.2f}"


def build_payment_receipt(*, business, payment, invoice, party) -> bytes:
    """Generate an in-memory downloadable receipt without storing another financial document."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, pageCompression=0)
    width, height = A4
    is_receipt = payment.payment_type == "receipt"
    title = "KHATA RECEIPT" if is_receipt else "SUPPLIER PAYMENT VOUCHER"
    pdf.setTitle(f"{title} {payment.id}")
    pdf.setAuthor(_pdf_text(business.name))
    pdf.setFillColorRGB(0.25, 0.21, 0.38)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(52, height - 65, "Artha Sutra")
    pdf.setFillColorRGB(0.38, 0.33, 0.54)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(52, height - 100, title)
    pdf.setStrokeColorRGB(0.86, 0.84, 0.89)
    pdf.line(52, height - 114, width - 52, height - 114)

    details = [
        ("Business", business.name),
        ("Location", ", ".join(x for x in (business.city, business.state) if x) or "—"),
        ("Party", getattr(party, "name", None) or "Unassigned party"),
        ("Document reference", invoice.invoice_number if invoice else "Khata payment"),
        ("Payment date", payment.payment_date.isoformat()),
        ("Payment method", payment.payment_method),
        ("Payment reference", payment.reference or "—"),
    ]
    y = height - 150
    for label, value in details:
        pdf.setFillColorRGB(0.48, 0.47, 0.51)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(54, y, _pdf_text(label))
        pdf.setFillColorRGB(0.15, 0.16, 0.20)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(205, y, _pdf_text(value)[:90])
        y -= 27

    pdf.setFillColorRGB(0.95, 0.94, 0.97)
    pdf.roundRect(52, y - 14, width - 104, 62, 10, fill=1, stroke=0)
    pdf.setFillColorRGB(0.42, 0.39, 0.48)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(68, y + 25, "AMOUNT RECEIVED" if is_receipt else "AMOUNT PAID")
    pdf.setFillColorRGB(0.18, 0.16, 0.24)
    pdf.setFont("Helvetica-Bold", 19)
    pdf.drawString(68, y - 1, _inr(payment.amount_paise))

    if invoice:
        balance = payment.balance_after_paise
        if balance is None:
            balance = invoice.outstanding_paise
        y -= 53
        pdf.setFillColorRGB(0.40, 0.39, 0.44)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(54, y, f"Balance remaining after this entry: {_inr(balance)}")

    pdf.setFillColorRGB(0.50, 0.49, 0.53)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(52, 48, "Generated from the recorded Khata payment. Keep this receipt with your business records.")
    pdf.drawRightString(width - 52, 48, f"Receipt ID {payment.id}")
    pdf.save()
    return buffer.getvalue()
