# app/services/outbound_notifier.py
import os
import urllib.parse
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

def get_twilio_client():
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip().replace('"', '')
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip().replace('"', '')
    try:
        if account_sid.startswith("AC") and auth_token:
            return Client(account_sid, auth_token)
    except Exception as e:
        print(f"[Twilio Client Init Warning]: {e}")
    return None

def get_twilio_from_number():
    raw_num = (
        os.getenv("TWILIO_PHONE_NUMBER") 
        or os.getenv("TWILIO_FROM_NUMBER") 
        or "+18147781439"
    )
    return raw_num.strip().replace('"', '')

def get_default_guardian_phone():
    raw_phone = os.getenv("GUARDIAN_DEFAULT_PHONE") or os.getenv("EMERGENCY_CONTACTS") or "+919391774539"
    return raw_phone.split(",")[0].strip().replace('"', '')

async def trigger_ai_guardian_call(victim_identifier: str, emergency_type: str, micro_location: str, target_phone: str = None):
    """
    Places an automated AI voice call to the victim's relative/guardian via Twilio TwiML.
    """
    client = get_twilio_client()
    from_number = get_twilio_from_number()
    target = (target_phone or get_default_guardian_phone()).strip().replace('"', '')

    twiml_msg = (
        f"<Response>"
        f"<Say voice='Polly.Aditi' language='en-IN'>"
        f"Emergency Alert from SafetySignal. Your relative {victim_identifier} has triggered an SOS alert. "
        f"Emergency type: {emergency_type}. "
        f"Reported location: {micro_location}. "
        f"First responders and statutory 112 units are actively being dispatched."
        f"</Say>"
        f"</Response>"
    )

    if client and from_number:
        try:
            call = client.calls.create(
                twiml=twiml_msg,
                to=target,
                from_=from_number
            )
            print(f"✓ AI Guardian Voice Call dispatched to {target} | Call SID: {call.sid}")
            return {"status": "dispatched", "call_sid": call.sid}
        except Exception as e:
            print(f"[Twilio Voice Call Error]: {e}")
            return {"status": "failed", "error": str(e)}
    else:
        print(f"ℹ️ [SIMULATED AI VOICE CALL] To: {target} | Speech: 'Your relative {victim_identifier} triggered SOS for {emergency_type} at {micro_location}'")
        return {"status": "simulated", "target": target}

async def send_responder_dispatch_sms(responder_phone: str, incident_id: int, lat: float, lng: float, micro_location: str, emergency_type: str):
    """
    Sends an outbound SMS summary with Google Maps tactical link to the assigned responder.
    """
    client = get_twilio_client()
    from_number = get_twilio_from_number()
    target = (responder_phone or get_default_guardian_phone()).strip().replace('"', '')
    maps_link = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"
    sms_body = (
        f"🚨 SafetySignal Mission #{incident_id}\n"
        f"Type: {emergency_type}\n"
        f"Location: {micro_location}\n"
        f"Live Tactical Route: {maps_link}"
    )

    if client and target and from_number:
        try:
            msg = client.messages.create(
                body=sms_body,
                to=target,
                from_=from_number
            )
            print(f"✓ Responder Dispatch SMS sent to {target} | Msg SID: {msg.sid}")
            return {"status": "sent", "sid": msg.sid}
        except Exception as e:
            print(f"[Responder SMS Dispatch Error]: {e}")
            return {"status": "failed", "error": str(e)}
    else:
        print(f"ℹ️ [SIMULATED RESPONDER SMS] To: {target} | Body:\n{sms_body}")
        return {"status": "simulated"}