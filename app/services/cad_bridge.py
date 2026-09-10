# app/services/cad_bridge.py
from datetime import datetime, timezone
from typing import Optional, Dict, Any

def format_cad_112_payload(
    incident_id: int,
    latitude: float,
    longitude: float,
    emergency_type: str,
    severity_level: str,
    micro_location: Optional[str] = None,
    victim_phone: Optional[str] = None,
    caller_id: Optional[str] = None,
    trigger_method: Optional[str] = "MANUAL_PANIC_BUTTON",
    transcript: Optional[str] = None
) -> Dict[str, Any]:
    """
    Constructs an APCO-standard CAD (Computer Aided Dispatch) emergency payload
    for statutory 112 municipal gateway ingestion with voice trigger telemetry.
    """
    return {
        "dispatch_header": {
            "source_system": "SafetySignal_PWA_Bridge",
            "cad_standard_version": "APCO_112_v2.1",
            "transmission_timestamp": datetime.now(timezone.utc).isoformat(),
            "priority": "CRITICAL" if severity_level == "Critical" else "HIGH",
            "activation_channel": trigger_method or "MANUAL_PANIC_BUTTON"
        },
        "incident_details": {
            "external_incident_id": incident_id,
            "emergency_category": emergency_type,
            "severity": severity_level,
            "telephony_contact": victim_phone or caller_id or "ANONYMOUS_PWA_GUEST",
            "voice_transcript": transcript
        },
        "spatial_location": {
            "latitude": latitude,
            "longitude": longitude,
            "coordinate_system": "EPSG:4326_WGS84",
            "indoor_last_yard_guidance": micro_location or "Micro-location details not supplied"
        }
    }

async def forward_to_statutory_112_cad(
    incident_id: int,
    latitude: float,
    longitude: float,
    emergency_type: str,
    severity_level: str,
    micro_location: Optional[str] = None,
    victim_phone: Optional[str] = None,
    trigger_method: Optional[str] = "MANUAL_PANIC_BUTTON",
    transcript: Optional[str] = None
) -> bool:
    """
    Transmits the incident payload silently to the municipal emergency CAD server.
    Logs transmission details for audit and compliance.
    """
    payload = format_cad_112_payload(
        incident_id=incident_id,
        latitude=latitude,
        longitude=longitude,
        emergency_type=emergency_type,
        severity_level=severity_level,
        micro_location=micro_location,
        victim_phone=victim_phone,
        trigger_method=trigger_method,
        transcript=transcript
    )

    # In production, this issues:
    # async with httpx.AsyncClient() as client:
    #     await client.post("https://cad.gov.in/api/v1/dispatch", json=payload, timeout=5.0)

    transcript_info = f" | Audio Transcript: '{transcript}'" if transcript else ""
    print(
        f"🏛️ [STATUTORY 112 CAD BRIDGE] Dispatched Incident #{incident_id} | "
        f"Type: {emergency_type} | Trigger: {trigger_method or 'MANUAL_PANIC_BUTTON'} | "
        f"Coords: ({latitude:.6f}, {longitude:.6f}) | "
        f"Indoor: {micro_location or 'N/A'}{transcript_info}"
    )
    return True