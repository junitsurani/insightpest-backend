import os
import unittest

os.environ.setdefault("SECRET_KEY", "paces-test-secret")
os.environ["AUTO_CREATE_TABLES"] = "false"

from flask import Flask

from app.models import db
from app.models.user import CRMCustomer
from app.routes.routes_Paces import api_paces


class PacesDemoApiTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        self.app.register_blueprint(api_paces)
        with self.app.app_context():
            db.create_all()
            customer = CRMCustomer(
                name="Existing Pest Customer", phone="+14165550188", postal_code="M5V 2T6",
                pest_issue="mice", status="lead", source="test",
            )
            db.session.add(customer)
            db.session.commit()
            self.customer_id = customer.id
        self.client = self.app.test_client()
        token = self.client.post("/api/paces/session").get_json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_session_is_required_and_bootstrap_is_seeded(self):
        self.assertEqual(self.client.get("/api/paces/bootstrap").status_code, 401)
        response = self.client.get("/api/paces/bootstrap", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertGreaterEqual(len(body["projects"]), 5)
        self.assertEqual(body["settings"]["workspaceName"], "Paces Demo")

    def test_paces_mutations_do_not_change_pest_customer(self):
        bootstrap = self.client.get("/api/paces/bootstrap", headers=self.headers).get_json()
        project = bootstrap["projects"][0]
        moved = self.client.patch(
            f"/api/paces/projects/{project['id']}", json={"stage": "Submission"}, headers=self.headers,
        )
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.get_json()["stage"], "Submission")

        saved = self.client.post("/api/paces/saved-searches", json={"name": "Midwest storage", "query": "Illinois"}, headers=self.headers)
        report = self.client.post("/api/paces/reports", json={"projectId": project["id"], "type": "Permitting", "priority": "Priority"}, headers=self.headers)
        agent = self.client.post("/api/paces/agent/runs", json={"prompt": "Rank projects by readiness"}, headers=self.headers)
        settings = self.client.patch("/api/paces/settings", json={"workspaceName": "Northstar Development", "weeklyPipelineSummary": False}, headers=self.headers)
        self.assertEqual((saved.status_code, report.status_code, agent.status_code, settings.status_code), (201, 201, 201, 200))

        with self.app.app_context():
            customer = db.session.get(CRMCustomer, self.customer_id)
            self.assertEqual(customer.name, "Existing Pest Customer")
            self.assertEqual(customer.status, "lead")


if __name__ == "__main__":
    unittest.main()
