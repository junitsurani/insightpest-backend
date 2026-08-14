import os
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
    BookingValidationError,
    INSIGHT_PROMPT,
    _append_transcript,
    _book_appointment,
    _parse_booking_date,
    _capture_service_request,
    _finalize_call,
    _get_or_create_call,
    _record_tool_failure,
    _summary_time_phrase,
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
                "postal_code": "L7M 2R4",
                "pest_issue": "Rodents in attic",
                "city": "Burlington",
                "province": "ON",
                "preferred_date": (date.today() + timedelta(days=2)).isoformat(),
                "preferred_time": "9:00 AM–11:00 AM",
            }, "CA_book")

            self.assertEqual(booking["appointment"]["status"], "requested")
            self.assertEqual(booking["work_order"]["source"], "voice_agent")
            self.assertEqual(CRMCustomer.query.count(), 2)
            self.assertEqual(ServiceAppointment.query.count(), 1)
            self.assertEqual(ServiceWorkOrder.query.count(), 1)
            self.assertIsNotNone(VoiceCall.query.filter_by(twilio_call_sid="CA_book").one().work_order_id)

    def test_booking_is_idempotent_for_one_twilio_call(self):
        payload = {
            "customer_name": "Sam Carter",
            "phone": "+1 647 555 0198",
            "postal_code": "M4B 1B3",
            "pest_issue": "Wasps near the front entry",
            "preferred_date": (date.today() + timedelta(days=3)).isoformat(),
            "preferred_time": "1:00 PM–3:00 PM",
        }
        with self.app.app_context():
            _get_or_create_call("CA_once", "inbound", payload["phone"], "+14165550100")
            first = _book_appointment(payload, "CA_once")
            second = _book_appointment(payload, "CA_once")

            self.assertEqual(first["appointment"]["id"], second["appointment"]["id"])
            self.assertEqual(ServiceAppointment.query.count(), 1)
            self.assertEqual(ServiceWorkOrder.query.count(), 1)

    def test_relative_dates_are_grounded_and_invalid_dates_are_rejected(self):
        today = date(2026, 8, 14)  # Friday

        self.assertEqual(_parse_booking_date("tomorrow", today), date(2026, 8, 15))
        self.assertEqual(_parse_booking_date("next Monday", today), date(2026, 8, 17))
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
        self.assertIn("Preserve the caller's complete full name exactly", prompt)
        self.assertIn("always say the resolved weekday, month, and day", prompt)
        self.assertIn("Use natural time prepositions", prompt)
        self.assertIn('Never say "at morning"', prompt)
        self.assertIn("never spend a separate turn requesting an optional field", compact_prompt)
        self.assertIn("read them back once", prompt)
        self.assertEqual(listener["eot_threshold"], 0.8)
        self.assertEqual(listener["eot_timeout_ms"], 6000)
        self.assertEqual(settings["agent"]["think"]["provider"]["model"], "gpt-4.1-mini")
        self.assertEqual(settings["agent"]["think"]["provider"]["temperature"], 0.0)

    def test_booking_validation_failure_is_visible_and_success_clears_it(self):
        payload = {
            "customer_name": "Casey Morgan",
            "phone": "+1 416 555 0188",
            "postal_code": "M4B 1B3",
            "pest_issue": "Mice in basement",
            "preferred_date": (date.today() + timedelta(days=4)).isoformat(),
            "preferred_time": "1 PM to 3 PM",
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
                {"customer_name", "phone", "postal_code", "pest_issue", "preferred_date", "preferred_time"},
            )

    def test_crm_summary_uses_natural_time_prepositions(self):
        self.assertEqual(_summary_time_phrase("in the afternoon"), "in the afternoon")
        self.assertEqual(_summary_time_phrase("afternoon"), "in the afternoon")
        self.assertEqual(_summary_time_phrase("1 PM to 3 PM"), "from 1 PM to 3 PM")
        self.assertEqual(_summary_time_phrase("3 PM"), "at 3 PM")

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
