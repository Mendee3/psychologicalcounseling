from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required, login_user, logout_user
from openpyxl import Workbook
from sqlalchemy import and_, func
from werkzeug.utils import secure_filename

from . import db
from .models import AdminUser, Appointment, AvailabilitySlot, Counselor

admin_bp = Blueprint("admin", __name__)
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _save_counselor_photo(file_storage) -> str:
    if not file_storage or not file_storage.filename:
        return ""

    suffix = Path(file_storage.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Зөвхөн jpg, jpeg, png, gif, webp зураг оруулна.")

    upload_dir = Path(current_app.static_folder) / "counselors"
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = secure_filename(Path(file_storage.filename).stem) or "counselor"
    filename = f"{safe_stem}-{secrets.token_hex(8)}{suffix}"
    target = upload_dir / filename
    file_storage.save(target)
    return f"counselors/{filename}"


def _parse_clock(value: str):
    return datetime.strptime(value, "%H:%M").time()


def _parse_date(value: str, fallback: date) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback


def _report_rows(report_start: date, report_end: date):
    return (
        db.session.query(
            Counselor.id,
            Counselor.name,
            Counselor.title,
            func.count(Appointment.id).label("meeting_count"),
        )
        .outerjoin(
            Appointment,
            and_(
                Appointment.counselor_id == Counselor.id,
                Appointment.status.in_(["confirmed", "completed"]),
            ),
        )
        .outerjoin(AvailabilitySlot, AvailabilitySlot.id == Appointment.slot_id)
        .filter(
            Counselor.active == True,
            ((AvailabilitySlot.slot_date >= report_start) & (AvailabilitySlot.slot_date <= report_end)) | (Appointment.id.is_(None)),
        )
        .group_by(Counselor.id, Counselor.name, Counselor.title)
        .order_by(func.count(Appointment.id).desc(), Counselor.name.asc())
        .all()
    )


@admin_bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    return render_template("admin_login.html")


@admin_bp.post("/login")
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = AdminUser.query.filter_by(username=username, active=True).first()
    if not user or not user.check_password(password):
        return render_template("admin_login.html", error="Нэвтрэх нэр эсвэл нууц үг буруу байна.")

    login_user(user)
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("admin.login"))


@admin_bp.get("")
@login_required
def dashboard():
    today = date.today()
    report_start = _parse_date(request.args.get("report_start"), today.replace(day=1))
    report_end = _parse_date(request.args.get("report_end"), today)
    slot_start = _parse_date(request.args.get("slot_start"), today)
    slot_end = _parse_date(request.args.get("slot_end"), today + timedelta(days=14))
    slot_counselor_id = request.args.get("slot_counselor_id", type=int)

    counselors = Counselor.query.order_by(Counselor.active.desc(), Counselor.name.asc()).all()
    appointments = Appointment.query.order_by(Appointment.created_at.desc()).limit(30).all()
    admin_users = AdminUser.query.order_by(AdminUser.active.desc(), AdminUser.username.asc()).all()

    slots_query = (
        AvailabilitySlot.query.join(Counselor)
        .filter(AvailabilitySlot.slot_date >= slot_start, AvailabilitySlot.slot_date <= slot_end)
        .order_by(AvailabilitySlot.slot_date.asc(), AvailabilitySlot.start_time.asc())
    )
    if slot_counselor_id:
        slots_query = slots_query.filter(AvailabilitySlot.counselor_id == slot_counselor_id)
    slots = slots_query.limit(200).all()

    report_rows = _report_rows(report_start, report_end)

    return render_template(
        "admin.html",
        counselors=counselors,
        appointments=appointments,
        admin_users=admin_users,
        slots=slots,
        report_rows=report_rows,
        today=today.isoformat(),
        report_start=report_start.isoformat(),
        report_end=report_end.isoformat(),
        slot_start=slot_start.isoformat(),
        slot_end=slot_end.isoformat(),
        slot_counselor_id=slot_counselor_id,
        message=request.args.get("message", "").strip(),
        error=request.args.get("error", "").strip(),
    )


@admin_bp.get("/reports/meetings.xlsx")
@login_required
def export_meetings_report():
    today = date.today()
    report_start = _parse_date(request.args.get("report_start"), today.replace(day=1))
    report_end = _parse_date(request.args.get("report_end"), today)
    rows = _report_rows(report_start, report_end)

    wb = Workbook()
    ws = wb.active
    ws.title = "Meetings"
    ws.append(["Сэтгэлзүйч", "Албан тушаал", "Уулзалтын тоо", "Эхлэх өдөр", "Дуусах өдөр"])
    for row in rows:
        ws.append([row.name, row.title, int(row.meeting_count or 0), report_start.isoformat(), report_end.isoformat()])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"psychologicalcounseling-report-{report_start.isoformat()}-{report_end.isoformat()}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@admin_bp.post("/admins")
@login_required
def add_admin():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return redirect(url_for("admin.dashboard", error="Админы нэр болон нууц үг заавал бөглөнө."))

    existing = AdminUser.query.filter_by(username=username).first()
    if existing:
        existing.set_password(password)
        existing.active = True
        message = "Админ хэрэглэгчийн эрх шинэчлэгдлээ."
    else:
        existing = AdminUser(username=username, active=True)
        existing.set_password(password)
        db.session.add(existing)
        message = "Шинэ админ хэрэглэгч үүслээ."

    db.session.commit()
    return redirect(url_for("admin.dashboard", message=message))


@admin_bp.post("/admins/<int:admin_id>/status")
@login_required
def update_admin_status(admin_id: int):
    admin_user = AdminUser.query.get_or_404(admin_id)
    active = request.form.get("active") == "true"

    if admin_user.id == current_user.id and not active:
        return redirect(url_for("admin.dashboard", error="Өөрийн админ эрхийг өөрөө хаах боломжгүй."))

    admin_user.active = active
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Админы төлөв шинэчлэгдлээ."))


@admin_bp.post("/counselors")
@login_required
def add_counselor():
    try:
        photo_path = _save_counselor_photo(request.files.get("photo"))
    except ValueError as exc:
        return redirect(url_for("admin.dashboard", error=str(exc)))

    counselor = Counselor(
        name=request.form.get("name", "").strip(),
        title=request.form.get("title", "").strip(),
        email=request.form.get("email", "").strip(),
        photo_path=photo_path,
        bio=request.form.get("bio", "").strip(),
        location=request.form.get("location", "").strip(),
        session_minutes=request.form.get("session_minutes", type=int) or 50,
        active=request.form.get("active") == "on",
    )
    db.session.add(counselor)
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Сэтгэлзүйч хадгалагдлаа."))


@admin_bp.post("/counselors/<int:counselor_id>/status")
@login_required
def update_counselor_status(counselor_id: int):
    counselor = Counselor.query.get_or_404(counselor_id)
    counselor.active = request.form.get("active") == "true"
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Сэтгэлзүйчийн төлөв шинэчлэгдлээ."))


@admin_bp.post("/slots")
@login_required
def add_slot():
    counselor = Counselor.query.get_or_404(request.form.get("counselor_id", type=int))
    start_date = date.fromisoformat(request.form.get("start_date", ""))
    end_date = date.fromisoformat(request.form.get("end_date", ""))
    range_start = _parse_clock(request.form.get("range_start", ""))
    range_end = _parse_clock(request.form.get("range_end", ""))
    session_minutes = request.form.get("session_minutes", type=int) or counselor.session_minutes or 50
    buffer_minutes = request.form.get("buffer_minutes", type=int) or 0
    capacity = request.form.get("capacity", type=int) or 1

    if session_minutes <= 0:
        return redirect(url_for("admin.dashboard", error="Нэг уулзалтын үргэлжлэх хугацаа 1 минутаас их байна."))
    if start_date > end_date:
        return redirect(url_for("admin.dashboard", error="Эхлэх өдөр нь дуусах өдрөөс өмнө эсвэл тэнцүү байх ёстой."))

    sample_start = datetime.combine(start_date, range_start)
    sample_end = datetime.combine(start_date, range_end)
    if sample_start >= sample_end:
        return redirect(url_for("admin.dashboard", error="Эхлэх цаг нь дуусах цагаас өмнө байх ёстой."))

    created = 0
    skipped = 0
    day_cursor = start_date
    step = timedelta(minutes=session_minutes + buffer_minutes)
    duration = timedelta(minutes=session_minutes)

    while day_cursor <= end_date:
        cursor = datetime.combine(day_cursor, range_start)
        end_dt = datetime.combine(day_cursor, range_end)
        while cursor + duration <= end_dt:
            start_time = cursor.time()
            end_time = (cursor + duration).time()
            exists = AvailabilitySlot.query.filter_by(
                counselor_id=counselor.id,
                slot_date=day_cursor,
                start_time=start_time,
            ).first()
            if exists:
                skipped += 1
            else:
                db.session.add(
                    AvailabilitySlot(
                        counselor_id=counselor.id,
                        slot_date=day_cursor,
                        start_time=start_time,
                        end_time=end_time,
                        capacity=capacity,
                        active=True,
                    )
                )
                created += 1
            cursor += step
        day_cursor += timedelta(days=1)

    db.session.commit()
    return redirect(url_for("admin.dashboard", message=f"{created} слот нэмэгдлээ. Алгассан: {skipped}."))


@admin_bp.post("/slots/<int:slot_id>/delete")
@login_required
def delete_slot(slot_id: int):
    slot = AvailabilitySlot.query.get_or_404(slot_id)
    db.session.delete(slot)
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Слот устгагдлаа."))


@admin_bp.post("/slots/bulk-delete")
@login_required
def bulk_delete_slots():
    slot_counselor_id = request.form.get("slot_counselor_id", type=int)
    slot_start = date.fromisoformat(request.form.get("slot_start", ""))
    slot_end = date.fromisoformat(request.form.get("slot_end", ""))
    if slot_start > slot_end:
        return redirect(url_for("admin.dashboard", error="Слот устгах мужийн эхлэх өдөр нь дуусахаас өмнө байх ёстой."))

    query = AvailabilitySlot.query.filter(AvailabilitySlot.slot_date >= slot_start, AvailabilitySlot.slot_date <= slot_end)
    if slot_counselor_id:
        query = query.filter(AvailabilitySlot.counselor_id == slot_counselor_id)
    removed = query.delete(synchronize_session=False)
    db.session.commit()
    return redirect(url_for("admin.dashboard", message=f"{removed} слот устгагдлаа."))


@admin_bp.post("/appointments/<int:appointment_id>/status")
@login_required
def update_appointment_status(appointment_id: int):
    appointment = Appointment.query.get_or_404(appointment_id)
    status = request.form.get("status", "requested").strip()
    if status not in {"requested", "confirmed", "declined", "cancelled", "completed"}:
        status = "requested"
    appointment.status = status
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Уулзалтын төлөв шинэчлэгдлээ."))


@admin_bp.get("/api/appointments")
@login_required
def api_appointments():
    rows = Appointment.query.order_by(Appointment.created_at.desc()).limit(100).all()
    return jsonify([
        {
            "id": row.id,
            "counselor": row.counselor.name,
            "slot_date": row.slot.slot_date.isoformat(),
            "slot_time": row.slot.label,
            "client_name": row.client_name,
            "client_phone": row.client_phone,
            "status": row.status,
        }
        for row in rows
    ])
