"""Greptile bounded context hosted inside the existing Pestcontrol service."""

from flask import Flask, jsonify, request

from app.models import db

from .auth import greptile_auth
from .models import (
    GreptileAuditFinding,
    GreptileAuditRun,
    GreptileCitation,
    GreptileCodeFile,
    GreptileContactLead,
    GreptileConversation,
    GreptileMessage,
    GreptilePullRequest,
    GreptileRepository,
    GreptileRepositorySnapshot,
    GreptileRule,
    GreptileSession,
    GreptileUser,
    GreptileWorkspace,
)
from .routes import greptile_api
from .services import seed_demo_user


GREPTILE_MODELS = (
    GreptileWorkspace,
    GreptileUser,
    GreptileSession,
    GreptileRepository,
    GreptileRepositorySnapshot,
    GreptileCodeFile,
    GreptileAuditRun,
    GreptileAuditFinding,
    GreptileConversation,
    GreptileMessage,
    GreptileCitation,
    GreptilePullRequest,
    GreptileRule,
    GreptileContactLead,
)


def _limit_payload_size():
    if request.content_length is not None and request.content_length > 64 * 1024:
        return jsonify({"error": "Request body is too large"}), 413
    return None


def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


for blueprint in (greptile_auth, greptile_api):
    blueprint.before_request(_limit_payload_size)
    blueprint.after_request(_security_headers)


def register_greptile(app: Flask) -> None:
    app.register_blueprint(greptile_auth)
    app.register_blueprint(greptile_api)


def initialize_greptile_schema() -> None:
    """Create only additive greptile_* tables and seed the local demo account."""
    db.metadata.create_all(bind=db.engine, tables=[model.__table__ for model in GREPTILE_MODELS])
    seed_demo_user()
