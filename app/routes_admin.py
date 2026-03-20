from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_user, logout_user
from openpyxl import Workbook
from sqlalchemy import and_, func
from werkzeug.utils import secure_filename

from . import db
from .appointment_utils import update_appointment_status
from .models import AdminUser, AppSetting, Appointment, AvailabilitySlot, Counselor

admin_bp = Blueprint("admin", __name__)
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
COUNSELOR_UPLOAD_SUBDIR = Path("uploads") / "counselors"


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("admin.login"))
        if getattr(current_user, "role", "admin") != "admin":
            return redirect(url_for("counselor.dashboard"))
        return view(*args, **kwargs)

    return wrapped


def _save_counselor_photo(file_storage) -> str:
    if not file_storage or not file_storage.filename:
        return ""

    suffix = Path(file_storage.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Зөвхөн jpg, jpeg, png, gif, webp зураг оруулна.")

    upload_dir = Path(current_app.static_folder) / COUNSELOR_UPLOAD_SUBDIR
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = secure_filename(Path(file_storage.filename).stem) or "counselor"
    filename = f"{safe_stem}-{secrets.token_hex(8)}{suffix}"
    target = upload_dir / filename
    file_storage.save(target)
    return f"{COUNSELOR_UPLOAD_SUBDIR.as_posix()}/{filename}"


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


def _setting(key: str, default: str = "") -> str:
    row = AppSetting.query.filter_by(key=key).first()
    return row.value if row else default


def _set_setting(key: str, value: str) -> None:
    row = AppSetting.query.filter_by(key=key).first()
    if not row:
        row = AppSetting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value


@admin_bp.get("/login")
def login():
    if current_user.is_authenticated:
        if getattr(current_user, "role", "admin") == "admin":
            return redirect(url_for("admin.dashboard"))
        logout_user()
    return render_template("admin_login.html")


@admin_bp.post("/login")
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = AdminUser.query.filter_by(username=username, active=True, role="admin").first()
    if not user or not user.check_password(password):
        return render_template("admin_login.html", error="Нэвтрэх нэр эсвэл нууц үг буруу байна.")

    login_user(user)
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/logout")
@admin_required
def logout():
    logout_user()
    return redirect(url_for("admin.login"))


@admin_bp.get("")
@admin_required
def dashboard():
    today = date.today()
    report_start = _parse_date(request.args.get("report_start"), today.replace(day=1))
    report_end = _parse_date(request.args.get("report_end"), today)
    slot_start = _parse_date(request.args.get("slot_start"), today)
    slot_end = _parse_date(request.args.get("slot_end"), today + timedelta(days=14))
    slot_counselor_id = request.args.get("slot_counselor_id", type=int)
    open_section = request.args.get("open_section", "counselors").strip() or "counselors"

    counselors = Counselor.query.order_by(Counselor.active.desc(), Counselor.name.asc()).all()
    appointments = Appointment.query.order_by(Appointment.created_at.desc()).limit(30).all()
    admin_users = (
        AdminUser.query.filter_by(role="admin")
        .order_by(AdminUser.active.desc(), AdminUser.username.asc())
        .all()
    )
    counselor_users = (
        AdminUser.query.filter_by(role="counselor")
        .order_by(AdminUser.active.desc(), AdminUser.username.asc())
        .all()
    )

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
        counselor_users=counselor_users,
        today=today.isoformat(),
        report_start=report_start.isoformat(),
        report_end=report_end.isoformat(),
        slot_start=slot_start.isoformat(),
        slot_end=slot_end.isoformat(),
        slot_counselor_id=slot_counselor_id,
        open_section=open_section,
        message=request.args.get("message", "").strip(),
        error=request.args.get("error", "").strip(),
        recommendation_enabled=_setting("recommendation_enabled", "true") == "true",
        recommendation_title=_setting("recommendation_title", "Зөвлөмж"),
        recommendation_body=_setting("recommendation_body", "Танд яаралтай дэмжлэг хэрэгтэй бол хамгийн ойрын сэтгэлзүйчээ сонгон уулзалтын хүсэлт илгээнэ үү."),
    )


@admin_bp.get("/reports/meetings.xlsx")
@admin_required
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
@admin_required
def add_admin():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return redirect(url_for("admin.dashboard", error="Админы нэр болон нууц үг заавал бөглөнө."))

    existing = AdminUser.query.filter_by(username=username).first()
    if existing:
        if existing.role != "admin":
            return redirect(url_for("admin.dashboard", error="Энэ нэвтрэх нэрийг сэтгэлзүйчийн эрх ашиглаж байна."))
        existing.set_password(password)
        existing.role = "admin"
        existing.counselor_id = None
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
@admin_required
def update_admin_status(admin_id: int):
    admin_user = AdminUser.query.get_or_404(admin_id)
    if admin_user.role != "admin":
        return redirect(url_for("admin.dashboard", error="Буруу админ хэрэглэгч сонгогдлоо."))
    active = request.form.get("active") == "true"

    if admin_user.id == current_user.id and not active:
        return redirect(url_for("admin.dashboard", error="Өөрийн админ эрхийг өөрөө хаах боломжгүй."))

    admin_user.active = active
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Админы төлөв шинэчлэгдлээ."))


@admin_bp.post("/counselors")
@admin_required
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


@admin_bp.get("/counselors/<int:counselor_id>/edit")
@admin_required
def edit_counselor(counselor_id: int):
    counselor = Counselor.query.get_or_404(counselor_id)
    return render_template(
        "admin_edit_counselor.html",
        counselor=counselor,
        error=request.args.get("error", "").strip(),
    )


@admin_bp.post("/counselors/<int:counselor_id>/edit")
@admin_required
def update_counselor(counselor_id: int):
    counselor = Counselor.query.get_or_404(counselor_id)

    try:
        photo_path = _save_counselor_photo(request.files.get("photo"))
    except ValueError as exc:
        return redirect(url_for("admin.edit_counselor", counselor_id=counselor.id, error=str(exc)))

    counselor.name = request.form.get("name", "").strip()
    counselor.title = request.form.get("title", "").strip()
    counselor.email = request.form.get("email", "").strip()
    counselor.bio = request.form.get("bio", "").strip()
    counselor.location = request.form.get("location", "").strip()
    counselor.session_minutes = request.form.get("session_minutes", type=int) or 50
    counselor.active = request.form.get("active") == "on"
    if photo_path:
        counselor.photo_path = photo_path

    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Сэтгэлзүйчийн мэдээлэл шинэчлэгдлээ."))


@admin_bp.post("/counselors/<int:counselor_id>/status")
@admin_required
def update_counselor_status(counselor_id: int):
    counselor = Counselor.query.get_or_404(counselor_id)
    counselor.active = request.form.get("active") == "true"
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Сэтгэлзүйчийн төлөв шинэчлэгдлээ."))


@admin_bp.get("/counselors/<int:counselor_id>/delete")
@admin_required
def confirm_delete_counselor(counselor_id: int):
    counselor = Counselor.query.get_or_404(counselor_id)
    slot_count = AvailabilitySlot.query.filter_by(counselor_id=counselor.id).count()
    appointment_count = Appointment.query.filter_by(counselor_id=counselor.id).count()
    can_delete = slot_count == 0 and appointment_count == 0
    return render_template(
        "admin_delete_counselor.html",
        counselor=counselor,
        slot_count=slot_count,
        appointment_count=appointment_count,
        can_delete=can_delete,
    )


@admin_bp.post("/counselors/<int:counselor_id>/delete")
@admin_required
def delete_counselor(counselor_id: int):
    counselor = Counselor.query.get_or_404(counselor_id)
    slot_count = AvailabilitySlot.query.filter_by(counselor_id=counselor.id).count()
    appointment_count = Appointment.query.filter_by(counselor_id=counselor.id).count()

    if slot_count or appointment_count:
        return redirect(
            url_for(
                "admin.dashboard",
                error="Слот эсвэл уулзалтын түүхтэй сэтгэлзүйчийг бүр мөсөн устгах боломжгүй. Идэвхгүй болгож нуухыг ашиглана уу.",
            )
        )

    db.session.delete(counselor)
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Сэтгэлзүйч бүр мөсөн устгагдлаа."))


@admin_bp.post("/slots")
@admin_required
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
@admin_required
def delete_slot(slot_id: int):
    slot = AvailabilitySlot.query.get_or_404(slot_id)
    db.session.delete(slot)
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Слот устгагдлаа."))


@admin_bp.post("/slots/bulk-delete")
@admin_required
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
@admin_required
def update_appointment_status_route(appointment_id: int):
    appointment = Appointment.query.get_or_404(appointment_id)
    result = update_appointment_status(appointment, request.form.get("status", "requested"))
    message = "Уулзалтын төлөв шинэчлэгдлээ."
    if result["changed"] and appointment.status == "completed" and not result["feedback_email_sent"] and appointment.client_email:
        message = "Уулзалтын төлөв шинэчлэгдлээ. Санал хүсэлтийн и-мэйл илгээгдсэнгүй."
    return redirect(url_for("admin.dashboard", message=message))


@admin_bp.get("/api/appointments")
@admin_required
def api_appointments():
    rows = Appointment.query.order_by(Appointment.created_at.desc()).limit(100).all()
    return jsonify([
        {
            "id": row.id,
            "counselor": row.counselor.name,
            "slot_date": row.slot.slot_date.isoformat(),
            "slot_time": row.slot.label,
            "client_name": row.client_name,
            "client_department": row.client_department,
            "client_phone": row.client_phone,
            "status": row.status,
        }
        for row in rows
    ])


@admin_bp.post("/counselor-users")
@admin_required
def upsert_counselor_user():
    counselor_id = request.form.get("counselor_id", type=int)
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not counselor_id or not username or not password:
        return redirect(url_for("admin.dashboard", error="Сэтгэлзүйчийн эрх үүсгэхдээ бүх талбарыг бөглөнө үү."))

    counselor = Counselor.query.get_or_404(counselor_id)
    user = AdminUser.query.filter_by(role="counselor", counselor_id=counselor.id).first()
    username_owner = AdminUser.query.filter(AdminUser.username == username, AdminUser.id != (user.id if user else 0)).first()
    if username_owner:
        return redirect(url_for("admin.dashboard", error="Энэ нэвтрэх нэрийг өөр хэрэглэгч ашиглаж байна."))

    if not user:
        user = AdminUser(username=username, role="counselor", counselor_id=counselor.id, active=True)
        db.session.add(user)
        message = "Сэтгэлзүйчийн эрх үүслээ."
    else:
        user.username = username
        user.active = True
        message = "Сэтгэлзүйчийн эрх шинэчлэгдлээ."

    user.set_password(password)
    db.session.commit()
    return redirect(url_for("admin.dashboard", message=message))


@admin_bp.post("/counselor-users/<int:user_id>/status")
@admin_required
def update_counselor_user_status(user_id: int):
    user = AdminUser.query.get_or_404(user_id)
    if user.role != "counselor":
        return redirect(url_for("admin.dashboard", error="Буруу хэрэглэгч сонгогдлоо."))

    user.active = request.form.get("active") == "true"
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Сэтгэлзүйчийн эрхийн төлөв шинэчлэгдлээ."))


@admin_bp.post("/recommendation")
@admin_required
def update_recommendation():
    _set_setting("recommendation_enabled", "true" if request.form.get("enabled") == "on" else "false")
    _set_setting("recommendation_title", request.form.get("title", "Зөвлөмж").strip() or "Зөвлөмж")
    _set_setting("recommendation_body", request.form.get("body", "").strip())
    db.session.commit()
    return redirect(url_for("admin.dashboard", message="Зөвлөмжийн хэсэг шинэчлэгдлээ."))
