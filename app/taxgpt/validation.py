from __future__ import annotations

import re
import uuid


class ValidationError(ValueError):
    pass


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def json_object(value):
    if not isinstance(value, dict):
        raise ValidationError("request body must be a JSON object")
    return value


def only_fields(data: dict, allowed: set[str]):
    unexpected = sorted(set(data) - allowed)
    if unexpected:
        raise ValidationError(f"unexpected fields: {', '.join(unexpected)}")


def text(value, field: str, *, minimum: int = 1, maximum: int = 4000) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    cleaned = value.strip()
    if len(cleaned) < minimum or len(cleaned) > maximum:
        raise ValidationError(f"{field} must be between {minimum} and {maximum} characters")
    return cleaned


def email(value) -> str:
    cleaned = text(value, "email", maximum=254).lower()
    if not EMAIL_RE.fullmatch(cleaned):
        raise ValidationError("email must be valid")
    return cleaned


def password(value) -> str:
    cleaned = text(value, "password", minimum=8, maximum=128)
    if not re.search(r"[A-Za-z]", cleaned) or not re.search(r"\d", cleaned):
        raise ValidationError("password must include a letter and a number")
    return cleaned


def identifier(value, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(f"{field} must be a valid identifier") from exc
