"""Nominal, persistent API for the isolated Paces product demo."""

from datetime import date, datetime, timedelta
from functools import wraps
import uuid

import jwt
from flask import Blueprint, jsonify, request

from app.models import db
from app.models.paces import (
    PacesAgentRun,
    PacesProject,
    PacesReportOrder,
    PacesSavedSearch,
    PacesWorkspaceSettings,
)
from app.routes.routes_auth import jwt_signing_key


api_paces = Blueprint("paces", __name__, url_prefix="/api/paces")
WORKSPACE = "paces-demo"
STAGES = {"Siting", "Due diligence", "Submission", "Construction ready"}
RISKS = {"Low", "Medium", "High"}
REPORT_TYPES = {"Site diligence", "Permitting", "Interconnection", "Market intelligence"}
PRIORITIES = {"Standard", "Priority"}


@api_paces.before_request
def limit_payload_size():
    if request.content_length and request.content_length > 64 * 1024:
        return jsonify({"error": "Request payload is too large"}), 413


def _json_body():
    return request.get_json(silent=True) or {}


def _clean_text(value, field, max_length, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = " ".join(value.split()).strip()
    if required and not value:
        raise ValueError(f"{field} is required")
    if len(value) > max_length:
        raise ValueError(f"{field} must be at most {max_length} characters")
    return value


def _number(value, field, minimum, maximum):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number")
    if result < minimum or result > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return result


def paces_session_required(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Paces demo session required"}), 401
        try:
            payload = jwt.decode(auth[7:], jwt_signing_key(), algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Paces demo session expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid Paces demo session"}), 401
        if payload.get("scope") != "paces_demo" or payload.get("workspace") != WORKSPACE:
            return jsonify({"error": "Invalid Paces demo scope"}), 403
        return handler(*args, **kwargs)
    return wrapped


def _seed_workspace():
    if not PacesProject.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).first():
        seeds = [
            ("Lone Star Solar", "Travis", "TX", 240, 1810, 1420, 92, "Due diligence", "Low", "Jordan Lee", "2026-09-18"),
            ("Prairie Creek Storage", "McLean", "IL", 180, 226, 192, 87, "Siting", "Medium", "Maya Chen", "2026-10-04"),
            ("Redwood Data Campus", "Henrico", "VA", 310, 374, 301, 84, "Submission", "Medium", "Alex Morgan", "2026-09-29"),
            ("Blue Ridge Solar", "Catawba", "NC", 155, 1124, 806, 79, "Siting", "High", "Priya Shah", "2026-10-21"),
            ("High Plains Wind", "Sherman", "KS", 420, 6680, 5110, 89, "Construction ready", "Low", "Jordan Lee", "2026-08-30"),
        ]
        for name, county, state, capacity, acres, buildable, score, stage, risk, owner, due in seeds:
            db.session.add(PacesProject(
                id=str(uuid.uuid4()), workspace_key=WORKSPACE, name=name, county=county,
                state=state, capacity_mw=capacity, acres=acres, buildable_acres=buildable,
                score=score, stage=stage, risk=risk, owner=owner, due_date=date.fromisoformat(due),
            ))
    if not PacesSavedSearch.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).first():
        db.session.add(PacesSavedSearch(
            id=str(uuid.uuid4()), workspace_key=WORKSPACE, name="Texas solar — 100+ MW",
            search_query="Texas", filters={"projectType": "Solar", "minimumCapacity": 100},
        ))
    if not PacesReportOrder.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).first():
        db.session.add(PacesReportOrder(
            id=str(uuid.uuid4()), workspace_key=WORKSPACE, project_name="Lone Star Solar",
            report_type="Site diligence", status="Ready", priority="Standard",
            completed_at=datetime.utcnow(),
        ))
    settings = PacesWorkspaceSettings.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).first()
    if not settings:
        db.session.add(PacesWorkspaceSettings(id=str(uuid.uuid4()), workspace_key=WORKSPACE))
    db.session.commit()


def _projects():
    return PacesProject.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).order_by(PacesProject.score.desc()).all()


@api_paces.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "paces-demo"})


@api_paces.route("/session", methods=["POST"])
def create_session():
    token = jwt.encode({
        "sub": "paces-demo-user", "scope": "paces_demo", "workspace": WORKSPACE,
        "exp": datetime.utcnow() + timedelta(hours=4),
    }, jwt_signing_key(), algorithm="HS256")
    return jsonify({"token": token, "expiresIn": 14400})


@api_paces.route("/bootstrap", methods=["GET"])
@paces_session_required
def bootstrap():
    _seed_workspace()
    settings = PacesWorkspaceSettings.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).first()
    return jsonify({
        "projects": [item.to_dict() for item in _projects()],
        "savedSearches": [item.to_dict() for item in PacesSavedSearch.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).order_by(PacesSavedSearch.updated_at.desc()).all()],
        "reports": [item.to_dict() for item in PacesReportOrder.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).order_by(PacesReportOrder.requested_at.desc()).all()],
        "agentRuns": [item.to_dict() for item in PacesAgentRun.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).order_by(PacesAgentRun.created_at.desc()).limit(8).all()],
        "settings": settings.to_dict(),
        "team": [
            {"id": "tm-1", "name": "Jordan Lee", "role": "Development lead", "status": "Online"},
            {"id": "tm-2", "name": "Maya Chen", "role": "GIS analyst", "status": "Online"},
            {"id": "tm-3", "name": "Priya Shah", "role": "Permitting", "status": "Away"},
            {"id": "tm-4", "name": "Alex Morgan", "role": "Interconnection", "status": "Online"},
        ],
        "dataCategories": [
            {"name": "Land & parcels", "layers": 18, "freshness": "Updated today"},
            {"name": "Grid & substations", "layers": 12, "freshness": "Updated 2 days ago"},
            {"name": "Permitting", "layers": 24, "freshness": "Updated this week"},
            {"name": "Environmental", "layers": 16, "freshness": "Updated this week"},
        ],
    })


@api_paces.route("/projects", methods=["POST"])
@paces_session_required
def create_project():
    data = _json_body()
    try:
        state = _clean_text(data.get("state"), "state", 2).upper()
        stage = data.get("stage", "Siting")
        risk = data.get("risk", "Low")
        if stage not in STAGES or risk not in RISKS:
            raise ValueError("Unsupported project stage or risk")
        acres = _number(data.get("acres"), "acres", 1, 1000000)
        project = PacesProject(
            id=str(uuid.uuid4()), workspace_key=WORKSPACE,
            name=_clean_text(data.get("name"), "name", 160),
            county=_clean_text(data.get("county"), "county", 100), state=state,
            capacity_mw=_number(data.get("capacityMw"), "capacityMw", 1, 50000),
            acres=acres, buildable_acres=_number(data.get("buildableAcres", acres * .78), "buildableAcres", 1, acres),
            score=int(_number(data.get("score", 75), "score", 0, 100)), stage=stage, risk=risk,
            owner=_clean_text(data.get("owner", "Unassigned"), "owner", 100),
        )
        db.session.add(project)
        db.session.commit()
        return jsonify(project.to_dict()), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Unable to create project"}), 500


@api_paces.route("/projects/<project_id>", methods=["PATCH"])
@paces_session_required
def update_project(project_id):
    project = PacesProject.query.filter_by(id=project_id, workspace_key=WORKSPACE, deleted_at=None).first_or_404()
    data = _json_body()
    try:
        if "stage" in data:
            if data["stage"] not in STAGES:
                raise ValueError("Unsupported project stage")
            project.stage = data["stage"]
        if "owner" in data:
            project.owner = _clean_text(data["owner"], "owner", 100)
        if "dueDate" in data:
            project.due_date = date.fromisoformat(data["dueDate"]) if data["dueDate"] else None
        project.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(project.to_dict())
    except (ValueError, TypeError):
        db.session.rollback()
        return jsonify({"error": "Invalid project update"}), 400


@api_paces.route("/saved-searches", methods=["POST"])
@paces_session_required
def create_saved_search():
    data = _json_body()
    try:
        filters = data.get("filters", {})
        if not isinstance(filters, dict) or len(filters) > 20:
            raise ValueError("filters must be an object with at most 20 fields")
        item = PacesSavedSearch(
            id=str(uuid.uuid4()), workspace_key=WORKSPACE,
            name=_clean_text(data.get("name"), "name", 120),
            search_query=_clean_text(data.get("query", ""), "query", 240, required=False) or "",
            filters=filters,
        )
        db.session.add(item)
        db.session.commit()
        return jsonify(item.to_dict()), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@api_paces.route("/reports", methods=["POST"])
@paces_session_required
def create_report():
    data = _json_body()
    try:
        report_type = data.get("type")
        priority = data.get("priority", "Standard")
        if report_type not in REPORT_TYPES or priority not in PRIORITIES:
            raise ValueError("Unsupported report type or priority")
        project_id = data.get("projectId")
        project = PacesProject.query.filter_by(id=project_id, workspace_key=WORKSPACE, deleted_at=None).first() if project_id else None
        project_name = project.name if project else _clean_text(data.get("project"), "project", 160)
        report = PacesReportOrder(
            id=str(uuid.uuid4()), workspace_key=WORKSPACE, project_id=project.id if project else None,
            project_name=project_name, report_type=report_type, priority=priority, status="Processing",
        )
        db.session.add(report)
        db.session.commit()
        return jsonify(report.to_dict()), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@api_paces.route("/agent/runs", methods=["POST"])
@paces_session_required
def create_agent_run():
    data = _json_body()
    try:
        prompt = _clean_text(data.get("prompt"), "prompt", 1200)
        matching = _projects()[:3]
        run = PacesAgentRun(
            id=str(uuid.uuid4()), workspace_key=WORKSPACE, prompt=prompt, status="Completed",
            result_summary=f"Analyzed {len(_projects())} active projects and prioritized {len(matching)} development opportunities.",
            result_count=len(matching), results=[item.to_dict() for item in matching], completed_at=datetime.utcnow(),
        )
        db.session.add(run)
        db.session.commit()
        return jsonify(run.to_dict()), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@api_paces.route("/settings", methods=["PATCH"])
@paces_session_required
def update_settings():
    _seed_workspace()
    settings = PacesWorkspaceSettings.query.filter_by(workspace_key=WORKSPACE, deleted_at=None).first()
    data = _json_body()
    try:
        mapping = {
            "workspaceName": ("workspace_name", 120), "primaryMarket": ("primary_market", 80),
            "projectType": ("project_type", 40), "capacityUnit": ("capacity_unit", 16),
        }
        for key, (attribute, limit) in mapping.items():
            if key in data:
                setattr(settings, attribute, _clean_text(data[key], key, limit))
        for key, attribute in (("expertReviewNotifications", "expert_review_notifications"), ("weeklyPipelineSummary", "weekly_pipeline_summary")):
            if key in data:
                if not isinstance(data[key], bool):
                    raise ValueError(f"{key} must be a boolean")
                setattr(settings, attribute, data[key])
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(settings.to_dict())
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
