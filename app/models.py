from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager


class AdminUser(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="admin", nullable=False, index=True)
    counselor_id = db.Column(db.Integer, db.ForeignKey("counselor.id"), nullable=True, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    counselor = db.relationship("Counselor", backref="portal_users")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id: str):
    return AdminUser.query.get(int(user_id))


class Counselor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), default="", nullable=False)
    photo_path = db.Column(db.String(255), default="", nullable=False)
    bio = db.Column(db.Text, default="", nullable=False)
    session_minutes = db.Column(db.Integer, default=50, nullable=False)
    location = db.Column(db.String(200), default="", nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AvailabilitySlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    counselor_id = db.Column(db.Integer, db.ForeignKey("counselor.id"), nullable=False, index=True)
    slot_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    capacity = db.Column(db.Integer, default=1, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    counselor = db.relationship("Counselor", backref="slots")

    __table_args__ = (
        db.UniqueConstraint("counselor_id", "slot_date", "start_time", name="uq_slot_unique"),
    )

    @property
    def label(self) -> str:
        return f"{self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    counselor_id = db.Column(db.Integer, db.ForeignKey("counselor.id"), nullable=False, index=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("availability_slot.id"), nullable=False, index=True)
    client_name = db.Column(db.String(120), nullable=False)
    client_department = db.Column(db.String(160), default="", nullable=False)
    client_phone = db.Column(db.String(40), nullable=False)
    client_email = db.Column(db.String(120), default="", nullable=False)
    topic = db.Column(db.String(200), default="", nullable=False)
    notes = db.Column(db.Text, default="", nullable=False)
    status = db.Column(db.String(20), default="requested", nullable=False, index=True)
    decision_token = db.Column(db.String(64), unique=True, nullable=False)
    responded_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    feedback_sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    counselor = db.relationship("Counselor", backref="appointments")
    slot = db.relationship("AvailabilitySlot", backref="appointments")

    __table_args__ = (
        db.UniqueConstraint("slot_id", "client_phone", name="uq_slot_client_phone"),
    )


class AppSetting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, default="", nullable=False)


DEFAULT_COUNSELOR = {
    "name": "Сэтгэлзүйч",
    "title": "Дотоод зөвлөх",
    "email": "",
    "photo_path": "",
    "bio": "Ажилтнуудтай нууцлалтай уулзалт товлох энгийн хуваарь.",
    "location": "Оффис уулзалтын өрөө",
    "session_minutes": 50,
}
