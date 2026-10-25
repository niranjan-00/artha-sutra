import os
import secrets


def _enabled(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development")
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        if APP_ENV == "production":
            raise RuntimeError("SECRET_KEY must be configured in production.")
        SECRET_KEY = secrets.token_hex(32)

    SESSION_COOKIE_NAME = "artha_sutra_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _enabled("COOKIE_SECURE", True)
    SESSION_COOKIE_SAMESITE = "None" if SESSION_COOKIE_SECURE else "Lax"
    SESSION_COOKIE_PATH = "/"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12
    WTF_CSRF_TIME_LIMIT = 60 * 60
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", str(10 * 1024 * 1024)))
    UPLOAD_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
