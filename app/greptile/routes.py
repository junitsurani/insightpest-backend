from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.models import db
from .audit_service import run_codebase_audit
from .auth import require_session
from .llm_engine import LLMConfigurationError, LLMResponseError
from .models import GreptileAuditRun, GreptileContactLead, GreptileConversation, GreptileMessage, GreptilePullRequest, GreptileRepository, GreptileRepositorySnapshot, GreptileRule
from .pull_request_service import review_pull_request as review_live_pull_request, sync_pull_requests
from .repository_indexer import RepositoryConnectionError, index_repository
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
    snapshot = GreptileRepositorySnapshot.query.filter_by(repository_id=repo.id, deleted_at=None).order_by(GreptileRepositorySnapshot.created_at.desc()).first()
    return {
        "id": str(repo.id), "owner": repo.owner, "name": repo.name, "provider": repo.provider,
        "defaultBranch": repo.default_branch,
        "status": snapshot.status if snapshot else "queued",
        "progress": repo.progress if snapshot else 0,
        "lastIndexedAt": repo.last_indexed_at.isoformat().replace("+00:00", "Z") if snapshot and repo.last_indexed_at else None,
        "remoteUrl": snapshot.remote_url if snapshot else f"https://{repo.provider}.com/{repo.owner}/{repo.name}",
        "commitSha": snapshot.commit_sha if snapshot else None,
        "fileCount": snapshot.file_count if snapshot else 0,
        "indexedFileCount": snapshot.indexed_file_count if snapshot else 0,
        "totalBytes": snapshot.total_bytes if snapshot else 0,
        "indexError": snapshot.error_message if snapshot and snapshot.status == "failed" else None,
    }


def serialize_pull_request(pr: GreptilePullRequest) -> dict:
    return {"id": str(pr.id), "number": pr.number, "title": pr.title, "author": pr.author, "branch": pr.branch, "status": pr.status, "issueCount": pr.issue_count, "updatedAt": pr.updated_at.isoformat().replace("+00:00", "Z")}


def serialize_rule(rule: GreptileRule) -> dict:
    return {"id": str(rule.id), "text": rule.text, "enabled": rule.enabled}


def serialize_audit(run: GreptileAuditRun, include_findings: bool = True) -> dict:
    result = {
        "id": str(run.id), "repositoryId": str(run.repository_id), "status": run.status,
        "score": run.score, "summary": run.summary, "model": run.model,
        "llmStatus": run.llm_status, "fileCount": run.file_count,
        "createdAt": run.created_at.isoformat().replace("+00:00", "Z"),
        "completedAt": run.completed_at.isoformat().replace("+00:00", "Z") if run.completed_at else None,
        "findingCount": len(run.findings),
    }
    if include_findings:
        result["findings"] = [{
            "id": str(item.id), "path": item.path, "startLine": item.start_line,
            "endLine": item.end_line, "severity": item.severity, "category": item.category,
            "title": item.title, "description": item.description,
            "recommendation": item.recommendation, "evidence": item.evidence,
        } for item in run.findings]
    return result


def serialize_citation(item) -> dict:
    repository, separator, path = item.path.partition("::")
    return {
        "id": str(item.id),
        "path": path if separator else item.path,
        "repository": repository if separator else None,
        "startLine": item.start_line,
        "endLine": item.end_line,
        "excerpt": item.excerpt,
    }


def serialize_conversation(item: GreptileConversation) -> dict:
    return {
        "id": str(item.id),
        "repositoryId": str(item.repository_id),
        "title": item.title,
        "messageCount": sum(1 for message in item.messages if message.deleted_at is None),
        "updatedAt": item.updated_at.isoformat().replace("+00:00", "Z"),
    }


def serialize_message(item: GreptileMessage) -> dict:
    return {
        "id": str(item.id),
        "role": item.role,
        "content": item.content,
        "durationMs": item.duration_ms,
        "feedbackRating": item.feedback_rating,
        "citations": [serialize_citation(citation) for citation in item.citations if citation.deleted_at is None],
    }


@greptile_api.errorhandler(ValidationError)
def handle_validation(error: ValidationError):
    return jsonify({"error": str(error)}), 400


@greptile_api.errorhandler(SQLAlchemyError)
def handle_database_error(_error: SQLAlchemyError):
    db.session.rollback()
    return jsonify({"error": "The request could not be completed"}), 500


@greptile_api.errorhandler(RepositoryConnectionError)
def handle_repository_connection(error: RepositoryConnectionError):
    db.session.rollback()
    return jsonify({"error": str(error)}), 422


@greptile_api.errorhandler(LLMConfigurationError)
def handle_llm_configuration(error: LLMConfigurationError):
    db.session.rollback()
    return jsonify({"error": str(error)}), 503


@greptile_api.errorhandler(LLMResponseError)
def handle_llm_response(error: LLMResponseError):
    db.session.rollback()
    return jsonify({"error": str(error)}), 422


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
    existing = GreptileRepository.query.filter_by(
        workspace_id=g.workspace_id, provider=identity.provider, owner=identity.owner,
        name=identity.name, deleted_at=None,
    ).first()
    if existing:
        index_repository(existing)
        return jsonify({"repository": serialize_repository(existing)}), 200
    repo = GreptileRepository(
        workspace_id=g.workspace_id, provider=identity.provider, owner=identity.owner,
        name=identity.name, default_branch=branch, status="queued", progress=0,
    )
    db.session.add(repo)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = GreptileRepository.query.filter_by(workspace_id=g.workspace_id, provider=identity.provider, owner=identity.owner, name=identity.name, deleted_at=None).first()
        if existing is None:
            raise
        index_repository(existing)
        return jsonify({"repository": serialize_repository(existing)}), 200
    index_repository(repo)
    return jsonify({"repository": serialize_repository(repo)}), 201


@greptile_api.post("/repositories/<repository_id>/sync")
@require_session
@rate_limit(30, 60)
def sync_repository(repository_id: str):
    repo_id = require_uuid(repository_id, "repositoryId")
    repo = repository_for_workspace(g.workspace_id, repo_id)
    if repo is None:
        return jsonify({"error": "Repository not found"}), 404
    index_repository(repo)
    return jsonify({"repository": serialize_repository(repo)})


@greptile_api.get("/repositories/<repository_id>/index")
@require_session
def repository_index(repository_id: str):
    repo = repository_for_workspace(g.workspace_id, require_uuid(repository_id, "repositoryId"))
    if repo is None:
        return jsonify({"error": "Repository not found"}), 404
    return jsonify({"repository": serialize_repository(repo)})


@greptile_api.get("/audits")
@require_session
def list_audits():
    query = GreptileAuditRun.query.filter_by(workspace_id=g.workspace_id, deleted_at=None)
    repository_id = request.args.get("repositoryId")
    if repository_id:
        query = query.filter_by(repository_id=require_uuid(repository_id, "repositoryId"))
    runs = query.order_by(GreptileAuditRun.created_at.desc()).limit(30).all()
    return jsonify({"audits": [serialize_audit(run) for run in runs]})


@greptile_api.post("/repositories/<repository_id>/audits")
@require_session
@rate_limit(10, 60)
def create_audit(repository_id: str):
    repo = repository_for_workspace(g.workspace_id, require_uuid(repository_id, "repositoryId"))
    if repo is None:
        return jsonify({"error": "Repository not found"}), 404
    run = run_codebase_audit(repo)
    return jsonify({"audit": serialize_audit(run)}), 201


@greptile_api.get("/audits/<audit_id>")
@require_session
def get_audit(audit_id: str):
    run = GreptileAuditRun.query.filter_by(
        id=require_uuid(audit_id, "auditId"), workspace_id=g.workspace_id, deleted_at=None
    ).first()
    if run is None:
        return jsonify({"error": "Audit not found"}), 404
    return jsonify({"audit": serialize_audit(run)})


@greptile_api.get("/pull-requests")
@require_session
def list_pull_requests():
    repository_id = request.args.get("repositoryId")
    query = GreptilePullRequest.query.filter_by(workspace_id=g.workspace_id, deleted_at=None)
    if repository_id:
        query = query.filter_by(repository_id=require_uuid(repository_id, "repositoryId"))
    return jsonify({"pullRequests": [serialize_pull_request(pr) for pr in query.order_by(GreptilePullRequest.updated_at.desc(), GreptilePullRequest.number.desc()).all()]})


@greptile_api.post("/repositories/<repository_id>/pull-requests/sync")
@require_session
@rate_limit(20, 60)
def sync_repository_pull_requests(repository_id: str):
    repository = repository_for_workspace(g.workspace_id, require_uuid(repository_id, "repositoryId"))
    if repository is None:
        return jsonify({"error": "Repository not found"}), 404
    pull_requests = sync_pull_requests(repository)
    return jsonify({"pullRequests": [serialize_pull_request(item) for item in pull_requests]})


@greptile_api.post("/pull-requests/<pull_request_id>/review")
@require_session
@rate_limit(30, 60)
def review_pull_request(pull_request_id: str):
    pr_id = require_uuid(pull_request_id, "pullRequestId")
    pr = GreptilePullRequest.query.filter_by(id=pr_id, workspace_id=g.workspace_id, deleted_at=None).first()
    if pr is None:
        return jsonify({"error": "Pull request not found"}), 404
    repository = repository_for_workspace(g.workspace_id, pr.repository_id)
    if repository is None:
        return jsonify({"error": "Repository not found"}), 404
    review_live_pull_request(pr, repository)
    return jsonify({"pullRequest": serialize_pull_request(pr)})


@greptile_api.get("/conversations")
@require_session
def list_conversations():
    rows = GreptileConversation.query.filter_by(
        workspace_id=g.workspace_id,
        deleted_at=None,
    ).options(selectinload(GreptileConversation.messages)).order_by(GreptileConversation.updated_at.desc()).limit(30).all()
    return jsonify({"conversations": [serialize_conversation(item) for item in rows]})


@greptile_api.get("/conversations/<conversation_id>")
@require_session
def get_conversation(conversation_id: str):
    conversation = GreptileConversation.query.filter_by(
        id=require_uuid(conversation_id, "conversationId"),
        workspace_id=g.workspace_id,
        deleted_at=None,
    ).options(
        selectinload(GreptileConversation.messages).selectinload(GreptileMessage.citations)
    ).first()
    if conversation is None:
        return jsonify({"error": "Conversation not found"}), 404
    return jsonify({
        "conversation": serialize_conversation(conversation),
        "messages": [serialize_message(item) for item in conversation.messages if item.deleted_at is None],
    })


@greptile_api.delete("/conversations/<conversation_id>")
@require_session
def delete_conversation(conversation_id: str):
    conversation = GreptileConversation.query.filter_by(
        id=require_uuid(conversation_id, "conversationId"),
        workspace_id=g.workspace_id,
        deleted_at=None,
    ).first()
    if conversation is None:
        return jsonify({"error": "Conversation not found"}), 404
    now = datetime.now(timezone.utc)
    conversation.deleted_at = now
    for message in conversation.messages:
        message.deleted_at = now
        for citation in message.citations:
            citation.deleted_at = now
    db.session.commit()
    return jsonify({"ok": True})


@greptile_api.post("/query")
@require_session
@rate_limit(40, 60)
def query_repository():
    data = json_body("repositoryId", "repositoryIds", "question", "conversationId")
    raw_repository_ids = data.get("repositoryIds")
    if raw_repository_ids is None:
        raw_repository_ids = [data.get("repositoryId")]
    if not isinstance(raw_repository_ids, list) or not 1 <= len(raw_repository_ids) <= 4:
        raise ValidationError("repositoryIds must contain between 1 and 4 repository IDs")
    repository_ids = []
    for raw_id in raw_repository_ids:
        parsed = require_uuid(raw_id, "repositoryId")
        if parsed not in repository_ids:
            repository_ids.append(parsed)
    question = require_text(data.get("question"), "question", minimum=3, maximum=2000)
    conversation_id = optional_uuid(data.get("conversationId"), "conversationId")
    repositories = [repository_for_workspace(g.workspace_id, repository_id) for repository_id in repository_ids]
    if any(repository is None for repository in repositories):
        return jsonify({"error": "Repository not found"}), 404
    conversation, message = answer_question(repositories, question, conversation_id)
    return jsonify({
        "conversationId": str(conversation.id),
        "messageId": str(message.id),
        "answer": message.content,
        "durationMs": message.duration_ms,
        "citations": [serialize_citation(item) for item in message.citations],
    })


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


@greptile_api.post("/product-feedback")
@require_session
@rate_limit(10, 60)
def product_feedback():
    data = json_body("message")
    user = g.greptile_user
    lead = GreptileContactLead(
        name=user.display_name,
        email=user.email,
        company="Greptile product feedback",
        message=require_text(data.get("message"), "message", minimum=10, maximum=4000),
    )
    db.session.add(lead)
    db.session.commit()
    return jsonify({"id": str(lead.id), "message": "Feedback recorded."}), 201


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
