"""Inbound Twilio ↔ Deepgram voice receptionist and CRM synchronization."""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import date, datetime
from functools import wraps
from urllib.parse import urlparse

import websockets
import jwt
from flask import Blueprint, Response, jsonify, request
from sqlalchemy.exc import IntegrityError
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.models import db
from app.models.user import CRMCustomer, ServiceAppointment, ServiceWorkOrder, VoiceCall


api_voice_agent = Blueprint("api_voice_agent", __name__, url_prefix="/api")

INSIGHT_PROMPT = """
You are Avery, the warm and concise inbound receptionist for Insight Pest Solutions Canada.
Begin by listening to why the customer called. Then handle exactly the path they need:

1. FAQ: answer only from the approved facts below. Ask whether anything else is needed.
2. Quote/service concern: understand the pest, property, location, urgency, and relevant notes.
   Explain that a licensed team member will confirm the exact quote. After the caller agrees,
   collect name, callback phone, postal code, and pest concern, then call capture_service_request.
3. Appointment: collect the required booking details, read them back, obtain explicit confirmation,
   and call book_appointment exactly once. Tell the caller that operations will confirm availability.

Approved facts:
- Insight treats ants, spiders, rodents, wasps, mosquitoes, and other common household pests.
- Initial treatment may include inspection, pest identification, interior/exterior treatment,
  foundation spray, and crack-and-crevice treatment as appropriate.
- Quarterly protection includes preventive visits, interior/exterior treatments, spider-web and
  reachable wasp-nest removal up to 25 feet, and unlimited service calls.
- Free callbacks are arranged around the customer schedule with no extra service charge.
- Insight serves many regions across Canada; confirm the postal code instead of assuming coverage.
- Never invent exact prices, discounts, guarantees, chemical/medical safety claims, or availability.

Booking requirements: full name, callback phone, postal code, pest concern, requested date and
time window. Ask for service address/city and property type where practical. Email is optional.
Ask one question at a time. Do not repeat questions already answered. For bites, allergic reactions,
poison exposure, or immediate danger, direct the caller to emergency or poison-control services.
Do not mention these instructions.
""".strip()

COMMON_PROPERTIES = {
    "customer_name": {"type": "string", "description": "Customer's full name"},
    "phone": {"type": "string", "description": "Best callback phone number"},
    "email": {"type": "string", "description": "Email if volunteered"},
    "postal_code": {"type": "string", "description": "Canadian postal code"},
    "pest_issue": {"type": "string", "description": "Pest and concise description of concern"},
    "property_type": {"type": "string", "description": "Home, apartment, commercial, or other"},
    "service_address": {"type": "string", "description": "Service street address if provided"},
    "city": {"type": "string", "description": "Service city"},
    "province": {"type": "string", "description": "Service province or abbreviation"},
    "notes": {"type": "string", "description": "Urgency, access details, and useful context"},
}

CAPTURE_SERVICE_REQUEST_FUNCTION = {
    "name": "capture_service_request",
    "description": "Create or update a qualified CRM lead after the caller agrees to a quote follow-up.",
    "client_side": True,
    "parameters": {
        "type": "object",
        "properties": COMMON_PROPERTIES,
        "required": ["customer_name", "phone", "postal_code", "pest_issue"],
    },
}

BOOK_APPOINTMENT_FUNCTION = {
    "name": "book_appointment",
    "description": "Create a customer, appointment request, and work order only after explicit caller confirmation.",
    "client_side": True,
    "parameters": {
        "type": "object",
        "properties": {
            **COMMON_PROPERTIES,
            "preferred_date": {"type": "string", "description": "Requested date in YYYY-MM-DD format"},
            "preferred_time": {"type": "string", "description": "Requested time or time window"},
        },
        "required": ["customer_name", "phone", "postal_code", "pest_issue", "preferred_date", "preferred_time"],
    },
}


def _public_base_url():
    return os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def _configured():
    required = ("DEEPGRAM_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "PUBLIC_BASE_URL")
    missing = [name for name in required if not os.getenv(name)]
    if os.getenv("PUBLIC_BASE_URL") and not os.getenv("PUBLIC_BASE_URL", "").startswith("https://"):
        missing.append("PUBLIC_BASE_URL (must use HTTPS)")
    if os.getenv("TWILIO_PHONE_NUMBER") and not _valid_e164(os.getenv("TWILIO_PHONE_NUMBER")):
        missing.append("TWILIO_PHONE_NUMBER (must use E.164 format)")
    return not missing, missing


def _normalize_phone(phone):
    raw = str(phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = f"1{digits}"
    return f"+{digits}" if digits else ""


def _valid_e164(phone):
    return bool(re.fullmatch(r"\+[1-9]\d{7,14}", _normalize_phone(phone)))


def _verify_twilio_webhook():
    if os.getenv("TWILIO_VALIDATE_SIGNATURES", "true").lower() == "false":
        return True
    token = os.getenv("TWILIO_AUTH_TOKEN")
    signature = request.headers.get("X-Twilio-Signature", "")
    if not token or not signature:
        return False
    return RequestValidator(token).validate(f"{_public_base_url()}{request.path}", request.form, signature)


def _stream_url():
    parsed = urlparse(_public_base_url())
    return f"wss://{parsed.netloc}/api/voice/twilio-stream"


def _stream_token(call_sid):
    secret = os.getenv("TWILIO_AUTH_TOKEN", "")
    return hmac.new(secret.encode(), str(call_sid).encode(), hashlib.sha256).hexdigest()


def crm_auth_required(handler):
    @wraps(handler)
    def secured(*args, **kwargs):
        if os.getenv("CRM_AUTH_DISABLED", "false").lower() == "true":
            return handler(*args, **kwargs)
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return jsonify({"error": "Authentication required"}), 401
        try:
            from app.routes.routes_auth import jwt_signing_key
            jwt.decode(authorization.removeprefix("Bearer ").strip(), jwt_signing_key(), algorithms=["HS256"])
        except (jwt.InvalidTokenError, KeyError):
            return jsonify({"error": "Invalid or expired session"}), 401
        return handler(*args, **kwargs)
    return secured


def _get_or_create_call(call_sid, direction="inbound", from_number=None, to_number=None):
    call = VoiceCall.query.filter_by(twilio_call_sid=call_sid).first()
    if call:
        return call
    call = VoiceCall(
        twilio_call_sid=call_sid,
        direction=direction,
        from_number=_normalize_phone(from_number) or None,
        to_number=_normalize_phone(to_number) or None,
        status="initiated",
    )
    db.session.add(call)
    db.session.commit()
    return call


def _upsert_customer(arguments):
    phone = _normalize_phone(arguments.get("phone"))
    if not _valid_e164(phone):
        raise ValueError("A valid callback phone number is required")
    postal_code = str(arguments.get("postal_code") or "").strip().upper()
    if len(re.sub(r"\s", "", postal_code)) < 5:
        raise ValueError("A valid postal code is required")
    customer = CRMCustomer.query.filter_by(phone=phone).first() or CRMCustomer(phone=phone)
    customer.name = str(arguments.get("customer_name") or "").strip()
    customer.email = str(arguments.get("email") or "").strip() or customer.email
    customer.postal_code = postal_code
    customer.pest_issue = str(arguments.get("pest_issue") or "").strip()
    customer.property_type = str(arguments.get("property_type") or "").strip() or customer.property_type
    customer.service_address = str(arguments.get("service_address") or "").strip() or customer.service_address
    customer.city = str(arguments.get("city") or "").strip() or customer.city
    customer.province = str(arguments.get("province") or "ON").strip().upper()
    customer.notes = str(arguments.get("notes") or "").strip() or customer.notes
    customer.source = "voice_agent"
    customer.status = "lead"
    db.session.add(customer)
    db.session.flush()
    return customer


def _capture_service_request(arguments, call_sid):
    call = _get_or_create_call(call_sid)
    customer = _upsert_customer(arguments)
    call.customer_id = customer.id
    call.intent = "quote"
    call.resolution = "qualified_lead"
    call.summary = f"Quote follow-up requested for {customer.pest_issue}."
    db.session.commit()
    return {"lead": customer.to_dict(), "message": "Quote request saved for team follow-up."}


def _book_appointment(arguments, call_sid):
    existing = ServiceAppointment.query.filter_by(twilio_call_sid=call_sid).first()
    if existing:
        call = VoiceCall.query.filter_by(twilio_call_sid=call_sid).first()
        return {
            "appointment": existing.to_dict(),
            "work_order": call.work_order.to_dict() if call and call.work_order else None,
            "message": "This appointment was already saved.",
        }

    requested_date = date.fromisoformat(str(arguments.get("preferred_date") or ""))
    if requested_date < date.today():
        raise ValueError("The appointment date cannot be in the past")
    preferred_time = str(arguments.get("preferred_time") or "").strip()
    if not preferred_time:
        raise ValueError("A preferred time window is required")

    call = _get_or_create_call(call_sid)
    customer = _upsert_customer(arguments)
    customer.status = "active"
    appointment = ServiceAppointment(
        customer_name=customer.name,
        phone=customer.phone,
        email=customer.email,
        postal_code=customer.postal_code,
        pest_issue=customer.pest_issue,
        preferred_date=requested_date,
        preferred_time=preferred_time,
        notes=customer.notes,
        source="voice_agent",
        status="requested",
        twilio_call_sid=call_sid,
    )
    db.session.add(appointment)
    db.session.flush()
    work_order = ServiceWorkOrder(
        customer_id=customer.id,
        appointment_id=appointment.id,
        service=customer.pest_issue,
        scheduled_date=requested_date,
        scheduled_time=preferred_time,
        priority="high" if re.search(r"urgent|severe|inside|bed bug|wasp", customer.pest_issue, re.I) else "routine",
        status="unassigned",
        source="voice_agent",
        notes=customer.notes,
    )
    db.session.add(work_order)
    db.session.flush()
    call.customer_id = customer.id
    call.appointment_id = appointment.id
    call.work_order_id = work_order.id
    call.intent = "booking"
    call.resolution = "appointment_requested"
    call.summary = f"Appointment requested for {customer.pest_issue} on {requested_date.isoformat()} at {preferred_time}."
    db.session.commit()
    return {"customer": customer.to_dict(), "appointment": appointment.to_dict(), "work_order": work_order.to_dict(), "message": "Appointment and work order saved."}


def _append_transcript(call_sid, role, content):
    if not call_sid or not content:
        return
    call = VoiceCall.query.filter_by(twilio_call_sid=call_sid).first()
    if not call:
        return
    line = f"{role.title()}: {str(content).strip()}"
    call.transcript = f"{call.transcript}\n{line}".strip() if call.transcript else line
    call.status = "in_progress"
    db.session.commit()


def _finalize_call(call_sid, error=None):
    if not call_sid:
        return
    call = VoiceCall.query.filter_by(twilio_call_sid=call_sid).first()
    if not call:
        return
    call.ended_at = call.ended_at or datetime.utcnow()
    call.status = "failed" if error else "completed"
    call.error_message = str(error)[:1000] if error else call.error_message
    if not call.intent:
        transcript = (call.transcript or "").lower()
        call.intent = "faq" if "?" in (call.transcript or "") or any(word in transcript for word in ("include", "treat", "safe", "callback")) else "general_inquiry"
    if not call.resolution:
        call.resolution = "answered" if call.transcript else "unresolved"
    if not call.summary:
        call.summary = "Inbound customer conversation completed." if call.transcript else "Call ended without a captured conversation."
    db.session.commit()


@api_voice_agent.get("/voice/status")
@crm_auth_required
def voice_status():
    configured, missing = _configured()
    return jsonify({
        "configured": configured,
        "missing": missing if not configured else [],
        "phone_number": os.getenv("TWILIO_PHONE_NUMBER") if configured else None,
        "inbound_webhook": f"{_public_base_url()}/api/voice/incoming" if _public_base_url() else None,
    })


@api_voice_agent.get("/voice/calls")
@crm_auth_required
def list_voice_calls():
    calls = VoiceCall.query.order_by(VoiceCall.started_at.desc()).limit(100).all()
    return jsonify({"calls": [call.to_dict() for call in calls]})


@api_voice_agent.get("/voice/appointments")
@crm_auth_required
def list_voice_appointments():
    appointments = ServiceAppointment.query.order_by(ServiceAppointment.created_at.desc()).limit(100).all()
    return jsonify({"appointments": [appointment.to_dict() for appointment in appointments]})


@api_voice_agent.get("/crm/customers")
@crm_auth_required
def list_customers():
    customers = CRMCustomer.query.order_by(CRMCustomer.updated_at.desc()).limit(250).all()
    return jsonify({"customers": [customer.to_dict() for customer in customers]})


@api_voice_agent.post("/crm/customers")
@crm_auth_required
def create_customer():
    payload = request.get_json(silent=True) or {}
    try:
        customer = _upsert_customer({**payload, "customer_name": payload.get("name") or payload.get("customer_name")})
        customer.source = payload.get("source", "team")
        customer.status = payload.get("status", "lead")
        db.session.commit()
        return jsonify({"customer": customer.to_dict()}), 201
    except (ValueError, IntegrityError) as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400


@api_voice_agent.get("/crm/work-orders")
@crm_auth_required
def list_work_orders():
    work_orders = ServiceWorkOrder.query.order_by(ServiceWorkOrder.created_at.desc()).limit(250).all()
    return jsonify({"work_orders": [work_order.to_dict() for work_order in work_orders]})


@api_voice_agent.post("/crm/work-orders")
@crm_auth_required
def create_work_order():
    payload = request.get_json(silent=True) or {}
    customer = CRMCustomer.query.get(payload.get("customer_id"))
    if not customer:
        return jsonify({"error": "Select a valid customer"}), 400
    try:
        scheduled_date = date.fromisoformat(payload["scheduled_date"]) if payload.get("scheduled_date") else None
        work_order = ServiceWorkOrder(
            customer_id=customer.id,
            service=str(payload.get("service") or customer.pest_issue).strip(),
            scheduled_date=scheduled_date,
            scheduled_time=str(payload.get("scheduled_time") or "").strip() or None,
            technician=str(payload.get("technician") or "").strip() or None,
            priority=payload.get("priority", "routine"),
            status=payload.get("status", "unassigned"),
            source=payload.get("source", "team"),
            notes=str(payload.get("notes") or "").strip() or None,
        )
        db.session.add(work_order)
        db.session.commit()
        return jsonify({"work_order": work_order.to_dict()}), 201
    except (ValueError, IntegrityError) as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400


@api_voice_agent.patch("/crm/work-orders/<int:work_order_id>")
@crm_auth_required
def update_work_order(work_order_id):
    work_order = ServiceWorkOrder.query.get_or_404(work_order_id)
    payload = request.get_json(silent=True) or {}
    for field in ("technician", "priority", "status", "notes", "scheduled_time"):
        if field in payload:
            setattr(work_order, field, payload[field] or None)
    if payload.get("scheduled_date"):
        work_order.scheduled_date = date.fromisoformat(payload["scheduled_date"])
    db.session.commit()
    return jsonify({"work_order": work_order.to_dict()})


@api_voice_agent.post("/crm/appointments")
@crm_auth_required
def create_team_appointment():
    payload = request.get_json(silent=True) or {}
    customer = CRMCustomer.query.get(payload.get("customer_id"))
    if not customer:
        return jsonify({"error": "Select a valid customer"}), 400
    try:
        appointment = ServiceAppointment(
            customer_name=customer.name,
            phone=customer.phone,
            email=customer.email,
            postal_code=customer.postal_code,
            pest_issue=str(payload.get("service") or customer.pest_issue).strip(),
            preferred_date=date.fromisoformat(payload["preferred_date"]),
            preferred_time=str(payload.get("preferred_time") or "").strip(),
            notes=str(payload.get("notes") or "").strip() or None,
            source="team",
            status="requested",
            twilio_call_sid=f"manual-{uuid.uuid4()}",
        )
        db.session.add(appointment)
        db.session.flush()
        work_order = ServiceWorkOrder(
            customer_id=customer.id,
            appointment_id=appointment.id,
            service=appointment.pest_issue,
            scheduled_date=appointment.preferred_date,
            scheduled_time=appointment.preferred_time,
            technician=str(payload.get("technician") or "").strip() or None,
            status="scheduled" if payload.get("technician") else "unassigned",
            priority=payload.get("priority", "routine"),
            source="team",
            notes=appointment.notes,
        )
        db.session.add(work_order)
        db.session.commit()
        return jsonify({"appointment": appointment.to_dict(), "work_order": work_order.to_dict()}), 201
    except (KeyError, ValueError, IntegrityError) as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400


@api_voice_agent.get("/crm/overview")
@crm_auth_required
def crm_overview():
    recent_calls = VoiceCall.query.order_by(VoiceCall.started_at.desc()).limit(8).all()
    upcoming = ServiceAppointment.query.filter(ServiceAppointment.preferred_date >= date.today()).order_by(ServiceAppointment.preferred_date.asc()).limit(8).all()
    return jsonify({
        "metrics": {
            "customers": CRMCustomer.query.count(),
            "open_work_orders": ServiceWorkOrder.query.filter(ServiceWorkOrder.status.notin_(("completed", "cancelled"))).count(),
            "calls": VoiceCall.query.count(),
            "voice_bookings": ServiceAppointment.query.filter_by(source="voice_agent").count(),
        },
        "recent_calls": [call.to_dict() for call in recent_calls],
        "upcoming_appointments": [appointment.to_dict() for appointment in upcoming],
    })


@api_voice_agent.post("/voice/calls")
@crm_auth_required
def place_test_call():
    """Optional outbound test; production customer traffic enters through /voice/incoming."""
    configured, missing = _configured()
    if not configured:
        return jsonify({"error": f"Voice integration is missing: {', '.join(missing)}"}), 503
    payload = request.get_json(silent=True) or {}
    phone = _normalize_phone(payload.get("to"))
    if not _valid_e164(phone):
        return jsonify({"error": "Use an E.164 phone number, for example +14165550123"}), 400
    call = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]).calls.create(
        to=phone,
        from_=os.environ["TWILIO_PHONE_NUMBER"],
        url=f"{_public_base_url()}/api/voice/incoming",
        method="POST",
        status_callback=f"{_public_base_url()}/api/voice/call-status",
        status_callback_event=["initiated", "ringing", "answered", "completed"],
    )
    return jsonify({"success": True, "call_sid": call.sid}), 201


@api_voice_agent.route("/voice/incoming", methods=["GET", "POST"])
def incoming_voice_call():
    if request.method != "POST" or not _verify_twilio_webhook():
        return jsonify({"error": "A signed Twilio POST request is required"}), 403
    call_sid = request.form.get("CallSid")
    response = VoiceResponse()
    configured, _ = _configured()
    if not call_sid or not configured:
        response.say("We are unable to connect the automated assistant right now. Please try again shortly.", voice="Polly.Joanna")
        return Response(str(response), mimetype="text/xml")
    _get_or_create_call(call_sid, request.form.get("Direction", "inbound"), request.form.get("From"), request.form.get("To"))
    response.say("This call is handled by an automated assistant and may be transcribed for service quality.", voice="Polly.Joanna")
    connect = Connect()
    stream = connect.stream(
        url=_stream_url(),
        status_callback=f"{_public_base_url()}/api/voice/stream-status",
        status_callback_method="POST",
    )
    stream.parameter(name="call_sid", value=call_sid)
    stream.parameter(name="stream_token", value=_stream_token(call_sid))
    response.append(connect)
    return Response(str(response), mimetype="text/xml")


@api_voice_agent.post("/voice/call-status")
def call_status():
    if not _verify_twilio_webhook():
        return jsonify({"error": "Invalid Twilio signature"}), 403
    call_sid = request.form.get("CallSid")
    if not call_sid:
        return jsonify({"error": "Missing CallSid"}), 400
    call = _get_or_create_call(call_sid, request.form.get("Direction", "inbound"), request.form.get("From"), request.form.get("To"))
    call.status = request.form.get("CallStatus", call.status)
    duration = request.form.get("CallDuration")
    if duration and duration.isdigit():
        call.duration_seconds = int(duration)
    if call.status in ("completed", "busy", "failed", "no-answer", "canceled"):
        call.ended_at = datetime.utcnow()
    db.session.commit()
    return ("", 204)


@api_voice_agent.post("/voice/stream-status")
def stream_status():
    if not _verify_twilio_webhook():
        return jsonify({"error": "Invalid Twilio signature"}), 403
    if request.form.get("StreamEvent") == "stream-error":
        call = VoiceCall.query.filter_by(twilio_call_sid=request.form.get("CallSid")).first()
        if call:
            call.status = "failed"
            call.error_message = request.form.get("StreamError", "Twilio media stream error")
            db.session.commit()
    return ("", 204)


def init_voice_socket(sock):
    @sock.route("/api/voice/twilio-stream")
    def twilio_stream(twilio_ws):
        from flask import current_app
        app = current_app._get_current_object()
        asyncio.run(_bridge_twilio_to_deepgram(twilio_ws, app))


async def _bridge_twilio_to_deepgram(twilio_ws, app):
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        twilio_ws.close()
        return

    audio_queue = asyncio.Queue()
    stream_sid = {"value": None}
    call_sid = {"value": None}
    authenticated = {"value": False}
    bridge_error = {"value": None}

    try:
        async with websockets.connect(
            "wss://agent.deepgram.com/v1/agent/converse",
            subprotocols=["token", api_key],
            ping_interval=20,
            ping_timeout=20,
        ) as deepgram_ws:
            welcome = json.loads(await asyncio.wait_for(deepgram_ws.recv(), timeout=10))
            if welcome.get("type") != "Welcome":
                raise RuntimeError("Deepgram did not acknowledge the voice session")
            settings = {
                "type": "Settings",
                "tags": ["insight-pest", "inbound"],
                "audio": {
                    "input": {"encoding": "mulaw", "sample_rate": 8000},
                    "output": {"encoding": "mulaw", "sample_rate": 8000, "container": "none"},
                },
                "agent": {
                    "listen": {"provider": {"type": "deepgram", "model": "flux-general-en", "version": "v2"}},
                    "think": {
                        "provider": {"type": "open_ai", "model": os.getenv("VOICE_LLM_MODEL", "gpt-4o-mini"), "temperature": 0.2},
                        "prompt": INSIGHT_PROMPT,
                        "functions": [CAPTURE_SERVICE_REQUEST_FUNCTION, BOOK_APPOINTMENT_FUNCTION],
                    },
                    "speak": {"provider": {"type": "deepgram", "model": os.getenv("VOICE_MODEL", "aura-2-thalia-en")}},
                    "greeting": "Thank you for calling Insight Pest Solutions Canada. I'm Avery, the automated assistant. Please tell me what is happening and how I can help.",
                },
            }
            await deepgram_ws.send(json.dumps(settings))
            settings_applied = json.loads(await asyncio.wait_for(deepgram_ws.recv(), timeout=10))
            if settings_applied.get("type") != "SettingsApplied":
                raise RuntimeError(settings_applied.get("description") or "Deepgram did not apply the voice settings")

            async def receive_twilio():
                buffer = bytearray()
                while True:
                    message = await asyncio.to_thread(twilio_ws.receive)
                    if message is None:
                        break
                    event = json.loads(message)
                    event_type = event.get("event")
                    if event_type == "start":
                        start = event.get("start", {})
                        custom = start.get("customParameters", {})
                        current_call_sid = start.get("callSid") or custom.get("call_sid")
                        if not current_call_sid or not hmac.compare_digest(custom.get("stream_token", ""), _stream_token(current_call_sid)):
                            raise PermissionError("Invalid Twilio media stream token")
                        stream_sid["value"] = start.get("streamSid")
                        call_sid["value"] = current_call_sid
                        authenticated["value"] = True
                        with app.app_context():
                            call = _get_or_create_call(current_call_sid)
                            call.status = "in_progress"
                            db.session.commit()
                    elif event_type == "media" and authenticated["value"] and event.get("media", {}).get("track", "inbound") == "inbound":
                        buffer.extend(base64.b64decode(event["media"]["payload"]))
                        while len(buffer) >= 3200:
                            await audio_queue.put(bytes(buffer[:3200]))
                            del buffer[:3200]
                    elif event_type == "stop":
                        break

            async def send_to_deepgram():
                while True:
                    await deepgram_ws.send(await audio_queue.get())

            async def receive_deepgram():
                async for message in deepgram_ws:
                    if isinstance(message, bytes):
                        if stream_sid["value"] and authenticated["value"]:
                            outbound = {"event": "media", "streamSid": stream_sid["value"], "media": {"payload": base64.b64encode(message).decode("ascii")}}
                            await asyncio.to_thread(twilio_ws.send, json.dumps(outbound))
                        continue
                    event = json.loads(message)
                    event_type = event.get("type")
                    if event_type == "UserStartedSpeaking" and stream_sid["value"]:
                        await asyncio.to_thread(twilio_ws.send, json.dumps({"event": "clear", "streamSid": stream_sid["value"]}))
                    elif event_type == "ConversationText":
                        with app.app_context():
                            _append_transcript(call_sid["value"], event.get("role", "unknown"), event.get("content"))
                    elif event_type == "FunctionCallRequest":
                        for function_call in event.get("functions", []):
                            function_id = function_call.get("id")
                            name = function_call.get("name")
                            try:
                                arguments = function_call.get("arguments", {})
                                if isinstance(arguments, str):
                                    arguments = json.loads(arguments)
                                with app.app_context():
                                    if name == "capture_service_request":
                                        result = _capture_service_request(arguments, call_sid["value"])
                                    elif name == "book_appointment":
                                        result = _book_appointment(arguments, call_sid["value"])
                                    else:
                                        raise ValueError("Unknown function request")
                                content = json.dumps({"success": True, **result})
                            except Exception as error:
                                with app.app_context():
                                    db.session.rollback()
                                content = json.dumps({"success": False, "error": str(error)})
                            response = {"type": "FunctionCallResponse", "id": function_id, "name": name, "content": content}
                            if function_call.get("thought_signature"):
                                response["thought_signature"] = function_call["thought_signature"]
                            await deepgram_ws.send(json.dumps(response))
                    elif event_type == "Error":
                        raise RuntimeError(event.get("description") or "Deepgram voice agent error")

            tasks = [asyncio.create_task(receive_twilio()), asyncio.create_task(send_to_deepgram()), asyncio.create_task(receive_deepgram())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
    except Exception as error:
        bridge_error["value"] = error
    finally:
        with app.app_context():
            try:
                _finalize_call(call_sid["value"], bridge_error["value"])
            except (IntegrityError, Exception):
                db.session.rollback()
        try:
            twilio_ws.close()
        except Exception:
            pass
