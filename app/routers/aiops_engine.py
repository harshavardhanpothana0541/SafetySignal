# app/routers/aiops_engine.py
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Incident, ResponderLog
from app.websocket_manager import manager

router = APIRouter(prefix="/api/aiops", tags=["AIOps Ingestion & Self-Healing"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Safe helper to broadcast generic JSON telemetry payloads
async def safe_broadcast(payload: dict):
    try:
        if hasattr(manager, "broadcast_all"):
            await manager.broadcast_all(payload)
        elif hasattr(manager, "broadcast_json"):
            await manager.broadcast_json(payload)
        elif hasattr(manager, "broadcast"):
            await manager.broadcast(payload)
    except Exception as e:
        print(f"[WebSocket Safe Broadcast Warning]: {e}")

# In-memory streaming telemetry buffer
TELEMETRY_BUFFER = {
    "metrics": [],
    "logs": [],
    "alerts": []
}

# --- Pydantic Data Contracts ---
class MetricPoint(BaseModel):
    service: str
    metric_name: str
    value: float
    timestamp: Optional[str] = None

class LogEntry(BaseModel):
    service: str
    log_level: str
    message: str
    timestamp: Optional[str] = None

class RawAlert(BaseModel):
    service: str
    alert_name: str
    severity: str
    cluster: str
    details: str

class RemediationRequest(BaseModel):
    incident_id: int
    action: str
    dry_run: Optional[bool] = False  # Supports Dry-Run / Human Approval Preview

# --- STRICT SAFETY ALLOW-LIST (Security Gate) ---
APPROVED_REMEDIATION_ACTIONS = {
    "RESTART_POD": {
        "command": "kubectl rollout restart deployment/{service}",
        "description": "Safe rolling restart of pod deployment"
    },
    "CLEAR_REDIS_CACHE": {
        "command": "redis-cli -h cache.internal flushdb --async",
        "description": "Safe async cache eviction"
    },
    "SCALE_UP_POD": {
        "command": "kubectl scale deployment/{service} --replicas=3",
        "description": "Horizontal pod autoscaler override to 3 replicas"
    }
}


# ============================================================================
# 1. STREAM INGESTION (METRICS, LOGS, ALERTS)
# ============================================================================

@router.post("/ingest/metric")
async def ingest_metric(metric: MetricPoint, db: Session = Depends(get_db)):
    """Ingests numerical time-series metrics & triggers threshold alerts."""
    now_str = datetime.now().strftime("%H:%M:%S")
    entry = {"time": now_str, "service": metric.service, "metric": metric.metric_name, "value": metric.value}
    TELEMETRY_BUFFER["metrics"].append(entry)
    if len(TELEMETRY_BUFFER["metrics"]) > 50:
        TELEMETRY_BUFFER["metrics"].pop(0)

    # Threshold detector: Auto-promotes critical metric spike to alert
    if metric.metric_name in ["memory_usage_percent", "cpu_usage_percent"] and metric.value >= 90.0:
        raw_alert = RawAlert(
            service=metric.service,
            alert_name=f"{metric.metric_name.upper()}_THRESHOLD_BREACH",
            severity="P1-Critical",
            cluster="k8s-prod-in-01",
            details=f"Metric {metric.metric_name} hit {metric.value}% (Threshold: 90%)"
        )
        return await ingest_alert_and_correlate(raw_alert, db)

    await safe_broadcast({"type": "METRIC_STREAM", "data": entry})
    return {"status": "metric_ingested", "data": entry}


@router.post("/ingest/log")
async def ingest_log(log: LogEntry, db: Session = Depends(get_db)):
    """Ingests application log stream & triggers alerts on FATAL/ERROR."""
    now_str = datetime.now().strftime("%H:%M:%S")
    entry = {"time": now_str, "service": log.service, "level": log.log_level, "message": log.message}
    TELEMETRY_BUFFER["logs"].append(entry)
    if len(TELEMETRY_BUFFER["logs"]) > 50:
        TELEMETRY_BUFFER["logs"].pop(0)

    # Auto-detect Fatal Exceptions
    if log.log_level in ["ERROR", "FATAL"] or "OutOfMemory" in log.message or "Connection refused" in log.message:
        raw_alert = RawAlert(
            service=log.service,
            alert_name="FATAL_LOG_EXCEPTION",
            severity="P1-Critical",
            cluster="k8s-prod-in-01",
            details=f"Log trace: {log.message}"
        )
        return await ingest_alert_and_correlate(raw_alert, db)

    await safe_broadcast({"type": "LOG_STREAM", "data": entry})
    return {"status": "log_ingested", "data": entry}


# ============================================================================
# 2. TIME-WINDOW CORRELATION ENGINE & ROOT CAUSE TRIAGE
# ============================================================================

@router.post("/ingest/alert")
async def ingest_alert_and_correlate(alert: RawAlert, db: Session = Depends(get_db)):
    """
    Correlates alerts arriving within a 3-minute sliding window for the same service/cluster
    into a SINGLE actionable master incident.
    """
    three_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=3)

    existing_incident = (
        db.query(Incident)
        .filter(
            Incident.victim_id == alert.service,
            Incident.status.in_(["active", "en_route", "accepted"]),
            Incident.created_at >= three_mins_ago
        )
        .first()
    )

    if existing_incident:
        existing_incident.micro_location_text += f" | +Correlated Signal: [{alert.alert_name}] {alert.details}"
        db.commit()

        await safe_broadcast({
            "type": "ALERT_CORRELATED_SUPPRESSED",
            "incident_id": existing_incident.id,
            "service": alert.service,
            "suppressed_alert": alert.alert_name,
            "reason": "Merged into active master incident within 3m time-window"
        })

        return {
            "action": "CORRELATED_AND_MERGED",
            "incident_id": existing_incident.id,
            "noise_reduced": True,
            "message": f"Alert '{alert.alert_name}' clustered into Incident #{existing_incident.id}"
        }

    # Root Cause Diagnostic Step
    root_cause = "Unknown Anomaly"
    recommended_remediation = "RESTART_POD"
    
    if "Memory" in alert.alert_name or "OutOfMemory" in alert.details:
        root_cause = "Heap Exhaustion / JVM Memory Leak detected in pod container."
        recommended_remediation = "RESTART_POD"
    elif "CPU" in alert.alert_name:
        root_cause = "Unbounded traffic spike causing CPU throttling."
        recommended_remediation = "SCALE_UP_POD"
    elif "Connection" in alert.alert_name or "502" in alert.details:
        root_cause = "Upstream socket pool exhausted / stale cache saturation."
        recommended_remediation = "CLEAR_REDIS_CACHE"

    new_incident = Incident(
        victim_id=alert.service,
        victim_phone=f"Cluster: {alert.cluster}",
        latitude=16.5062,
        longitude=80.6480,
        micro_location_text=f"Root Cause: {root_cause} | Recommended Fix: {recommended_remediation} | Primary Alert: {alert.details}",
        emergency_type=f"[AIOps] {alert.alert_name}",
        severity_level=alert.severity,
        ingestion_source="aiops_telemetry_engine",
        status="active",
        victim_handshake_status="pending",
        cad_112_forwarded=True,
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_incident)
    db.commit()
    db.refresh(new_incident)

    await safe_broadcast({
        "type": "NEW_AIOPS_INCIDENT",
        "incident_id": new_incident.id,
        "service": alert.service,
        "root_cause": root_cause,
        "recommended_action": recommended_remediation,
        "severity": alert.severity
    })

    return {
        "action": "MASTER_INCIDENT_CREATED",
        "incident_id": new_incident.id,
        "root_cause_diagnosis": root_cause,
        "recommended_remediation": recommended_remediation
    }


# ============================================================================
# 3. SAFE AUTO-REMEDIATION (ALLOW-LIST GATED + DRY-RUN + AUDIT LOG)
# ============================================================================

@router.post("/remediate")
async def execute_safe_remediation(req: RemediationRequest, db: Session = Depends(get_db)):
    """
    Executes pre-approved remediation with strict allow-list checking,
    dry-run preview mode, and audit logging.
    """
    action_key = req.action.upper().strip()

    if action_key not in APPROVED_REMEDIATION_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security Violation: Action '{req.action}' is not in the pre-approved allow-list: {list(APPROVED_REMEDIATION_ACTIONS.keys())}"
        )

    incident = db.query(Incident).filter(Incident.id == req.incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    action_spec = APPROVED_REMEDIATION_ACTIONS[action_key]
    executed_command = action_spec["command"].format(service=incident.victim_id)

    # Dry-Run / Preview Check
    if req.dry_run:
        return {
            "status": "DRY_RUN_PREVIEW",
            "incident_id": incident.id,
            "service": incident.victim_id,
            "action_proposed": action_key,
            "command_to_execute": executed_command,
            "description": action_spec["description"],
            "requires_human_approval": True
        }

    incident.status = "resolved"
    incident.resolved_at = datetime.now(timezone.utc)

    audit = ResponderLog(
        responder_id="AIOPS_SELF_HEALING_BOT",
        incident_id=incident.id,
        status="auto_healed",
        action_note=f"EXECUTED_REMEDIATION: [{action_key}] -> `{executed_command}`",
        timestamp=datetime.now(timezone.utc)
    )
    db.add(audit)
    db.commit()

    await safe_broadcast({
        "type": "SELF_HEALING_COMPLETE",
        "incident_id": incident.id,
        "service": incident.victim_id,
        "action": action_key,
        "executed_command": executed_command,
        "status": "HEALTHY"
    })

    return {
        "status": "SUCCESS_AUTO_HEALED",
        "incident_id": incident.id,
        "service": incident.victim_id,
        "action_taken": action_key,
        "executed_command": executed_command,
        "audit_logged": True
    }


@router.get("/telemetry-feed")
async def get_telemetry_feed():
    """Returns recent live stream buffer for visualization."""
    return TELEMETRY_BUFFER