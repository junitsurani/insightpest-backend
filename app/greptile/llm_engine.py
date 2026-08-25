from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from .models import GreptileCodeFile


class LLMConfigurationError(RuntimeError):
    pass


class LLMResponseError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceChunk:
    path: str
    start_line: int
    end_line: int
    excerpt: str
    content: str
    repository_id: str = ""
    repository: str = ""


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", value.lower()) if token not in {"the", "and", "for", "with", "from", "this", "that", "how", "does", "where"}}


def retrieve_sources(files: list[GreptileCodeFile], query: str, *, limit: int = 8) -> list[SourceChunk]:
    query_tokens = _tokens(query)
    ranked: list[tuple[int, GreptileCodeFile]] = []
    for item in files:
        path_lower = item.path.lower()
        content_lower = item.content.lower()
        score = sum(12 for token in query_tokens if token in path_lower)
        score += sum(min(content_lower.count(token), 8) for token in query_tokens)
        if score or not query_tokens:
            ranked.append((score, item))
    if not ranked:
        ranked = [(0, item) for item in files]
    ranked.sort(key=lambda pair: (-pair[0], pair[1].path))

    sources: list[SourceChunk] = []
    for _, item in ranked[:limit]:
        lines = item.content.splitlines()
        match_indexes = [
            index for index, line in enumerate(lines)
            if any(token in line.lower() for token in query_tokens)
        ]
        center = match_indexes[0] if match_indexes else 0
        start = max(0, center - 35)
        end = min(len(lines), start + 90)
        numbered = "\n".join(f"{index + 1:04d} {lines[index]}" for index in range(start, end))
        excerpt = "\n".join(lines[start:min(end, start + 8)]).strip()[:900]
        sources.append(SourceChunk(
            item.path,
            start + 1,
            max(start + 1, end),
            excerpt,
            numbered,
            repository_id=str(item.repository_id),
        ))
    return sources


def _client_and_model():
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise LLMConfigurationError("AI analysis is not configured on the backend. Set the existing OPENAI_API_KEY and redeploy.")
    try:
        from openai import OpenAI
        return OpenAI(api_key=key, timeout=45.0, max_retries=1), os.getenv("GREPTILE_LLM_MODEL", "gpt-4o-mini")
    except Exception as exc:
        raise LLMConfigurationError("The backend AI client could not be initialized.") from exc


def _json_completion(system: str, user: str) -> tuple[dict, str]:
    client, model = _client_and_model()
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        raw = response.choices[0].message.content or "{}"
        return json.loads(raw), model
    except LLMConfigurationError:
        raise
    except Exception as exc:
        raise LLMResponseError("The AI analysis request failed. Please retry.") from exc


def generate_grounded_answer(
    files: list[GreptileCodeFile],
    question: str,
    rules: list[str],
    repository_labels: dict[str, str] | None = None,
) -> tuple[str, list[SourceChunk], str]:
    labels = repository_labels or {}
    sources = [
        SourceChunk(
            source.path,
            source.start_line,
            source.end_line,
            source.excerpt,
            source.content,
            repository_id=source.repository_id,
            repository=labels.get(source.repository_id, "repository"),
        )
        for source in retrieve_sources(files, question)
    ]
    if not sources:
        raise LLMResponseError("This repository has no indexed source files.")
    source_text = "\n\n".join(
        f"SOURCE {index}\nREPOSITORY: {source.repository}\nPATH: {source.path}\nLINES: {source.start_line}-{source.end_line}\n{source.content}"
        for index, source in enumerate(sources, 1)
    )
    payload, model = _json_completion(
        "You are a senior codebase analyst. Answer only from supplied repository sources. "
        "If evidence is incomplete, say so. Return JSON with keys answer (string) and source_indexes (array of integers). "
        "Never invent paths, APIs, behavior, or citations. When multiple repositories are supplied, "
        "state which repository contains each relevant behavior.",
        f"QUESTION:\n{question}\n\nACTIVE REVIEW RULES:\n" +
        ("\n".join(f"- {rule}" for rule in rules) or "- none") +
        f"\n\nREPOSITORY SOURCES:\n{source_text}",
    )
    answer = payload.get("answer")
    indexes = payload.get("source_indexes")
    if not isinstance(answer, str) or not answer.strip() or not isinstance(indexes, list):
        raise LLMResponseError("The AI returned an invalid repository answer.")
    selected: list[SourceChunk] = []
    for raw_index in indexes:
        if isinstance(raw_index, int) and 1 <= raw_index <= len(sources):
            source = sources[raw_index - 1]
            if source not in selected:
                selected.append(source)
    if not selected:
        selected = sources[:1]
    return answer.strip(), selected[:6], model


def generate_audit_findings(sources: list[SourceChunk], rules: list[str]) -> tuple[str, list[dict], str]:
    if not sources:
        raise LLMResponseError("This repository has no indexed source files.")
    source_text = "\n\n".join(
        f"SOURCE {index}\nPATH: {source.path}\nLINES: {source.start_line}-{source.end_line}\n{source.content}"
        for index, source in enumerate(sources, 1)
    )
    payload, model = _json_completion(
        "Audit source code for concrete correctness, security, reliability, and maintainability defects. "
        "Report only issues directly supported by supplied code. Return JSON with summary (string) and findings (array). "
        "Each finding must contain source_index (integer), line (integer), severity (critical|high|medium|low|info), "
        "category, title, description, and recommendation. Do not report formatting preferences.",
        "ACTIVE TEAM RULES:\n" + ("\n".join(f"- {rule}" for rule in rules) or "- none") +
        f"\n\nSOURCE CODE:\n{source_text}",
    )
    summary = payload.get("summary")
    raw_findings = payload.get("findings")
    if not isinstance(summary, str) or not isinstance(raw_findings, list):
        raise LLMResponseError("The AI returned an invalid audit result.")
    findings: list[dict] = []
    for item in raw_findings[:30]:
        if not isinstance(item, dict):
            continue
        source_index = item.get("source_index")
        severity = str(item.get("severity", "")).lower()
        if not isinstance(source_index, int) or not 1 <= source_index <= len(sources):
            continue
        if severity not in {"critical", "high", "medium", "low", "info"}:
            continue
        source = sources[source_index - 1]
        try:
            line = int(item.get("line") or source.start_line)
        except (TypeError, ValueError):
            line = source.start_line
        line = min(max(line, source.start_line), source.end_line)
        findings.append({
            "path": source.path,
            "start_line": line,
            "end_line": line,
            "severity": severity,
            "category": str(item.get("category") or "code-quality")[:80],
            "title": str(item.get("title") or "Audit finding")[:240],
            "description": str(item.get("description") or "Review the cited code."),
            "recommendation": str(item.get("recommendation") or "Add a focused test and correct the implementation."),
            "evidence": source.excerpt,
        })
    return summary.strip(), findings, model
