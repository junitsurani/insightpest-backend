from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Uuid

from app.models import db


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class AuditMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    source_system = db.Column(db.String(40), nullable=False, default="greptile_clone")


class GreptileWorkspace(AuditMixin, db.Model):
    __tablename__ = "greptile_workspace"

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    name = db.Column(db.String(120), nullable=False, default="Demo workspace")
    repositories = db.relationship("GreptileRepository", back_populates="workspace", cascade="all, delete-orphan")
    users = db.relationship("GreptileUser", back_populates="workspace", cascade="all, delete-orphan")


class GreptileUser(AuditMixin, db.Model):
    __tablename__ = "greptile_user"
    __table_args__ = (
        db.UniqueConstraint("email", name="uq_greptile_user_email"),
        db.Index("ix_greptile_user_workspace_active", "workspace_id", "is_active"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_workspace.id", ondelete="CASCADE"), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    workspace = db.relationship("GreptileWorkspace", back_populates="users")
    sessions = db.relationship("GreptileSession", back_populates="user", cascade="all, delete-orphan")


class GreptileSession(AuditMixin, db.Model):
    __tablename__ = "greptile_session"
    __table_args__ = (
        db.UniqueConstraint("token_hash", name="uq_greptile_session_token_hash"),
        db.Index("ix_greptile_session_user_expires", "user_id", "expires_at"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_user.id", ondelete="CASCADE"), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    user = db.relationship("GreptileUser", back_populates="sessions")


class GreptileRepository(AuditMixin, db.Model):
    __tablename__ = "greptile_repository"
    __table_args__ = (
        db.UniqueConstraint("workspace_id", "provider", "owner", "name", name="uq_greptile_repository_identity"),
        db.Index("ix_greptile_repository_workspace_status", "workspace_id", "status"),
        CheckConstraint("provider IN ('github', 'gitlab')", name="ck_greptile_repository_provider"),
        CheckConstraint("status IN ('queued', 'indexing', 'ready', 'failed')", name="ck_greptile_repository_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_greptile_repository_progress"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_workspace.id", ondelete="CASCADE"), nullable=False)
    provider = db.Column(db.String(20), nullable=False, default="github")
    owner = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    default_branch = db.Column(db.String(120), nullable=False, default="main")
    status = db.Column(db.String(20), nullable=False, default="queued")
    progress = db.Column(db.Integer, nullable=False, default=0)
    last_indexed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    workspace = db.relationship("GreptileWorkspace", back_populates="repositories")


class GreptileConversation(AuditMixin, db.Model):
    __tablename__ = "greptile_conversation"
    __table_args__ = (db.Index("ix_greptile_conversation_workspace_updated", "workspace_id", "updated_at"),)

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_workspace.id", ondelete="CASCADE"), nullable=False)
    repository_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_repository.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    messages = db.relationship("GreptileMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="GreptileMessage.created_at")


class GreptileMessage(AuditMixin, db.Model):
    __tablename__ = "greptile_message"
    __table_args__ = (
        db.Index("ix_greptile_message_conversation_created", "conversation_id", "created_at"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_greptile_message_role"),
        CheckConstraint("feedback_rating IS NULL OR feedback_rating IN (-1, 1)", name="ck_greptile_message_feedback"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_greptile_message_duration"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    conversation_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_conversation.id", ondelete="CASCADE"), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    duration_ms = db.Column(db.Integer, nullable=True)
    feedback_rating = db.Column(db.SmallInteger, nullable=True)
    conversation = db.relationship("GreptileConversation", back_populates="messages")
    citations = db.relationship("GreptileCitation", back_populates="message", cascade="all, delete-orphan")


class GreptileCitation(AuditMixin, db.Model):
    __tablename__ = "greptile_citation"
    __table_args__ = (
        CheckConstraint("start_line > 0", name="ck_greptile_citation_start_line"),
        CheckConstraint("end_line >= start_line", name="ck_greptile_citation_line_range"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    message_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_message.id", ondelete="CASCADE"), nullable=False)
    path = db.Column(db.String(500), nullable=False)
    start_line = db.Column(db.Integer, nullable=False)
    end_line = db.Column(db.Integer, nullable=False)
    excerpt = db.Column(db.Text, nullable=False)
    message = db.relationship("GreptileMessage", back_populates="citations")


class GreptilePullRequest(AuditMixin, db.Model):
    __tablename__ = "greptile_pull_request"
    __table_args__ = (
        db.UniqueConstraint("repository_id", "number", name="uq_greptile_pull_request_number"),
        db.Index("ix_greptile_pull_request_repository_status", "repository_id", "status"),
        CheckConstraint("number > 0", name="ck_greptile_pull_request_number"),
        CheckConstraint("issue_count >= 0", name="ck_greptile_pull_request_issue_count"),
        CheckConstraint("status IN ('open', 'reviewing', 'issues_found', 'passed', 'closed')", name="ck_greptile_pull_request_status"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_workspace.id", ondelete="CASCADE"), nullable=False)
    repository_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_repository.id", ondelete="CASCADE"), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(240), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    branch = db.Column(db.String(160), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open")
    issue_count = db.Column(db.Integer, nullable=False, default=0)


class GreptileRule(AuditMixin, db.Model):
    __tablename__ = "greptile_rule"
    __table_args__ = (db.Index("ix_greptile_rule_workspace_enabled", "workspace_id", "enabled"),)

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("greptile_workspace.id", ondelete="CASCADE"), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)


class GreptileContactLead(AuditMixin, db.Model):
    __tablename__ = "greptile_contact_lead"
    __table_args__ = (
        db.Index("ix_greptile_contact_lead_email_created", "email", "created_at"),
        CheckConstraint("status IN ('new', 'contacted', 'qualified', 'closed')", name="ck_greptile_contact_lead_status"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    company = db.Column(db.String(160), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="new")
