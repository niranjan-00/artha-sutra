from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect


# Database ORM.
db = SQLAlchemy()

# Database migration management.
migrate = Migrate()

# User authentication and session management.
login_manager = LoginManager()

# Cross-site request forgery protection.
csrf = CSRFProtect()