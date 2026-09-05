# app/services/geofence.py
import math
from typing import Tuple

def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates the great-circle distance between two points on the Earth surface in meters.
    Uses the Haversine formula.
    """
    R = 6371000.0  # Earth's radius in meters
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    
    return R * c

def verify_resolution_geofence(
    responder_lat: float,
    responder_lon: float,
    incident_lat: float,
    incident_lon: float,
    threshold_meters: float = 50.0
) -> Tuple[bool, float]:
    """
    Validates if the responder is within the mandatory proximity geofence radius.
    
    Returns:
        (is_within_fence: bool, distance_in_meters: float)
    """
    distance = calculate_haversine_distance(
        responder_lat, responder_lon,
        incident_lat, incident_lon
    )
    return distance <= threshold_meters, round(distance, 2)