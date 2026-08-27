import io
import unittest

from flask import Flask
from werkzeug.security import generate_password_hash

from app.models import db
from app.taxgpt import initialize_taxgpt_schema, register_taxgpt
from app.taxgpt.models import TaxGptDemoRequest, TaxGptRateEvent


class TaxGptApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="taxgpt-test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TAXGPT_DUMMY_PASSWORD_HASH=generate_password_hash("not-a-real-password"),
            TAXGPT_MAX_FILE_BYTES=10 * 1024 * 1024,
            TAXGPT_SESSION_HOURS=12,
            TAXGPT_REMEMBER_DAYS=7,
            TAXGPT_AUTH_RATE_LIMIT=10,
            TAXGPT_DEMO_RATE_LIMIT=5,
            TAXGPT_TRUST_PROXY_HEADERS=False,
            TAXGPT_TRUSTED_ORIGINS=("https://tax.example",),
        )
        db.init_app(self.app)
        register_taxgpt(self.app)
        with self.app.app_context():
            initialize_taxgpt_schema()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def signup(self, email="alex@example.com"):
        return self.client.post("/api/taxgpt/auth/signup", json={"email": email, "password": "Secure123", "displayName": "Alex Morgan", "workspaceName": "Northstar CPAs", "country": "US", "remember": True})

    def test_health_is_public_and_hardened(self):
        response = self.client.get("/api/taxgpt/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["service"], "taxgpt")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Permissions-Policy"], "camera=(), microphone=(), geolocation=()")

    def test_schema_is_strictly_namespaced(self):
        with self.app.app_context():
            taxgpt_tables = {
                table.name for table in db.metadata.sorted_tables if table.name.startswith("taxgpt_")
            }
            self.assertEqual(len(taxgpt_tables), 14)
            self.assertTrue(all(name.startswith("taxgpt_") for name in taxgpt_tables))

    def test_signup_session_logout_and_duplicate_protection(self):
        response = self.signup()
        self.assertEqual(response.status_code, 201)
        self.assertIn("taxgpt_session=", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])
        self.assertEqual(self.client.get("/api/taxgpt/auth/session").status_code, 200)
        settings = self.client.post("/api/taxgpt/settings", json={"displayName": "Alexandra Morgan", "workspaceName": "Northstar Tax", "country": "CA"})
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(settings.json["workspace"]["country"], "CA")
        self.assertEqual(self.client.get("/api/taxgpt/bootstrap").json["user"]["displayName"], "Alexandra Morgan")
        self.assertEqual(self.client.post("/api/taxgpt/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/taxgpt/bootstrap").status_code, 401)
        duplicate_client = self.app.test_client()
        duplicate = duplicate_client.post("/api/taxgpt/auth/signup", json={"email": "alex@example.com", "password": "Secure123", "displayName": "Other User", "workspaceName": "Other Firm", "country": "US"})
        self.assertEqual(duplicate.status_code, 409)

    def test_weak_password_and_unknown_fields_are_rejected(self):
        weak = self.client.post("/api/taxgpt/auth/signup", json={"email": "weak@example.com", "password": "password", "displayName": "Weak User", "workspaceName": "Weak Firm"})
        self.assertEqual(weak.status_code, 400)
        unknown = self.client.post("/api/taxgpt/auth/signup", json={"email": "weak@example.com", "password": "Secure123", "displayName": "Weak User", "workspaceName": "Weak Firm", "isAdmin": True})
        self.assertEqual(unknown.status_code, 400)

    def test_demo_request_requires_and_persists_the_complete_original_form(self):
        missing_employees = self.client.post("/api/taxgpt/demo", json={"name": "Amanda Johnson", "email": "amanda@example.com", "persona": "pro", "sourcePath": "/demo"})
        self.assertEqual(missing_employees.status_code, 400)
        response = self.client.post("/api/taxgpt/demo", json={"name": "Amanda Johnson", "email": "amanda@example.com", "persona": "pro", "employees": "50", "sourcePath": "/demo", "website": ""})
        self.assertEqual(response.status_code, 201)
        with self.app.app_context():
            request_row = TaxGptDemoRequest.query.one()
            self.assertEqual(request_row.employees, "50")
            self.assertEqual(request_row.status, "new")
            self.assertEqual(len(request_row.request_fingerprint), 64)
            self.assertNotIn("127.0.0.1", request_row.request_fingerprint)

    def test_demo_request_rejects_unknown_fields_and_honeypot_is_not_persisted(self):
        unknown = self.client.post("/api/taxgpt/demo", json={"name": "Amanda Johnson", "email": "amanda@example.com", "persona": "pro", "employees": "10", "admin": True})
        self.assertEqual(unknown.status_code, 400)
        bot = self.client.post("/api/taxgpt/demo", json={"name": "Amanda Johnson", "email": "amanda@example.com", "persona": "pro", "employees": "10", "website": "spam.invalid"})
        self.assertEqual(bot.status_code, 201)
        with self.app.app_context():
            self.assertEqual(TaxGptDemoRequest.query.count(), 0)

    def test_rate_limits_are_persisted_and_shared(self):
        self.app.config["TAXGPT_DEMO_RATE_LIMIT"] = 2
        payload = {"name": "Amanda Johnson", "email": "amanda@example.com", "persona": "pro", "employees": "10", "website": ""}
        self.assertEqual(self.client.post("/api/taxgpt/demo", json=payload).status_code, 201)
        self.assertEqual(self.client.post("/api/taxgpt/demo", json=payload).status_code, 201)
        self.assertEqual(self.app.test_client().post("/api/taxgpt/demo", json=payload).status_code, 429)
        with self.app.app_context():
            self.assertEqual(TaxGptRateEvent.query.filter_by(scope="demo").count(), 2)

    def test_oversized_json_is_rejected_before_route_processing(self):
        response = self.client.post("/api/taxgpt/demo", data=b"x" * (64 * 1024 + 1), content_type="application/json")
        self.assertEqual(response.status_code, 413)

    def test_untrusted_browser_origin_is_rejected_before_mutation(self):
        response = self.client.post(
            "/api/taxgpt/demo",
            json={"name": "Amanda Johnson", "email": "amanda@example.com", "persona": "pro", "employees": "10"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertEqual(TaxGptDemoRequest.query.count(), 0)

    def test_research_persists_conversation_and_primary_citations(self):
        self.signup()
        response = self.client.post("/api/taxgpt/research", json={"question": "What should I consider for an S corporation election?", "jurisdiction": "United States"})
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json["message"]["citations"]), 3)
        conversation_id = response.json["conversation"]["id"]
        detail = self.client.get(f"/api/taxgpt/conversations/{conversation_id}")
        self.assertEqual(len(detail.json["conversation"]["messages"]), 2)

    def test_client_document_writer_matrix_and_review_flow(self):
        self.signup()
        client_response = self.client.post("/api/taxgpt/clients", json={"name": "Acme Holdings LLC", "entityType": "llc", "jurisdiction": "Delaware", "taxYear": 2026, "notes": "Multi-state software company"})
        self.assertEqual(client_response.status_code, 201)
        client_id = client_response.json["client"]["id"]
        upload = self.client.post("/api/taxgpt/documents", data={"clientId": client_id, "file": (io.BytesIO(b"Trial balance\nRevenue,100000\nExpenses,65000"), "trial-balance.csv", "text/csv")}, content_type="multipart/form-data")
        self.assertEqual(upload.status_code, 201)
        document_id = upload.json["document"]["id"]
        research = self.client.post("/api/taxgpt/research", json={"question": "Analyze the uploaded trial balance for the client", "clientId": client_id, "documentIds": [document_id]})
        self.assertEqual(research.status_code, 200)
        self.assertIn("Revenue: $100,000.00", research.json["message"]["content"])
        draft = self.client.post("/api/taxgpt/writer", json={"prompt": "Draft a tax memo about the entity election", "draftType": "memo", "clientId": client_id, "documentIds": [document_id]})
        self.assertEqual(draft.status_code, 201)
        self.assertIn("Facts", draft.json["draft"]["content"])
        self.assertIn("Revenue: $100,000.00", draft.json["draft"]["content"])
        matrix = self.client.post("/api/taxgpt/matrix", json={"question": "When is a sales tax return required?", "jurisdictions": ["California", "Texas", "New York"]})
        self.assertEqual(matrix.status_code, 201)
        self.assertEqual(len(matrix.json["matrix"]["results"]), 3)
        review = self.client.post("/api/taxgpt/reviews", json={"documentId": document_id, "formType": "1120-S"})
        self.assertEqual(review.status_code, 201)
        self.assertEqual({finding["flag"] for finding in review.json["review"]["findings"]}, {"red", "green", "cleared"})
        finding_id = review.json["review"]["findings"][0]["id"]
        resolved = self.client.post(f"/api/taxgpt/reviews/{review.json['review']['id']}/findings/{finding_id}/resolve", json={})
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json["review"]["findings"][0]["status"], "reviewed")
        templates = self.client.get("/api/taxgpt/workflows/templates")
        self.assertGreaterEqual(len(templates.json["templates"]), 6)
        run = self.client.post("/api/taxgpt/workflows/runs", json={"templateKey": "1040-proconnect", "clientId": client_id, "documentIds": [document_id], "taxSoftware": "ProConnect", "folderPath": "Client/2026", "notes": "Prepare for partner review"})
        self.assertEqual(run.status_code, 201)
        self.assertEqual(run.json["run"]["status"], "review_required")
        self.assertEqual(run.json["run"]["result"]["documentsReviewed"], ["trial-balance.csv"])
        completed = self.client.post(f"/api/taxgpt/workflows/runs/{run.json['run']['id']}/complete", json={})
        self.assertEqual(completed.json["run"]["status"], "complete")

    def test_cross_workspace_access_is_denied(self):
        self.signup("first@example.com")
        created = self.client.post("/api/taxgpt/clients", json={"name": "Private Client", "entityType": "individual", "jurisdiction": "California", "taxYear": 2026, "notes": ""}).json["client"]
        other = self.app.test_client()
        other.post("/api/taxgpt/auth/signup", json={"email": "second@example.com", "password": "Secure123", "displayName": "Second User", "workspaceName": "Second Firm", "country": "US"})
        response = other.post("/api/taxgpt/research", json={"question": "Analyze this client", "clientId": created["id"]})
        self.assertEqual(response.status_code, 404)
        workflow = other.post("/api/taxgpt/workflows/runs", json={"templateKey": "tax-planning", "clientId": created["id"], "documentIds": [], "taxSoftware": "Not specified", "folderPath": "Not specified", "notes": "No additional instructions"})
        self.assertEqual(workflow.status_code, 404)

    def test_upload_validation_rejects_spoofed_pdf(self):
        self.signup()
        response = self.client.post("/api/taxgpt/documents", data={"file": (io.BytesIO(b"not a pdf"), "return.pdf", "application/pdf")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertIn("valid PDF", response.json["error"])


if __name__ == "__main__":
    unittest.main()
