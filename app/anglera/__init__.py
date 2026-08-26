"""Anglera catalog-enrichment bounded context inside the existing service."""

from datetime import timedelta

from flask import Flask, jsonify, request

from app.greptile.models import GreptileUser
from app.models import db
from .models import AngleraEvent, AngleraJob, AngleraMember, AngleraProduct, AngleraSource, AngleraWorkspace
from .routes import anglera_api
from .services import seed_demo_workspace, utcnow


ANGLERA_MODELS = (AngleraWorkspace, AngleraProduct, AngleraSource, AngleraMember, AngleraJob, AngleraEvent)


def _limit_payload_size():
    if request.content_length is not None and request.content_length > 3 * 1024 * 1024:
        return jsonify({"error": "Request body is too large"}), 413
    return None


def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if response.mimetype != "text/event-stream":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


anglera_api.before_request(_limit_payload_size)
anglera_api.after_request(_security_headers)


def register_anglera(app: Flask) -> None:
    app.register_blueprint(anglera_api)


def initialize_anglera_schema() -> None:
    """Create only additive anglera_* tables and seed the existing demo workspace."""
    db.metadata.create_all(bind=db.engine, tables=[model.__table__ for model in ANGLERA_MODELS])
    stale_before = utcnow() - timedelta(minutes=30)
    stale_jobs = AngleraJob.query.filter(AngleraJob.status.in_(["queued", "running"]), AngleraJob.updated_at < stale_before).all()
    for job in stale_jobs:
        job.status = "failed"
        job.error_message = "The service restarted before this operation completed. Please retry."
        job.completed_at = utcnow()
    demo_user = GreptileUser.query.filter_by(email="a@gmail.com", deleted_at=None).first()
    seed_demo_workspace(demo_user)
    db.session.commit()
