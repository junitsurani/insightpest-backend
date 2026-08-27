from __future__ import annotations

import hashlib
import hmac
import ipaddress
from datetime import datetime, timedelta, timezone

from flask import current_app, request
from sqlalchemy import text as sql_text

from app.models import db
from .models import TaxGptRateEvent


def _client_address() -> str:
    address = request.remote_addr or "unknown"
    if current_app.config.get("TAXGPT_TRUST_PROXY_HEADERS"):
        forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        if forwarded:
            try:
                address = str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
    return address


def subject_fingerprint(identity: str) -> str:
    secret = str(current_app.config.get("SECRET_KEY") or "taxgpt-unconfigured")
    value = f"{_client_address()}:{identity.strip().lower()}".encode()
    return hmac.new(secret.encode(), value, hashlib.sha256).hexdigest()


def allow_request(scope: str, identity: str, *, limit: int, seconds: int) -> bool:
    """Persist rate events so limits are shared across Gunicorn workers."""
    subject_hash = subject_fingerprint(identity)
    if db.engine.dialect.name == "postgresql":
        db.session.execute(
            sql_text("SELECT pg_advisory_xact_lock(hashtext(:rate_key))"),
            {"rate_key": f"taxgpt:{scope}:{subject_hash}"},
        )
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    count = TaxGptRateEvent.query.filter(
        TaxGptRateEvent.scope == scope,
        TaxGptRateEvent.subject_hash == subject_hash,
        TaxGptRateEvent.created_at >= cutoff,
        TaxGptRateEvent.deleted_at.is_(None),
    ).count()
    if count >= limit:
        return False
    db.session.add(TaxGptRateEvent(scope=scope, subject_hash=subject_hash))
    db.session.commit()
    return True
