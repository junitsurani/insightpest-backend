"""Isolated persistence models for the Paces product demo.

These tables intentionally have no foreign keys to the pest-control domain.
"""

from datetime import datetime

from . import db


class PacesProject(db.Model):
    __tablename__ = "paces_project"

    id = db.Column(db.String(36), primary_key=True)
    workspace_key = db.Column(db.String(80), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    county = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(2), nullable=False)
    capacity_mw = db.Column(db.Float, nullable=False)
    acres = db.Column(db.Float, nullable=False)
    buildable_acres = db.Column(db.Float, nullable=False)
    score = db.Column(db.Integer, nullable=False)
    stage = db.Column(db.String(32), nullable=False, default="Siting")
    risk = db.Column(db.String(16), nullable=False, default="Low")
    owner = db.Column(db.String(100), nullable=False, default="Unassigned")
    due_date = db.Column(db.Date, nullable=True)
    source_system = db.Column(db.String(32), nullable=False, default="paces_demo")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "county": self.county,
            "state": self.state,
            "capacityMw": self.capacity_mw,
            "acres": self.acres,
            "buildableAcres": self.buildable_acres,
            "score": self.score,
            "stage": self.stage,
            "risk": self.risk,
            "owner": self.owner,
            "dueDate": self.due_date.isoformat() if self.due_date else None,
            "updatedAt": self.updated_at.isoformat() + "Z",
        }


class PacesSavedSearch(db.Model):
    __tablename__ = "paces_saved_search"

    id = db.Column(db.String(36), primary_key=True)
    workspace_key = db.Column(db.String(80), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    search_query = db.Column("query", db.String(240), nullable=False, default="")
    filters = db.Column(db.JSON, nullable=False, default=dict)
    source_system = db.Column(db.String(32), nullable=False, default="paces_demo")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "query": self.search_query,
            "filters": self.filters or {},
            "updatedAt": self.updated_at.isoformat() + "Z",
        }


class PacesReportOrder(db.Model):
    __tablename__ = "paces_report_order"

    id = db.Column(db.String(36), primary_key=True)
    workspace_key = db.Column(db.String(80), nullable=False, index=True)
    project_id = db.Column(db.String(36), nullable=True, index=True)
    project_name = db.Column(db.String(160), nullable=False)
    report_type = db.Column(db.String(80), nullable=False)
    priority = db.Column(db.String(16), nullable=False, default="Standard")
    status = db.Column(db.String(32), nullable=False, default="Processing")
    source_system = db.Column(db.String(32), nullable=False, default="paces_demo")
    requested_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "projectId": self.project_id,
            "project": self.project_name,
            "type": self.report_type,
            "priority": self.priority,
            "status": self.status,
            "requestedAt": self.requested_at.isoformat() + "Z",
        }


class PacesAgentRun(db.Model):
    __tablename__ = "paces_agent_run"

    id = db.Column(db.String(36), primary_key=True)
    workspace_key = db.Column(db.String(80), nullable=False, index=True)
    prompt = db.Column(db.String(1200), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="Completed")
    result_summary = db.Column(db.Text, nullable=False)
    result_count = db.Column(db.Integer, nullable=False, default=0)
    results = db.Column(db.JSON, nullable=False, default=list)
    source_system = db.Column(db.String(32), nullable=False, default="paces_demo")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "prompt": self.prompt,
            "status": self.status,
            "summary": self.result_summary,
            "resultCount": self.result_count,
            "results": self.results or [],
            "createdAt": self.created_at.isoformat() + "Z",
        }


class PacesWorkspaceSettings(db.Model):
    __tablename__ = "paces_workspace_settings"

    id = db.Column(db.String(36), primary_key=True)
    workspace_key = db.Column(db.String(80), nullable=False, unique=True, index=True)
    workspace_name = db.Column(db.String(120), nullable=False, default="Paces Demo")
    primary_market = db.Column(db.String(80), nullable=False, default="Texas")
    project_type = db.Column(db.String(40), nullable=False, default="Solar")
    capacity_unit = db.Column(db.String(16), nullable=False, default="MW")
    expert_review_notifications = db.Column(db.Boolean, nullable=False, default=True)
    weekly_pipeline_summary = db.Column(db.Boolean, nullable=False, default=True)
    source_system = db.Column(db.String(32), nullable=False, default="paces_demo")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "workspaceName": self.workspace_name,
            "primaryMarket": self.primary_market,
            "projectType": self.project_type,
            "capacityUnit": self.capacity_unit,
            "expertReviewNotifications": self.expert_review_notifications,
            "weeklyPipelineSummary": self.weekly_pipeline_summary,
        }


class PacesTeamMember(db.Model):
    __tablename__ = "paces_team_member"

    id = db.Column(db.String(36), primary_key=True)
    workspace_key = db.Column(db.String(80), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    role = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="Invited")
    access = db.Column(db.String(80), nullable=False, default="Projects & reports")
    source_system = db.Column(db.String(32), nullable=False, default="paces_demo")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint("workspace_key", "email", name="uq_paces_team_workspace_email"),)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "status": self.status,
            "access": self.access,
        }


class PacesDataSource(db.Model):
    __tablename__ = "paces_data_source"

    id = db.Column(db.String(36), primary_key=True)
    workspace_key = db.Column(db.String(80), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60), nullable=False)
    source_type = db.Column(db.String(40), nullable=False, default="Workspace upload")
    status = db.Column(db.String(24), nullable=False, default="Connected")
    freshness = db.Column(db.String(80), nullable=False, default="Added just now")
    source_system = db.Column(db.String(32), nullable=False, default="paces_demo")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "sourceType": self.source_type,
            "status": self.status,
            "freshness": self.freshness,
        }
