from __future__ import annotations

import hashlib
import hmac
import ipaddress
from datetime import datetime, timedelta, timezone

from flask import current_app, request
from sqlalchemy import text as sql_text

from app.models import db
from .models import OpenmartRateEvent


def _client_address() -> str:
    address = request.remote_addr or "unknown"
    if current_app.config.get("OPENMART_TRUST_PROXY_HEADERS"):
        forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        if forwarded:
            try:
                address = str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
    return address


def subject_fingerprint(identity: str) -> str:
    secret = str(current_app.config.get("SECRET_KEY") or "openmart-unconfigured")
    value = f"{_client_address()}:{identity.strip().lower()}".encode()
    return hmac.new(secret.encode(), value, hashlib.sha256).hexdigest()


def allow_request(scope: str, identity: str, *, limit: int, seconds: int) -> bool:
    subject_hash = subject_fingerprint(identity)
    if db.engine.dialect.name == "postgresql":
        db.session.execute(sql_text("SELECT pg_advisory_xact_lock(hashtext(:rate_key))"), {"rate_key": f"openmart:{scope}:{subject_hash}"})
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    count = OpenmartRateEvent.query.filter(
        OpenmartRateEvent.scope == scope,
        OpenmartRateEvent.subject_hash == subject_hash,
        OpenmartRateEvent.created_at >= cutoff,
        OpenmartRateEvent.deleted_at.is_(None),
    ).count()
    if count >= limit:
        return False
    db.session.add(OpenmartRateEvent(scope=scope, subject_hash=subject_hash))
    db.session.commit()
    return True
