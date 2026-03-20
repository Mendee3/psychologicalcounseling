from __future__ import annotations

from datetime import date
from functools import wraps

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func

from .appointment_utils import APPOINTMENT_STATUSES, update_appointment_status
from .models import AdminUser, Appointment, AvailabilitySlot

counselor_bp = Blueprint("counselor", __name__)


def counselor_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("counselor.login"))
        if getattr(current_user, "role", "") != "counselor":
            return redirect(url_for("admin.dashboard"))
        if not current_user.active or not current_user.counselor:
            logout_user()
            return redirect(url_for("counselor.login"))
        return view(*args, **kwargs)

    return wrapped


@counselor_bp.get("/login")
def login():
    if current_user.is_authenticated:
        if getattr(current_user, "role", "") == "counselor":
            return redirect(url_for("counselor.dashboard"))
        logout_user()
    return render_template("counselor_login.html")


@counselor_bp.post("/login")
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = AdminUser.query.filter_by(username=username, active=True, role="counselor").first()
    if not user or not user.check_password(password) or not user.counselor or not user.counselor.active:
        return render_template("counselor_login.html", error="Нэвтрэх нэр эсвэл нууц үг буруу байна.")

    login_user(user)
    return redirect(url_for("counselor.dashboard"))


@counselor_bp.post("/logout")
@counselor_required
def logout():
    logout_user()
    return redirect(url_for("counselor.login"))


@counselor_bp.get("")
@counselor_required
def dashboard():
    counselor = current_user.counselor
    appointments = (
        Appointment.query.join(AvailabilitySlot)
        .filter(Appointment.counselor_id == counselor.id)
        .order_by(AvailabilitySlot.slot_date.desc(), AvailabilitySlot.start_time.desc())
        .limit(100)
        .all()
    )
    completed_count = Appointment.query.filter_by(counselor_id=counselor.id, status="completed").count()
    total_meetings = Appointment.query.filter(Appointment.counselor_id == counselor.id).count()
    latest_meeting = (
        Appointment.query.join(AvailabilitySlot)
        .filter(
            Appointment.counselor_id == counselor.id,
            Appointment.status == "completed",
        )
        .order_by(AvailabilitySlot.slot_date.desc(), AvailabilitySlot.start_time.desc())
        .first()
    )
    meetings_by_day = (
        Appointment.query.join(AvailabilitySlot)
        .with_entities(AvailabilitySlot.slot_date.label("slot_date"), func.count(Appointment.id).label("count"))
        .filter(
            Appointment.counselor_id == counselor.id,
            Appointment.status == "completed",
        )
        .group_by(AvailabilitySlot.slot_date)
        .order_by(AvailabilitySlot.slot_date.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "counselor_dashboard.html",
        counselor=counselor,
        appointments=appointments,
        completed_count=completed_count,
        total_meetings=total_meetings,
        latest_meeting=latest_meeting,
        meetings_by_day=meetings_by_day,
        today=date.today().isoformat(),
        statuses=APPOINTMENT_STATUSES,
        message=request.args.get("message", "").strip(),
        error=request.args.get("error", "").strip(),
    )


@counselor_bp.post("/appointments/<int:appointment_id>/status")
@counselor_required
def update_status(appointment_id: int):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.counselor_id != current_user.counselor_id:
        return redirect(url_for("counselor.dashboard", error="Та зөвхөн өөрийн уулзалтыг шинэчилнэ."))

    result = update_appointment_status(appointment, request.form.get("status", "requested"))
    message = "Уулзалтын төлөв шинэчлэгдлээ."
    if result["changed"] and appointment.status == "completed" and not result["feedback_email_sent"] and appointment.client_email:
        message = "Уулзалтын төлөв шинэчлэгдлээ. Санал хүсэлтийн и-мэйл илгээгдсэнгүй."
    return redirect(url_for("counselor.dashboard", message=message))
