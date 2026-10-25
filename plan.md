# Artha Sutra — Audit and Implementation Plan

## Project audit

The supplied attachment contains the 1,616-line requirements brief, not a source ZIP. Per the user's direction, proceed from that brief without waiting for an archive. The newly initialized `/home/ubuntu/arthasutra` project is empty: it contains only Git metadata, with no dashboard, stylesheets, branding assets, route implementation, database, or interactive behavior to reuse. Consequently, the original interface cannot be directly audited; the brief's design and workflow requirements are the reference.

## Implementation plan

Build the app as a Python 3.11-compatible Flask application with an application factory, Jinja2 pages, Bootstrap 5, custom CSS, vanilla JavaScript, Chart.js, SQLAlchemy, Flask-Migrate, Flask-Login, Flask-WTF/CSRF, Werkzeug, and pytest. Keep one SQLite database and migrations as the initial persistence layer; do not enable the managed MySQL database or introduce a JavaScript application runtime. The preview server will bind `0.0.0.0:3000`. Financial amounts will be stored as integer paise and converted to/from `decimal.Decimal` at input, calculation, and presentation boundaries.

Organize the application into `app/models.py` (user, business, parties, transaction, invoice, payment, recurring expense, notification), `app/services/` (money, forecasting, recommendations/demo seeding), `app/routes/` (auth, onboarding, dashboard, financial records, monthly cash calendar, settings), `app/templates/` (shared shell, auth, dashboard, ledger, parties/invoices, forecast/scenario, forms), `app/static/css/` and `app/static/js/`, plus `migrations/`, `tests/`, `run.py`, `config.py`, `requirements.txt`, `.env.example`, `Dockerfile`, `README.md`, and `/manus-routes.json`.

Implement secure email/password registration/login/logout, protected routes, business onboarding and ownership-scoped database queries. Core financial workflows will include transaction CRUD and CSV export, customer/supplier records, receivable/payable invoices and atomic full/partial payment recording, private bill uploads with manual invoice entry/review, database-backed dashboard/notifications, deterministic 7/30/90-day cash forecasts, in-memory what-if scenarios, configurable reserve/settings, and an explicitly labeled isolated demo workspace/reset. Use a real SQL persistence layer for user data; never claim a document was OCR-scanned when it was not.

Design direction: a calm, precise Indian small-business fintech interface, with a warm neutral canvas, deep ink/navy text, restrained violet as the brand accent, and green/amber/red reserved for cash status. Use a compact left navigation on desktop and an accessible collapsible menu on mobile, with a data-dense dashboard, clear cash-flow chart, small status labels, subtle separators, and a simple custom SVG Devanagari-inspired brand mark. Favor immediate feedback and honest empty/loading/error states over decorative motion.

Forecasting will use Decimal-safe daily aggregation. Available cash includes opening balance plus settled cash movements only. Expected receipts and unpaid bills remain forecast items until actual payment is recorded; payment postings will atomically update invoice/payment and create exactly one cash movement. Forecast results will explicitly label assumptions, handle overdue/missing dates conservatively, identify first reserve/negative-cash risk and causes, and be shared by dashboard, forecast page, and scenario comparisons.

## Material constraints

No source ZIP or assets were supplied, so this is a fresh reimplementation from the written brief rather than a code-level migration. The managed preview/deployment container has temporary writable storage; SQLite and locally stored uploads are suitable for the MVP's local/demo run, but durable published multi-user operation needs persistent disk or a durable database/object store. Do not claim durable production hosting until that infrastructure is configured. Keep the app's storage/database boundary compatible with a later PostgreSQL and durable object-storage change.

## Project structure

```text
arthasutra/
├── run.py, config.py, requirements.txt, .env.example, README.md, Dockerfile
├── app/
│   ├── __init__.py, extensions.py, models.py
│   ├── routes/ (auth, onboarding, dashboard, transactions, parties, invoices, forecast, settings)
│   ├── services/ (money, cashflow, recommendations, demo)
│   ├── templates/ (base, auth, dashboard, finance, settings, errors)
│   └── static/ (css, js, images)
├── migrations/
├── tests/
└── public/manus-routes.json
```

The plan retains the brief's required Flask/SQLite/browser stack and its financial correctness, privacy, demo-isolation, testing, and Windows-run requirements. Optional external integrations (bank/UPI sync, production OCR, SMS/email, paid AI) remain out of scope and must be identified as unavailable rather than simulated.

## Added calendar and setup requirement
The authenticated `/cash-calendar` page presents month navigation, expected receipts, bills, recurring commitments, pending transactions and settled activity with daily estimated closing cash. It shares date inclusion rules with the existing forecast, distinguishes uncertain overdue customer receipts from overdue supplier obligations, and links each entry to a business-scoped record. After registration/login, users without a business receive a complete signed-in business setup screen in the workspace shell; successful setup continues to the dashboard.

## Calendar and first-time setup extension
The authenticated `/cash-calendar` view presents a navigable month grid, expected receipts, bills, recurring commitments, pending transactions and settled activity with daily estimated closing cash. It reuses the cash forecast's date inclusion rules, keeps past-due customer receipts uncertain rather than guaranteed, and links entries to owner-scoped source records. After registration or login, users without a business see a complete setup form inside the authenticated workspace shell, then continue to the dashboard after saving.

## Khata, voice/OCR, receipts, profile and theme extension
Keep bookkeeping on the existing SQLAlchemy `Invoice`, `Payment`, `Transaction`, `Customer` and `Supplier` models. Add a dedicated authenticated `/khata` ledger with owner-scoped open customer/vendor balances and a manual credit-entry form that creates the same receivable/payable records used by cash-flow forecasting; payments continue through the established atomic invoice-payment workflow. Add a business-scoped receipt PDF download for each recorded payment, generated with ReportLab and never exposed as a public file. Add accessible browser Web Speech dictation to descriptive text fields with a typed-entry fallback and no audio persistence. For bill images (PNG/JPEG), run OCR locally in the browser with Tesseract.js, offer clearly marked field suggestions for manual review, and store the original only through the existing private Flask upload path after the user submits; PDF bills remain manually reviewed. Persist `light`/`dark` preference on User with a forward-only Flask-Migrate migration, a responsive accessible topbar toggle, and a settings selector. Preserve current profile-name/email and business-edit behavior, make Bills to Pay and logout easy to reach, and retain existing due-date/settlement/ownership protections. No paid AI or bank integration is required; OCR and dictation must degrade honestly when browser support/network/language data is unavailable.
