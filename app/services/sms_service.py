import os
import json
import logging
import base64
import urllib.request
import urllib.parse
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SafetySignal-Alerts")

class AlertService:
    def __init__(self):
        # 1. Telegram Dispatch Config
        self.tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        # 2. Twilio Gateway Config
        self.twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.twilio_from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()

        # 3. Exotel Gateway Config (Indian Telecom Route)
        self.exotel_sid = os.getenv("EXOTEL_SID", "").strip()
        self.exotel_token = os.getenv("EXOTEL_TOKEN", "").strip()
        self.exotel_subdomain = os.getenv("EXOTEL_SUBDOMAIN", "").strip()
        self.exotel_sender_id = os.getenv("EXOTEL_SENDER_ID", "").strip()

    # --- Telecom SMS Dispatch Engine (Twilio / Exotel / Local) ---
    def send_sms(self, to_phone: str, body: str) -> dict:
        """
        Dispatches outbound direct SMS via Twilio, Exotel, or Local Console Sandbox.
        """
        clean_phone = to_phone.strip()
        
        # A. Twilio Gateway Attempt
        if self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number:
            try:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_account_sid}/Messages.json"
                data = urllib.parse.urlencode({
                    "To": clean_phone,
                    "From": self.twilio_from_number,
                    "Body": body
                }).encode('utf-8')

                req = urllib.request.Request(url, data=data, method="POST")
                auth_header = base64.b64encode(
                    f"{self.twilio_account_sid}:{self.twilio_auth_token}".encode('utf-8')
                ).decode('utf-8')
                req.add_header("Authorization", f"Basic {auth_header}")

                with urllib.request.urlopen(req, timeout=8) as response:
                    res_body = json.loads(response.read().decode('utf-8'))
                    logger.info(f"✅ [TWILIO SMS] Delivered to {clean_phone} (SID: {res_body.get('sid')})")
                    return {
                        "status": "delivered",
                        "provider": "twilio",
                        "message_sid": res_body.get("sid")
                    }
            except Exception as e:
                logger.warning(f"⚠️ [TWILIO ERROR] {e}. Falling back to secondary...")

        # B. Exotel Gateway Attempt
        if self.exotel_sid and self.exotel_token and self.exotel_subdomain:
            try:
                url = f"https://api.exotel.com/v1/Accounts/{self.exotel_sid}/Sms/send.json"
                data = urllib.parse.urlencode({
                    "From": self.exotel_sender_id or "SAFETY",
                    "To": clean_phone,
                    "Body": body
                }).encode('utf-8')

                req = urllib.request.Request(url, data=data, method="POST")
                auth_header = base64.b64encode(
                    f"{self.exotel_sid}:{self.exotel_token}".encode('utf-8')
                ).decode('utf-8')
                req.add_header("Authorization", f"Basic {auth_header}")

                with urllib.request.urlopen(req, timeout=8) as response:
                    res_body = json.loads(response.read().decode('utf-8'))
                    logger.info(f"✅ [EXOTEL SMS] Delivered to {clean_phone}")
                    return {
                        "status": "delivered",
                        "provider": "exotel",
                        "sms_id": res_body.get("SMSMessage", {}).get("Sid")
                    }
            except Exception as e:
                logger.warning(f"⚠️ [EXOTEL ERROR] {e}. Falling back to sandbox...")

        # C. Local Sandbox Fallback
        logger.info(f"\n================ [SMS DISPATCH GATEWAY] ================")
        logger.info(f"📱 TO:       {clean_phone}")
        logger.info(f"💬 MESSAGE:  {body}")
        logger.info(f"⚙️ PROVIDER: Local Carrier Sandbox (No API Keys Configured)")
        logger.info(f"========================================================\n")

        return {
            "status": "simulated",
            "provider": "local_sandbox",
            "recipient": clean_phone,
            "body": body
        }

    # --- Bidirectional Telephony Handshakes ---
    def dispatch_safety_handshake(self, to_phone: str, incident_id: int, micro_location: str = None) -> dict:
        """Sends 2-way verification SMS prompt to offline/keypad victim."""
        msg = (
            f"🚨 SafetySignal Alert #{incident_id}: Incident logged at {micro_location or 'Registered Base Location'}.\n"
            f"Tactical responders & CAD 112 alerted.\n"
            f"REPLY:\n"
            f"1 -> If you are SAFE (Cancel Alert)\n"
            f"0 -> If you STILL NEED HELP"
        )
        return self.send_sms(to_phone, msg)

    def dispatch_responder_assigned(self, to_phone: str, incident_id: int, responder_name: str, eta_mins: int = 4) -> dict:
        """Notifies offline victim when an EMT unit accepts dispatch."""
        msg = (
            f"🚨 SafetySignal Update: Responder {responder_name} claimed Incident #{incident_id}.\n"
            f"ETA: ~{eta_mins} mins. Keep phone line free."
        )
        return self.send_sms(to_phone, msg)

    # --- Telegram Broadcast Channel Dispatch ---
    def send_emergency_sms(self, phone_numbers: List[str], incident_type: str, lat: float, lon: float, incident_id: int):
        token = os.getenv("TELEGRAM_BOT_TOKEN", self.tg_token).strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", self.tg_chat_id).strip()

        maps_link = f"https://www.google.com/maps?q={lat},{lon}"
        
        message_text = (
            f"🚨 EMERGENCY SOS BROADCAST #{incident_id}\n\n"
            f"📌 Category: {incident_type}\n"
            f"📍 Location: {lat:.5f}, {lon:.5f}\n"
            f"🗺️ Live Route: {maps_link}\n\n"
            f"⚡ Immediate First-Responder Dispatch Required!"
        )

        logger.info(f"📤 Preparing Telegram SOS broadcast for Incident #{incident_id}...")

        if token and chat_id:
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = json.dumps({
                    "chat_id": chat_id,
                    "text": message_text,
                    "disable_web_page_preview": False
                }).encode("utf-8")

                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"}
                )
                
                with urllib.request.urlopen(req, timeout=10) as response:
                    res_body = response.read().decode("utf-8")
                    logger.info(f"✅ Telegram Dispatch Successful! Server replied: {res_body}")
                    return {"status": "success", "channel": "telegram"}

            except Exception as e:
                logger.error(f"❌ Telegram API Dispatch Error: {e}", exc_info=True)
        else:
            logger.warning(f"⚠️ Telegram credentials missing: Token={bool(token)}, ChatID={bool(chat_id)}")

        # Also dispatch to direct SMS numbers
        for phone in phone_numbers:
            self.send_sms(phone, message_text)

        return {"status": "completed"}

sms_service = AlertService()