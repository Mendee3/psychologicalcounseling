from __future__ import annotations

from datetime import datetime

from . import db
from .email_utils import send_appointment_decision_email, send_feedback_request_email
from .models import Appointment

APPOINTMENT_STATUSES = ("requested", "confirmed", "declined", "cancelled", "completed")


def update_appointment_status(appointment: Appointment, status: str) -> dict[str, bool]:
    normalized = (status or "requested").strip()
    if normalized not in APPOINTMENT_STATUSES:
        normalized = "requested"

    previous_status = appointment.status
    changed = previous_status != normalized

    appointment.status = normalized
    if normalized == "completed":
        appointment.completed_at = appointment.completed_at or datetime.utcnow()
    elif previous_status == "completed":
        appointment.completed_at = None

    if not changed:
        db.session.commit()
        return {"changed": False, "decision_email_sent": False, "feedback_email_sent": False}

    decision_email_sent = False
    feedback_email_sent = False
    if normalized in {"confirmed", "declined", "cancelled", "completed"}:
        try:
            send_appointment_decision_email(appointment)
            decision_email_sent = True
        except Exception:
            decision_email_sent = False

    if normalized == "completed" and appointment.client_email and not appointment.feedback_sent_at:
        try:
            send_feedback_request_email(appointment)
            appointment.feedback_sent_at = datetime.utcnow()
            feedback_email_sent = True
        except Exception:
            feedback_email_sent = False

    db.session.commit()
    return {
        "changed": True,
        "decision_email_sent": decision_email_sent,
        "feedback_email_sent": feedback_email_sent,
    }
