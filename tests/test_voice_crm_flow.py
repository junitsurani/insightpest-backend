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
from app.routes.routes_VoiceAgent import _book_appointment, _capture_service_request, _get_or_create_call, api_voice_agent


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
