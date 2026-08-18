import os
import asyncio
import base64
import json
import threading
import unittest
from unittest.mock import patch
from datetime import date, timedelta
import hashlib
import jwt
from datetime import datetime

from flask import Flask

os.environ.update({
    "TWILIO_VALIDATE_SIGNATURES": "false",
    "TWILIO_ACCOUNT_SID": "AC_test",
    "TWILIO_AUTH_TOKEN": "test-token",
    "TWILIO_PHONE_NUMBER": "+14165550100",
    "DEEPGRAM_API_KEY": "test-key",
    "PUBLIC_BASE_URL": "https://crm.example.test",
    "CRM_AUTH_DISABLED": "true",
})

from app.models import db
from app.models.user import CRMCustomer, ServiceAppointment, ServiceWorkOrder, VoiceCall
from app.routes.routes_VoiceAgent import (
    BOOK_APPOINTMENT_FUNCTION,
    CAPTURE_SERVICE_REQUEST_FUNCTION,
    BookingValidationError,
    INSIGHT_PROMPT,
    _arguments_with_call_phone,
    _append_transcript,
    _book_appointment,
    _bridge_twilio_to_deepgram,
    _parse_booking_date,
    _preferred_time_from_arguments,
    _capture_service_request,
    _finalize_call,
    _get_or_create_call,
    _normalize_postal_code,
    _normalize_service_address,
    _record_tool_failure,
    _summary_time_phrase,
    _stream_token,
    _tool_error_response,
    _voice_agent_prompt,
    _voice_agent_settings,
    api_voice_agent,
)


class VoiceCRMFlowTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(self.app)
        self.app.register_blueprint(api_voice_agent)
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_quote_and_booking_populate_crm(self):
        with self.app.app_context():
            _get_or_create_call("CA_quote", "inbound", "+14165550111", "+14165550100")
            lead = _capture_service_request({
                "customer_name": "Taylor Green",
                "phone": "416-555-0111",
                "service_address": "18 King Street West",
                "postal_code": "M5V 2T6",
                "pest_issue": "Ants in kitchen",
                "city": "Toronto",
                "province": "ON",
            }, "CA_quote")
            self.assertEqual(lead["lead"]["status"], "lead")

            _get_or_create_call("CA_book", "inbound", "+19055550122", "+14165550100")
            booking = _book_appointment({
                "customer_name": "Jordan Lee",
                "phone": "+1 905 555 0122",
                "service_address": "25 Brant Street",
                "postal_code": "L7M 2R4",
                "pest_issue": "Rodents in attic",
                "city": "Burlington",
                "province": "ON",
                "preferred_date": (date.today() + timedelta(days=2)).isoformat(),
                "preferred_time": "9:00 AM–11:00 AM",
                "caller_confirmation": "Yes, that is correct",
            }, "CA_book")

            self.assertEqual(booking["appointment"]["status"], "requested")
            self.assertEqual(booking["work_order"]["source"], "voice_agent")
            self.assertEqual(lead["lead"]["service_address"], "18 King Street West")
            self.assertIn("25 Brant Street", booking["work_order"]["location"])
            self.assertEqual(CRMCustomer.query.count(), 2)
            self.assertEqual(ServiceAppointment.query.count(), 1)
            self.assertEqual(ServiceWorkOrder.query.count(), 1)
            self.assertIsNotNone(VoiceCall.query.filter_by(twilio_call_sid="CA_book").one().work_order_id)

    def test_booking_is_idempotent_for_one_twilio_call(self):
        payload = {
            "customer_name": "Sam Carter",
            "phone": "+1 647 555 0198",
            "service_address": "90 Queen Street East",
            "postal_code": "M4B 1B3",
            "pest_issue": "Wasps near the front entry",
            "preferred_date": (date.today() + timedelta(days=3)).isoformat(),
            "preferred_time": "1:00 PM–3:00 PM",
            "caller_confirmation": "Please book it",
        }
        with self.app.app_context():
            _get_or_create_call("CA_once", "inbound", payload["phone"], "+14165550100")
            first = _book_appointment(payload, "CA_once")
            second = _book_appointment(payload, "CA_once")

            self.assertEqual(first["appointment"]["id"], second["appointment"]["id"])
            self.assertEqual(ServiceAppointment.query.count(), 1)
            self.assertEqual(ServiceWorkOrder.query.count(), 1)

    def test_booking_requires_the_actual_caller_confirmation_turn(self):
        payload = {
            "customer_name": "Morgan",
            "service_address": "44 Danforth Avenue",
            "postal_code": "M4B 1B3",
            "pest_issue": "Mice in the basement",
            "preferred_date": (date.today() + timedelta(days=3)).isoformat(),
            "preferred_date_phrase": "this Thursday",
            "preferred_time": "5 PM",
            "preferred_time_phrase": "at five PM",
            "caller_confirmation": "Yes, that is correct",
        }
        with self.app.app_context():
            _get_or_create_call("CA_confirm", "inbound", "+16475550198", "+14165550100")
            _append_transcript("CA_confirm", "user", "Tomorrow at five would be good")

            with self.assertRaises(BookingValidationError) as raised:
                _book_appointment(payload, "CA_confirm")
            self.assertEqual(raised.exception.code, "confirmation_required")
            self.assertEqual(ServiceAppointment.query.count(), 0)

            _append_transcript("CA_confirm", "assistant", "To confirm, Thursday at five PM, is that correct?")
            _append_transcript("CA_confirm", "user", "Yes, but actually make it Wednesday")
            with self.assertRaises(BookingValidationError) as corrected:
                _book_appointment(payload, "CA_confirm")
            self.assertEqual(corrected.exception.code, "confirmation_required")
            self.assertEqual(ServiceAppointment.query.count(), 0)

            _append_transcript(
                "CA_confirm",
                "assistant",
                "To confirm, mice service on Thursday at five PM, is that correct?",
            )
            _append_transcript("CA_confirm", "user", "Yes, that's correct")
            booking = _book_appointment(payload, "CA_confirm")

            self.assertEqual(booking["appointment"]["status"], "requested")
            self.assertEqual(ServiceAppointment.query.count(), 1)

    def test_relative_dates_are_grounded_and_invalid_dates_are_rejected(self):
        today = date(2026, 8, 14)  # Friday

        self.assertEqual(_parse_booking_date("tomorrow", today), date(2026, 8, 15))
        self.assertEqual(_parse_booking_date("tomorrow morning at nine AM", today), date(2026, 8, 15))
        self.assertEqual(_parse_booking_date("next Monday", today), date(2026, 8, 17))
        self.assertEqual(_parse_booking_date("Monday next week", date(2026, 8, 17)), date(2026, 8, 24))
        self.assertEqual(_parse_booking_date("next week Monday", date(2026, 8, 17)), date(2026, 8, 24))
        self.assertEqual(_parse_booking_date("Monday next week at five", date(2026, 8, 17)), date(2026, 8, 24))
        self.assertEqual(_parse_booking_date("2026-08-20", today), date(2026, 8, 20))

        for value, code in (("next week", "ambiguous_relative_date"), ("last week", "past_date"), ("2026-08-13", "past_date")):
            with self.subTest(value=value), self.assertRaises(BookingValidationError) as raised:
                _parse_booking_date(value, today)
            self.assertEqual(raised.exception.code, code)

    def test_prompt_is_spoken_only_and_contains_a_live_calendar(self):
        prompt = _voice_agent_prompt(date(2026, 8, 14))
        compact_prompt = " ".join(prompt.split())
        settings = _voice_agent_settings()
        listener = settings["agent"]["listen"]["provider"]

        self.assertIn("Today is Friday, August 14, 2026", prompt)
        self.assertIn("Monday, August 17, 2026 = 2026-08-17", prompt)
        self.assertIn("Never use Markdown", prompt)
        self.assertIn("CRITICAL SPOKEN-OUTPUT CONTRACT", prompt)
        self.assertIn("rewrite any list into one flowing sentence", compact_prompt)
        self.assertIn('For a range, say "on Tuesday, August 18 from one to three PM."', prompt)
        self.assertIn('Never place "at" before "from" or "in."', prompt)
        self.assertIn("Accept the name exactly as the caller provides it", prompt)
        self.assertIn("Ask one concise question at a time", prompt)
        self.assertIn("Do not start every turn with \"thank you,\"", prompt)
        self.assertIn("Never ask the same question twice using the same wording", prompt)
        self.assertIn("Do not treat a nonsensical or low-context transcript as a confirmed fact", prompt)
        self.assertIn("close warmly in one sentence", prompt)
        self.assertIn("never recite the list of other pests", prompt)
        self.assertIn("When both the appointment day and time are missing", prompt)
        self.assertIn("service address, including the city and postal code", prompt)
        self.assertIn("free, no-obligation quote", prompt)
        self.assertIn("should not move large furniture", prompt)
        self.assertIn("technician's specific preparation and re-entry instructions", compact_prompt)
        self.assertIn("during an active quote or booking", prompt)
        self.assertIn("a pricing question does not change the intent to a quote", prompt)
        self.assertIn('never "in the morning at nine AM."', prompt)
        self.assertIn("Never ask the caller to repeat that number", prompt)
        self.assertIn("preferred_date_phrase", prompt)
        self.assertIn("always say the resolved weekday, month, and day", prompt)
        self.assertIn("Use natural time prepositions", prompt)
        self.assertIn('Never say "at morning"', prompt)
        self.assertIn("never spend a separate turn requesting an optional field", compact_prompt)
        self.assertIn("read them back once", prompt)
        self.assertEqual(listener["eot_threshold"], 0.8)
        self.assertEqual(listener["eot_timeout_ms"], 6000)
        self.assertIn("cockroaches", listener["keyterms"])
        self.assertIn("postal code", listener["keyterms"])
        self.assertEqual(settings["agent"]["think"]["provider"]["model"], "gpt-4.1-mini")
        self.assertEqual(settings["agent"]["think"]["provider"]["temperature"], 0.0)

    def test_booking_validation_failure_is_visible_and_success_clears_it(self):
        payload = {
            "customer_name": "Casey Morgan",
            "phone": "+1 416 555 0188",
            "service_address": "10 Victoria Park Avenue",
            "postal_code": "M4B 1B3",
            "pest_issue": "Mice in basement",
            "preferred_date": (date.today() + timedelta(days=4)).isoformat(),
            "preferred_time": "1 PM to 3 PM",
            "caller_confirmation": "Correct",
        }
        with self.app.app_context():
            _get_or_create_call("CA_retry", "inbound", payload["phone"], "+14165550100")
            error = BookingValidationError(
                "A weekday is required for a request for next week",
                "ambiguous_relative_date",
                "Ask which weekday works best.",
            )
            _record_tool_failure("CA_retry", "book_appointment", error)
            failure = VoiceCall.query.filter_by(twilio_call_sid="CA_retry").one()
            response = _tool_error_response("book_appointment", error)

            self.assertEqual(failure.intent, "booking")
            self.assertEqual(failure.resolution, "booking_failed")
            self.assertEqual(response["error_code"], "ambiguous_relative_date")
            self.assertIn("upcoming_calendar", response)

            booking = _book_appointment(payload, "CA_retry")
            recovered = VoiceCall.query.filter_by(twilio_call_sid="CA_retry").one()
            self.assertEqual(booking["appointment"]["status"], "requested")
            self.assertEqual(recovered.resolution, "appointment_requested")
            self.assertIsNone(recovered.error_message)

    def test_faq_conversation_is_recorded_as_answered(self):
        with self.app.app_context():
            _get_or_create_call("CA_faq", "inbound", "+14165550177", "+14165550100")
            _append_transcript("CA_faq", "user", "Do you treat ants and spiders?")
            _append_transcript("CA_faq", "assistant", "Yes, Insight treats ants, spiders, and other common household pests.")
            _finalize_call("CA_faq")

            call = VoiceCall.query.filter_by(twilio_call_sid="CA_faq").one()
            self.assertEqual(call.intent, "faq")
            self.assertEqual(call.resolution, "answered")
            self.assertIsNotNone(call.duration_seconds)
            self.assertIn("ants", INSIGHT_PROMPT.lower())
            self.assertNotIn("client_side", BOOK_APPOINTMENT_FUNCTION)
            self.assertEqual(
                set(BOOK_APPOINTMENT_FUNCTION["parameters"]["required"]),
                {"customer_name", "service_address", "postal_code", "pest_issue", "preferred_date", "preferred_date_phrase", "preferred_time", "preferred_time_phrase", "caller_confirmation"},
            )
            self.assertEqual(
                set(CAPTURE_SERVICE_REQUEST_FUNCTION["parameters"]["required"]),
                {"customer_name", "service_address", "postal_code", "pest_issue"},
            )

    def test_twilio_caller_number_is_used_without_asking_for_it(self):
        with self.app.app_context(), patch("app.routes.routes_VoiceAgent._local_today", return_value=date(2026, 8, 17)):
            call = _get_or_create_call("CA_caller_id", "inbound", "+13474417085", "+12362057547")
            enriched = _arguments_with_call_phone({"customer_name": "Eric"}, call.twilio_call_sid)
            self.assertEqual(enriched["phone"], "+13474417085")

            booking = _book_appointment({
                "customer_name": "Eric",
                "service_address": "77 Front Street East",
                "postal_code": "M5A 2J1",
                "pest_issue": "Rat issue",
                "preferred_date": "2026-08-17",
                "preferred_date_phrase": "Monday next week",
                "preferred_time": "5 PM",
                "preferred_time_phrase": "at five PM",
                "caller_confirmation": "Yes, that is correct",
            }, call.twilio_call_sid)

            self.assertEqual(booking["customer"]["phone"], "+13474417085")
            self.assertEqual(booking["appointment"]["preferred_date"], "2026-08-24")

        settings = _voice_agent_settings("+13474417085")
        prompt = settings["agent"]["think"]["prompt"]
        self.assertIn("Twilio verified the customer's callback number as +13474417085", prompt)
        self.assertIn("Never ask the caller for a phone number", prompt)
        self.assertNotIn("phone", CAPTURE_SERVICE_REQUEST_FUNCTION["parameters"]["required"])

    def test_canadian_postal_codes_are_normalized_and_invalid_transcripts_are_rejected(self):
        self.assertEqual(_normalize_postal_code("l4y2g9"), "L4Y 2G9")
        self.assertEqual(_normalize_postal_code("M5A 2J1"), "M5A 2J1")

        for invalid in ("M5B 231", "four y t g nine", "12345", ""):
            with self.subTest(invalid=invalid), self.assertRaises(BookingValidationError) as raised:
                _normalize_postal_code(invalid)
            self.assertEqual(raised.exception.code, "invalid_postal_code")
            response = _tool_error_response("book_appointment", raised.exception)
            self.assertNotIn("upcoming_calendar", response)

    def test_voice_service_address_is_required_and_normalized(self):
        self.assertEqual(_normalize_service_address("  123   Main Street  "), "123 Main Street")

        for invalid in ("", "Main Street", "12345", "12"):
            with self.subTest(invalid=invalid), self.assertRaises(BookingValidationError) as raised:
                _normalize_service_address(invalid)
            self.assertEqual(raised.exception.code, "invalid_service_address")

    def test_crm_summary_uses_natural_time_prepositions(self):
        self.assertEqual(_summary_time_phrase("in the afternoon"), "in the afternoon")
        self.assertEqual(_summary_time_phrase("afternoon"), "in the afternoon")
        self.assertEqual(_summary_time_phrase("1 PM to 3 PM"), "from 1 PM to 3 PM")
        self.assertEqual(_summary_time_phrase("3 PM"), "at 3 PM")
        self.assertEqual(
            _preferred_time_from_arguments({"preferred_time": "morning", "preferred_time_phrase": "morning at nine AM"}),
            "nine AM",
        )
        self.assertEqual(
            _preferred_time_from_arguments({"preferred_time": "morning", "preferred_time_phrase": "morning at 9 a.m."}),
            "9 AM",
        )

    def test_inbound_twiml_and_crm_endpoints(self):
        client = self.app.test_client()
        response = client.post("/api/voice/incoming", data={
            "CallSid": "CA_inbound",
            "Direction": "inbound",
            "From": "+16475550133",
            "To": "+14165550100",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"wss://crm.example.test/api/voice/twilio-stream", response.data)
        self.assertIn(b"stream_token", response.data)
        self.assertIn(b"caller_phone", response.data)

        for path in (
            "/api/crm/overview",
            "/api/crm/customers",
            "/api/crm/work-orders",
            "/api/voice/appointments",
            "/api/voice/calls",
            "/api/voice/status",
        ):
            self.assertEqual(client.get(path).status_code, 200)

        status = client.get("/api/voice/status").get_json()
        self.assertEqual(status["llm_model"], "gpt-4.1-mini")
        self.assertEqual(status["timezone"], "America/Toronto")

    def test_twilio_start_context_is_applied_before_deepgram_greeting(self):
        call_sid = "CA_bridge_context"
        with self.app.app_context():
            _get_or_create_call(call_sid, "inbound", "+13474417085", "+12362057547")

        class FakeTwilioSocket:
            def __init__(self):
                self.messages = [
                    json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}),
                    json.dumps({
                        "event": "start",
                        "start": {
                            "streamSid": "MZ_bridge",
                            "callSid": call_sid,
                            "customParameters": {
                                "call_sid": call_sid,
                                "stream_token": _stream_token(call_sid),
                                "caller_phone": "+13474417085",
                            },
                        },
                    }),
                    json.dumps({"event": "stop", "stop": {"callSid": call_sid}}),
                ]

            def receive(self):
                return self.messages.pop(0) if self.messages else None

            def send(self, _message):
                return None

            def close(self):
                return None

        class FakeDeepgramSocket:
            def __init__(self):
                self.received = [json.dumps({"type": "Welcome"}), json.dumps({"type": "SettingsApplied"})]
                self.sent = []

            async def recv(self):
                return self.received.pop(0)

            async def send(self, message):
                self.sent.append(message)

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Future()

        class FakeConnection:
            def __init__(self, socket):
                self.socket = socket

            async def __aenter__(self):
                return self.socket

            async def __aexit__(self, *_args):
                return False

        deepgram = FakeDeepgramSocket()
        with patch("app.routes.routes_VoiceAgent.websockets.connect", return_value=FakeConnection(deepgram)):
            asyncio.run(_bridge_twilio_to_deepgram(FakeTwilioSocket(), self.app))

        settings = json.loads(deepgram.sent[0])
        self.assertEqual(settings["type"], "Settings")
        self.assertIn("Twilio verified the customer's callback number as +13474417085", settings["agent"]["think"]["prompt"])
        self.assertIn("roaches", settings["agent"]["listen"]["provider"]["keyterms"])

    def test_barge_in_immediately_clears_playback_and_drops_stale_audio(self):
        call_sid = "CA_barge_in"
        deepgram_finished = threading.Event()
        with self.app.app_context():
            _get_or_create_call(call_sid, "inbound", "+13474417085", "+12362057547")

        class FakeTwilioSocket:
            def __init__(self):
                self.messages = [
                    json.dumps({"event": "connected"}),
                    json.dumps({
                        "event": "start",
                        "start": {
                            "streamSid": "MZ_barge",
                            "callSid": call_sid,
                            "customParameters": {
                                "call_sid": call_sid,
                                "stream_token": _stream_token(call_sid),
                                "caller_phone": "+13474417085",
                            },
                        },
                    }),
                ]
                self.sent = []

            def receive(self):
                if self.messages:
                    return self.messages.pop(0)
                deepgram_finished.wait(timeout=2)
                return json.dumps({"event": "stop"})

            def send(self, message):
                self.sent.append(json.loads(message))

            def close(self):
                return None

        class FakeDeepgramSocket:
            def __init__(self):
                self.received = [json.dumps({"type": "Welcome"}), json.dumps({"type": "SettingsApplied"})]
                self.events = [
                    b"before interruption",
                    json.dumps({"type": "UserStartedSpeaking"}),
                    b"stale interrupted audio",
                    json.dumps({"type": "ConversationText", "role": "assistant", "content": "What day works best?"}),
                    b"new response audio",
                ]
                self.sent = []

            async def recv(self):
                return self.received.pop(0)

            async def send(self, message):
                self.sent.append(message)

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.events:
                    return self.events.pop(0)
                deepgram_finished.set()
                raise StopAsyncIteration

        class FakeConnection:
            def __init__(self, socket):
                self.socket = socket

            async def __aenter__(self):
                return self.socket

            async def __aexit__(self, *_args):
                return False

        twilio = FakeTwilioSocket()
        deepgram = FakeDeepgramSocket()
        with patch.dict(os.environ, {"VOICE_BARGE_IN_DELAY_MS": "0"}), patch(
            "app.routes.routes_VoiceAgent.websockets.connect",
            return_value=FakeConnection(deepgram),
        ):
            asyncio.run(_bridge_twilio_to_deepgram(twilio, self.app))

        events = [message["event"] for message in twilio.sent]
        media_payloads = [
            base64.b64decode(message["media"]["payload"])
            for message in twilio.sent
            if message["event"] == "media"
        ]
        self.assertEqual(events, ["media", "clear", "media"])
        self.assertEqual(media_payloads, [b"before interruption", b"new response audio"])

    def test_crm_requires_a_valid_signed_session(self):
        client = self.app.test_client()
        with patch.dict(os.environ, {"CRM_AUTH_DISABLED": "false", "SECRET_KEY": "test-secret"}):
            self.assertEqual(client.get("/api/crm/overview").status_code, 401)
            signing_key = hashlib.sha256(b"test-secret").digest()
            token = jwt.encode({"sub": "operator", "exp": datetime.utcnow() + timedelta(minutes=5)}, signing_key, algorithm="HS256")
            response = client.get("/api/crm/overview", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
