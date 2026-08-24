import unittest

from flask import Flask
from werkzeug.security import generate_password_hash

from app.greptile import initialize_greptile_schema, register_greptile
from app.greptile.models import GreptileSession
from app.models import db


class GreptileApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="greptile-test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            GREPTILE_DUMMY_PASSWORD_HASH=generate_password_hash("not-the-seed-password"),
        )
        db.init_app(self.app)
        register_greptile(self.app)
        with self.app.app_context():
            initialize_greptile_schema()
        self.client = self.app.test_client()
        self.headers = {"Content-Type": "application/json"}

    def login(self, password="1", remember=True):
        return self.client.post(
            "/api/greptile/auth/login",
            json={"email": "a@gmail.com", "password": password, "remember": remember},
        )

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_health_is_public_and_hardened(self):
        response = self.client.get("/api/greptile/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["service"], "greptile")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_protected_routes_require_a_server_session(self):
        response = self.client.get("/api/greptile/repositories")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"], "Authentication required")

    def test_seed_user_can_login_and_logout_with_http_only_cookie(self):
        invalid = self.login(password="wrong")
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(invalid.json["error"], "The email or password is incorrect.")

        valid = self.login()
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json["user"]["email"], "a@gmail.com")
        cookie = valid.headers.get("Set-Cookie", "")
        self.assertIn("greptile_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("a@gmail.com", cookie)

        session = self.client.get("/api/greptile/auth/session")
        self.assertEqual(session.status_code, 200)
        logout = self.client.post("/api/greptile/auth/logout")
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/greptile/repositories").status_code, 401)
        with self.app.app_context():
            self.assertIsNotNone(GreptileSession.query.filter(GreptileSession.revoked_at.isnot(None)).first())

    def test_reverse_proxy_https_marks_session_cookie_secure(self):
        response = self.client.post(
            "/api/greptile/auth/login",
            json={"email": "a@gmail.com", "password": "1", "remember": True},
            headers={"X-Forwarded-Proto": "https"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers.get("Set-Cookie", ""))

    def test_first_access_seeds_repository_and_pull_requests_idempotently(self):
        self.login()
        first = self.client.get("/api/greptile/repositories", headers=self.headers)
        second = self.client.get("/api/greptile/repositories", headers=self.headers)
        pulls = self.client.get("/api/greptile/pull-requests", headers=self.headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.json["repositories"]), 1)
        self.assertEqual(first.json, second.json)
        self.assertEqual(len(pulls.json["pullRequests"]), 3)

    def test_repository_url_validation_blocks_untrusted_hosts(self):
        self.login()
        response = self.client.post("/api/greptile/repositories", headers=self.headers, json={"url": "https://127.0.0.1/private", "defaultBranch": "main"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("GitHub or GitLab", response.json["error"])

    def test_client_cannot_override_the_session_workspace(self):
        self.login()
        repo = self.client.get("/api/greptile/repositories", headers=self.headers).json["repositories"][0]
        spoofed = {**self.headers, "X-Greptile-Workspace": "22222222-2222-4222-8222-222222222222"}
        response = self.client.post(f"/api/greptile/repositories/{repo['id']}/sync", headers=spoofed)
        self.assertEqual(response.status_code, 200)

    def test_query_returns_persisted_citations(self):
        self.login()
        repo = self.client.get("/api/greptile/repositories", headers=self.headers).json["repositories"][0]
        response = self.client.post("/api/greptile/query", headers=self.headers, json={"repositoryId": repo["id"], "question": "How does authentication work?"})
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json["citations"]), 2)
        self.assertIn("requireWorkspaceAccess", response.json["answer"])
        feedback = self.client.post(f"/api/greptile/messages/{response.json['messageId']}/feedback", headers=self.headers, json={"rating": 1})
        self.assertEqual(feedback.status_code, 200)

    def test_custom_rules_are_persisted_and_toggleable(self):
        self.login()
        initial = self.client.get("/api/greptile/rules")
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(len(initial.json["rules"]), 4)
        created = self.client.post("/api/greptile/rules", json={"text": "Require an authorization test for every protected route."})
        self.assertEqual(created.status_code, 201)
        toggled = self.client.post(f"/api/greptile/rules/{created.json['rule']['id']}/toggle", json={"enabled": False})
        self.assertEqual(toggled.status_code, 200)
        self.assertFalse(toggled.json["rule"]["enabled"])

    def test_oversized_and_unknown_fields_do_not_bypass_validation(self):
        self.login()
        repo = self.client.get("/api/greptile/repositories", headers=self.headers).json["repositories"][0]
        response = self.client.post("/api/greptile/query", headers=self.headers, json={"repositoryId": repo["id"], "question": "x" * 2001, "workspaceId": "22222222-2222-4222-8222-222222222222"})
        self.assertEqual(response.status_code, 400)
        unknown = self.client.post("/api/greptile/query", headers=self.headers, json={"repositoryId": repo["id"], "question": "Explain the service", "workspaceId": "22222222-2222-4222-8222-222222222222"})
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("unexpected fields", unknown.json["error"])


if __name__ == "__main__":
    unittest.main()
