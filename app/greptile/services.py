from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.models import db

from .models import GreptileCitation, GreptileConversation, GreptileMessage, GreptilePullRequest, GreptileRepository, GreptileRule, GreptileUser, GreptileWorkspace


DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def ensure_workspace(workspace_id: uuid.UUID) -> GreptileWorkspace:
    workspace = GreptileWorkspace.query.filter_by(id=workspace_id, deleted_at=None).first()
    if workspace:
        return workspace
    workspace = GreptileWorkspace(id=workspace_id, name="Demo workspace")
    repository = GreptileRepository(owner="acme", name="platform", provider="github", default_branch="main", status="ready", progress=100, last_indexed_at=datetime.now(timezone.utc))
    workspace.repositories.append(repository)
    db.session.add(workspace)
    db.session.flush()
    db.session.add_all([
        GreptilePullRequest(workspace_id=workspace.id, repository_id=repository.id, number=284, title="Prevent duplicate ledger writes on payment retry", author="sarah-chen", branch="fix/idempotent-retry", status="issues_found", issue_count=2),
        GreptilePullRequest(workspace_id=workspace.id, repository_id=repository.id, number=279, title="Cache organization permissions", author="marco", branch="perf/org-permissions", status="passed", issue_count=0),
        GreptilePullRequest(workspace_id=workspace.id, repository_id=repository.id, number=271, title="Add webhook delivery retries", author="alex-r", branch="feat/webhook-retries", status="open", issue_count=0),
    ])
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


def answer_question(repository: GreptileRepository, question: str, conversation_id: uuid.UUID | None) -> tuple[GreptileConversation, GreptileMessage]:
    started = time.perf_counter()
    conversation = None
    if conversation_id:
        conversation = GreptileConversation.query.filter_by(id=conversation_id, workspace_id=repository.workspace_id, repository_id=repository.id, deleted_at=None).first()
    if conversation is None:
        conversation = GreptileConversation(workspace_id=repository.workspace_id, repository_id=repository.id, title=question[:180])
        db.session.add(conversation)
        db.session.flush()

    db.session.add(GreptileMessage(conversation_id=conversation.id, role="user", content=question))
    lowered = question.lower()
    if any(token in lowered for token in ("auth", "session", "login", "permission")):
        answer = "Authentication enters through the route handler, validates the signed session, and resolves organization membership before protected services execute. The critical boundary is requireWorkspaceAccess, which prevents cross-workspace repository reads."
        citations = [
            ("src/api/auth/[...session]/route.ts", 18, 46, "const session = await verifySession(request);"),
            ("src/security/require-workspace-access.ts", 31, 64, "await memberships.assertAccess(userId, workspaceId);"),
        ]
    elif any(token in lowered for token in ("payment", "retry", "ledger", "284")):
        answer = "PR #284 improves retry detection, but the ledger write still occurs before the retry marker commits. Two workers can race and create duplicate entries. Put both operations in one transaction and lock the payment-attempt row."
        citations = [
            ("src/payments/retry-payment.ts", 72, 111, "await ledger.recordCapture(attempt);"),
            ("src/db/payment-attempt-repository.ts", 44, 82, "return db.paymentAttempt.update({ ... });"),
            ("src/workers/payment-retry-worker.ts", 21, 57, "await retryPayment(job.data.attemptId);"),
        ]
    else:
        answer = f"I traced this question across {repository.owner}/{repository.name}. The main execution path starts in the API route, passes through the application service, and ends in the persistence adapter. The cited files are the highest-confidence code-graph matches."
        citations = [
            ("src/api/repositories/route.ts", 24, 66, "return repositoryService.execute(command);"),
            ("src/services/repository-service.ts", 48, 109, "await repository.save(aggregate);"),
        ]
    message = GreptileMessage(conversation_id=conversation.id, role="assistant", content=answer, duration_ms=max(1, int((time.perf_counter() - started) * 1000)))
    db.session.add(message)
    db.session.flush()
    for path, start_line, end_line, excerpt in citations:
        db.session.add(GreptileCitation(message_id=message.id, path=path, start_line=start_line, end_line=end_line, excerpt=excerpt))
    conversation.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return conversation, message
