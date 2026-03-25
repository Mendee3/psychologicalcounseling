from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from . import db
from .email_utils import send_appointment_decision_email, send_appointment_request_email
from .models import AppSetting, Appointment, AvailabilitySlot, Counselor, DEFAULT_COUNSELOR

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


def calendar_days(counselor_id: int, start_date: date, days: int = 15, *, today: date | None = None):
    end_date = start_date + timedelta(days=20)
    today = today or date.today()
    slots = (
        AvailabilitySlot.query.filter(
            AvailabilitySlot.counselor_id == counselor_id,
            AvailabilitySlot.slot_date >= start_date,
            AvailabilitySlot.slot_date <= end_date,
            AvailabilitySlot.active.is_(True),
        )
        .order_by(AvailabilitySlot.slot_date.asc(), AvailabilitySlot.start_time.asc())
        .all()
    )
    slot_ids = [slot.id for slot in slots]
    booked_counts = {}
    if slot_ids:
        booked_counts = {
            slot_id: count
            for slot_id, count in db.session.query(Appointment.slot_id, db.func.count(Appointment.id))
            .filter(
                Appointment.slot_id.in_(slot_ids),
                Appointment.status.in_(tuple(BOOKED_STATUSES)),
            )
            .group_by(Appointment.slot_id)
            .all()
        }

    available_by_day = {}
    for slot in slots:
        remaining = max(slot.capacity - booked_counts.get(slot.id, 0), 0)
        if remaining > 0:
            available_by_day[slot.slot_date] = available_by_day.get(slot.slot_date, 0) + remaining

    weekday_labels = ["Да", "Мя", "Лх", "Пү", "Ба", "Бя", "Ня"]
    result = []
    current = start_date
    while len(result) < days:
        if current.weekday() < 5:
            available_count = available_by_day.get(current, 0)
            selectable = current >= today and available_count > 0
            result.append(
                {
                    "date": current.isoformat(),
                    "day": current.strftime("%d"),
                    "month": current.strftime("%m/%d"),
                    "weekday": weekday_labels[current.weekday()],
                    "available": selectable,
                    "available_count": available_count,
                    "is_today": current == today,
                    "is_past": current < today,
                }
            )
        current += timedelta(days=1)
    return result


def _setting(key: str, default: str = "") -> str:
    row = AppSetting.query.filter_by(key=key).first()
    return row.value if row else default


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

    if selected_date < today_obj:
        selected_date = today_obj
        selected_date_raw = today

    week_offset = max(request.args.get("week_offset", default=0, type=int) or 0, 0)
    visible_start = today_obj - timedelta(days=today_obj.weekday()) + timedelta(days=week_offset * 7)
    visible_end = visible_start + timedelta(days=20)

    selected_id = request.args.get("counselor_id", type=int)
    selected_counselor = next((item for item in counselors if item.id == selected_id), None)
    days = []
    has_available_days = False
    if selected_date < visible_start or selected_date > visible_end:
        selected_date = max(today_obj, visible_start)
        selected_date_raw = selected_date.isoformat()

    if selected_counselor:
        days = calendar_days(selected_counselor.id, visible_start, days=15, today=today_obj)
        available_dates = [item["date"] for item in days if item["available"]]
        has_available_days = bool(available_dates)
        if available_dates and selected_date_raw not in {item["date"] for item in days}:
            selected_date_raw = available_dates[0]
            selected_date = date.fromisoformat(selected_date_raw)
        elif available_dates and selected_date_raw not in available_dates and selected_date >= today_obj:
            matching_day = next((item for item in days if item["date"] == selected_date_raw), None)
            if matching_day and matching_day["is_past"]:
                selected_date_raw = available_dates[0]
                selected_date = date.fromisoformat(selected_date_raw)
    slots = available_slots(selected_counselor.id, selected_date) if selected_counselor else []
    return render_template(
        "public.html",
        counselors=counselors,
        counselor=selected_counselor,
        counselor_summaries=counselor_summaries(selected_date),
        today=today,
        selected_date=selected_date_raw,
        slots=slots,
        calendar_days=days,
        has_available_days=has_available_days,
        week_offset=week_offset,
        calendar_window_label=f"{visible_start.strftime('%Y-%m-%d')} - {visible_end.strftime('%Y-%m-%d')}",
        booked=request.args.get("booked", ""),
        recommendation_enabled=_setting("recommendation_enabled", "true") == "true",
        recommendation_title=_setting("recommendation_title", "Зөвлөмж"),
        recommendation_body=_setting("recommendation_body", "Танд яаралтай дэмжлэг хэрэгтэй бол хамгийн ойрын сэтгэлзүйчээ сонгон уулзалтын хүсэлт илгээнэ үү."),
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


@public_bp.get("/api/counselor-summaries")
def api_counselor_summaries():
    raw_date = request.args.get("date", "")
    if not raw_date:
        return jsonify([])
    try:
        selected = date.fromisoformat(raw_date)
    except ValueError:
        return jsonify([])
    return jsonify([
        {
            "id": row["id"],
            "available_count": row["available_count"],
        }
        for row in counselor_summaries(selected)
    ])


@public_bp.post("/book")
def book():
    counselor_id = request.form.get("counselor_id", type=int)
    slot_id = request.form.get("slot_id", type=int)
    client_name = request.form.get("client_name", "").strip()
    client_department = request.form.get("client_department", "").strip()
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
        client_department=client_department,
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
