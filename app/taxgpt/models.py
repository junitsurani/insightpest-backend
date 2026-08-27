from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Uuid

from app.models import db


def now():
    return datetime.now(timezone.utc)


def new_id():
    return uuid.uuid4()


class AuditMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now, onupdate=now)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    source_system = db.Column(db.String(40), nullable=False, default="taxgpt_clone")


class TaxGptDemoRequest(AuditMixin, db.Model):
    __tablename__ = "taxgpt_demo_request"
    __table_args__ = (
        CheckConstraint("persona IN ('pro', 'business', 'individual')", name="ck_taxgpt_demo_persona"),
        CheckConstraint("employees IN ('10', '50', '250', '251')", name="ck_taxgpt_demo_employees"),
        CheckConstraint("status IN ('new', 'contacted', 'scheduled', 'closed')", name="ck_taxgpt_demo_status"),
        db.Index("ix_taxgpt_demo_created", "created_at"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    full_name = db.Column(db.String(120), nullable=False)
    work_email = db.Column(db.String(254), nullable=False, index=True)
    persona = db.Column(db.String(20), nullable=False)
    employees = db.Column(db.String(10), nullable=False)
    source_path = db.Column(db.String(240), nullable=False, default="/demo")
    request_fingerprint = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="new")


class TaxGptRateEvent(AuditMixin, db.Model):
    __tablename__ = "taxgpt_rate_event"
    __table_args__ = (db.Index("ix_taxgpt_rate_scope_subject_created", "scope", "subject_hash", "created_at"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    scope = db.Column(db.String(40), nullable=False)
    subject_hash = db.Column(db.String(64), nullable=False)


class TaxGptWorkspace(AuditMixin, db.Model):
    __tablename__ = "taxgpt_workspace"
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    name = db.Column(db.String(160), nullable=False)
    country = db.Column(db.String(2), nullable=False, default="US")
    users = db.relationship("TaxGptUser", back_populates="workspace", cascade="all, delete-orphan")


class TaxGptUser(AuditMixin, db.Model):
    __tablename__ = "taxgpt_user"
    __table_args__ = (db.UniqueConstraint("email", name="uq_taxgpt_user_email"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    email = db.Column(db.String(254), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="owner")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    workspace = db.relationship("TaxGptWorkspace", back_populates="users")
    sessions = db.relationship("TaxGptSession", back_populates="user", cascade="all, delete-orphan")


class TaxGptSession(AuditMixin, db.Model):
    __tablename__ = "taxgpt_session"
    __table_args__ = (db.UniqueConstraint("token_hash", name="uq_taxgpt_session_token_hash"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_user.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    user = db.relationship("TaxGptUser", back_populates="sessions")


class TaxGptConversation(AuditMixin, db.Model):
    __tablename__ = "taxgpt_conversation"
    __table_args__ = (
        CheckConstraint("kind IN ('research', 'writer', 'document')", name="ck_taxgpt_conversation_kind"),
        db.Index("ix_taxgpt_conversation_workspace_updated", "workspace_id", "updated_at"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_workspace.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_user.id", ondelete="CASCADE"), nullable=False)
    client_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_client.id", ondelete="SET NULL"), nullable=True)
    kind = db.Column(db.String(20), nullable=False, default="research")
    title = db.Column(db.String(180), nullable=False)
    jurisdiction = db.Column(db.String(40), nullable=False, default="United States")
    messages = db.relationship("TaxGptMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="TaxGptMessage.created_at")


class TaxGptMessage(AuditMixin, db.Model):
    __tablename__ = "taxgpt_message"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_taxgpt_message_role"),
        CheckConstraint("feedback IS NULL OR feedback IN (-1, 1)", name="ck_taxgpt_message_feedback"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    conversation_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    feedback = db.Column(db.SmallInteger, nullable=True)
    conversation = db.relationship("TaxGptConversation", back_populates="messages")
    citations = db.relationship("TaxGptCitation", back_populates="message", cascade="all, delete-orphan")


class TaxGptCitation(AuditMixin, db.Model):
    __tablename__ = "taxgpt_citation"
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    message_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_message.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(240), nullable=False)
    publisher = db.Column(db.String(140), nullable=False)
    url = db.Column(db.String(700), nullable=False)
    excerpt = db.Column(db.Text, nullable=False)
    citation_order = db.Column(db.Integer, nullable=False, default=0)
    message = db.relationship("TaxGptMessage", back_populates="citations")


class TaxGptClient(AuditMixin, db.Model):
    __tablename__ = "taxgpt_client"
    __table_args__ = (
        CheckConstraint("entity_type IN ('individual', 'llc', 'partnership', 's_corp', 'c_corp', 'trust', 'nonprofit')", name="ck_taxgpt_client_entity_type"),
        db.Index("ix_taxgpt_client_workspace_name", "workspace_id", "name"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_workspace.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(180), nullable=False)
    entity_type = db.Column(db.String(30), nullable=False)
    jurisdiction = db.Column(db.String(80), nullable=False)
    tax_year = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text, nullable=False, default="")
    documents = db.relationship("TaxGptDocument", back_populates="client")


class TaxGptDocument(AuditMixin, db.Model):
    __tablename__ = "taxgpt_document"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'ready', 'failed')", name="ck_taxgpt_document_status"),
        db.Index("ix_taxgpt_document_workspace_created", "workspace_id", "created_at"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_workspace.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_user.id", ondelete="CASCADE"), nullable=False)
    client_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_client.id", ondelete="SET NULL"), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="ready")
    extracted_text = db.Column(db.Text, nullable=False, default="")
    content_blob = db.Column(db.LargeBinary, nullable=False)
    client = db.relationship("TaxGptClient", back_populates="documents")


class TaxGptDraft(AuditMixin, db.Model):
    __tablename__ = "taxgpt_draft"
    __table_args__ = (CheckConstraint("draft_type IN ('memo', 'client_email', 'notice_response', 'engagement_letter')", name="ck_taxgpt_draft_type"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_user.id", ondelete="CASCADE"), nullable=False)
    client_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_client.id", ondelete="SET NULL"), nullable=True)
    draft_type = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(240), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)


class TaxGptMatrix(AuditMixin, db.Model):
    __tablename__ = "taxgpt_matrix"
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_user.id", ondelete="CASCADE"), nullable=False)
    question = db.Column(db.String(1200), nullable=False)
    jurisdictions_json = db.Column(db.Text, nullable=False)
    results_json = db.Column(db.Text, nullable=False)


class TaxGptReview(AuditMixin, db.Model):
    __tablename__ = "taxgpt_review"
    __table_args__ = (CheckConstraint("status IN ('queued', 'reviewing', 'complete')", name="ck_taxgpt_review_status"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_user.id", ondelete="CASCADE"), nullable=False)
    document_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_document.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="complete")
    form_type = db.Column(db.String(30), nullable=False)
    findings_json = db.Column(db.Text, nullable=False)


class TaxGptWorkflowRun(AuditMixin, db.Model):
    __tablename__ = "taxgpt_workflow_run"
    __table_args__ = (
        CheckConstraint("status IN ('review_required', 'complete')", name="ck_taxgpt_workflow_run_status"),
        db.Index("ix_taxgpt_workflow_workspace_created", "workspace_id", "created_at"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_workspace.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_user.id", ondelete="CASCADE"), nullable=False)
    client_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("taxgpt_client.id", ondelete="SET NULL"), nullable=True)
    template_key = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="review_required")
    inputs_json = db.Column(db.Text, nullable=False)
    result_json = db.Column(db.Text, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
