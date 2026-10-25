import os
from datetime import date
from pathlib import Path

from flask import Flask, render_template, send_from_directory
from flask_login import current_user

from app.extensions import csrf, db, login_manager, migrate
from app.models import Notification, User
from app.services.money import format_inr


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.instance_path, "uploads").mkdir(parents=True, exist_ok=True)

    from config import Config
    app.config.from_object(Config)
    if not os.environ.get("DATABASE_URL"):
        database_path = Path(app.instance_path, "arthasutra.sqlite3").as_posix()
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database_path}"
    app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER") or str(Path(app.instance_path, "uploads"))
    if test_config:
        app.config.update(test_config)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    setattr(login_manager, "login_view", "auth.login")
    login_manager.login_message = "Sign in to continue to your business workspace."
    login_manager.login_message_category = "info"
    csrf.init_app(app)

    from app.routes.auth import bp as auth_bp
    from app.routes.main import bp as main_bp
    from app.routes.transactions import bp as transactions_bp
    from app.routes.parties import bp as parties_bp
    from app.routes.invoices import bp as invoices_bp
    from app.routes.finance import bp as finance_bp
    from app.routes.recurring import bp as recurring_bp
    from app.routes.calendar import bp as calendar_bp
    from app.routes.khata import bp as khata_bp
    for blueprint in (auth_bp, main_bp, transactions_bp, parties_bp, invoices_bp, finance_bp, recurring_bp, calendar_bp, khata_bp):
        app.register_blueprint(blueprint)

    @app.get("/manus-routes.json")
    def route_manifest():
        return send_from_directory(Path(app.root_path).parent / "public", "manus-routes.json", mimetype="application/json")

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    @app.template_filter("money")
    def money_filter(amount_paise, currency="INR"):
        return format_inr(amount_paise, currency)

    @app.context_processor
    def inject_shell_data():
        unread = 0
        if current_user.is_authenticated and current_user.business:
            unread = Notification.query.filter_by(business_id=current_user.business.id, is_read=False).count()
        return {"unread_notification_count": unread, "today_iso": date.today().isoformat()}

    @app.after_request
    def protect_responses(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/error.html", code=404, title="Page not found", message="That page is not available in this workspace."), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("errors/error.html", code=413, title="File too large", message="Choose a file smaller than 10 MB."), 413

    @app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()
        return render_template("errors/error.html", code=500, title="Something went wrong", message="Your records were not confirmed as saved. Please try again."), 500

    return app
