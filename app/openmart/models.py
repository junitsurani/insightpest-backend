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
    source_system = db.Column(db.String(40), nullable=False, default="openmart_clone")


class OpenmartRateEvent(AuditMixin, db.Model):
    __tablename__ = "openmart_rate_event"
    __table_args__ = (db.Index("ix_openmart_rate_scope_subject_created", "scope", "subject_hash", "created_at"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    scope = db.Column(db.String(40), nullable=False)
    subject_hash = db.Column(db.String(64), nullable=False)


class OpenmartWorkspace(AuditMixin, db.Model):
    __tablename__ = "openmart_workspace"
    __table_args__ = (CheckConstraint("plan IN ('free', 'starter', 'pro', 'enterprise')", name="ck_openmart_workspace_plan"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    name = db.Column(db.String(160), nullable=False)
    plan = db.Column(db.String(20), nullable=False, default="free")
    credits_balance = db.Column(db.Integer, nullable=False, default=200)
    default_country = db.Column(db.String(2), nullable=False, default="US")
    users = db.relationship("OpenmartUser", back_populates="workspace", cascade="all, delete-orphan")


class OpenmartUser(AuditMixin, db.Model):
    __tablename__ = "openmart_user"
    __table_args__ = (
        db.UniqueConstraint("email", name="uq_openmart_user_email"),
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_openmart_user_role"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    email = db.Column(db.String(254), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="owner")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    workspace = db.relationship("OpenmartWorkspace", back_populates="users")
    sessions = db.relationship("OpenmartSession", back_populates="user", cascade="all, delete-orphan")


class OpenmartSession(AuditMixin, db.Model):
    __tablename__ = "openmart_session"
    __table_args__ = (db.UniqueConstraint("token_hash", name="uq_openmart_session_token_hash"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_user.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    user = db.relationship("OpenmartUser", back_populates="sessions")


class OpenmartBusiness(AuditMixin, db.Model):
    __tablename__ = "openmart_business"
    __table_args__ = (
        db.UniqueConstraint("workspace_id", "external_id", name="uq_openmart_business_workspace_external"),
        db.Index("ix_openmart_business_workspace_name", "workspace_id", "name"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(120), nullable=False)
    street = db.Column(db.String(240), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    region = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(2), nullable=False, default="US")
    postal_code = db.Column(db.String(20), nullable=False, default="")
    website = db.Column(db.String(500), nullable=False, default="")
    phone = db.Column(db.String(40), nullable=False, default="")
    company_email = db.Column(db.String(254), nullable=False, default="")
    owner_name = db.Column(db.String(160), nullable=False, default="")
    owner_title = db.Column(db.String(120), nullable=False, default="")
    owner_email = db.Column(db.String(254), nullable=False, default="")
    owner_phone = db.Column(db.String(40), nullable=False, default="")
    rating = db.Column(db.Float, nullable=False, default=0)
    review_count = db.Column(db.Integer, nullable=False, default=0)
    employee_count = db.Column(db.Integer, nullable=False, default=0)
    revenue_estimate = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="lead")
    is_enriched = db.Column(db.Boolean, nullable=False, default=False)


class OpenmartLeadList(AuditMixin, db.Model):
    __tablename__ = "openmart_lead_list"
    __table_args__ = (db.Index("ix_openmart_list_workspace_updated", "workspace_id", "updated_at"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_workspace.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_user.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(800), nullable=False, default="")
    items = db.relationship("OpenmartLeadListItem", back_populates="lead_list", cascade="all, delete-orphan")


class OpenmartLeadListItem(AuditMixin, db.Model):
    __tablename__ = "openmart_lead_list_item"
    __table_args__ = (
        db.UniqueConstraint("lead_list_id", "business_id", name="uq_openmart_list_business"),
        CheckConstraint("contact_status IN ('lead', 'contacted', 'replied', 'qualified', 'archived')", name="ck_openmart_item_status"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    lead_list_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_lead_list.id", ondelete="CASCADE"), nullable=False, index=True)
    business_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_business.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_status = db.Column(db.String(20), nullable=False, default="lead")
    notes = db.Column(db.String(2000), nullable=False, default="")
    lead_list = db.relationship("OpenmartLeadList", back_populates="items")
    business = db.relationship("OpenmartBusiness")


class OpenmartSavedSearch(AuditMixin, db.Model):
    __tablename__ = "openmart_saved_search"
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_user.id", ondelete="CASCADE"), nullable=False)
    search_query = db.Column("query", db.String(240), nullable=False)
    location = db.Column(db.String(240), nullable=False)
    filters_json = db.Column(db.Text, nullable=False, default="{}")
    result_count = db.Column(db.Integer, nullable=False, default=0)


class OpenmartExport(AuditMixin, db.Model):
    __tablename__ = "openmart_export"
    __table_args__ = (CheckConstraint("format IN ('csv', 'xlsx')", name="ck_openmart_export_format"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_user.id", ondelete="CASCADE"), nullable=False)
    lead_list_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_lead_list.id", ondelete="SET NULL"), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    format = db.Column(db.String(10), nullable=False, default="csv")
    fields_json = db.Column(db.Text, nullable=False)
    row_count = db.Column(db.Integer, nullable=False, default=0)


class OpenmartSequence(AuditMixin, db.Model):
    __tablename__ = "openmart_sequence"
    __table_args__ = (CheckConstraint("status IN ('draft', 'active', 'paused', 'completed')", name="ck_openmart_sequence_status"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_user.id", ondelete="CASCADE"), nullable=False)
    lead_list_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_lead_list.id", ondelete="SET NULL"), nullable=True)
    name = db.Column(db.String(180), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")
    sender_email = db.Column(db.String(254), nullable=False, default="")
    sent_count = db.Column(db.Integer, nullable=False, default=0)
    reply_count = db.Column(db.Integer, nullable=False, default=0)
    steps = db.relationship("OpenmartSequenceStep", back_populates="sequence", cascade="all, delete-orphan", order_by="OpenmartSequenceStep.step_order")


class OpenmartSequenceStep(AuditMixin, db.Model):
    __tablename__ = "openmart_sequence_step"
    __table_args__ = (db.UniqueConstraint("sequence_id", "step_order", name="uq_openmart_sequence_step_order"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    sequence_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_sequence.id", ondelete="CASCADE"), nullable=False, index=True)
    step_order = db.Column(db.Integer, nullable=False)
    delay_days = db.Column(db.Integer, nullable=False, default=0)
    subject = db.Column(db.String(240), nullable=False)
    body = db.Column(db.Text, nullable=False)
    sequence = db.relationship("OpenmartSequence", back_populates="steps")


class OpenmartApiKey(AuditMixin, db.Model):
    __tablename__ = "openmart_api_key"
    __table_args__ = (db.UniqueConstraint("key_hash", name="uq_openmart_api_key_hash"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_user.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    key_prefix = db.Column(db.String(16), nullable=False)
    key_hash = db.Column(db.String(64), nullable=False)
    last_used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)


class OpenmartUsageEvent(AuditMixin, db.Model):
    __tablename__ = "openmart_usage_event"
    __table_args__ = (db.Index("ix_openmart_usage_workspace_created", "workspace_id", "created_at"),)
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_workspace.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_user.id", ondelete="CASCADE"), nullable=False)
    event_type = db.Column(db.String(60), nullable=False)
    subject = db.Column(db.String(240), nullable=False)
    credits_delta = db.Column(db.Integer, nullable=False, default=0)


class OpenmartInvitation(AuditMixin, db.Model):
    __tablename__ = "openmart_invitation"
    __table_args__ = (
        db.UniqueConstraint("workspace_id", "email", name="uq_openmart_invitation_workspace_email"),
        CheckConstraint("role IN ('admin', 'member')", name="ck_openmart_invitation_role"),
        CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="ck_openmart_invitation_status"),
    )
    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    invited_by_id = db.Column(Uuid(as_uuid=True), db.ForeignKey("openmart_user.id", ondelete="CASCADE"), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="member")
    status = db.Column(db.String(20), nullable=False, default="pending")
