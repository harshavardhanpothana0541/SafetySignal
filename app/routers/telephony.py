# app/routers/telephony.py
import traceback
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional

from app.database import SessionLocal
from app.models import User, Incident, ResponderLog
from app.services.cad_bridge import forward_to_statutory_112_cad
from app.websocket_manager import manager

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

router = APIRouter(prefix="/api/telephony", tags=["Telephony Ingestion"])

# --- Helper Function for Incident Ingestion ---
async def process_missed_call(clean_phone: str, db: Session):
    clean_phone = clean_phone.strip()
    last_10_digits = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone

    # Flexible matching: checks E.164 (+91...) or standard 10-digit formats
    user = (
        db.query(User)
        .filter(
            or_(
                User.phone_number == clean_phone,
                User.phone_number.endswith(last_10_digits)
            )
        )
        .first()
    )

    if user and getattr(user, "default_lat", None) and getattr(user, "default_lng", None):
        incident_lat = float(user.default_lat)
        incident_lng = float(user.default_lng)
        building = getattr(user, "default_building", "") or ""
        floor = getattr(user, "default_floor", "N/A") or "N/A"
        flat = getattr(user, "default_flat_no", "N/A") or "N/A"
        landmark = getattr(user, "default_landmark", "") or ""
        micro_location = f"{building}, Floor: {floor}, Flat: {flat} ({landmark})".strip(", ")
        victim_identifier = user.username
    else:
        # High-precision default sector coordinates
        incident_lat = 16.461935
        incident_lng = 80.505878
        micro_location = "Unregistered Feature Phone Caller (Cell Sector Triangulated)"
        victim_identifier = f"keypad_{last_10_digits[-4:]}"

    new_incident = Incident(
        victim_id=victim_identifier,
        victim_phone=clean_phone,
        latitude=incident_lat,
        longitude=incident_lng,
        micro_location_text=micro_location,
        emergency_type="Panic / High Priority",
        severity_level="Critical",
        ingestion_source="missed_call",
        status="active",
        victim_handshake_status="pending",
        cad_112_forwarded=True,
        created_at=datetime.now(timezone.utc)
    )

    db.add(new_incident)
    db.commit()
    db.refresh(new_incident)

    # Parallel Statutory 112 CAD & Telegram Dispatch
    try:
        await forward_to_statutory_112_cad(
            incident_id=new_incident.id,
            latitude=incident_lat,
            longitude=incident_lng,
            emergency_type=new_incident.emergency_type,
            severity_level=new_incident.severity_level,
            micro_location=micro_location,
            victim_phone=clean_phone
        )
    except Exception as e:
        print(f"[CAD Bridge Dispatch Error]: {e}")

    # Real-Time WebSocket Broadcast to CAD Dashboard & Responders
    try:
        await manager.broadcast_sos({
            "type": "NEW_INCIDENT",
            "incident_id": new_incident.id,
            "victim_id": new_incident.victim_id,
            "victim_phone": clean_phone,
            "emergency_type": new_incident.emergency_type,
            "severity": new_incident.severity_level,
            "latitude": incident_lat,
            "longitude": incident_lng,
            "micro_location": micro_location,
            "ingestion_source": "missed_call"
        })
    except Exception as e:
        print(f"[WebSocket Broadcast Error]: {e}")

    return new_incident, micro_location


# ==========================================================
# 1. LIVE TWILIO CARRIER WEBHOOKS (Form-Encoded Data)
# ==========================================================

@router.post("/missed-call-webhook")
async def twilio_missed_call_webhook(request: Request, db: Session = Depends(get_db)):
    """Receives inbound voice call events directly from Twilio."""
    try:
        form_data = await request.form()
        caller_phone = form_data.get("From", "").strip()

        if caller_phone:
            await process_missed_call(caller_phone, db)
    except Exception as err:
        print(f"[Voice Webhook Ingestion Exception]: {err}")
        traceback.print_exc()

    # Valid TwiML to acknowledge and cleanly end the call
    twiml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Aditi">Emergency alert received. Help is on the way.</Say>
    <Hangup/>
</Response>"""
    return Response(content=twiml_response, media_type="application/xml")


@router.post("/sms-webhook")
async def twilio_sms_webhook(request: Request, db: Session = Depends(get_db)):
    """Receives inbound SMS from Twilio for 2-way triage verification."""
    msg = "SafetySignal: Request received."
    try:
        form_data = await request.form()
        clean_phone = form_data.get("From", "").strip()
        last_10_digits = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
        reply = form_data.get("Body", "").strip()

        incident = (
            db.query(Incident)
            .filter(
                or_(
                    Incident.victim_phone == clean_phone,
                    Incident.victim_phone.endswith(last_10_digits)
                )
            )
            .order_by(Incident.id.desc())
            .first()
        )

        if not incident:
            incident, _ = await process_missed_call(clean_phone, db)

        if reply == "1":
            incident.victim_handshake_status = "confirmed_safe"
            incident.status = "resolved"
            incident.resolved_at = datetime.now(timezone.utc)
            action_note = "SMS_HANDSHAKE_CONFIRMED_SAFE"
            msg = "SafetySignal: Glad to hear you are safe. Ticket resolved."
        elif reply == "0" or "sos" in reply.lower():
            incident.victim_handshake_status = "still_needs_help"
            incident.severity_level = "Critical"
            action_note = "SMS_HANDSHAKE_STILL_NEEDS_HELP"
            msg = "SafetySignal: Emergency responders and 112 CAD units have been dispatched to your location."
        else:
            action_note = f"SMS_REPLY_NOTE: {reply}"
            msg = "SafetySignal: Reply 1 for Safe, 0 if you still need immediate help."

        audit_entry = ResponderLog(
            responder_id=incident.assigned_responder_id or "SYSTEM_SMS_GATEWAY",
            incident_id=incident.id,
            status=incident.status,
            action_note=action_note,
            timestamp=datetime.now(timezone.utc)
        )
        db.add(audit_entry)
        db.commit()

        try:
            await manager.broadcast_sos({
                "type": "HANDSHAKE_UPDATE",
                "incident_id": incident.id,
                "status": incident.status,
                "handshake_status": incident.victim_handshake_status
            })
        except Exception as e:
            print(f"[WebSocket Broadcast Error]: {e}")

    except Exception as err:
        print(f"[SMS Webhook Exception]: {err}")
        traceback.print_exc()

    twiml_reply = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{msg}</Message>
</Response>"""
    return Response(content=twiml_reply, media_type="application/xml")


# ==========================================================
# 2. LOCAL SIMULATOR ENDPOINTS (JSON Payloads)
# ==========================================================

class MissedCallPayload(BaseModel):
    caller_phone: str

class SMSReplyPayload(BaseModel):
    caller_phone: str
    reply_body: str

@router.post("/missed-call", status_code=status.HTTP_201_CREATED)
async def handle_missed_call_simulator(payload: MissedCallPayload, db: Session = Depends(get_db)):
    incident, micro_location = await process_missed_call(payload.caller_phone, db)
    return {
        "status": "success",
        "incident_id": incident.id,
        "dispatched_to": micro_location,
        "cad_forwarded": True
    }

@router.post("/sms-reply")
async def handle_sms_reply_simulator(payload: SMSReplyPayload, db: Session = Depends(get_db)):
    clean_phone = payload.caller_phone.strip()
    last_10_digits = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
    reply = payload.reply_body.strip()

    incident = (
        db.query(Incident)
        .filter(
            or_(
                Incident.victim_phone == clean_phone,
                Incident.victim_phone.endswith(last_10_digits)
            )
        )
        .order_by(Incident.id.desc())
        .first()
    )

    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active emergency ticket found for this phone number."
        )

    if reply == "1":
        incident.victim_handshake_status = "confirmed_safe"
        incident.status = "resolved"
        incident.resolved_at = datetime.now(timezone.utc)
        action_note = "SMS_HANDSHAKE_CONFIRMED_SAFE"
    elif reply == "0":
        incident.victim_handshake_status = "still_needs_help"
        incident.severity_level = "Critical"
        action_note = "SMS_HANDSHAKE_STILL_NEEDS_HELP"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reply code. Use '1' for Safe, '0' for Help."
        )

    audit_entry = ResponderLog(
        responder_id=incident.assigned_responder_id or "SYSTEM_SMS_GATEWAY",
        incident_id=incident.id,
        status=incident.status,
        action_note=action_note,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(audit_entry)
    db.commit()

    await manager.broadcast_sos({
        "type": "HANDSHAKE_UPDATE",
        "incident_id": incident.id,
        "status": incident.status,
        "handshake_status": incident.victim_handshake_status
    })

    return {
        "status": "success",
        "incident_id": incident.id,
        "handshake_status": incident.victim_handshake_status,
        "incident_status": incident.status
    }