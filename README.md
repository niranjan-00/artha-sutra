# Artha Sutra

A Flask cash-flow management MVP for Indian small businesses. The fresh project was built from the supplied written brief; no source ZIP or existing interface assets were available. The app uses Jinja, Bootstrap 5, custom CSS, vanilla JavaScript, Chart.js and SQLAlchemy. It does not use a JavaScript application server or a simulated financial-data backend.

## What is implemented

- User registration, Werkzeug password hashing, sign-in/sign-out, CSRF-protected form actions, secure-cookie configuration, one-business onboarding and owner/business-scoped record queries.
- Database-backed cash dashboard, transaction search/filter/sort/CSV export, customer and supplier contacts, bills/receivables/payables, full/partial payment tracking, private PDF/image upload and download, invoice metadata review, recurring expenses, in-app notifications, reserve settings, a 7/30/90-day deterministic forecast, and a month-based cash calendar for expected receipts/bills, recurring expenses, scheduled transactions and settled history.
- New accounts and signed-in users without a business see a business-setup workspace before financial pages; existing owners continue to the dashboard.
- Khata uses the existing customer receivables, supplier payables and invoice payment records; manual entries remain expected balances until a payment is recorded. Recorded payments have owner-authorized PDF receipts/vouchers.
- Voice dictation uses browser speech recognition in supported browsers after explicit microphone permission; the app does not store audio, but the browser speech service may process it depending on the browser. Bill-image field suggestions use browser-side Tesseract.js for PNG/JPEG; the owner must review every value before saving. OCR requires the Tesseract CDN/language data; PDF bills remain manual-entry/review.
- Profile name/email and business details are editable in settings. Light/dark preference is stored per account; a toolbar toggle changes the persisted setting.
- What-if adjustments are calculated in memory and do not update actual records. A clearly labeled fictional grocery demo is available at `/demo` and can be reset from its dashboard. The sample workspace is shared among demo visitors (but isolated from real accounts); do not enter personal or sensitive details. Private file uploads are disabled in the shared demo.
- Money is stored as integer paise; rupee values are parsed through `Decimal`. OCR suggestions are browser-side only; bank/UPI synchronization, external payment settlement, SMS/email and AI-generated financial predictions are not provided.
- Daily business summary is available at `/daily-summary` with date presets/custom ranges, revenue versus collections, payment-method breakdown, product sales, outstanding credit, estimated profit disclosure, CSV export, and PDF export.
- The owner-controlled business assistant is available at `/assistant`; recommendations are deterministic explanations of actual ledger, invoice, Khata, and inventory records and do not mutate records or create purchases.
- UPI reconciliation is available at `/upi-import` for CSV preview, manual review, duplicate-reference checks, and explicit confirmation. Imported credits are ledger entries and are never silently treated as new sales.
- Related capabilities are grouped into canonical workflows: Reports & Summary (`/daily-summary`), Ledger & Reconciliation (`/ledger` and `/upi-import`), Forecast & Simulator (`/forecast` and `/scenarios`), Smart Reminders (`/reminders` and recurring expenses), Khata Recovery (`/khata/prioritizer`), and GST Tracker (`/gst`). Existing URLs remain available for compatibility.
- Settled ledger transactions now have generic PDF receipt/voucher generation and a share page with download, print, device share, WhatsApp, Telegram, and email draft actions. External delivery is never claimed without a configured provider response.
- GST records and deadlines are owner-entered with an explicit verification disclaimer; no government deadline or penalty is invented. User preferences now persist theme and language choices (English, Kannada, Hindi, Marathi) for the multilingual UI rollout.

## Requirements

- Python 3.11 or compatible Python (the checked build uses Python 3.12).
- A virtual environment. Internet access is needed for Python package installation and the Bootstrap/Chart.js/CDN assets.

## Windows setup

From the project directory in PowerShell or Command Prompt:

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and replace `SECRET_KEY` with a long random value. For local HTTP, leave `COOKIE_SECURE=0`; HTTPS preview/production must set `COOKIE_SECURE=1`. The default database is `instance/arthasutra.sqlite3` and uploaded files go to `instance/uploads/`. These directories contain private/local data and are ignored by Git.

This source project already contains its Alembic migration history. Apply it to create or upgrade your local database; do not reinitialize migrations or delete an existing database:

```powershell
flask --app run.py db upgrade
```

For a later model change, generate a new migration, review the generated file, then run `flask --app run.py db upgrade`. Only run `flask --app run.py db init` when intentionally creating a new migration repository that has no existing `migrations` directory.

Run locally:

```powershell
python run.py
```

Open <http://127.0.0.1:5000>. For the demo, select **Explore the demo** or visit `/demo`; the fictional shared workspace is created on first entry. Reset it from the demo banner. Avoid real business or personal details in this public sample workspace; document uploads are disabled there.

## Tests

```powershell
python -m pytest -q
```

The tests use a temporary SQLite database and disable CSRF only in the test app. Production/local forms remain CSRF-protected. Review test output rather than assuming coverage guarantees deployment readiness.

## Important financial rules

- Actual available cash starts at the opening cash on the configured financial start date and changes only for settled income, settled expenses, settled receipts/payments and refunds recorded as outflows. Transfers do not change aggregate cash.
- Unpaid invoices, pending dated movements and recurring items affect forecasts, not settled cash. Partial/full payment creates one payment record and one settled cash movement in the same database transaction. Overpayment and repeat submissions are rejected or idempotently ignored.
- Overdue customer receivables are not assumed to arrive on their old due dates. Past-due supplier obligations are treated as due now; missing invoice/recurrence dates are disclosed and excluded from a dated movement. Forecasts are estimates, not guarantees.
- Scenarios compare original and alternative estimates without saving scenario inputs to actual records.

## Security and private records

Set a high-entropy `SECRET_KEY`; never commit `.env`, database files or uploads. Forms use CSRF tokens. Transactions, contacts, invoices, payments and downloads are queried through the authenticated business scope. Uploads are limited by `MAX_CONTENT_LENGTH` (10 MiB by default), use generated filenames, validate PDF/PNG/JPEG signatures and are never placed in the static directory. The document route requires login and checks ownership. Passwords are hashed; they are not stored in plain text. Configure HTTPS and `COOKIE_SECURE=1` in production/HTTPS Preview; the cookie uses `SameSite=None` for embedded HTTPS preview and `Lax` for local HTTP.

## Deployment notes and material limits

- A container can be run with `gunicorn --workers 2 --bind 0.0.0.0:${PORT:-3000} run:app`; `Dockerfile` exposes 3000 and `/healthz` is an unauthenticated readiness route. Set `APP_ENV=production`, a strong `SECRET_KEY`, `COOKIE_SECURE=1`, `PORT`, and any `DATABASE_URL`/`UPLOAD_FOLDER` at **runtime**. Apply Alembic migrations before serving a new schema.
- The Docker container and managed preview have temporary writable storage. SQLite files and local invoice uploads are **not durable** across container replacement unless the host is explicitly configured with persistent storage. Do not use this configuration for real, durable multi-user financial records. Back up the DB/uploads before any manual migration/reset.
- For a durable deployment, configure an external PostgreSQL database with its runtime driver/URL and a durable private object store or persistent upload volume, then apply and test migrations before routing live users. The ORM boundary and paise representation are designed to ease a PostgreSQL move; it has not been configured or verified in this project.
- A deployment with `COOKIE_SECURE=1` must be served over public HTTPS. Avoid enabling debug mode in production. Use an account recovery/password reset process, authentication rate limiting, backup/restore procedures, operational monitoring and a privacy/legal review before accepting real financial records. Those operational systems are not implemented here.
- Bootstrap, Bootstrap Icons and Chart.js are loaded from public CDNs; supply locally hosted, versioned assets and a compatible content-security policy if your production environment requires offline assets or a restrictive CSP.

## Project layout

```text
run.py, config.py, requirements.txt, Dockerfile
app/
  __init__.py, extensions.py, models.py
  routes/       auth, business onboarding, transactions, parties, invoices, forecasts, settings, recurring costs
  services/     money, cash-flow rules, demo seed/reset, recommendations and notifications
  templates/    public pages, auth, dashboard, finance, contacts, shared layout, errors
  static/       custom CSS, vanilla JavaScript, SVG brand mark
migrations/     Alembic schema history
public/         /manus-routes.json
instance/       local SQLite database and private uploads (ignored by Git)
tests/          isolated pytest workflows
```

## Inventory (phase 1)

- `/inventory` products and stock, `/inventory/alerts` low-stock alerts, `/inventory/expiry` expiry monitor. Apply the new migration with `flask --app run.py db upgrade`.
- Stock is the sum of `stock_movements`; there is no stored stock total. Receiving or adjusting stock records quantity only and does not create a payment or expense.
- Stockout predictions use recorded `sale` movements and are withheld until there are 7 days of history and 3 selling days. Sales entry that writes sale movements is a later phase, so predictions stay empty until then.
- Alerts are created once per condition and level, can be acknowledged, and also appear in Notifications. Email and WhatsApp delivery are not implemented. Expiry alert windows are fixed (30/14/7/3/0 days); making them configurable is pending.
