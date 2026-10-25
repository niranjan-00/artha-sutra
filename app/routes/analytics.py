from __future__ import annotations
import csv
import io
from datetime import date, timedelta
from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from app.extensions import db
from app.models import Transaction
from app.routes.common import business_or_redirect, parse_date
from app.services.analytics import daily_summary, decision_insights
from app.services.money import format_inr
from app.services.receipts import _pdf_text
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

bp = Blueprint("analytics", __name__)

def _dates():
    today = date.today()
    preset = request.args.get("range", "30")
    if preset == "today": return today, today, preset
    if preset == "yesterday": return today - timedelta(days=1), today - timedelta(days=1), preset
    if preset == "7": return today - timedelta(days=6), today, preset
    if preset == "month": return today.replace(day=1), today, preset
    if preset == "previous":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last, preset
    try:
        start = parse_date(request.args.get("from"), required=False) or today - timedelta(days=29)
        end = parse_date(request.args.get("to"), required=False) or today
    except ValueError:
        start, end = today - timedelta(days=29), today
    return start, end, "custom"

@bp.get("/daily-summary")
@login_required
def daily_summary_page():
    business, response = business_or_redirect()
    if response: return response
    start, end, preset = _dates()
    summary = daily_summary(business, start, end)
    return render_template("analytics/daily_summary.html", business=business, summary=summary, start=start, end=end, preset=preset)

@bp.get("/daily-summary.csv")
@login_required
def daily_summary_csv():
    business, response = business_or_redirect()
    if response: return response
    start, end, _ = _dates()
    summary = daily_summary(business, start, end)
    out = io.StringIO(); writer = csv.writer(out)
    writer.writerow(["Artha Sutra daily business summary", start.isoformat(), end.isoformat()])
    writer.writerow(["Metric", "Amount / value"])
    for label, value in (("Sales", summary["sales_paise"]), ("Purchases", summary["purchases_paise"]), ("Operating expenses", summary["expenses_paise"]), ("Collections", summary["collections_paise"]), ("Refunds", summary["refunds_paise"]), ("Estimated profit", summary["estimated_profit_paise"]), ("Outstanding credit", summary["outstanding_credit_paise"]), ("Sales transactions", summary["sales_count"]), ("Purchase records", summary["purchase_count"])):
        writer.writerow([label, f"{value / 100:.2f}" if isinstance(value, int) else value])
    writer.writerow([]); writer.writerow(["Date", "Sales", "Collections", "Expenses", "Purchases"])
    for row in summary["chart"]: writer.writerow([row["date"], row["sales"]/100, row["collections"]/100, row["expenses"]/100, row["purchases"]/100])
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=artha-sutra-daily-summary.csv"})

@bp.get("/daily-summary.pdf")
@login_required
def daily_summary_pdf():
    business, response = business_or_redirect()
    if response: return response
    start, end, _ = _dates(); summary = daily_summary(business, start, end)
    buffer = io.BytesIO(); pdf = canvas.Canvas(buffer, pagesize=A4); width, height = A4
    pdf.setTitle(f"Daily summary {start.isoformat()} to {end.isoformat()}")
    pdf.setFillColorRGB(.25,.21,.38); pdf.setFont("Helvetica-Bold", 22); pdf.drawString(48, height-60, _pdf_text(business.name))
    pdf.setFont("Helvetica-Bold", 13); pdf.drawString(48, height-88, "Daily business summary")
    pdf.setFillColorRGB(.35,.35,.4); pdf.setFont("Helvetica", 10); pdf.drawString(48, height-108, f"Period: {start.isoformat()} to {end.isoformat()} · INR")
    y = height - 150
    rows = [("Sales revenue", summary["sales_paise"]), ("Collections received", summary["collections_paise"]), ("Purchases", summary["purchases_paise"]), ("Operating expenses", summary["expenses_paise"]), ("Refunds", summary["refunds_paise"]), ("Estimated profit", summary["estimated_profit_paise"]), ("Outstanding customer credit", summary["outstanding_credit_paise"])]
    for label, value in rows:
        pdf.setFillColorRGB(.3,.3,.35); pdf.setFont("Helvetica", 10); pdf.drawString(54, y, _pdf_text(label)); pdf.setFillColorRGB(.12,.12,.15); pdf.setFont("Helvetica-Bold", 11); pdf.drawRightString(width-54, y, f"INR {value/100:,.2f}"); y -= 25
    y -= 10; pdf.setFillColorRGB(.3,.3,.35); pdf.setFont("Helvetica-Bold", 11); pdf.drawString(54, y, "Top products")
    y -= 22; pdf.setFont("Helvetica", 10)
    for item in summary["top_products"]: pdf.drawString(64, y, f"{_pdf_text(item['name'])}: {item['units']} units"); y -= 18
    y -= 15; pdf.setFont("Helvetica", 8); pdf.setFillColorRGB(.45,.45,.5); pdf.drawString(48, 42, "Estimated profit uses recorded revenue less recorded operating expenses and refunds; it is not a tax statement.")
    pdf.save(); buffer.seek(0)
    return Response(buffer.getvalue(), mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=artha-sutra-daily-summary.pdf"})

@bp.get("/assistant")
@login_required
def assistant():
    business, response = business_or_redirect()
    if response: return response
    start, end, _ = _dates(); summary = daily_summary(business, start, end)
    return render_template("analytics/assistant.html", business=business, summary=summary, insights=decision_insights(business, summary), start=start, end=end)

@bp.route("/upi-import", methods=["GET", "POST"])
@login_required
def upi_import():
    business, response = business_or_redirect()
    if response: return response
    preview = session.get("upi_preview")
    if request.method == "POST":
        action = request.form.get("action")
        if action == "clear": session.pop("upi_preview", None); return redirect(url_for("analytics.upi_import"))
        if action == "import" and preview:
            imported = 0; skipped = 0
            for row in preview:
                ref = row.get("reference") or None
                if ref and Transaction.query.filter_by(business_id=business.id, reference=ref).first(): skipped += 1; continue
                db.session.add(Transaction(business_id=business.id, transaction_type="customer_payment", description=row["description"][:240], amount_paise=row["amount_paise"], category="UPI import — review", transaction_date=date.fromisoformat(row["date"]), payment_method="UPI", payment_status="settled", reference=ref, notes="Imported from UPI statement; matched manually by owner.")); imported += 1
            db.session.commit(); session.pop("upi_preview", None); flash(f"Imported {imported} UPI payment(s); skipped {skipped} possible duplicate(s). Review the ledger before treating them as sales.", "success"); return redirect(url_for("transactions.list_transactions"))
        file = request.files.get("statement")
        if not file or not file.filename.lower().endswith(".csv"):
            flash("Upload a CSV statement. PDF/image extraction is not enabled until a reliable extractor is configured.", "warning")
        else:
            try:
                text = file.read(2_000_001).decode("utf-8-sig")
                rows = []
                for raw in csv.DictReader(io.StringIO(text)):
                    date_value = raw.get("date") or raw.get("Date") or raw.get("transaction_date")
                    amount = raw.get("amount") or raw.get("Amount") or raw.get("credit")
                    if not date_value or not amount: continue
                    parsed = float(str(amount).replace(",", "").replace("₹", "").strip())
                    if parsed <= 0: continue
                    rows.append({"date": date.fromisoformat(date_value.strip()).isoformat(), "amount_paise": round(parsed * 100), "description": (raw.get("description") or raw.get("narration") or "UPI payment").strip(), "reference": (raw.get("reference") or raw.get("utr") or "").strip()})
                session["upi_preview"] = rows[:200]
                preview = session["upi_preview"]
                flash(f"Preview ready: {len(preview)} credit row(s). Confirm only after checking matches and duplicates.", "info")
            except Exception:
                flash("The CSV could not be parsed. Use date, amount, description, and optional reference/UTR columns.", "danger")
    return render_template("analytics/upi_import.html", preview=preview or [])
