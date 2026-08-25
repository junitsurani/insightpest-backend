from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.models import db

from .llm_engine import LLMResponseError, generate_grounded_answer
from .models import GreptileCitation, GreptileCodeFile, GreptileConversation, GreptileMessage, GreptileRepository, GreptileRepositorySnapshot, GreptileRule, GreptileUser, GreptileWorkspace


DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def ensure_workspace(workspace_id: uuid.UUID) -> GreptileWorkspace:
    workspace = GreptileWorkspace.query.filter_by(id=workspace_id, deleted_at=None).first()
    if workspace:
        return workspace
    workspace = GreptileWorkspace(id=workspace_id, name="Demo workspace")
    db.session.add(workspace)
    try:
        db.session.commit()
    except IntegrityError:
        # Two first requests for the same workspace can race. The primary key
        # makes the operation idempotent; the loser reloads the committed row.
        db.session.rollback()
        workspace = GreptileWorkspace.query.filter_by(id=workspace_id, deleted_at=None).first()
        if workspace is None:
            raise
    return workspace


def seed_demo_user() -> GreptileUser:
    """Idempotently seed the local Greptile account without touching Paces data."""
    email = os.getenv("GREPTILE_SEED_EMAIL", "a@gmail.com").strip().lower()
    password = os.getenv("GREPTILE_SEED_PASSWORD", "1")
    display_name = os.getenv("GREPTILE_SEED_DISPLAY_NAME", "Junits Demo")
    workspace = ensure_workspace(DEFAULT_WORKSPACE_ID)
    user = GreptileUser.query.filter_by(email=email, deleted_at=None).first()
    if user:
        return user
    user = GreptileUser(
        workspace_id=workspace.id,
        email=email,
        display_name=display_name,
        password_hash=generate_password_hash(password),
        is_active=True,
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        user = GreptileUser.query.filter_by(email=email, deleted_at=None).first()
        if user is None:
            raise
    return user


def ensure_default_rules(workspace_id: uuid.UUID) -> list[GreptileRule]:
    rules = GreptileRule.query.filter_by(workspace_id=workspace_id, deleted_at=None).order_by(GreptileRule.created_at.asc()).all()
    if rules:
        return rules
    rules = [
        GreptileRule(workspace_id=workspace_id, text="Verify authorization before every workspace-scoped database read."),
        GreptileRule(workspace_id=workspace_id, text="Flag retry handlers that are not idempotent."),
        GreptileRule(workspace_id=workspace_id, text="Require tests when payment or subscription behavior changes."),
        GreptileRule(workspace_id=workspace_id, text="Do not expose internal errors or stack traces in API responses."),
    ]
    db.session.add_all(rules)
    db.session.commit()
    return rules


def repository_for_workspace(workspace_id: uuid.UUID, repository_id: uuid.UUID) -> GreptileRepository | None:
    return GreptileRepository.query.filter_by(id=repository_id, workspace_id=workspace_id, deleted_at=None).first()


def answer_question(repositories: list[GreptileRepository], question: str, conversation_id: uuid.UUID | None) -> tuple[GreptileConversation, GreptileMessage]:
    started = time.perf_counter()
    if not repositories:
        raise LLMResponseError("Select at least one indexed repository.")
    repository = repositories[0]
    conversation = None
    if conversation_id:
        conversation = GreptileConversation.query.filter_by(id=conversation_id, workspace_id=repository.workspace_id, repository_id=repository.id, deleted_at=None).first()
    if conversation is None:
        conversation = GreptileConversation(workspace_id=repository.workspace_id, repository_id=repository.id, title=question[:180])
        db.session.add(conversation)
        db.session.flush()

    files: list[GreptileCodeFile] = []
    repository_labels: dict[str, str] = {}
    for selected in repositories:
        snapshot = GreptileRepositorySnapshot.query.filter_by(
            repository_id=selected.id,
            workspace_id=repository.workspace_id,
            status="ready",
            deleted_at=None,
        ).order_by(GreptileRepositorySnapshot.created_at.desc()).first()
        if snapshot is None:
            raise LLMResponseError(f"Index {selected.owner}/{selected.name} before asking codebase questions.")
        files.extend(GreptileCodeFile.query.filter_by(snapshot_id=snapshot.id, deleted_at=None).all())
        repository_labels[str(selected.id)] = f"{selected.owner}/{selected.name}"
    if not files:
        raise LLMResponseError("The latest repository index contains no supported source files.")
    rules = [
        rule.text for rule in GreptileRule.query.filter_by(
            workspace_id=repository.workspace_id,
            enabled=True,
            deleted_at=None,
        ).all()
    ]
    answer, grounded_sources, _model = generate_grounded_answer(files, question, rules, repository_labels)

    db.session.add(GreptileMessage(conversation_id=conversation.id, role="user", content=question))
    message = GreptileMessage(conversation_id=conversation.id, role="assistant", content=answer, duration_ms=max(1, int((time.perf_counter() - started) * 1000)))
    db.session.add(message)
    db.session.flush()
    for source in grounded_sources:
        db.session.add(GreptileCitation(
            message_id=message.id,
            path=f"{source.repository}::{source.path}" if source.repository else source.path,
            start_line=source.start_line,
            end_line=source.end_line,
            excerpt=source.excerpt,
        ))
    conversation.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return conversation, message
