from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import Flask, redirect, url_for
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "scheduler.db"

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "admin.login"


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _ensure_admin_user_foreign_key(inspector) -> None:
    foreign_keys = inspector.get_foreign_keys("admin_user")
    has_counselor_fk = any(
        fk.get("referred_table") == "counselor" and fk.get("constrained_columns") == ["counselor_id"]
        for fk in foreign_keys
    )
    if has_counselor_fk:
        return

    db.session.execute(text("PRAGMA foreign_keys=OFF"))
    db.session.execute(
        text(
            "UPDATE admin_user SET counselor_id = NULL WHERE counselor_id IS NOT NULL AND counselor_id NOT IN (SELECT id FROM counselor)"
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE admin_user__new (
                id INTEGER NOT NULL PRIMARY KEY,
                username VARCHAR(80) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                active BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'admin',
                counselor_id INTEGER,
                FOREIGN KEY(counselor_id) REFERENCES counselor (id) ON DELETE SET NULL
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            INSERT INTO admin_user__new (id, username, password_hash, active, created_at, role, counselor_id)
            SELECT id, username, password_hash, active, created_at, role, counselor_id
            FROM admin_user
            """
        )
    )
    db.session.execute(text("DROP TABLE admin_user"))
    db.session.execute(text("ALTER TABLE admin_user__new RENAME TO admin_user"))
    db.session.execute(text("CREATE INDEX ix_admin_user_role ON admin_user (role)"))
    db.session.execute(text("CREATE INDEX ix_admin_user_counselor_id ON admin_user (counselor_id)"))
    db.session.execute(text("PRAGMA foreign_keys=ON"))
    db.session.commit()


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

    inspector = inspect(db.engine)
    _ensure_admin_user_foreign_key(inspector)


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
