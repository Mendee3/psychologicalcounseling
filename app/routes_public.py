from __future__ import annotations

import secrets
from datetime import date, datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from . import db
from .email_utils import send_appointment_decision_email, send_appointment_request_email
from .models import Appointment, AvailabilitySlot, Counselor, DEFAULT_COUNSELOR

public_bp = Blueprint("public", __name__)


BOOKED_STATUSES = {"requested", "confirmed"}


def ensure_default_counselor() -> Counselor:
    counselor = Counselor.query.order_by(Counselor.id.asc()).first()
    if counselor:
        return counselor

    counselor = Counselor(**DEFAULT_COUNSELOR)
    db.session.add(counselor)
    db.session.commit()
    return counselor


def active_counselors() -> list[Counselor]:
    ensure_default_counselor()
    return Counselor.query.filter_by(active=True).order_by(Counselor.name.asc()).all()


def available_slots(counselor_id: int, slot_date: date):
    slots = (
        AvailabilitySlot.query.filter_by(counselor_id=counselor_id, slot_date=slot_date, active=True)
        .order_by(AvailabilitySlot.start_time.asc())
        .all()
    )
    result = []
    for slot in slots:
        active_count = Appointment.query.filter(
            Appointment.slot_id == slot.id,
            Appointment.status.in_(tuple(BOOKED_STATUSES)),
        ).count()
        remaining = max(slot.capacity - active_count, 0)
        if remaining > 0:
            result.append({"id": slot.id, "label": slot.label, "remaining": remaining})
    return result


def counselor_summaries(slot_date: date):
    result = []
    for counselor in active_counselors():
        slots = available_slots(counselor.id, slot_date)
        result.append(
            {
                "id": counselor.id,
                "name": counselor.name,
                "title": counselor.title,
                "bio": counselor.bio,
                "location": counselor.location,
                "session_minutes": counselor.session_minutes,
                "available_count": len(slots),
                "photo_path": counselor.photo_path,
            }
        )
    return result


@public_bp.get("/")
def home():
    counselors = active_counselors()
    today_obj = date.today()
    today = today_obj.isoformat()
    selected_date_raw = request.args.get("date", today)
    try:
        selected_date = date.fromisoformat(selected_date_raw)
    except ValueError:
        selected_date = today_obj
        selected_date_raw = today

    selected_id = request.args.get("counselor_id", type=int)
    selected_counselor = next((item for item in counselors if item.id == selected_id), None)
    if not selected_counselor:
        selected_counselor = counselors[0] if counselors else ensure_default_counselor()

    slots = available_slots(selected_counselor.id, selected_date)
    return render_template(
        "public.html",
        counselors=counselors,
        counselor=selected_counselor,
        counselor_summaries=counselor_summaries(selected_date),
        today=today,
        selected_date=selected_date_raw,
        slots=slots,
        booked=request.args.get("booked", ""),
    )


@public_bp.get("/api/slots")
def api_slots():
    counselor_id = request.args.get("counselor_id", type=int)
    raw_date = request.args.get("date", "")
    if not counselor_id or not raw_date:
        return jsonify([])
    try:
        selected = date.fromisoformat(raw_date)
    except ValueError:
        return jsonify([])
    return jsonify(available_slots(counselor_id, selected))


@public_bp.post("/book")
def book():
    counselor_id = request.form.get("counselor_id", type=int)
    slot_id = request.form.get("slot_id", type=int)
    client_name = request.form.get("client_name", "").strip()
    client_phone = request.form.get("client_phone", "").strip()
    client_email = request.form.get("client_email", "").strip()
    topic = request.form.get("topic", "").strip()
    notes = request.form.get("notes", "").strip()
    selected_date = request.form.get("selected_date", "")

    counselor = Counselor.query.get_or_404(counselor_id)
    slot = AvailabilitySlot.query.get_or_404(slot_id)

    if slot.counselor_id != counselor.id or not slot.active:
        return redirect(url_for("public.home"))
    if not client_email:
        return redirect(url_for("public.home", booked="email_required", date=selected_date, counselor_id=counselor.id))

    active_count = Appointment.query.filter(
        Appointment.slot_id == slot.id,
        Appointment.status.in_(tuple(BOOKED_STATUSES)),
    ).count()
    if active_count >= slot.capacity:
        return redirect(url_for("public.home", booked="full", date=selected_date, counselor_id=counselor.id))

    appointment = Appointment(
        counselor_id=counselor.id,
        slot_id=slot.id,
        client_name=client_name,
        client_phone=client_phone,
        client_email=client_email,
        topic=topic,
        notes=notes,
        status="requested",
        decision_token=secrets.token_urlsafe(24),
    )
    db.session.add(appointment)
    db.session.commit()

    try:
        send_appointment_request_email(appointment)
    except Exception:
        return redirect(url_for("public.home", booked="mail_error", date=selected_date, counselor_id=counselor.id))

    return redirect(url_for("public.home", booked="requested", date=selected_date, counselor_id=counselor.id))


@public_bp.route("/appointment-response/<token>", methods=["GET", "POST"])
def appointment_response(token: str):
    appointment = Appointment.query.filter_by(decision_token=token).first_or_404()

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        if appointment.status in {"confirmed", "declined"}:
            return redirect(url_for("public.appointment_response", token=token, result="done"))
        if action == "accept":
            appointment.status = "confirmed"
        elif action == "refuse":
            appointment.status = "declined"
        else:
            return redirect(url_for("public.appointment_response", token=token, result="invalid"))
        appointment.responded_at = datetime.utcnow()
        db.session.commit()
        mail_result = "mail_sent"
        try:
            send_appointment_decision_email(appointment)
        except Exception:
            mail_result = "mail_failed"
        return redirect(url_for("public.appointment_response", token=token, result=appointment.status, notify=mail_result))

    return render_template(
        "appointment_response.html",
        appointment=appointment,
        result=request.args.get("result", ""),
        notify=request.args.get("notify", ""),
    )
