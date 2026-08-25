import unittest
import uuid
import base64
from datetime import datetime, timezone
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from app.greptile import initialize_greptile_schema, register_greptile
from app.greptile.auth import _login_windows
from app.greptile.llm_engine import SourceChunk
from app.greptile.models import GreptileCodeFile, GreptileRepository, GreptileRepositorySnapshot, GreptileSession
from app.greptile.routes import _rate_windows
from app.greptile.repository_indexer import RepositoryClient, RepositoryTarget
from app.models import db


class GreptileApiTestCase(unittest.TestCase):
    def setUp(self):
        _rate_windows.clear()
        _login_windows.clear()
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

    @staticmethod
    def _index_repository(repository):
        snapshot = GreptileRepositorySnapshot(
            workspace_id=repository.workspace_id,
            repository_id=repository.id,
            remote_url=f"https://{repository.provider}.com/{repository.owner}/{repository.name}",
            commit_sha="abc123",
            default_branch="main",
            status="ready",
            file_count=2,
            indexed_file_count=2,
            total_bytes=180,
        )
        db.session.add(snapshot)
        db.session.flush()
        db.session.add_all([
            GreptileCodeFile(
                workspace_id=repository.workspace_id, repository_id=repository.id,
                snapshot_id=snapshot.id, path="src/auth.py", language="Python",
                source_sha="file1", size_bytes=90, line_count=4,
                content="def require_workspace_access(user, workspace):\n    return memberships.assert_access(user, workspace)\n",
            ),
            GreptileCodeFile(
                workspace_id=repository.workspace_id, repository_id=repository.id,
                snapshot_id=snapshot.id, path="src/worker.py", language="Python",
                source_sha="file2", size_bytes=90, line_count=3,
                content="import subprocess\nsubprocess.run(command, shell=True)\n",
            ),
        ])
        repository.status = "ready"
        repository.progress = 100
        repository.last_indexed_at = datetime.now(timezone.utc)
        db.session.commit()
        return snapshot

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
        with patch("app.greptile.routes.index_repository", side_effect=self._index_repository):
            response = self.client.post(f"/api/greptile/repositories/{repo['id']}/sync", headers=spoofed)
        self.assertEqual(response.status_code, 200)

    def test_query_returns_persisted_citations(self):
        self.login()
        repo = self.client.get("/api/greptile/repositories", headers=self.headers).json["repositories"][0]
        with self.app.app_context():
            self._index_repository(db.session.get(GreptileRepository, uuid.UUID(repo["id"])))
        grounded = [
            SourceChunk("src/auth.py", 1, 4, "def require_workspace_access(...)", "0001 def require_workspace_access(...):"),
            SourceChunk("src/worker.py", 1, 3, "subprocess.run(...)", "0001 subprocess.run(...)"),
        ]
        with patch("app.greptile.services.generate_grounded_answer", return_value=("Authentication is enforced by require_workspace_access.", grounded, "test-model")):
            response = self.client.post("/api/greptile/query", headers=self.headers, json={"repositoryId": repo["id"], "question": "How does authentication work?"})
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json["citations"]), 2)
        self.assertIn("require_workspace_access", response.json["answer"])
        feedback = self.client.post(f"/api/greptile/messages/{response.json['messageId']}/feedback", headers=self.headers, json={"rating": 1})
        self.assertEqual(feedback.status_code, 200)

    def test_add_repository_invokes_real_indexing_contract(self):
        self.login()
        with patch("app.greptile.routes.index_repository", side_effect=self._index_repository) as index:
            response = self.client.post(
                "/api/greptile/repositories",
                headers=self.headers,
                json={"url": "https://github.com/octocat/Hello-World", "defaultBranch": "main"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["repository"]["status"], "ready")
        self.assertEqual(response.json["repository"]["indexedFileCount"], 2)
        index.assert_called_once()

    def test_github_connector_reads_remote_tree_and_source_blob(self):
        calls = []

        class Response:
            def __init__(self, payload=None, content=b"", status=200):
                self._payload = payload
                self.content = content or (b"{}" if payload is not None else b"")
                self.status_code = status

            def json(self):
                return self._payload

        encoded = base64.b64encode(b"def login():\n    return True\n").decode()

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/octocat/Hello-World"):
                return Response({"default_branch": "master"})
            if "/git/trees/master" in url:
                return Response({"sha": "commit123", "truncated": False, "tree": [
                    {"type": "blob", "path": "src/auth.py", "sha": "blob123", "size": 29},
                    {"type": "blob", "path": "node_modules/ignored.js", "sha": "blob999", "size": 10},
                ]})
            if url.endswith("/git/blobs/blob123"):
                return Response({"encoding": "base64", "content": encoded})
            return Response(status=404)

        repository = GreptileRepository(provider="github", owner="octocat", name="Hello-World", default_branch="main")
        connector = RepositoryClient(get=fake_get)
        remote = connector.describe(repository)
        content = connector.fetch_content(RepositoryTarget("github", "octocat", "Hello-World"), remote, remote.files[0])
        self.assertEqual(remote.default_branch, "master")
        self.assertEqual(remote.commit_sha, "commit123")
        self.assertEqual([item.path for item in remote.files], ["src/auth.py"])
        self.assertIn("def login", content)
        self.assertTrue(all(call[1]["allow_redirects"] is False for call in calls))

    def test_codebase_audit_persists_llm_and_static_findings(self):
        self.login()
        repo = self.client.get("/api/greptile/repositories", headers=self.headers).json["repositories"][0]
        with self.app.app_context():
            self._index_repository(db.session.get(GreptileRepository, uuid.UUID(repo["id"])))
        ai_finding = {
            "path": "src/auth.py", "start_line": 1, "end_line": 1, "severity": "medium",
            "category": "authorization", "title": "Missing explicit denial",
            "description": "The helper does not show an explicit denial path.",
            "recommendation": "Fail closed and add an unauthorized workspace test.",
            "evidence": "def require_workspace_access(...)",
        }
        with patch("app.greptile.audit_service.generate_audit_findings", return_value=("Audit complete.", [ai_finding], "test-model")):
            response = self.client.post(f"/api/greptile/repositories/{repo['id']}/audits", headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["audit"]["llmStatus"], "complete")
        self.assertGreaterEqual(response.json["audit"]["findingCount"], 2)
        listed = self.client.get(f"/api/greptile/audits?repositoryId={repo['id']}", headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json["audits"]), 1)

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
