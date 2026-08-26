from __future__ import annotations

import ipaddress
import re
import socket
import uuid
from urllib.parse import urlparse


class ValidationError(ValueError):
    pass


def json_object(value: object, *allowed_fields: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError("request body must be a JSON object")
    unexpected = sorted(set(value) - set(allowed_fields))
    if unexpected:
        raise ValidationError(f"unexpected fields: {', '.join(unexpected)}")
    return value


def require_text(value: object, field: str, *, minimum: int = 1, maximum: int = 2000) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    cleaned = " ".join(value.split())
    if not minimum <= len(cleaned) <= maximum:
        raise ValidationError(f"{field} must be between {minimum} and {maximum} characters")
    return cleaned


def optional_text(value: object, field: str, *, maximum: int = 2000, default: str = "") -> str:
    if value in (None, ""):
        return default
    return require_text(value, field, maximum=maximum)


def require_uuid(value: object, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(f"{field} must be a valid UUID") from exc


def require_uuid_list(value: object, field: str, *, maximum: int = 5000, allow_empty: bool = True) -> list[uuid.UUID]:
    if value is None and allow_empty:
        return []
    if not isinstance(value, list) or len(value) > maximum or (not allow_empty and not value):
        qualifier = f"between 1 and {maximum}" if not allow_empty else f"at most {maximum}"
        raise ValidationError(f"{field} must contain {qualifier} IDs")
    parsed: list[uuid.UUID] = []
    for raw in value:
        item = require_uuid(raw, field)
        if item not in parsed:
            parsed.append(item)
    return parsed


def require_email(value: object) -> str:
    email = require_text(value, "email", minimum=3, maximum=254).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValidationError("email must be valid")
    return email


def require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be a boolean")
    return value


def require_password(value: object) -> str:
    if not isinstance(value, str) or not 8 <= len(value) <= 128:
        raise ValidationError("password must be between 8 and 128 characters")
    return value


def require_https_url(value: object, field: str = "location") -> str:
    url = require_text(value, field, minimum=12, maximum=500)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError(f"{field} must be a public HTTPS URL")
    if parsed.port not in (None, 443):
        raise ValidationError(f"{field} must use the standard HTTPS port")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValidationError(f"{field} must be a public HTTPS URL")
    return url


def assert_public_hostname(url: str) -> None:
    """Resolve every address before a fetch so sources cannot reach private services."""
    host = urlparse(url).hostname or ""
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValidationError("source hostname could not be resolved") from exc
    if not addresses:
        raise ValidationError("source hostname could not be resolved")
    for raw in addresses:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
        if not address.is_global:
            raise ValidationError("source hostname resolves to a private or reserved address")
