import unittest

from flask import Flask
from werkzeug.security import generate_password_hash

from app.models import db
from app.openmart import initialize_openmart_schema, register_openmart


class OpenmartApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="openmart-test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            OPENMART_DUMMY_PASSWORD_HASH=generate_password_hash("not-a-real-password"),
            OPENMART_SESSION_HOURS=12,
            OPENMART_REMEMBER_DAYS=7,
            OPENMART_AUTH_RATE_LIMIT=10,
            OPENMART_TRUST_PROXY_HEADERS=False,
            OPENMART_TRUSTED_ORIGINS=("https://openmart.example",),
            OPENMART_MAX_BODY_BYTES=1024 * 1024,
            OPENMART_AUTO_CREATE_TABLES=True,
            OPENMART_SEED_ENABLED=True,
            OPENMART_SEED_EMAIL="demo@gmail.com",
            OPENMART_SEED_PASSWORD="openmartdemo",
            OPENMART_SEED_DISPLAY_NAME="Openmart Demo",
            OPENMART_SEED_WORKSPACE="Openmart Demo",
        )
        db.init_app(self.app)
        register_openmart(self.app)
        with self.app.app_context():
            initialize_openmart_schema()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def signup(self, email="alex@example.com"):
        return self.client.post("/api/openmart/auth/signup", json={
            "email": email, "password": "Secure123", "displayName": "Alex Morgan",
            "workspaceName": "Northstar Growth", "country": "US", "remember": True,
        })

    def test_seed_credentials_can_login(self):
        response = self.client.post("/api/openmart/auth/login", json={"email": "demo@gmail.com", "password": "openmartdemo", "remember": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["displayName"], "Openmart Demo")
        self.assertIn("openmart_session=", response.headers["Set-Cookie"])
        bootstrap = self.client.get("/api/openmart/bootstrap")
        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.json["stats"]["leadLists"], 3)
        self.assertEqual(bootstrap.json["stats"]["savedLeads"], 11)
        self.assertEqual(bootstrap.json["stats"]["enrichedLeads"], 6)
        self.assertEqual(bootstrap.json["stats"]["activeSequences"], 1)
        with self.app.app_context():
            initialize_openmart_schema()
        repeated = self.client.get("/api/openmart/bootstrap")
        self.assertEqual(repeated.json["stats"], bootstrap.json["stats"])

    def test_auth_health_and_namespaced_schema(self):
        health = self.client.get("/api/openmart/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json["service"], "openmart")
        self.assertEqual(health.headers["X-Content-Type-Options"], "nosniff")
        signup = self.signup()
        self.assertEqual(signup.status_code, 201)
        self.assertIn("openmart_session=", signup.headers["Set-Cookie"])
        self.assertIn("HttpOnly", signup.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", signup.headers["Set-Cookie"])
        self.assertEqual(self.client.get("/api/openmart/auth/session").status_code, 200)
        with self.app.app_context():
            tables = {table.name for table in db.metadata.sorted_tables if table.name.startswith("openmart_")}
            self.assertEqual(len(tables), 14)
            self.assertTrue(all(name.startswith("openmart_") for name in tables))

    def test_search_list_enrich_export_and_cross_tenant_security(self):
        self.signup()
        search = self.client.post("/api/openmart/search", json={"query": "Dentist", "location": "California", "filters": {"minimumRating": 4.5}, "limit": 20})
        self.assertEqual(search.status_code, 200)
        self.assertGreaterEqual(search.json["total"], 2)
        business_ids = [row["id"] for row in search.json["businesses"]]
        created = self.client.post("/api/openmart/lists", json={"name": "California dentists", "description": "Owner-led clinics", "businessIds": business_ids})
        self.assertEqual(created.status_code, 201)
        list_id = created.json["list"]["id"]
        enriched = self.client.post(f"/api/openmart/businesses/{business_ids[0]}/enrich", json={"fields": ["companyEmail", "ownerEmail", "ownerPhone"]})
        self.assertEqual(enriched.status_code, 200)
        self.assertTrue(enriched.json["business"]["ownerEmail"])
        exported = self.client.post("/api/openmart/exports", json={"leadListId": list_id, "format": "csv", "fields": ["name", "ownerEmail", "ownerPhone"]})
        self.assertEqual(exported.status_code, 201)
        download = self.client.get(exported.json["export"]["downloadUrl"])
        self.assertEqual(download.status_code, 200)
        self.assertIn("name,ownerEmail,ownerPhone", download.get_data(as_text=True))
        other = self.app.test_client()
        other.post("/api/openmart/auth/signup", json={"email": "other@example.com", "password": "Secure123", "displayName": "Other User", "workspaceName": "Other Workspace", "country": "US"})
        self.assertEqual(other.get(f"/api/openmart/lists/{list_id}").status_code, 404)

    def test_sequences_settings_team_and_api_keys(self):
        self.signup()
        results = self.client.post("/api/openmart/search", json={"query": "Restaurant", "location": "Miami", "filters": {}, "limit": 10}).json["businesses"]
        for business in results:
            self.client.post(f"/api/openmart/businesses/{business['id']}/enrich", json={"fields": ["companyEmail"]})
        lead_list = self.client.post("/api/openmart/lists", json={"name": "Miami restaurants", "businessIds": [row["id"] for row in results]}).json["list"]
        sequence = self.client.post("/api/openmart/sequences", json={
            "name": "Miami restaurant intro", "leadListId": lead_list["id"], "senderEmail": "alex@example.com",
            "steps": [
                {"delayDays": 0, "subject": "Quick question for {{business_name}}", "body": "Hi {{owner_name}}, I noticed your Miami location."},
                {"delayDays": 3, "subject": "Following up", "body": "Would a short conversation be useful?"},
            ],
        })
        self.assertEqual(sequence.status_code, 201)
        launched = self.client.post(f"/api/openmart/sequences/{sequence.json['sequence']['id']}/launch", json={})
        self.assertEqual(launched.status_code, 200)
        self.assertEqual(launched.json["sequence"]["status"], "active")
        invitation = self.client.post("/api/openmart/team/invitations", json={"email": "teammate@example.com", "role": "member"})
        self.assertEqual(invitation.status_code, 201)
        key = self.client.post("/api/openmart/api-keys", json={"name": "Production API"})
        self.assertEqual(key.status_code, 201)
        self.assertTrue(key.json["apiKey"]["token"].startswith("om_live_"))
        api_client = self.app.test_client()
        api_search = api_client.post(
            "/api/openmart/search",
            headers={"x-api-key": key.json["apiKey"]["token"]},
            json={"query": "Dentist", "location": "California", "filters": {}, "limit": 10},
        )
        self.assertEqual(api_search.status_code, 200)
        self.assertGreaterEqual(api_search.json["total"], 2)
        listed = self.client.get("/api/openmart/api-keys")
        self.assertNotIn("token", listed.get_data(as_text=True))
        key_id = key.json["apiKey"]["id"]
        self.assertEqual(self.client.delete(f"/api/openmart/api-keys/{key_id}").status_code, 200)
        self.assertEqual(
            api_client.post(
                "/api/openmart/search",
                headers={"x-api-key": key.json["apiKey"]["token"]},
                json={"query": "Dentist", "location": "California", "filters": {}, "limit": 10},
            ).status_code,
            401,
        )
        settings = self.client.patch("/api/openmart/settings", json={"displayName": "Alexandra Morgan", "workspaceName": "Northstar Data", "country": "CA"})
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(settings.json["workspace"]["country"], "CA")

    def test_remaining_crud_and_collection_endpoints(self):
        self.signup("crud@example.com")
        businesses = self.client.post(
            "/api/openmart/search",
            json={"query": "Dentist", "location": "California", "filters": {}, "limit": 10},
        ).json["businesses"]
        self.assertGreaterEqual(len(businesses), 2)

        created = self.client.post(
            "/api/openmart/lists",
            json={"name": "CRUD leads", "description": "Initial", "businessIds": [businesses[0]["id"]]},
        )
        self.assertEqual(created.status_code, 201)
        list_id = created.json["list"]["id"]
        self.assertEqual(len(self.client.get("/api/openmart/lists").json["lists"]), 1)

        updated = self.client.patch(
            f"/api/openmart/lists/{list_id}",
            json={"name": "Updated CRUD leads", "description": "Updated"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["list"]["name"], "Updated CRUD leads")

        added = self.client.post(
            f"/api/openmart/lists/{list_id}/items",
            json={"businessIds": [businesses[1]["id"]]},
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(added.json["list"]["recordCount"], 2)

        detail = self.client.get(f"/api/openmart/lists/{list_id}")
        self.assertEqual(detail.status_code, 200)
        item_id = detail.json["list"]["items"][0]["id"]
        item_update = self.client.patch(
            f"/api/openmart/lists/{list_id}/items/{item_id}",
            json={"contactStatus": "qualified", "notes": "Ready for outreach"},
        )
        self.assertEqual(item_update.status_code, 200)
        self.assertEqual(item_update.json["item"]["contactStatus"], "qualified")
        self.assertEqual(self.client.delete(f"/api/openmart/lists/{list_id}/items/{item_id}").status_code, 200)

        exported = self.client.post(
            "/api/openmart/exports",
            json={"leadListId": list_id, "format": "csv", "fields": ["name", "category"]},
        )
        self.assertEqual(exported.status_code, 201)
        self.assertEqual(len(self.client.get("/api/openmart/exports").json["exports"]), 1)

        key = self.client.post("/api/openmart/api-keys", json={"name": "Temporary key"}).json["apiKey"]
        self.assertEqual(self.client.delete(f"/api/openmart/api-keys/{key['id']}").status_code, 200)
        self.assertIsNotNone(self.client.get("/api/openmart/api-keys").json["apiKeys"][0]["revokedAt"])

        self.client.post("/api/openmart/team/invitations", json={"email": "crud-team@example.com", "role": "admin"})
        team = self.client.get("/api/openmart/team")
        self.assertEqual(team.status_code, 200)
        self.assertEqual(team.json["invitations"][0]["role"], "admin")
        self.assertEqual(self.client.get("/api/openmart/settings").status_code, 200)
        self.assertGreater(len(self.client.get("/api/openmart/activity").json["events"]), 0)

        self.assertEqual(self.client.delete(f"/api/openmart/lists/{list_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/openmart/lists/{list_id}").status_code, 404)

    def test_validation_origin_rate_and_oversized_payload_protection(self):
        weak = self.client.post("/api/openmart/auth/signup", json={"email": "weak@example.com", "password": "password", "displayName": "Weak User", "workspaceName": "Weak"})
        self.assertEqual(weak.status_code, 400)
        unknown = self.client.post("/api/openmart/auth/signup", json={"email": "weak@example.com", "password": "Secure123", "displayName": "Weak User", "workspaceName": "Weak", "isAdmin": True})
        self.assertEqual(unknown.status_code, 400)
        blocked = self.client.post("/api/openmart/auth/signup", json={"email": "blocked@example.com", "password": "Secure123", "displayName": "Blocked User", "workspaceName": "Blocked"}, headers={"Origin": "https://evil.example"})
        self.assertEqual(blocked.status_code, 403)
        oversized = self.client.post("/api/openmart/auth/signup", data=b"x" * (1024 * 1024 + 1), content_type="application/json")
        self.assertEqual(oversized.status_code, 413)


if __name__ == "__main__":
    unittest.main()
