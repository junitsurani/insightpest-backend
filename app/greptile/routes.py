from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .auth import require_session
from app.models import db
from .models import GreptileContactLead, GreptileMessage, GreptilePullRequest, GreptileRepository, GreptileRule
from .services import answer_question, ensure_default_rules, repository_for_workspace
from .validation import ValidationError, optional_uuid, parse_repository_url, require_email, require_text, require_uuid

greptile_api = Blueprint("greptile_api", __name__, url_prefix="/api/greptile")
_rate_windows: dict[str, deque[float]] = defaultdict(deque)


def json_body(*allowed_fields: str) -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")
    unexpected = sorted(set(data) - set(allowed_fields))
    if unexpected:
        raise ValidationError(f"unexpected fields: {', '.join(unexpected)}")
    return data


def rate_limit(limit: int, seconds: int):
    def decorator(handler):
        @wraps(handler)
        def wrapped(*args, **kwargs):
            key = f"{getattr(g, 'workspace_id', request.remote_addr)}:{request.endpoint}"
            now = time.monotonic()
            window = _rate_windows[key]
            while window and window[0] <= now - seconds:
                window.popleft()
            if len(window) >= limit:
                return jsonify({"error": "Too many requests"}), 429
            window.append(now)
            return handler(*args, **kwargs)
        return wrapped
    return decorator


def serialize_repository(repo: GreptileRepository) -> dict:
    return {"id": str(repo.id), "owner": repo.owner, "name": repo.name, "provider": repo.provider, "defaultBranch": repo.default_branch, "status": repo.status, "progress": repo.progress, "lastIndexedAt": repo.last_indexed_at.isoformat().replace("+00:00", "Z") if repo.last_indexed_at else None}


def serialize_pull_request(pr: GreptilePullRequest) -> dict:
    return {"id": str(pr.id), "number": pr.number, "title": pr.title, "author": pr.author, "branch": pr.branch, "status": pr.status, "issueCount": pr.issue_count, "updatedAt": pr.updated_at.isoformat().replace("+00:00", "Z")}


def serialize_rule(rule: GreptileRule) -> dict:
    return {"id": str(rule.id), "text": rule.text, "enabled": rule.enabled}


@greptile_api.errorhandler(ValidationError)
def handle_validation(error: ValidationError):
    return jsonify({"error": str(error)}), 400


@greptile_api.errorhandler(SQLAlchemyError)
def handle_database_error(_error: SQLAlchemyError):
    db.session.rollback()
    return jsonify({"error": "The request could not be completed"}), 500


@greptile_api.get("/health")
def health():
    return jsonify({"status": "ok", "service": "greptile"})


@greptile_api.get("/repositories")
@require_session
def list_repositories():
    repos = GreptileRepository.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(GreptileRepository.created_at.asc()).all()
    return jsonify({"repositories": [serialize_repository(repo) for repo in repos]})


@greptile_api.post("/repositories")
@require_session
@rate_limit(20, 60)
def create_repository():
    data = json_body("url", "defaultBranch")
    identity = parse_repository_url(data.get("url"))
    branch = require_text(data.get("defaultBranch", "main"), "defaultBranch", maximum=120)
    repo = GreptileRepository(workspace_id=g.workspace_id, provider=identity.provider, owner=identity.owner, name=identity.name, default_branch=branch, status="ready", progress=100, last_indexed_at=datetime.now(timezone.utc))
    db.session.add(repo)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = GreptileRepository.query.filter_by(workspace_id=g.workspace_id, provider=identity.provider, owner=identity.owner, name=identity.name, deleted_at=None).first()
        return jsonify({"repository": serialize_repository(existing)}), 200
    return jsonify({"repository": serialize_repository(repo)}), 201


@greptile_api.post("/repositories/<repository_id>/sync")
@require_session
@rate_limit(30, 60)
def sync_repository(repository_id: str):
    repo_id = require_uuid(repository_id, "repositoryId")
    repo = repository_for_workspace(g.workspace_id, repo_id)
    if repo is None:
        return jsonify({"error": "Repository not found"}), 404
    repo.status, repo.progress, repo.last_indexed_at = "ready", 100, datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"repository": serialize_repository(repo)})


@greptile_api.get("/pull-requests")
@require_session
def list_pull_requests():
    repository_id = request.args.get("repositoryId")
    query = GreptilePullRequest.query.filter_by(workspace_id=g.workspace_id, deleted_at=None)
    if repository_id:
        query = query.filter_by(repository_id=require_uuid(repository_id, "repositoryId"))
    return jsonify({"pullRequests": [serialize_pull_request(pr) for pr in query.order_by(GreptilePullRequest.updated_at.desc()).all()]})


@greptile_api.post("/pull-requests/<pull_request_id>/review")
@require_session
@rate_limit(30, 60)
def review_pull_request(pull_request_id: str):
    pr_id = require_uuid(pull_request_id, "pullRequestId")
    pr = GreptilePullRequest.query.filter_by(id=pr_id, workspace_id=g.workspace_id, deleted_at=None).first()
    if pr is None:
        return jsonify({"error": "Pull request not found"}), 404
    pr.status = "issues_found" if pr.number in {271, 284} else "passed"
    pr.issue_count = 1 if pr.number == 271 else 2 if pr.number == 284 else 0
    db.session.commit()
    return jsonify({"pullRequest": serialize_pull_request(pr)})


@greptile_api.post("/query")
@require_session
@rate_limit(40, 60)
def query_repository():
    data = json_body("repositoryId", "question", "conversationId")
    repository_id = require_uuid(data.get("repositoryId"), "repositoryId")
    question = require_text(data.get("question"), "question", minimum=3, maximum=2000)
    conversation_id = optional_uuid(data.get("conversationId"), "conversationId")
    repo = repository_for_workspace(g.workspace_id, repository_id)
    if repo is None:
        return jsonify({"error": "Repository not found"}), 404
    _conversation, message = answer_question(repo, question, conversation_id)
    return jsonify({"messageId": str(message.id), "answer": message.content, "durationMs": message.duration_ms, "citations": [{"id": str(item.id), "path": item.path, "startLine": item.start_line, "endLine": item.end_line, "excerpt": item.excerpt} for item in message.citations]})


@greptile_api.post("/messages/<message_id>/feedback")
@require_session
def message_feedback(message_id: str):
    data = json_body("rating")
    rating = data.get("rating")
    if rating not in (-1, 1):
        raise ValidationError("rating must be 1 or -1")
    message = GreptileMessage.query.join(GreptileMessage.conversation).filter(GreptileMessage.id == require_uuid(message_id, "messageId"), GreptileMessage.deleted_at.is_(None)).first()
    if message is None or message.conversation.workspace_id != g.workspace_id:
        return jsonify({"error": "Message not found"}), 404
    message.feedback_rating = rating
    db.session.commit()
    return jsonify({"ok": True})


@greptile_api.get("/rules")
@require_session
def list_rules():
    return jsonify({"rules": [serialize_rule(rule) for rule in ensure_default_rules(g.workspace_id)]})


@greptile_api.post("/rules")
@require_session
@rate_limit(20, 60)
def create_rule():
    data = json_body("text")
    rule = GreptileRule(workspace_id=g.workspace_id, text=require_text(data.get("text"), "text", minimum=8, maximum=500), enabled=True)
    db.session.add(rule)
    db.session.commit()
    return jsonify({"rule": serialize_rule(rule)}), 201


@greptile_api.post("/rules/<rule_id>/toggle")
@require_session
def toggle_rule(rule_id: str):
    data = json_body("enabled")
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        raise ValidationError("enabled must be a boolean")
    rule = GreptileRule.query.filter_by(id=require_uuid(rule_id, "ruleId"), workspace_id=g.workspace_id, deleted_at=None).first()
    if rule is None:
        return jsonify({"error": "Rule not found"}), 404
    rule.enabled = enabled
    db.session.commit()
    return jsonify({"rule": serialize_rule(rule)})


@greptile_api.post("/contact")
@rate_limit(10, 60)
def contact_sales():
    data = json_body("name", "email", "company", "message")
    lead = GreptileContactLead(name=require_text(data.get("name"), "name", maximum=120), email=require_email(data.get("email")), company=require_text(data.get("company"), "company", maximum=160), message=require_text(data.get("message"), "message", minimum=10, maximum=4000))
    db.session.add(lead)
    db.session.commit()
    return jsonify({"id": str(lead.id), "message": "Thanks — our team will be in touch."}), 201
