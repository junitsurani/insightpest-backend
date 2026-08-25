from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse


class ValidationError(ValueError):
    pass


def require_uuid(value: str | None, field: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(value or "")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(f"{field} must be a valid UUID") from exc
    return parsed


def require_text(value: object, field: str, *, minimum: int = 1, maximum: int = 2000) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    cleaned = " ".join(value.split())
    if not minimum <= len(cleaned) <= maximum:
        raise ValidationError(f"{field} must be between {minimum} and {maximum} characters")
    return cleaned


def optional_uuid(value: object, field: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return require_uuid(str(value), field)


@dataclass(frozen=True)
class RepositoryIdentity:
    provider: str
    owner: str
    name: str


def parse_repository_url(value: object) -> RepositoryIdentity:
    url = require_text(value, "url", minimum=12, maximum=500)
    parsed = urlparse(url)
    host = parsed.hostname.lower() if parsed.hostname else ""
    if parsed.scheme != "https" or host not in {"github.com", "gitlab.com"}:
        raise ValidationError("url must be an HTTPS GitHub or GitLab repository URL")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    provider = "github" if host == "github.com" else "gitlab"
    if (provider == "github" and len(parts) != 2) or (provider == "gitlab" and len(parts) < 2):
        raise ValidationError("url must identify one repository")
    owner, name = "/".join(parts[:-1]), parts[-1]
    name = name.removesuffix(".git")
    valid = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
    if len(owner) > 100 or not all(valid.fullmatch(part) for part in owner.split("/")) or not valid.fullmatch(name):
        raise ValidationError("repository owner or name contains unsupported characters")
    return RepositoryIdentity(provider, owner, name)


def require_email(value: object) -> str:
    email = require_text(value, "email", minimum=3, maximum=254).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValidationError("email must be valid")
    return email
