# app/models.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    phone_number = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, default="Anonymous Citizen")
    role = Column(String, default="responder")  # "victim", "pending_responder", "responder", "admin"
    badge_number = Column(String, unique=True, nullable=True)  # e.g., "MED-8841"
    is_verified = Column(Boolean, default=True)

    # Pre-Saved "Home Base" Micro-Location Details
    default_building = Column(String, nullable=True)
    default_floor = Column(String, nullable=True)
    default_flat_no = Column(String, nullable=True)
    default_landmark = Column(String, nullable=True)
    default_lat = Column(Float, nullable=True)
    default_lng = Column(Float, nullable=True)

    # Emergency Medical Profile & ICE Contact
    blood_group = Column(String, nullable=True)
    ice_contact_name = Column(String, nullable=True)
    ice_contact_phone = Column(String, nullable=True)

    # Trust & Reputation Metrics
    karma_score = Column(Integer, default=100)
    reliability_rating = Column(Float, default=5.0)
    strikes = Column(Integer, default=0)  # Tracks abandonment / timeout release counts
    is_suspended = Column(Boolean, default=False)  # Blacklisting metric for repeated abandonment
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    victim_id = Column(String, index=True, nullable=False)
    victim_phone = Column(String, nullable=True)
    assigned_responder_id = Column(String, nullable=True)
    
    # Incident GPS & Micro-Location
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    micro_location_text = Column(Text, nullable=True)  # e.g., "Tower B, 4th Floor, Flat 402"
    
    emergency_type = Column(String, default="Medical Emergency")  # Medical, Fire, Crime, Hazard, Panic
    severity_level = Column(String, default="High")  # Critical, High, Moderate
    ingestion_source = Column(String, default="pwa_online")  # pwa_online, offline_sms, missed_call, guest_sos
    status = Column(String, default="active")  # active, accepted, arrived, resolved, escalated, false_alarm
    
    # Voice Activation & Triage Evidence Telemetry
    trigger_method = Column(String, default="MANUAL_PANIC_BUTTON")  # MANUAL_PANIC_BUTTON, VOICE_TRIGGERED
    transcript = Column(Text, nullable=True)                         # Recognized voice trigger text
    media_url = Column(String, nullable=True)                          # Link to 5s situational triage buffer
    
    # Handshake & Verification Locks
    is_geofence_verified = Column(Boolean, default=False)
    victim_handshake_status = Column(String, default="pending")  # pending, confirmed_safe, still_needs_help
    cad_112_forwarded = Column(Boolean, default=False)
    
    # Tracking & Timestamps
    accepted_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    last_responder_lat = Column(Float, nullable=True)
    last_responder_lon = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ResponderLog(Base):
    __tablename__ = "responder_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    responder_id = Column(String, index=True, nullable=False)
    incident_id = Column(Integer, index=True, nullable=False)
    status = Column(String, default="accepted")  # accepted, aborted, timeout_released, resolved, geofence_verified
    action_note = Column(String, nullable=True)  # e.g., "GEOFENCE_LOCKED", "BEACON_TRIGGERED"
    recorded_lat = Column(Float, nullable=True)
    recorded_lng = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))