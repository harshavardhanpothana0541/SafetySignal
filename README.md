# 🚨 SafetySignal - Real-Time Autonomous Emergency Dispatch System

SafetySignal is a high-speed, geolocation-aware emergency dispatch platform built with **FastAPI**, **Leaflet.js**, **WebSockets**, and **SQLite**. It enables bystanders and victims to trigger instant geolocated SOS alerts, provides AI-driven natural language triage protocols, performs distance-based responder routing, and issues automated multi-channel SMS fallbacks.

---

## 🌟 Key Architecture & Capabilities

- 📍 **Real-Time GPS Tracking & Proximity Radius**: Broadcasts emergency alerts exclusively to responders within proximity using the Haversine distance algorithm.
- ⚡ **Full-Duplex WebSockets**: Sub-100ms latency communication between victims, dispatchers, and first responders.
- 🎙️ **Hands-Free AI Emergency Triage**: Browser Web Speech API combined with heuristic natural-language triage to classify severity (Cardiac, Trauma, Severe Bleeding, Hazard) and render instant step-by-step first-aid action cards.
- 🗺️ **Turn-by-Turn Routing Engine**: Dynamic road route calculation directly inside the responder's HUD using Leaflet Routing Machine.
- 📲 **Automated Multi-Channel Fallback**: Instant SMS pin broadcasts with direct Google Maps links.
- 📊 **Analytics Command Center**: Administrative live monitoring dashboard tracking incident resolution lifecycle and response metrics.

---

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.10+), SQLAlchemy, Uvicorn, SQLite
- **Frontend**: Vanilla JavaScript (ES6+), Leaflet.js, OpenStreetMap, Bootstrap 5
- **Communication**: WebSockets (WSS), Web Speech API
- **Services**: AI Triage Classifier, Fast2SMS / Twilio SMS Dispatcher

---

## 🚀 Quick Start Guide

### 1. Clone & Setup Environment
```bash
git clone [https://github.com/your-username/safetysignal.git](https://github.com/your-username/safetysignal.git)
cd safetysignal
python -m venv venv
.\venv\Scripts\activate   # On Windows
# source venv/bin/activate # On macOS/Linux
