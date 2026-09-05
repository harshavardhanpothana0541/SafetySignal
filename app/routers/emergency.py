# app/routers/emergency.py
import os
import json
import asyncio
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.websocket_manager import manager
from app.database import SessionLocal
from app import models
from app.services.sms_service import sms_service
from app.services.ai_triage import ai_triage_service
from app.services.auth_service import auth_service
from app.services.geofence import verify_resolution_geofence
from app.services.cad_bridge import forward_to_statutory_112_cad
from app.services.outbound_notifier import trigger_ai_guardian_call, send_responder_dispatch_sms

load_dotenv()

raw_contacts = os.getenv("EMERGENCY_CONTACTS", "+919876543210")
DEFAULT_EMERGENCY_CONTACTS = [num.strip() for num in raw_contacts.split(",") if num.strip()]

router = APIRouter(prefix="/api/emergency", tags=["Emergency"])

class TriageRequest(BaseModel):
    description: Optional[str] = "Emergency Alert"
    emergency_type: Optional[str] = "Medical / Cardiac"
    latitude: Optional[float] = 16.461935
    longitude: Optional[float] = 80.505878
    micro_location: Optional[str] = "Live Web App Distress Pin"
    victim_phone: Optional[str] = "+919391774539"
    guardian_phone: Optional[str] = "+919391774539"

class ResolveRequest(BaseModel):
    incident_id: int
    responder_id: str
    responder_lat: Optional[float] = None
    responder_lon: Optional[float] = None
    action_note: Optional[str] = "RESOLVED_MANUAL_VERIFICATION"


@router.post("/ai-triage")
async def perform_ai_triage(req: TriageRequest):
    """
    REST SOS Ingestion: Analyzes emergency, creates database record, 
    bridges 112 CAD, broadcasts WebSocket update, and fires AI Guardian Voice Call.
    """
    triage_analysis = ai_triage_service.analyze_incident(req.description or req.emergency_type)
    
    db = SessionLocal()
    new_incident = models.Incident(
        victim_id="web_victim_user",
        victim_phone=req.victim_phone,
        latitude=req.latitude,
        longitude=req.longitude,
        micro_location_text=req.micro_location,
        emergency_type=req.emergency_type or triage_analysis.get("incident_type", "General Emergency"),
        severity_level=triage_analysis.get("severity", "Critical"),
        ingestion_source="pwa_sos_button",
        status="active",
        victim_handshake_status="pending",
        cad_112_forwarded=True,
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_incident)
    db.commit()
    db.refresh(new_incident)
    inc_id = new_incident.id
    db.close()

    # 1. Statutory 112 CAD / Telegram Bridge
    asyncio.create_task(forward_to_statutory_112_cad(
        incident_id=inc_id,
        latitude=req.latitude,
        longitude=req.longitude,
        emergency_type=new_incident.emergency_type,
        severity_level=new_incident.severity_level,
        micro_location=req.micro_location,
        victim_phone=req.victim_phone
    ))

    # 2. Outbound AI Guardian Call to Emergency Contact
    asyncio.create_task(trigger_ai_guardian_call(
        victim_identifier=req.victim_phone or "Family Member",
        emergency_type=new_incident.emergency_type,
        micro_location=req.micro_location,
        target_phone=req.guardian_phone or req.victim_phone or DEFAULT_EMERGENCY_CONTACTS[0]
    ))

    # 3. Broadcast to all Connected Responders via WebSocket
    if hasattr(manager, "broadcast_sos"):
        await manager.broadcast_sos(
            victim_id="web_victim_user",
            lat=req.latitude,
            lon=req.longitude,
            emergency_type=new_incident.emergency_type,
            incident_id=inc_id,
            created_at=datetime.now(timezone.utc).isoformat() + "Z",
            radius_km=25.0
        )
    elif hasattr(manager, "broadcast_all"):
        await manager.broadcast_all({
            "type": "NEW_INCIDENT",
            "incident_id": inc_id,
            "emergency_type": new_incident.emergency_type,
            "lat": req.latitude,
            "lon": req.longitude,
            "micro_location": req.micro_location
        })

    return {
        "status": "dispatched",
        "incident_id": inc_id,
        "ai_analysis": triage_analysis,
        "ai_guardian_call": "dispatched"
    }


@router.get("/active-incidents")
async def get_active_incidents():
    """Fetches active incidents within 2 hours or currently accepted cases."""
    db = SessionLocal()
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=2)

    incidents = db.query(models.Incident).filter(
        (models.Incident.status == "accepted") |
        (models.Incident.status == "en_route") |
        ((models.Incident.status == "active") & (models.Incident.created_at >= cutoff_time))
    ).order_by(models.Incident.id.desc()).all()
    
    results = [
        {
            "incident_id": inc.id,
            "id": inc.id,
            "victim_id": inc.victim_id,
            "victim_phone": inc.victim_phone,
            "lat": inc.latitude,
            "lon": inc.longitude,
            "micro_location": inc.micro_location_text,
            "emergency_type": inc.emergency_type,
            "severity_level": inc.severity_level,
            "status": inc.status,
            "assigned_responder_id": inc.assigned_responder_id,
            "created_at": (inc.created_at.isoformat() + "Z") if inc.created_at else None
        }
        for inc in incidents
    ]
    db.close()
    return results


@router.post("/accept-dispatch/{incident_id}")
async def accept_dispatch_rest(incident_id: int, responder_phone: Optional[str] = "+919391774539"):
    """REST endpoint for dispatch claim with instant SMS routing dispatch."""
    db = SessionLocal()
    try:
        incident = db.query(models.Incident).filter(
            models.Incident.id == incident_id,
            models.Incident.status == "active"
        ).first()

        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found or already claimed")

        incident.status = "accepted"
        incident.assigned_responder_id = "responder_unit_alpha"
        incident.accepted_at = datetime.now(timezone.utc)

        db.add(models.ResponderLog(
            responder_id="responder_unit_alpha",
            incident_id=incident.id,
            status="accepted",
            timestamp=datetime.now(timezone.utc)
        ))
        db.commit()

        # Send outbound SMS route summary to responder
        asyncio.create_task(send_responder_dispatch_sms(
            responder_phone=responder_phone,
            incident_id=incident.id,
            lat=incident.latitude,
            lng=incident.longitude,
            micro_location=incident.micro_location_text or "Tactical GPS Location",
            emergency_type=incident.emergency_type
        ))

        if hasattr(manager, "broadcast_all"):
            await manager.broadcast_all({
                "type": "INCIDENT_CLAIMED",
                "incident_id": incident.id,
                "assigned_responder_id": "responder_unit_alpha",
                "status": "accepted"
            })

        return {"status": "accepted", "incident_id": incident.id, "dispatch_sms": "dispatched"}
    finally:
        db.close()


@router.get("/analytics")
async def get_analytics_data():
    """Returns aggregated analytics data for the CAD dashboard."""
    db = SessionLocal()
    try:
        incidents = db.query(models.Incident).order_by(models.Incident.id.desc()).all()
        users = db.query(models.User).filter(models.User.role == "responder").all()
        
        cutoff_2hr = datetime.now(timezone.utc) - timedelta(hours=2)

        total = len(incidents)
        active_in_progress = 0
        resolved = 0
        unaccepted_escalated = 0

        active_list = []
        unaccepted_list = []
        resolved_list = []

        for inc in incidents:
            created_dt = inc.created_at
            if created_dt and created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)

            accepted_dt = inc.accepted_at
            if accepted_dt and accepted_dt.tzinfo is None:
                accepted_dt = accepted_dt.replace(tzinfo=timezone.utc)
            
            is_stale_unaccepted = (inc.status == "active") and (created_dt < cutoff_2hr if created_dt else False)
            is_stalled_accepted = (inc.status in ["accepted", "en_route"]) and (accepted_dt < cutoff_2hr if accepted_dt else False)

            status_display = inc.status
            if is_stale_unaccepted:
                status_display = "UNACCEPTED (ESCALATED)"
            elif is_stalled_accepted:
                status_display = "STALLED DISPATCH (ESCALATED)"

            item = {
                "id": inc.id,
                "victim_id": inc.victim_id,
                "assigned_responder_id": inc.assigned_responder_id or "None",
                "latitude": inc.latitude,
                "longitude": inc.longitude,
                "micro_location": inc.micro_location_text,
                "emergency_type": inc.emergency_type,
                "status": status_display,
                "created_at": (created_dt.isoformat()) if created_dt else None
            }

            if inc.status == "resolved":
                resolved += 1
                resolved_list.append(item)
            elif is_stale_unaccepted or is_stalled_accepted:
                unaccepted_escalated += 1
                unaccepted_list.append(item)
            else:
                active_in_progress += 1
                active_list.append(item)

        responders_status = [
            {
                "username": u.username,
                "badge_number": u.badge_number,
                "karma_score": getattr(u, "karma_score", 100),
                "strikes": u.strikes,
                "is_suspended": u.is_suspended
            }
            for u in users
        ]

        return {
            "total": total,
            "active": active_in_progress,
            "resolved": resolved,
            "unaccepted": unaccepted_escalated,
            "active_incidents": active_list,
            "unaccepted_incidents": unaccepted_list,
            "all_incidents": active_list + unaccepted_list + resolved_list,
            "responders": responders_status
        }
    finally:
        db.close()


@router.post("/resolve")
async def resolve_incident_rest(payload: ResolveRequest):
    """
    REST Endpoint: Enforces Geofence verification if coordinates provided,
    awards karma, and writes an immutable audit log.
    """
    db = SessionLocal()
    try:
        incident = db.query(models.Incident).filter(models.Incident.id == payload.incident_id).first()
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")

        distance_m = 0.0
        if payload.responder_lat is not None and payload.responder_lon is not None:
            within_fence, distance_m = verify_resolution_geofence(
                responder_lat=payload.responder_lat,
                responder_lon=payload.responder_lon,
                incident_lat=incident.latitude,
                incident_lon=incident.longitude,
                threshold_meters=50.0
            )
            if not within_fence:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Geofence Lock Active: You are {distance_m:.1f}m away. You must be within 50.0m to mark resolved."
                )

        incident.status = "resolved"
        incident.is_geofence_verified = True
        incident.resolved_at = datetime.now(timezone.utc)

        responder = db.query(models.User).filter(models.User.username == payload.responder_id).first()
        if responder:
            responder.karma_score = getattr(responder, "karma_score", 100) + 15

        db.add(models.ResponderLog(
            responder_id=payload.responder_id,
            incident_id=incident.id,
            status="resolved",
            action_note=payload.action_note or "GEOFENCE_VERIFIED_RESOLUTION",
            recorded_lat=payload.responder_lat or incident.latitude,
            recorded_lng=payload.responder_lon or incident.longitude,
            timestamp=datetime.now(timezone.utc)
        ))
        db.commit()

        if hasattr(manager, "broadcast_all"):
            await manager.broadcast_all({
                "type": "INCIDENT_RESOLVED_ALL",
                "incident_id": incident.id,
                "distance_meters": distance_m
            })

        return {"status": "success", "incident_id": incident.id, "distance_meters": distance_m, "karma_awarded": 15}
    finally:
        db.close()


# --- Background Watchdog: 2-Min SLA Unacknowledged & 5-Min Deadman Inactivity ---
async def monitor_abandoned_incidents():
    while True:
        await asyncio.sleep(30)
        db = SessionLocal()
        try:
            now_utc = datetime.now(timezone.utc)
            two_mins_ago = now_utc - timedelta(minutes=2)
            five_mins_ago = now_utc - timedelta(minutes=5)

            # 1. 2-Minute Unacknowledged SLA Escalation
            unclaimed = db.query(models.Incident).filter(
                models.Incident.status == "active",
                models.Incident.created_at <= two_mins_ago
            ).all()

            for inc in unclaimed:
                if "SLA BREACH" not in (inc.micro_location_text or ""):
                    inc.severity_level = "P0-SLA-BREACHED"
                    inc.micro_location_text = (inc.micro_location_text or "") + " [⚠️ SLA BREACH: UNCLAIMED > 2 MINS]"
                    db.add(models.ResponderLog(
                        responder_id="SLA_MONITOR_DAEMON",
                        incident_id=inc.id,
                        status="escalated",
                        action_note="SLA_VIOLATION_AUTO_ESCALATION_TIER2",
                        timestamp=now_utc
                    ))
                    db.commit()
                    if hasattr(manager, "broadcast_all"):
                        await manager.broadcast_all({
                            "type": "SLA_BREACH_ESCALATION",
                            "incident_id": inc.id,
                            "severity": "P0-SLA-BREACHED"
                        })
                    print(f"⚠️ [SLA ALERT]: Incident #{inc.id} escalated due to inactivity.")

            # 2. 5-Minute Deadman Timeout for Accepted cases
            stalled_cases = db.query(models.Incident).filter(
                models.Incident.status.in_(["accepted", "en_route"]),
                models.Incident.accepted_at <= five_mins_ago
            ).all()

            for inc in stalled_cases:
                responder_id = inc.assigned_responder_id
                user = db.query(models.User).filter(models.User.username == responder_id).first()
                if user:
                    user.strikes += 1
                    if user.strikes >= 2:
                        user.is_suspended = True

                inc.status = "active"
                inc.assigned_responder_id = None
                inc.accepted_at = None

                db.add(models.ResponderLog(
                    responder_id=responder_id or "unknown",
                    incident_id=inc.id,
                    status="timeout_released",
                    timestamp=now_utc
                ))
                db.commit()

                if hasattr(manager, "send_to_victim"):
                    await manager.send_to_victim(inc.victim_id, {
                        "type": "RESPONDER_TIMEOUT_REASSIGNING",
                        "incident_id": inc.id,
                        "message": "Assigned responder inactive. Re-broadcasting to nearest available unit."
                    })

                if hasattr(manager, "broadcast_sos"):
                    await manager.broadcast_sos(
                        victim_id=inc.victim_id,
                        lat=inc.latitude,
                        lon=inc.longitude,
                        emergency_type=inc.emergency_type,
                        incident_id=inc.id,
                        created_at=(inc.created_at.isoformat() + "Z") if inc.created_at else None,
                        radius_km=25.0
                    )
        except Exception as e:
            print(f"[Watchdog Loop Exception]: {e}")
        finally:
            db.close()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    payload = auth_service.decode_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Unauthorized: Invalid Token")
        return

    user_id = payload.get("sub")
    role = payload.get("role")

    await manager.connect(user_id, websocket, role)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            action = data.get("action")

            if action == "UPDATE_LOCATION":
                lat = data["lat"]
                lon = data["lon"]
                incident_id = data.get("incident_id")

                manager.update_location(user_id, lat, lon)

                if incident_id:
                    db = SessionLocal()
                    incident = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
                    if incident and incident.status in ["active", "accepted", "en_route"]:
                        incident.last_responder_lat = lat
                        incident.last_responder_lon = lon
                        db.commit()
                    db.close()

                await manager.broadcast_location_update(user_id, lat, lon, incident_id)

            elif action == "TRIGGER_SOS":
                lat = data["lat"]
                lon = data["lon"]
                emergency_type = data.get("emergency_type", "Medical / Cardiac")
                raw_text = data.get("raw_text", "")
                victim_phone = data.get("victim_phone")

                db = SessionLocal()
                user = db.query(models.User).filter(models.User.username == user_id).first() if user_id else None
                
                micro_location = ""
                if user and user.default_flat_no:
                    micro_location = f"{user.default_building or ''}, Floor {user.default_floor or 'N/A'}, Flat {user.default_flat_no}"
                elif raw_text:
                    micro_location = raw_text

                manager.update_location(user_id, lat, lon)

                new_incident = models.Incident(
                    victim_id=user_id,
                    victim_phone=victim_phone or (user.phone_number if user else None),
                    latitude=lat,
                    longitude=lon,
                    micro_location_text=micro_location or "GPS Coordinate Pin",
                    emergency_type=emergency_type,
                    severity_level="Critical" if "heart" in raw_text.lower() or "fire" in emergency_type.lower() else "High",
                    status="active",
                    cad_112_forwarded=True,
                    created_at=datetime.now(timezone.utc)
                )
                db.add(new_incident)
                db.commit()
                db.refresh(new_incident)
                incident_id = new_incident.id
                incident_time = (new_incident.created_at.isoformat() + "Z") if new_incident.created_at else None
                db.close()

                # Parallel Statutory CAD 112 Forwarding
                asyncio.create_task(forward_to_statutory_112_cad(
                    incident_id=incident_id,
                    latitude=lat,
                    longitude=lon,
                    emergency_type=emergency_type,
                    severity_level=new_incident.severity_level,
                    micro_location=micro_location,
                    victim_phone=victim_phone
                ))

                # Parallel AI Guardian Voice Call
                asyncio.create_task(trigger_ai_guardian_call(
                    victim_identifier=user_id or "Registered Citizen",
                    emergency_type=emergency_type,
                    micro_location=micro_location,
                    target_phone=victim_phone or DEFAULT_EMERGENCY_CONTACTS[0]
                ))

                # Outbound SMS Gateway Broadcast
                sms_service.send_emergency_sms(
                    phone_numbers=DEFAULT_EMERGENCY_CONTACTS,
                    incident_type=emergency_type,
                    lat=lat,
                    lon=lon,
                    incident_id=incident_id
                )

                await manager.broadcast_sos(
                    victim_id=user_id,
                    lat=lat,
                    lon=lon,
                    emergency_type=emergency_type,
                    incident_id=incident_id,
                    created_at=incident_time,
                    radius_km=25.0
                )

            elif action == "ACCEPT_INCIDENT":
                if role != "responder":
                    continue

                db = SessionLocal()
                user_record = db.query(models.User).filter(models.User.username == user_id).first()
                if user_record and user_record.is_suspended:
                    db.close()
                    if user_id in manager.active_connections:
                        await manager.active_connections[user_id]["ws"].send_text(json.dumps({
                            "type": "ACCOUNT_SUSPENDED",
                            "message": "Account suspended due to repeated unfulfilled dispatches. Contact Admin."
                        }))
                    continue

                incident_id = data.get("incident_id")
                victim_id = data.get("victim_id")

                incident = db.query(models.Incident).filter(
                    models.Incident.id == incident_id,
                    models.Incident.status == "active"
                ).first()

                if incident:
                    incident.status = "accepted"
                    incident.assigned_responder_id = user_id
                    incident.accepted_at = datetime.now(timezone.utc)
                    
                    log = models.ResponderLog(responder_id=user_id, incident_id=incident_id, status="accepted")
                    db.add(log)
                    db.commit()

                    inc_lat = incident.latitude
                    inc_lon = incident.longitude
                    emergency_type = incident.emergency_type
                    micro_loc = incident.micro_location_text
                    responder_phone = user_record.phone_number if user_record else None
                    db.close()

                    # Send Outbound SMS route summary
                    asyncio.create_task(send_responder_dispatch_sms(
                        responder_phone=responder_phone or DEFAULT_EMERGENCY_CONTACTS[0],
                        incident_id=incident_id,
                        lat=inc_lat,
                        lng=inc_lon,
                        micro_location=micro_loc or "GPS Pin",
                        emergency_type=emergency_type
                    ))

                    await manager.send_to_victim(victim_id, {
                        "type": "HELP_ON_THE_WAY",
                        "responder_id": user_id
                    })

                    await manager.broadcast_all({
                        "type": "INCIDENT_CLAIMED",
                        "incident_id": incident_id,
                        "assigned_responder_id": user_id,
                        "emergency_type": emergency_type,
                        "lat": inc_lat,
                        "lon": inc_lon
                    })
                else:
                    db.close()
                    if user_id in manager.active_connections:
                        await manager.active_connections[user_id]["ws"].send_text(json.dumps({
                            "type": "INCIDENT_ALREADY_TAKEN",
                            "incident_id": incident_id
                        }))

            elif action == "RELEASE_INCIDENT":
                if role != "responder":
                    continue

                incident_id = data.get("incident_id")
                victim_id = data.get("victim_id")

                db = SessionLocal()
                incident = db.query(models.Incident).filter(
                    models.Incident.id == incident_id,
                    models.Incident.status.in_(["accepted", "en_route"]),
                    models.Incident.assigned_responder_id == user_id
                ).first()

                if incident:
                    incident.status = "active"
                    incident.assigned_responder_id = None
                    incident.accepted_at = None

                    log = models.ResponderLog(responder_id=user_id, incident_id=incident_id, status="aborted")
                    db.add(log)
                    db.commit()

                    inc_data = {
                        "incident_id": incident.id,
                        "victim_id": incident.victim_id,
                        "lat": incident.latitude,
                        "lon": incident.longitude,
                        "emergency_type": incident.emergency_type,
                        "created_at": (incident.created_at.isoformat() + "Z") if incident.created_at else None
                    }
                    db.close()

                    await manager.send_to_victim(victim_id, {
                        "type": "RESPONDER_ABORTED",
                        "message": "Assigned unit faced an obstacle. Re-routing dispatch immediately..."
                    })

                    await manager.broadcast_sos(
                        victim_id=inc_data["victim_id"],
                        lat=inc_data["lat"],
                        lon=inc_data["lon"],
                        emergency_type=inc_data["emergency_type"],
                        incident_id=inc_data["incident_id"],
                        created_at=inc_data["created_at"],
                        radius_km=25.0
                    )
                else:
                    db.close()

            elif action == "RESOLVE_INCIDENT":
                if role not in ["responder", "admin"]:
                    continue

                incident_id = data.get("incident_id")
                victim_id = data.get("victim_id")
                resp_lat = data.get("lat")
                resp_lon = data.get("lon")

                db = SessionLocal()
                incident = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
                
                if incident:
                    if resp_lat is not None and resp_lon is not None:
                        within_fence, dist_m = verify_resolution_geofence(resp_lat, resp_lon, incident.latitude, incident.longitude, 50.0)
                        if not within_fence:
                            db.close()
                            if user_id in manager.active_connections:
                                await manager.active_connections[user_id]["ws"].send_text(json.dumps({
                                    "type": "GEOFENCE_LOCK_ACTIVE",
                                    "message": f"Must be within 50m of door to resolve. Current distance: {dist_m:.1f}m"
                                }))
                            continue

                    incident.status = "resolved"
                    incident.is_geofence_verified = True
                    incident.resolved_at = datetime.now(timezone.utc)

                    user_record = db.query(models.User).filter(models.User.username == user_id).first()
                    if user_record:
                        user_record.karma_score = getattr(user_record, "karma_score", 100) + 15

                    log = models.ResponderLog(
                        responder_id=user_id,
                        incident_id=incident_id,
                        status="resolved",
                        action_note="GEOFENCE_VERIFIED_RESOLUTION",
                        recorded_lat=resp_lat,
                        recorded_lng=resp_lon,
                        timestamp=datetime.now(timezone.utc)
                    )
                    db.add(log)
                    db.commit()
                    db.close()

                    await manager.send_to_victim(victim_id, {
                        "type": "INCIDENT_RESOLVED",
                        "incident_id": incident_id
                    })
                    await manager.broadcast_all({
                        "type": "INCIDENT_RESOLVED_ALL",
                        "incident_id": incident_id
                    })

    except WebSocketDisconnect:
        manager.disconnect(user_id)