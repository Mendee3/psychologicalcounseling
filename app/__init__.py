from __future__ import annotations

import os
from pathlib import Path

from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "scheduler.db"

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "admin.login"


def _ensure_schema() -> None:
    inspector = inspect(db.engine)

    counselor_columns = {col["name"] for col in inspector.get_columns("counselor")}
    if "email" not in counselor_columns:
        db.session.execute(text("ALTER TABLE counselor ADD COLUMN email VARCHAR(120) NOT NULL DEFAULT ''"))
    if "photo_path" not in counselor_columns:
        db.session.execute(text("ALTER TABLE counselor ADD COLUMN photo_path VARCHAR(255) NOT NULL DEFAULT ''"))

    appointment_columns = {col["name"] for col in inspector.get_columns("appointment")}
    if "decision_token" not in appointment_columns:
        db.session.execute(text("ALTER TABLE appointment ADD COLUMN decision_token VARCHAR(64) NOT NULL DEFAULT ''"))
    if "responded_at" not in appointment_columns:
        db.session.execute(text("ALTER TABLE appointment ADD COLUMN responded_at DATETIME"))

    db.session.commit()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("PC_SECRET_KEY", "CHANGE_ME_TO_RANDOM_LONG_STRING")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)

    from .routes_public import public_bp
    from .routes_admin import admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()
        _ensure_schema()

    return app
