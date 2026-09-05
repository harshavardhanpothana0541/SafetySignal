import math
import json
from typing import Dict, Any, Optional
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Format: {user_id: {"ws": WebSocket, "role": str, "lat": Optional[float], "lon": Optional[float]}}
        self.active_connections: Dict[str, Dict[str, Any]] = {}

    async def connect(self, user_id: str, websocket: WebSocket, role: str):
        await websocket.accept()
        self.active_connections[user_id] = {
            "ws": websocket,
            "role": role,
            "lat": None,
            "lon": None
        }

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    def update_location(self, user_id: str, lat: float, lon: float):
        if user_id in self.active_connections:
            self.active_connections[user_id]["lat"] = lat
            self.active_connections[user_id]["lon"] = lon

    @staticmethod
    def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculates the great-circle distance between two points in km via the Haversine formula."""
        R = 6371.0  # Earth radius in kilometers
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (math.sin(d_lat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(d_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    async def broadcast_sos(
        self,
        victim_id: str,
        lat: float,
        lon: float,
        emergency_type: str,
        incident_id: int,
        created_at: Optional[str] = None,
        radius_km: float = 25.0
    ):
        """Dispatches an SOS only to responders within the dynamic spatial geofence."""
        base_payload = {
            "type": "NEW_SOS",
            "incident_id": incident_id,
            "victim_id": victim_id,
            "lat": lat,
            "lon": lon,
            "emergency_type": emergency_type,
            "created_at": created_at
        }

        # Iterate over snapshot to ensure thread-safety during connects/disconnects
        for uid, user_data in list(self.active_connections.items()):
            if user_data.get("role") == "responder":
                r_lat = user_data.get("lat")
                r_lon = user_data.get("lon")

                alert_payload = dict(base_payload)

                # Apply spatial filter if responder GPS coordinates are active
                if r_lat is not None and r_lon is not None:
                    dist = self.calculate_distance(lat, lon, r_lat, r_lon)
                    if dist <= radius_km:
                        alert_payload["distance_km"] = round(dist, 2)
                        try:
                            await user_data["ws"].send_text(json.dumps(alert_payload))
                        except Exception:
                            pass
                else:
                    # Dispatch to command stations where exact GPS is not yet acquired
                    alert_payload["distance_km"] = None
                    try:
                        await user_data["ws"].send_text(json.dumps(alert_payload))
                    except Exception:
                        pass

    async def broadcast_location_update(
        self,
        user_id: str,
        lat: float,
        lon: float,
        incident_id: Optional[int] = None
    ):
        """Streams moving GPS telemetry to connected responders."""
        stream_payload = {
            "type": "LOCATION_STREAM",
            "user_id": user_id,
            "incident_id": incident_id,
            "lat": lat,
            "lon": lon
        }

        for uid, user_data in list(self.active_connections.items()):
            if user_data.get("role") == "responder":
                try:
                    await user_data["ws"].send_text(json.dumps(stream_payload))
                except Exception:
                    pass

    async def send_to_victim(self, victim_id: str, payload: dict):
        """Pushes direct status updates and alerts to a specific victim."""
        if victim_id in self.active_connections:
            try:
                await self.active_connections[victim_id]["ws"].send_text(json.dumps(payload))
            except Exception:
                pass

manager = ConnectionManager()