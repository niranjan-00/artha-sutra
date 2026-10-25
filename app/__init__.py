import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, render_template, send_from_directory
from flask_login import current_user

from app.extensions import csrf, db, login_manager, migrate
from app.models import Notification, User
from app.services.money import format_inr


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    # Create the instance and upload directories.
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.instance_path, "uploads").mkdir(parents=True, exist_ok=True)

    from config import Config

    app.config.from_object(Config)

    # Database configuration.
    #
    # Priority:
    # 1. Explicit test configuration.
    # 2. Turso when both Turso environment variables are present.
    # 3. DATABASE_URL when provided.
    # 4. Local SQLite as the default.

    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    database_url = os.environ.get("DATABASE_URL")

    if test_config and "SQLALCHEMY_DATABASE_URI" in test_config:
        # Preserve the database configuration supplied by tests.
        pass

    elif turso_url or turso_token:
        if not turso_url or not turso_token:
            raise RuntimeError(
                "Both TURSO_DATABASE_URL and TURSO_AUTH_TOKEN "
                "must be configured."
            )

        # Accept URLs such as:
        # libsql://database-name-org.turso.io
        # https://database-name-org.turso.io

        parsed_url = urlparse(
            turso_url if "://" in turso_url else f"libsql://{turso_url}"
        )

        turso_host = parsed_url.netloc

        if not turso_host or parsed_url.scheme not in ("libsql", "https"):
            raise RuntimeError(
                "TURSO_DATABASE_URL must be a valid libsql:// or https:// URL."
            )

        app.config["SQLALCHEMY_DATABASE_URI"] = (
            f"sqlite+libsql://{turso_host}?secure=true"
        )

        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "connect_args": {
                "auth_token": turso_token,
            }
        }

    elif database_url:
        # Support standard database URLs.
        #
        # Some providers return postgres:// URLs. Normalize those
        # to the SQLAlchemy PostgreSQL URL scheme.
        if database_url.startswith("postgres://"):
            database_url = database_url.replace(
                "postgres://",
                "postgresql://",
                1,
            )

        app.config["SQLALCHEMY_DATABASE_URI"] = database_url

    else:
        # Local Windows development uses SQLite.
        database_path = Path(
            app.instance_path,
            "arthasutra.sqlite3",
        ).as_posix()

        app.config["SQLALCHEMY_DATABASE_URI"] = (
            f"sqlite:///{database_path}"
        )

    # Configure uploaded files.
    app.config["UPLOAD_FOLDER"] = (
        os.environ.get("UPLOAD_FOLDER")
        or str(Path(app.instance_path, "uploads"))
    )

    if test_config:
        app.config.update(test_config)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(
        parents=True,
        exist_ok=True,
    )

    # Initialize Flask extensions.
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = (
        "Sign in to continue to your business workspace."
    )
    login_manager.login_message_category = "info"

    csrf.init_app(app)

    # Import and register application routes.
    from app.routes.auth import bp as auth_bp
    from app.routes.main import bp as main_bp
    from app.routes.transactions import bp as transactions_bp
    from app.routes.parties import bp as parties_bp
    from app.routes.invoices import bp as invoices_bp
    from app.routes.finance import bp as finance_bp
    from app.routes.recurring import bp as recurring_bp
    from app.routes.calendar import bp as calendar_bp
    from app.routes.khata import bp as khata_bp

    blueprints = (
        auth_bp,
        main_bp,
        transactions_bp,
        parties_bp,
        invoices_bp,
        finance_bp,
        recurring_bp,
        calendar_bp,
        khata_bp,
    )

    for blueprint in blueprints:
        app.register_blueprint(blueprint)

    # Public route manifest.
    @app.get("/manus-routes.json")
    def route_manifest():
        return send_from_directory(
            Path(app.root_path).parent / "public",
            "manus-routes.json",
            mimetype="application/json",
        )

    # Flask-Login user loader.
    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    # Currency formatting filter.
    @app.template_filter("money")
    def money_filter(amount_paise, currency="INR"):
        return format_inr(amount_paise, currency)

    # Shared template context.
    @app.context_processor
    def inject_shell_data():
        unread = 0

        if current_user.is_authenticated and current_user.business:
            unread = Notification.query.filter_by(
                business_id=current_user.business.id,
                is_read=False,
            ).count()

        return {
            "unread_notification_count": unread,
            "today_iso": date.today().isoformat(),
        }

    # Default security headers.
    @app.after_request
    def protect_responses(response):
        response.headers.setdefault(
            "X-Content-Type-Options",
            "nosniff",
        )
        response.headers.setdefault(
            "Referrer-Policy",
            "strict-origin-when-cross-origin",
        )
        response.headers.setdefault(
            "Cache-Control",
            "no-store",
        )

        return response

    # Error handlers.
    @app.errorhandler(404)
    def not_found(_error):
        return (
            render_template(
                "errors/error.html",
                code=404,
                title="Page not found",
                message=(
                    "That page is not available in this workspace."
                ),
            ),
            404,
        )

    @app.errorhandler(413)
    def too_large(_error):
        return (
            render_template(
                "errors/error.html",
                code=413,
                title="File too large",
                message="Choose a file smaller than 10 MB.",
            ),
            413,
        )

    @app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()

        return (
            render_template(
                "errors/error.html",
                code=500,
                title="Something went wrong",
                message=(
                    "Your records were not confirmed as saved. "
                    "Please try again."
                ),
            ),
            500,
        )

    return app