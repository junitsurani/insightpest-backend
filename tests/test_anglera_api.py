import unittest
import uuid
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from app.anglera import initialize_anglera_schema, register_anglera
from app.anglera.models import AngleraJob, AngleraMember, AngleraProduct, AngleraSource
from app.anglera.routes import _rate_windows
from app.greptile import initialize_greptile_schema, register_greptile
from app.greptile.auth import _login_windows
from app.models import db


class AngleraApiTestCase(unittest.TestCase):
    def setUp(self):
        _rate_windows.clear()
        _login_windows.clear()
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="anglera-test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            GREPTILE_DUMMY_PASSWORD_HASH=generate_password_hash("not-the-seed-password"),
            ANGLERA_RUN_JOBS_INLINE=True,
            ANGLERA_FRONTEND_URL="http://127.0.0.1:3000",
        )
        db.init_app(self.app)
        register_greptile(self.app)
        register_anglera(self.app)
        with self.app.app_context():
            initialize_greptile_schema()
            initialize_anglera_schema()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self):
        return self.client.post("/api/greptile/auth/login", json={"email": "a@gmail.com", "password": "1", "remember": True})

    def test_health_and_workspace_authentication(self):
        health = self.client.get("/api/anglera/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json["realtime"], "sse")
        self.assertEqual(health.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.client.get("/api/anglera/workspace").status_code, 401)
        self.login()
        workspace = self.client.get("/api/anglera/workspace")
        self.assertEqual(workspace.status_code, 200)
        self.assertEqual(len(workspace.json["products"]), 17)
        image_paths = {product["image"] for product in workspace.json["products"]}
        self.assertEqual(len(image_paths), 17)
        self.assertTrue(all(path.startswith("/anglera-assets/products/") for path in image_paths))
        self.assertEqual(workspace.json["members"][0]["role"], "Owner")
        self.assertEqual(workspace.json["webSettings"]["crawlDepth"], "product-and-docs")

    def test_import_is_persisted_upserts_skus_and_rejects_unknown_fields(self):
        self.login()
        payload = {"products": [{"name": "New Drill", "sku": " new-100 ", "specification": "Awaiting enrichment", "image": "/anglera-assets/products/dp4020.png"}]}
        created = self.client.post("/api/anglera/products/import", json=payload)
        self.assertEqual(created.status_code, 201)
        product_id = created.json["products"][0]["id"]
        updated = self.client.post("/api/anglera/products/import", json={"products": [{**payload["products"][0], "name": "Updated Drill"}]})
        self.assertEqual(updated.status_code, 201)
        self.assertEqual(updated.json["products"][0]["id"], product_id)
        self.assertEqual(updated.json["products"][0]["name"], "Updated Drill")
        invalid = self.client.post("/api/anglera/products/import", json={"products": [{**payload["products"][0], "workspaceId": str(uuid.uuid4())}]})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("unexpected fields", invalid.json["error"])
        duplicate = self.client.post("/api/anglera/products/import", json={"products": [payload["products"][0], payload["products"][0]]})
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("duplicate SKU", duplicate.json["error"])

    def test_enrichment_job_is_idempotent_and_updates_persisted_product(self):
        self.login()
        created = self.client.post("/api/anglera/products/import", json={"products": [{"name": "Enrichment Target", "sku": "ENR-1", "specification": "A complete technical description", "image": "/anglera-assets/products/dp4020.png"}]})
        product_id = created.json["products"][0]["id"]
        request_body = {"ids": [product_id], "idempotencyKey": "enrich-enr-1"}
        first = self.client.post("/api/anglera/products/enrich", json=request_body)
        second = self.client.post("/api/anglera/products/enrich", json=request_body)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json["job"]["id"], second.json["job"]["id"])
        self.assertEqual(first.json["job"]["status"], "succeeded")
        workspace = self.client.get("/api/anglera/workspace").json
        product = next(item for item in workspace["products"] if item["id"] == product_id)
        self.assertEqual(product["status"], "ready")
        with self.app.app_context():
            self.assertEqual(AngleraJob.query.filter_by(idempotency_key="enrich-enr-1").count(), 1)

    def test_source_validation_blocks_ssrf_and_sync_failure_is_visible(self):
        self.login()
        bad_scheme = self.client.post("/api/anglera/sources", json={"name": "Private", "type": "Website", "location": "http://127.0.0.1/admin"})
        self.assertEqual(bad_scheme.status_code, 400)
        created = self.client.post("/api/anglera/sources", json={"name": "Private HTTPS", "type": "Website", "location": "https://127.0.0.1/admin"})
        self.assertEqual(created.status_code, 201)
        source_id = created.json["source"]["id"]
        synced = self.client.post("/api/anglera/sources/sync", json={"ids": [source_id], "idempotencyKey": "sync-private"})
        self.assertEqual(synced.status_code, 202)
        workspace = self.client.get("/api/anglera/workspace").json
        source = next(item for item in workspace["sources"] if item["id"] == source_id)
        self.assertEqual(source["status"], "Needs attention")
        self.assertIn("private or reserved", source["lastError"])

    def test_live_source_sync_fetches_public_html_without_redirects(self):
        self.login()
        created = self.client.post("/api/anglera/sources", json={"name": "Catalog", "type": "Website", "location": "https://catalog.example.com/products"})
        source_id = created.json["source"]["id"]

        class RemoteResponse:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            content = b'<html><script type="application/ld+json">{"@type":"Product"}</script><body>SKU ENR-1 professional drill</body></html>'
            encoding = "utf-8"

            def iter_content(self, chunk_size=65536):
                yield self.content

            def close(self):
                pass

        with patch("app.anglera.services.assert_public_hostname"), patch("app.anglera.services.requests.get", return_value=RemoteResponse()) as get:
            synced = self.client.post("/api/anglera/sources/sync", json={"ids": [source_id], "idempotencyKey": "sync-public"})
        self.assertEqual(synced.status_code, 202)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        with self.app.app_context():
            source = db.session.get(AngleraSource, uuid.UUID(source_id))
            self.assertEqual(source.status, "Connected")
            self.assertEqual(source.record_count, 1)
            self.assertIn("professional drill", source.content_text)

    def test_roles_and_workspace_scope_prevent_unauthorized_mutation(self):
        self.login()
        with self.app.app_context():
            owner = AngleraMember.query.filter_by(email="a@gmail.com").first()
            owner.role = "Viewer"
            foreign = AngleraProduct(workspace_id=uuid.uuid4(), name="Foreign", sku="FOREIGN-1", status="ready", confidence=100, source_count=1)
            db.session.add(foreign)
            db.session.commit()
            foreign_id = str(foreign.id)
        denied = self.client.post("/api/anglera/products/delete", json={"ids": [foreign_id]})
        self.assertEqual(denied.status_code, 403)
        with self.app.app_context():
            self.assertIsNone(db.session.get(AngleraProduct, uuid.UUID(foreign_id)).deleted_at)

    def test_invites_roles_settings_analytics_and_event_stream(self):
        self.login()
        invite = self.client.post("/api/anglera/invitations", json={"email": "editor@example.com"})
        self.assertEqual(invite.status_code, 201)
        self.assertNotIn("invitation_token_hash", invite.json)
        self.assertIn("/login?invite=", invite.json["invitationUrl"])
        member_id = invite.json["member"]["id"]
        role = self.client.patch(f"/api/anglera/members/{member_id}", json={"role": "Viewer"})
        self.assertEqual(role.json["member"]["role"], "Viewer")
        settings = self.client.patch("/api/anglera/settings", json={
            "webSettings": {"primaryDomain": "https://example.com", "crawlDepth": "product-only", "includePdfManuals": False, "respectRobots": True, "automaticEnrichment": False},
            "workspaceProfile": {"displayName": "Catalog Owner", "workspaceName": "Acme Catalog"},
        })
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(settings.json["workspace"]["workspaceProfile"]["workspaceName"], "Acme Catalog")
        analytics = self.client.get("/api/anglera/analytics?days=7")
        self.assertEqual(analytics.status_code, 200)
        self.assertEqual(analytics.json["analytics"]["periodDays"], 7)
        stream = self.client.get("/api/anglera/events?after=0", buffered=False)
        first_chunk = next(stream.response).decode()
        self.assertIn("event: workspace", first_chunk)
        self.assertIn("member.invited", first_chunk)
        stream.close()

    def test_invitation_token_creates_an_account_and_can_only_be_used_once(self):
        self.login()
        invite = self.client.post("/api/anglera/invitations", json={"email": "new.user@example.com"})
        token = invite.json["invitationUrl"].split("invite=", 1)[1]
        self.client.post("/api/greptile/auth/logout")
        details = self.client.get(f"/api/anglera/invitations/details?token={token}")
        self.assertEqual(details.status_code, 200)
        self.assertEqual(details.json["invitation"]["email"], "new.user@example.com")
        accepted = self.client.post("/api/anglera/invitations/accept", json={"token": token, "displayName": "New User", "password": "safe-password-123"})
        self.assertEqual(accepted.status_code, 201)
        reused = self.client.post("/api/anglera/invitations/accept", json={"token": token, "displayName": "New User", "password": "safe-password-123"})
        self.assertEqual(reused.status_code, 400)
        login = self.client.post("/api/greptile/auth/login", json={"email": "new.user@example.com", "password": "safe-password-123", "remember": True})
        self.assertEqual(login.status_code, 200)
        workspace = self.client.get("/api/anglera/workspace")
        self.assertEqual(workspace.status_code, 200)
        joined = next(item for item in workspace.json["members"] if item["email"] == "new.user@example.com")
        self.assertEqual(joined["status"], "Active")


if __name__ == "__main__":
    unittest.main()
