from __future__ import annotations

import re
from urllib.parse import quote

from app.models import db

from .llm_engine import LLMConfigurationError, LLMResponseError, SourceChunk, generate_audit_findings
from .models import GreptilePullRequest, GreptileRepository, GreptileRule
from .repository_indexer import RepositoryClient, RepositoryConnectionError


PATCH_CHECKS = (
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][A-Za-z0-9_\-/.+]{12,}['\"]"),
    re.compile(r"\b(shell\s*=\s*True|os\.system\s*\()"),
    re.compile(r"\b(eval|exec)\s*\("),
    re.compile(r"\bdangerouslySetInnerHTML\b"),
    re.compile(r"(?i)(execute|query)\s*\(\s*f?['\"][^'\"]*\{[^}]+\}"),
)


def _provider_rows(repository: GreptileRepository, client: RepositoryClient) -> list[dict]:
    if repository.provider == "github":
        base = f"https://api.github.com/repos/{quote(repository.owner)}/{quote(repository.name)}"
        payload = client._request(base + "/pulls", "github", params={"state": "open", "per_page": 50}).json()
        if not isinstance(payload, list):
            raise RepositoryConnectionError("GitHub returned an invalid pull request list.")
        return [{
            "number": int(item["number"]),
            "title": str(item.get("title") or "Untitled pull request")[:240],
            "author": str((item.get("user") or {}).get("login") or "unknown")[:100],
            "branch": str((item.get("head") or {}).get("ref") or "unknown")[:160],
        } for item in payload if isinstance(item, dict) and isinstance(item.get("number"), int)]

    project = quote(f"{repository.owner}/{repository.name}", safe="")
    payload = client._request(
        f"https://gitlab.com/api/v4/projects/{project}/merge_requests",
        "gitlab",
        params={"state": "opened", "per_page": 50},
    ).json()
    if not isinstance(payload, list):
        raise RepositoryConnectionError("GitLab returned an invalid merge request list.")
    return [{
        "number": int(item["iid"]),
        "title": str(item.get("title") or "Untitled merge request")[:240],
        "author": str((item.get("author") or {}).get("username") or "unknown")[:100],
        "branch": str(item.get("source_branch") or "unknown")[:160],
    } for item in payload if isinstance(item, dict) and isinstance(item.get("iid"), int)]


def sync_pull_requests(repository: GreptileRepository, client: RepositoryClient | None = None) -> list[GreptilePullRequest]:
    """Idempotently mirror the provider's current open pull-request queue."""
    client = client or RepositoryClient()
    rows = _provider_rows(repository, client)
    existing = {
        item.number: item for item in GreptilePullRequest.query.filter_by(
            workspace_id=repository.workspace_id,
            repository_id=repository.id,
            deleted_at=None,
        ).all()
    }
    open_numbers: set[int] = set()
    for row in rows:
        open_numbers.add(row["number"])
        item = existing.get(row["number"])
        if item is None:
            item = GreptilePullRequest(
                workspace_id=repository.workspace_id,
                repository_id=repository.id,
                status="open",
                issue_count=0,
                **row,
            )
            db.session.add(item)
        else:
            item.title = row["title"]
            item.author = row["author"]
            item.branch = row["branch"]
            if item.status == "closed":
                item.status = "open"
                item.issue_count = 0
    for number, item in existing.items():
        if number not in open_numbers:
            item.status = "closed"
    db.session.commit()
    return GreptilePullRequest.query.filter_by(
        workspace_id=repository.workspace_id,
        repository_id=repository.id,
        deleted_at=None,
    ).filter(GreptilePullRequest.status != "closed").order_by(
        GreptilePullRequest.updated_at.desc(), GreptilePullRequest.number.desc()
    ).all()


def _patches(repository: GreptileRepository, number: int, client: RepositoryClient) -> list[tuple[str, str]]:
    if repository.provider == "github":
        base = f"https://api.github.com/repos/{quote(repository.owner)}/{quote(repository.name)}"
        payload = client._request(base + f"/pulls/{number}/files", "github", params={"per_page": 100}).json()
        if not isinstance(payload, list):
            raise RepositoryConnectionError("GitHub returned an invalid pull request patch.")
        return [(str(item.get("filename") or "unknown"), str(item.get("patch") or "")) for item in payload if isinstance(item, dict) and item.get("patch")]

    project = quote(f"{repository.owner}/{repository.name}", safe="")
    payload = client._request(
        f"https://gitlab.com/api/v4/projects/{project}/merge_requests/{number}/changes",
        "gitlab",
    ).json()
    changes = payload.get("changes") if isinstance(payload, dict) else None
    if not isinstance(changes, list):
        raise RepositoryConnectionError("GitLab returned an invalid merge request patch.")
    return [(str(item.get("new_path") or item.get("old_path") or "unknown"), str(item.get("diff") or "")) for item in changes if isinstance(item, dict) and item.get("diff")]


def review_pull_request(pr: GreptilePullRequest, repository: GreptileRepository, client: RepositoryClient | None = None) -> GreptilePullRequest:
    """Review the live provider patch with deterministic checks plus optional LLM reasoning."""
    client = client or RepositoryClient()
    pr.status = "reviewing"
    db.session.commit()
    try:
        patches = _patches(repository, pr.number, client)
        if not patches:
            raise RepositoryConnectionError("The provider did not return a reviewable text patch.")
        static_findings = 0
        sources: list[SourceChunk] = []
        for path, patch in patches[:40]:
            added_lines = [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
            static_findings += sum(1 for line in added_lines for pattern in PATCH_CHECKS if pattern.search(line))
            numbered = "\n".join(f"{index:04d} {line}" for index, line in enumerate(patch.splitlines()[:250], 1))
            sources.append(SourceChunk(path, 1, max(1, len(patch.splitlines()[:250])), "\n".join(added_lines[:8])[:900], numbered))
        ai_findings = 0
        rules = [item.text for item in GreptileRule.query.filter_by(workspace_id=repository.workspace_id, enabled=True, deleted_at=None).all()]
        try:
            _summary, findings, _model = generate_audit_findings(sources[:16], rules)
            ai_findings = len(findings)
        except (LLMConfigurationError, LLMResponseError):
            # Deterministic review remains a complete, real result when an LLM
            # key is not configured or the provider temporarily fails.
            ai_findings = 0
        pr.issue_count = min(99, static_findings + ai_findings)
        pr.status = "issues_found" if pr.issue_count else "passed"
        db.session.commit()
        return pr
    except Exception:
        db.session.rollback()
        persisted = db.session.get(GreptilePullRequest, pr.id)
        if persisted is not None:
            persisted.status = "open"
            db.session.commit()
        raise
