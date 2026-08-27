"""TaxGPT bounded context hosted inside the shared Pestcontrol service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Flask, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from app.models import db

from .auth import taxgpt_auth
from .models import (
    TaxGptCitation,
    TaxGptClient,
    TaxGptConversation,
    TaxGptDemoRequest,
    TaxGptDocument,
    TaxGptDraft,
    TaxGptMatrix,
    TaxGptMessage,
    TaxGptRateEvent,
    TaxGptReview,
    TaxGptSession,
    TaxGptUser,
    TaxGptWorkflowRun,
    TaxGptWorkspace,
)
from .routes import taxgpt_api


TAXGPT_MODELS = (
    TaxGptDemoRequest,
    TaxGptRateEvent,
    TaxGptWorkspace,
    TaxGptUser,
    TaxGptSession,
    TaxGptClient,
    TaxGptConversation,
    TaxGptMessage,
    TaxGptCitation,
    TaxGptDocument,
    TaxGptDraft,
    TaxGptMatrix,
    TaxGptReview,
    TaxGptWorkflowRun,
)


def _limit_payload_size():
    origin = request.headers.get("Origin", "").rstrip("/")
    same_origin = request.host_url.rstrip("/")
    trusted = set(current_app.config.get("TAXGPT_TRUSTED_ORIGINS", ()))
    if origin and origin != same_origin and origin not in trusted:
        return jsonify({"error": "Origin is not allowed"}), 403
    if request.method not in {"POST", "PUT", "PATCH"}:
        return None
    upload_path = request.path == "/api/taxgpt/documents"
    maximum = int(current_app.config.get("TAXGPT_MAX_FILE_BYTES", 10 * 1024 * 1024)) + 32 * 1024
    if not upload_path:
        maximum = 64 * 1024
    if request.content_length is not None and request.content_length > maximum:
        return jsonify({"error": "Request body is too large"}), 413
    return None


def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


def _unexpected_error(error):
    if isinstance(error, HTTPException):
        return jsonify({"error": error.description}), error.code
    db.session.rollback()
    current_app.logger.exception("Unhandled TaxGPT request failure")
    return jsonify({"error": "The request could not be completed"}), 500


for blueprint in (taxgpt_auth, taxgpt_api):
    blueprint.before_request(_limit_payload_size)
    blueprint.after_request(_security_headers)
    blueprint.register_error_handler(Exception, _unexpected_error)


def register_taxgpt(app: Flask) -> None:
    app.register_blueprint(taxgpt_auth)
    app.register_blueprint(taxgpt_api)


def initialize_taxgpt_schema() -> None:
    """Create only additive taxgpt_* tables with check-first semantics."""
    if current_app.config.get("TAXGPT_AUTO_CREATE_TABLES", True):
        db.metadata.create_all(bind=db.engine, tables=[model.__table__ for model in TAXGPT_MODELS])
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    TaxGptRateEvent.query.filter(TaxGptRateEvent.created_at < cutoff).delete(synchronize_session=False)
    session_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    TaxGptSession.query.filter(
        (TaxGptSession.expires_at < session_cutoff) | (TaxGptSession.revoked_at < session_cutoff)
    ).delete(synchronize_session=False)
    db.session.commit()
