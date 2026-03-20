from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, redirect, request, url_for
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.exceptions import RequestEntityTooLarge
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
    if "client_department" not in appointment_columns:
        db.session.execute(text("ALTER TABLE appointment ADD COLUMN client_department VARCHAR(160) NOT NULL DEFAULT ''"))
    if "decision_token" not in appointment_columns:
        db.session.execute(text("ALTER TABLE appointment ADD COLUMN decision_token VARCHAR(64) NOT NULL DEFAULT ''"))
    if "responded_at" not in appointment_columns:
        db.session.execute(text("ALTER TABLE appointment ADD COLUMN responded_at DATETIME"))
    if "completed_at" not in appointment_columns:
        db.session.execute(text("ALTER TABLE appointment ADD COLUMN completed_at DATETIME"))
    if "feedback_sent_at" not in appointment_columns:
        db.session.execute(text("ALTER TABLE appointment ADD COLUMN feedback_sent_at DATETIME"))

    admin_columns = {col["name"] for col in inspector.get_columns("admin_user")}
    if "role" not in admin_columns:
        db.session.execute(text("ALTER TABLE admin_user ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'admin'"))
    if "counselor_id" not in admin_columns:
        db.session.execute(text("ALTER TABLE admin_user ADD COLUMN counselor_id INTEGER"))

    db.session.execute(text("UPDATE admin_user SET role = 'admin' WHERE role IS NULL OR role = ''"))

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
    from .routes_counselor import counselor_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(counselor_bp, url_prefix="/counselor")

    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()
        _ensure_schema()

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_entity_too_large(_exc):
        return redirect(url_for("admin.dashboard", error="Зураг хэт том байна. Жижигрүүлж эсвэл тайраад дахин оруулна уу."))

    return app
