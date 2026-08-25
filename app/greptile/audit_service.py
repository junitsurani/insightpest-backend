from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models import db

from .llm_engine import LLMConfigurationError, LLMResponseError, generate_audit_findings, retrieve_sources
from .models import (
    GreptileAuditFinding,
    GreptileAuditRun,
    GreptileCodeFile,
    GreptileRepository,
    GreptileRepositorySnapshot,
    GreptileRule,
)


STATIC_CHECKS = (
    (
        re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][A-Za-z0-9_\-/.+]{12,}['\"]"),
        "high", "security", "Possible hard-coded credential",
        "A credential-like value is assigned directly in source code.",
        "Move the value to a secret manager or runtime environment variable and rotate the exposed value.",
    ),
    (
        re.compile(r"\b(shell\s*=\s*True|os\.system\s*\()"),
        "high", "command-injection", "Unsafe shell execution",
        "The process executes through a shell, which can turn untrusted input into operating-system commands.",
        "Use an argument array without a shell and strictly validate every user-controlled argument.",
    ),
    (
        re.compile(r"\b(eval|exec)\s*\("),
        "high", "code-injection", "Dynamic code execution",
        "Dynamic evaluation can execute attacker-controlled code when input reaches this call.",
        "Replace dynamic evaluation with an explicit parser or a fixed dispatch table.",
    ),
    (
        re.compile(r"(?i)(execute|query)\s*\(\s*f?['\"][^'\"]*\{[^}]+\}"),
        "high", "sql-injection", "Interpolated database query",
        "Values appear to be interpolated into a database statement.",
        "Use parameterized queries and bind values through the database driver.",
    ),
    (
        re.compile(r"\bdangerouslySetInnerHTML\b"),
        "medium", "cross-site-scripting", "Raw HTML rendering",
        "Raw HTML is rendered directly and may introduce cross-site scripting if the value is not trusted.",
        "Render structured components or sanitize the HTML with a well-maintained allow-list sanitizer.",
    ),
)


def _static_findings(files: list[GreptileCodeFile]) -> list[dict]:
    findings: list[dict] = []
    for code_file in files:
        for line_number, line in enumerate(code_file.content.splitlines(), 1):
            for pattern, severity, category, title, description, recommendation in STATIC_CHECKS:
                if pattern.search(line):
                    findings.append({
                        "path": code_file.path,
                        "start_line": line_number,
                        "end_line": line_number,
                        "severity": severity,
                        "category": category,
                        "title": title,
                        "description": description,
                        "recommendation": recommendation,
                        "evidence": line.strip()[:900],
                    })
                    if len(findings) >= 50:
                        return findings
    return findings


def _deduplicate(findings: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple[str, int, str]] = set()
    for item in findings:
        key = (item["path"], item["start_line"], item["title"].lower())
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _score(findings: list[dict]) -> int:
    weights = {"critical": 25, "high": 12, "medium": 6, "low": 2, "info": 0}
    return max(0, 100 - sum(weights.get(item["severity"], 0) for item in findings))


def run_codebase_audit(repository: GreptileRepository) -> GreptileAuditRun:
    snapshot = GreptileRepositorySnapshot.query.filter_by(
        repository_id=repository.id,
        workspace_id=repository.workspace_id,
        status="ready",
        deleted_at=None,
    ).order_by(GreptileRepositorySnapshot.created_at.desc()).first()
    if snapshot is None:
        raise LLMResponseError("Index this repository before running an audit.")
    files = GreptileCodeFile.query.filter_by(snapshot_id=snapshot.id, deleted_at=None).order_by(GreptileCodeFile.path.asc()).all()
    if not files:
        raise LLMResponseError("The latest repository index contains no supported source files.")

    run = GreptileAuditRun(
        workspace_id=repository.workspace_id,
        repository_id=repository.id,
        snapshot_id=snapshot.id,
        status="running",
        file_count=len(files),
    )
    db.session.add(run)
    db.session.commit()

    static_findings = _static_findings(files)
    rules = [
        rule.text for rule in GreptileRule.query.filter_by(
            workspace_id=repository.workspace_id, enabled=True, deleted_at=None
        ).all()
    ]
    sources = retrieve_sources(
        files,
        "security authentication authorization input database query command shell secret password token retry transaction error",
        limit=14,
    )
    llm_findings: list[dict] = []
    ai_summary = ""
    try:
        ai_summary, llm_findings, model = generate_audit_findings(sources, rules)
        run.model = model
        run.llm_status = "complete"
    except LLMConfigurationError:
        run.model = "static-analysis"
        run.llm_status = "not_configured"
    except LLMResponseError:
        run.model = "static-analysis"
        run.llm_status = "failed"

    findings = _deduplicate(static_findings + llm_findings)
    score = _score(findings)
    if ai_summary:
        summary = ai_summary
    elif findings:
        summary = f"Static analysis found {len(findings)} actionable issue{'s' if len(findings) != 1 else ''} across {len(files)} indexed files."
    else:
        summary = f"No high-confidence static issues were found across {len(files)} indexed files."
    if run.llm_status == "not_configured":
        summary += " AI reasoning is available after the backend OPENAI_API_KEY is configured."
    elif run.llm_status == "failed":
        summary += " AI reasoning failed for this run; the persisted static findings are still available."

    db.session.add_all([GreptileAuditFinding(audit_id=run.id, **item) for item in findings])
    run.status = "complete"
    run.score = score
    run.summary = summary
    run.completed_at = datetime.now(timezone.utc)
    db.session.commit()
    return run
