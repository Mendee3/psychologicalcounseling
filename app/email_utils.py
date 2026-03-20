from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from .models import Appointment


def _smtp_enabled() -> bool:
    return all(
        os.getenv(key)
        for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD")
    )


def _deliver(msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587")), timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"))
        server.send_message(msg)


def send_appointment_request_email(appointment: Appointment) -> None:
    counselor = appointment.counselor
    if not counselor.email or not _smtp_enabled():
        return

    base_url = os.getenv("PC_BASE_URL", "http://psychologicalcounseling").rstrip("/")
    review_url = f"{base_url}/appointment-response/{appointment.decision_token}"

    msg = EmailMessage()
    msg["Subject"] = "Psychological counseling appointment request"
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER")
    msg["To"] = counselor.email
    msg.set_content(
        f"""Сайн байна уу, {counselor.name}.

Шинэ уулзалтын хүсэлт ирлээ.

Ажилтан: {appointment.client_name}
Алба хэлтэс: {appointment.client_department or '-'}
Утас: {appointment.client_phone}
И-мэйл: {appointment.client_email or '-'}
Огноо: {appointment.slot.slot_date.isoformat()}
Цаг: {appointment.slot.label}
Сэдэв: {appointment.topic or '-'}
Тэмдэглэл: {appointment.notes or '-'}

Хүсэлтийг зөвшөөрөх эсвэл татгалзахын тулд энэ холбоосоор орно уу:
{review_url}

Холбоос дотор ажилтны мэдрэмтгий мэдээлэл агуулаагүй болно.
"""
    )
    _deliver(msg)


def send_appointment_decision_email(appointment: Appointment) -> None:
    if not appointment.client_email or not _smtp_enabled():
        return

    status_map = {
        "confirmed": ("зөвшөөрөгдлөө", "Таны уулзалтын хүсэлтийг сэтгэлзүйч зөвшөөрлөө."),
        "declined": ("татгалзагдлаа", "Таны уулзалтын хүсэлтийг сэтгэлзүйч татгалзлаа."),
        "cancelled": ("цуцлагдлаа", "Таны уулзалтын хүсэлт цуцлагдлаа."),
        "completed": ("дууслаа", "Таны уулзалт дууссан төлөвт шилжлээ."),
    }
    title, summary = status_map.get(appointment.status, (appointment.status, "Таны уулзалтын хүсэлтийн төлөв шинэчлэгдлээ."))

    msg = EmailMessage()
    msg["Subject"] = f"Сэтгэлзүйн уулзалтын хүсэлт {title}"
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER")
    msg["To"] = appointment.client_email
    msg.set_content(
        f"""Сайн байна уу, {appointment.client_name}.

{summary}

Сэтгэлзүйч: {appointment.counselor.name}
Алба хэлтэс: {appointment.client_department or '-'}
Огноо: {appointment.slot.slot_date.isoformat()}
Цаг: {appointment.slot.label}
Сэдэв: {appointment.topic or '-'}
Одоогийн төлөв: {appointment.status}

Шаардлагатай бол админтай эсвэл сэтгэлзүйчтэйгээ дахин холбогдоно уу.
"""
    )
    _deliver(msg)


def send_feedback_request_email(appointment: Appointment) -> None:
    if not appointment.client_email or not _smtp_enabled():
        return

    feedback_url = os.getenv("PC_FEEDBACK_URL", "").strip()
    feedback_line = (
        f"Санал хүсэлт үлдээх холбоос: {feedback_url}"
        if feedback_url
        else "Санал хүсэлтээ энэ и-мэйлд хариу бичиж үлдээж болно."
    )

    msg = EmailMessage()
    msg["Subject"] = "Сэтгэлзүйн уулзалтын санал хүсэлт"
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER")
    msg["To"] = appointment.client_email
    msg.set_content(
        f"""Сайн байна уу, {appointment.client_name}.

Таны {appointment.slot.slot_date.isoformat()}-ны {appointment.slot.label} цагийн уулзалт дууссан байна.

Сэтгэлзүйч: {appointment.counselor.name}
Алба хэлтэс: {appointment.client_department or '-'}
Сэдэв: {appointment.topic or '-'}

Үйлчилгээний чанарыг сайжруулахын тулд богино санал хүсэлт үлдээнэ үү.
{feedback_line}

Хэрэв дараагийн шатанд тусгай асуулгын маягт ашиглах бол энэ и-мэйл доторх холбоосыг шинэчилж ашиглаж болно.
"""
    )
    _deliver(msg)
