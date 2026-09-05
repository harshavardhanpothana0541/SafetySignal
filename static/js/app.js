let ws = null;
let currentCoords = null;
let userId = "user_" + Math.floor(Math.random() * 10000);
let currentRole = "victim";
let selectedEmergencyType = "Medical / Cardiac";
let currentIncident = null;
let routingControl = null;
let incidentMarker = null;

let responderToken = localStorage.getItem("responder_token") || null;
let responderBadge = localStorage.getItem("responder_badge") || null;

const authModal = new bootstrap.Modal(document.getElementById('authModal'));

const FIRST_AID_PROTOCOLS = {
    "Medical / Cardiac": [
        "Check responsiveness and breathing immediately.",
        "If unresponsive, begin CPR: 30 hard and fast chest compressions (100–120 bpm).",
        "Keep the victim's airway clear and tilted back slightly."
    ],
    "Trauma / Accident": [
        "Do NOT move the patient unless there is immediate danger (e.g., fire/explosion).",
        "Stabilize the head, neck, and spine to avoid secondary injury.",
        "Check for consciousness and keep them warm."
    ],
    "Severe Bleeding": [
        "Apply direct, continuous pressure on the wound using a clean cloth or bandage.",
        "Elevate the injured limb above heart level.",
        "Do NOT remove deeply embedded objects; apply firm pressure around them."
    ],
    "Fire / Hazard": [
        "Move to an open, well-ventilated area away from smoke and fire.",
        "If clothes are on fire: STOP, DROP, and ROLL.",
        "Cool minor burns with cool, running water for at least 10 minutes."
    ]
};

// Initialize Leaflet Map
const map = L.map('map').setView([20.5937, 78.9629], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap'
}).addTo(map);

let userMarker = null;

function initLocation() {
    if (navigator.geolocation) {
        navigator.geolocation.watchPosition(
            (pos) => {
                currentCoords = { lat: pos.coords.latitude, lon: pos.coords.longitude };

                if (!userMarker) {
                    userMarker = L.marker([currentCoords.lat, currentCoords.lon]).addTo(map);
                    map.setView([currentCoords.lat, currentCoords.lon], 15);
                } else {
                    userMarker.setLatLng([currentCoords.lat, currentCoords.lon]);
                }

                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({
                        action: "UPDATE_LOCATION",
                        lat: currentCoords.lat,
                        lon: currentCoords.lon
                    }));
                }
            },
            (err) => console.error("Location error:", err),
            { enableHighAccuracy: true }
        );
    }
}

function showFirstAid(type, severity = "HIGH") {
    const card = document.getElementById("firstAidCard");
    const title = document.getElementById("firstAidTitle");
    const stepsList = document.getElementById("firstAidSteps");
    const severityBadge = document.getElementById("severityBadge");

    const steps = FIRST_AID_PROTOCOLS[type] || FIRST_AID_PROTOCOLS["Medical / Cardiac"];
    title.innerText = `📋 Immediate Protocol: ${type}`;
    severityBadge.innerText = severity;
    stepsList.innerHTML = steps.map((step, idx) => `<li class="list-group-item px-0 py-1"><strong>${idx + 1}.</strong> ${step}</li>`).join("");
    card.style.display = "block";
}

function setCategory(type) {
    selectedEmergencyType = type;
    document.querySelectorAll(".emergency-type-btn").forEach(btn => {
        if (btn.getAttribute("data-type") === type) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });
}

document.querySelectorAll(".emergency-type-btn").forEach((btn) => {
    btn.addEventListener("click", () => setCategory(btn.getAttribute("data-type")));
});

async function triggerAITriage(text) {
    try {
        const response = await fetch("/api/emergency/ai-triage", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ description: text })
        });
        const data = await response.json();
        setCategory(data.classified_type);
        showFirstAid(data.classified_type, data.severity);
    } catch (err) {
        console.error("AI Triage Request Failed:", err);
    }
}

document.getElementById("aiTriageBtn").addEventListener("click", () => {
    const input = document.getElementById("aiIncidentInput").value.trim();
    if (!input) return;
    triggerAITriage(input);
});

// Web Speech API
const micBtn = document.getElementById("micBtn");
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

if (SpeechRecognition) {
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.lang = 'en-US';

    micBtn.addEventListener("click", () => {
        recognition.start();
        micBtn.classList.replace("btn-outline-secondary", "btn-danger");
        micBtn.innerText = "Listening...";
    });

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        document.getElementById("aiIncidentInput").value = transcript;
        micBtn.classList.replace("btn-danger", "btn-outline-secondary");
        micBtn.innerText = "🎙️ Speak";
        triggerAITriage(transcript);
    };

    recognition.onerror = () => {
        micBtn.classList.replace("btn-danger", "btn-outline-secondary");
        micBtn.innerText = "🎙️ Speak";
    };
}

// Toggle Password Visibility
const togglePasswordBtn = document.getElementById("togglePasswordBtn");
const passwordInput = document.getElementById("authPassword");

if (togglePasswordBtn && passwordInput) {
    togglePasswordBtn.addEventListener("click", () => {
        const isPassword = passwordInput.getAttribute("type") === "password";
        passwordInput.setAttribute("type", isPassword ? "text" : "password");
        togglePasswordBtn.innerText = isPassword ? "🙈" : "👁️";
    });
}

// Authentication Modal Handlers
document.getElementById("loginBtn").addEventListener("click", async () => {
    const u = document.getElementById("authUsername").value.trim();
    const p = document.getElementById("authPassword").value.trim();
    if (!u || !p) return alert("Enter credentials");

    try {
        const res = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: u, password: p })
        });
        const data = await res.json();
        if (res.ok) {
            localStorage.setItem("responder_token", data.access_token);
            localStorage.setItem("responder_badge", data.badge_number);
            responderToken = data.access_token;
            responderBadge = data.badge_number;
            authModal.hide();
            enableResponderMode();
        } else {
            alert(data.detail || "Authentication Failed");
        }
    } catch (e) {
        alert("Server error");
    }
});

document.getElementById("registerBtn").addEventListener("click", async () => {
    const u = document.getElementById("authUsername").value.trim();
    const p = document.getElementById("authPassword").value.trim();
    const b = document.getElementById("authBadge").value.trim();
    if (!u || !p || !b) return alert("Fill all fields");

    try {
        const res = await fetch("/api/auth/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: u, password: p, badge_number: b })
        });
        const data = await res.json();
        if (res.ok) {
            localStorage.setItem("responder_token", data.access_token);
            localStorage.setItem("responder_badge", data.badge_number);
            responderToken = data.access_token;
            responderBadge = data.badge_number;
            authModal.hide();
            enableResponderMode();
        } else {
            alert(data.detail || "Registration Failed");
        }
    } catch (e) {
        alert("Server error");
    }
});

document.getElementById("closeAuthModal").addEventListener("click", () => {
    document.getElementById("roleVictim").checked = true;
    currentRole = "victim";
    authModal.hide();
});

function enableResponderMode() {
    document.getElementById("victimSection").style.display = "none";
    const badge = document.getElementById("verifiedBadge");
    badge.style.display = "inline-block";
    badge.innerText = `🛡️ Verified (${responderBadge || 'EMT'})`;

    if (ws) ws.close();
    setupWebSocket();
}

// WebSocket Connection
function setupWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/api/emergency/ws/${userId}/${currentRole}`);

    ws.onopen = () => {
        const badge = document.getElementById("connectionBadge");
        badge.className = "badge bg-success";
        badge.innerText = `Connected (${currentRole})`;

        if (currentCoords) {
            ws.send(JSON.stringify({
                action: "UPDATE_LOCATION",
                lat: currentCoords.lat,
                lon: currentCoords.lon
            }));
        }
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === "EMERGENCY_ALERT") {
            currentIncident = data;
            const alertContainer = document.getElementById("alertContainer");
            const alertInfo = document.getElementById("alertInfo");
            const acceptBtn = document.getElementById("acceptBtn");
            const resolveBtn = document.getElementById("resolveBtn");

            alertContainer.style.display = "block";
            acceptBtn.style.display = "block";
            acceptBtn.disabled = false;
            acceptBtn.innerText = "Accept & Navigate";
            resolveBtn.style.display = "none";

            alertInfo.innerText = `${data.emergency_type} reported approx ${data.distance_km} km away.`;
            showFirstAid(data.emergency_type);

            if (incidentMarker) map.removeLayer(incidentMarker);
            incidentMarker = L.circle([data.latitude, data.longitude], {
                color: 'red',
                fillColor: '#dc3545',
                fillOpacity: 0.5,
                radius: 100
            }).addTo(map).bindPopup(`🚨 ${data.emergency_type}`).openPopup();
        }

        if (data.type === "HELP_ON_THE_WAY") {
            alert("✅ A First Responder has accepted your SOS and is navigating to your location!");
        }

        if (data.type === "INCIDENT_RESOLVED") {
            alert("✨ This emergency incident has been marked as RESOLVED by the responder.");
            document.getElementById("firstAidCard").style.display = "none";
        }
    };

    ws.onclose = () => {
        const badge = document.getElementById("connectionBadge");
        badge.className = "badge bg-danger";
        badge.innerText = "Disconnected";
        setTimeout(setupWebSocket, 3000);
    };
}

// Accept Incident
document.getElementById("acceptBtn").addEventListener("click", () => {
    if (!currentIncident || !currentCoords) return;

    ws.send(JSON.stringify({
        action: "ACCEPT_INCIDENT",
        incident_id: currentIncident.incident_id,
        victim_id: currentIncident.victim_id
    }));

    if (routingControl) {
        map.removeControl(routingControl);
    }

    routingControl = L.Routing.control({
        waypoints: [
            L.latLng(currentCoords.lat, currentCoords.lon),
            L.latLng(currentIncident.latitude, currentIncident.longitude)
        ],
        routeWhileDragging: false,
        addWaypoints: false
    }).addTo(map);

    document.getElementById("acceptBtn").style.display = "none";
    document.getElementById("resolveBtn").style.display = "block";
});

// Resolve Incident
document.getElementById("resolveBtn").addEventListener("click", () => {
    if (!currentIncident) return;

    ws.send(JSON.stringify({
        action: "RESOLVE_INCIDENT",
        incident_id: currentIncident.incident_id,
        victim_id: currentIncident.victim_id
    }));

    if (routingControl) {
        map.removeControl(routingControl);
        routingControl = null;
    }
    if (incidentMarker) {
        map.removeLayer(incidentMarker);
        incidentMarker = null;
    }

    document.getElementById("alertContainer").style.display = "none";
    document.getElementById("firstAidCard").style.display = "none";
    alert("Mission Completed: Incident marked as resolved.");
});

document.getElementById("dismissBtn").addEventListener("click", () => {
    document.getElementById("alertContainer").style.display = "none";
});

// Role Toggle with Auth Guard
document.querySelectorAll("input[name='roleRadio']").forEach((input) => {
    input.addEventListener("change", (e) => {
        currentRole = e.target.value;
        const victimSec = document.getElementById("victimSection");
        const alertSec = document.getElementById("alertContainer");
        const firstAidCard = document.getElementById("firstAidCard");
        const verifiedBadge = document.getElementById("verifiedBadge");

        if (currentRole === "responder") {
            if (!responderToken) {
                authModal.show();
            } else {
                enableResponderMode();
            }
        } else {
            victimSec.style.display = "block";
            alertSec.style.display = "none";
            firstAidCard.style.display = "none";
            verifiedBadge.style.display = "none";
            if (ws) ws.close();
            setupWebSocket();
        }
    });
});

document.getElementById("sosBtn").addEventListener("click", () => {
    if (!currentCoords) {
        alert("Acquiring GPS location. Please allow location permissions.");
        return;
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            action: "TRIGGER_SOS",
            lat: currentCoords.lat,
            lon: currentCoords.lon,
            emergency_type: selectedEmergencyType
        }));
        showFirstAid(selectedEmergencyType);
        alert(`🚨 ${selectedEmergencyType} SOS broadcasted!`);
    }
});

initLocation();
setupWebSocket();