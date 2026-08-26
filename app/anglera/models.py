from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Uuid

from app.models import db


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    source_system = db.Column(db.String(40), nullable=False, default="anglera_clone")


class AngleraWorkspace(AuditMixin, db.Model):
    __tablename__ = "anglera_workspace"

    id = db.Column(Uuid(as_uuid=True), primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    primary_domain = db.Column(db.String(500), nullable=False, default="https://www.makitatools.com")
    crawl_depth = db.Column(db.String(30), nullable=False, default="product-and-docs")
    include_pdf_manuals = db.Column(db.Boolean, nullable=False, default=True)
    respect_robots = db.Column(db.Boolean, nullable=False, default=True)
    automatic_enrichment = db.Column(db.Boolean, nullable=False, default=True)


class AngleraProduct(AuditMixin, db.Model):
    __tablename__ = "anglera_product"
    __table_args__ = (
        db.UniqueConstraint("workspace_id", "sku", name="uq_anglera_product_workspace_sku"),
        db.Index("ix_anglera_product_workspace_status", "workspace_id", "status"),
        db.Index("ix_anglera_product_workspace_updated", "workspace_id", "updated_at"),
        CheckConstraint("status IN ('ready', 'processing', 'needs-review')", name="ck_anglera_product_status"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_anglera_product_confidence"),
        CheckConstraint("source_count >= 0", name="ck_anglera_product_source_count"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="needs-review")
    name = db.Column(db.String(240), nullable=False)
    sku = db.Column(db.String(120), nullable=False)
    image_url = db.Column(db.String(1000), nullable=False, default="/anglera-assets/products/dp4020.png")
    specification = db.Column(db.Text, nullable=False, default="Awaiting enrichment")
    source_count = db.Column(db.Integer, nullable=False, default=1)
    confidence = db.Column(db.Integer, nullable=False, default=0)


class AngleraSource(AuditMixin, db.Model):
    __tablename__ = "anglera_source"
    __table_args__ = (
        db.UniqueConstraint("workspace_id", "location", name="uq_anglera_source_workspace_location"),
        db.Index("ix_anglera_source_workspace_status", "workspace_id", "status"),
        CheckConstraint("source_type IN ('Website', 'Document', 'Catalog feed')", name="ck_anglera_source_type"),
        CheckConstraint("status IN ('Connected', 'Syncing', 'Needs attention')", name="ck_anglera_source_status"),
        CheckConstraint("record_count >= 0", name="ck_anglera_source_record_count"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    source_type = db.Column(db.String(30), nullable=False)
    location = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Connected")
    record_count = db.Column(db.Integer, nullable=False, default=0)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_error = db.Column(db.String(500), nullable=True)
    content_text = db.Column(db.Text, nullable=True)
    content_etag = db.Column(db.String(160), nullable=True)


class AngleraMember(AuditMixin, db.Model):
    __tablename__ = "anglera_member"
    __table_args__ = (
        db.UniqueConstraint("workspace_id", "email", name="uq_anglera_member_workspace_email"),
        db.Index("ix_anglera_member_workspace_status", "workspace_id", "status"),
        CheckConstraint("role IN ('Owner', 'Admin', 'Editor', 'Viewer')", name="ck_anglera_member_role"),
        CheckConstraint("status IN ('Active', 'Invited')", name="ck_anglera_member_status"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), nullable=False)
    user_id = db.Column(Uuid(as_uuid=True), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="Editor")
    status = db.Column(db.String(20), nullable=False, default="Invited")
    invited_by_user_id = db.Column(Uuid(as_uuid=True), nullable=True)
    invitation_token_hash = db.Column(db.String(64), nullable=True, unique=True)
    invitation_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)


class AngleraJob(AuditMixin, db.Model):
    __tablename__ = "anglera_job"
    __table_args__ = (
        db.UniqueConstraint("workspace_id", "idempotency_key", name="uq_anglera_job_idempotency"),
        db.Index("ix_anglera_job_workspace_status", "workspace_id", "status"),
        CheckConstraint("kind IN ('enrich-products', 'sync-sources')", name="ck_anglera_job_kind"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_anglera_job_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_anglera_job_progress"),
    )

    id = db.Column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    workspace_id = db.Column(Uuid(as_uuid=True), nullable=False)
    requested_by_user_id = db.Column(Uuid(as_uuid=True), nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="queued")
    progress = db.Column(db.Integer, nullable=False, default=0)
    idempotency_key = db.Column(db.String(80), nullable=False)
    payload_json = db.Column(db.JSON, nullable=False, default=dict)
    result_json = db.Column(db.JSON, nullable=True)
    error_message = db.Column(db.String(500), nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)


class AngleraEvent(db.Model):
    __tablename__ = "anglera_event"
    __table_args__ = (db.Index("ix_anglera_event_workspace_id", "workspace_id", "id"),)

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    workspace_id = db.Column(Uuid(as_uuid=True), nullable=False)
    actor_user_id = db.Column(Uuid(as_uuid=True), nullable=True)
    event_type = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.String(80), nullable=True)
    payload_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
