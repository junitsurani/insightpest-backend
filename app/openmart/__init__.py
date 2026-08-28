"""Openmart bounded context hosted inside the shared Pestcontrol service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Flask, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from app.models import db
from .auth import openmart_auth
from .models import (
    OpenmartApiKey, OpenmartBusiness, OpenmartExport, OpenmartInvitation,
    OpenmartLeadList, OpenmartLeadListItem, OpenmartRateEvent, OpenmartSavedSearch,
    OpenmartSequence, OpenmartSequenceStep, OpenmartSession, OpenmartUsageEvent,
    OpenmartUser, OpenmartWorkspace,
)
from .routes import openmart_api
from .services import seed_demo_user, seed_demo_workspace


OPENMART_MODELS = (
    OpenmartRateEvent, OpenmartWorkspace, OpenmartUser, OpenmartSession,
    OpenmartBusiness, OpenmartLeadList, OpenmartLeadListItem, OpenmartSavedSearch,
    OpenmartExport, OpenmartSequence, OpenmartSequenceStep, OpenmartApiKey,
    OpenmartUsageEvent, OpenmartInvitation,
)


def _limit_payload_size():
    origin = request.headers.get("Origin", "").rstrip("/")
    same_origin = request.host_url.rstrip("/")
    trusted = set(current_app.config.get("OPENMART_TRUSTED_ORIGINS", ()))
    if origin and origin != same_origin and origin not in trusted:
        return jsonify({"error": "Origin is not allowed"}), 403
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    maximum = int(current_app.config.get("OPENMART_MAX_BODY_BYTES", 1024 * 1024))
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
    current_app.logger.exception("Unhandled Openmart request failure")
    return jsonify({"error": "The request could not be completed"}), 500


for blueprint in (openmart_auth, openmart_api):
    blueprint.before_request(_limit_payload_size)
    blueprint.after_request(_security_headers)
    blueprint.register_error_handler(Exception, _unexpected_error)


def register_openmart(app: Flask) -> None:
    app.register_blueprint(openmart_auth)
    app.register_blueprint(openmart_api)


def initialize_openmart_schema() -> None:
    if current_app.config.get("OPENMART_AUTO_CREATE_TABLES", True):
        db.metadata.create_all(bind=db.engine, tables=[model.__table__ for model in OPENMART_MODELS])
    demo_user = seed_demo_user()
    seed_demo_workspace(demo_user)
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    OpenmartRateEvent.query.filter(OpenmartRateEvent.created_at < cutoff).delete(synchronize_session=False)
    session_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    OpenmartSession.query.filter((OpenmartSession.expires_at < session_cutoff) | (OpenmartSession.revoked_at < session_cutoff)).delete(synchronize_session=False)
    db.session.commit()
