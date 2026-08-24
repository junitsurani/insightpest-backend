from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash

from app.models import db
from .models import GreptileSession, GreptileUser
from .validation import ValidationError, require_email, require_text


greptile_auth = Blueprint("greptile_auth", __name__, url_prefix="/api/greptile/auth")
SESSION_COOKIE = "greptile_session"
_login_windows: dict[str, deque[float]] = defaultdict(deque)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cookie_secure() -> bool:
    configured = current_app.config.get("GREPTILE_COOKIE_SECURE")
    if configured is not None:
        return bool(configured)
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    return request.is_secure or forwarded_proto == "https"


def _set_session_cookie(response, token: str, max_age: int):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="Strict",
        path="/",
    )
    return response


def _clear_session_cookie(response):
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=_cookie_secure(),
        samesite="Strict",
        path="/",
    )
    return response


def _serialize_user(user: GreptileUser) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "displayName": user.display_name,
        "workspaceId": str(user.workspace_id),
    }


def _rate_limit_login(email: str) -> bool:
    key = f"{request.remote_addr or 'unknown'}:{email}"
    now = time.monotonic()
    window = _login_windows[key]
    while window and window[0] <= now - 60:
        window.popleft()
    if len(window) >= 10:
        return False
    window.append(now)
    return True


def current_session() -> GreptileSession | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or len(token) > 200:
        return None
    session = GreptileSession.query.filter_by(token_hash=_token_hash(token), revoked_at=None, deleted_at=None).first()
    if session is None or _as_utc(session.expires_at) <= _now():
        return None
    if session.user is None or not session.user.is_active or session.user.deleted_at is not None:
        return None
    return session


def require_session(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        session = current_session()
        if session is None:
            response = jsonify({"error": "Authentication required"})
            return _clear_session_cookie(response), 401
        g.greptile_session = session
        g.greptile_user = session.user
        g.workspace_id = session.user.workspace_id
        return handler(*args, **kwargs)

    return wrapped


@greptile_auth.errorhandler(ValidationError)
def handle_validation(error: ValidationError):
    return jsonify({"error": str(error)}), 400


@greptile_auth.post("/login")
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")
    unexpected = sorted(set(data) - {"email", "password", "remember"})
    if unexpected:
        raise ValidationError(f"unexpected fields: {', '.join(unexpected)}")

    email = require_email(data.get("email")).lower()
    password = require_text(data.get("password"), "password", maximum=128)
    remember = data.get("remember", True)
    if not isinstance(remember, bool):
        raise ValidationError("remember must be a boolean")
    if not _rate_limit_login(email):
        return jsonify({"error": "Too many sign-in attempts. Try again in a minute."}), 429

    user = GreptileUser.query.filter_by(email=email, deleted_at=None).first()
    # Always run a password check so missing users and incorrect passwords have
    # comparable work factors and do not disclose whether an email exists.
    password_hash = user.password_hash if user else current_app.config["GREPTILE_DUMMY_PASSWORD_HASH"]
    password_valid = check_password_hash(password_hash, password)
    if user is None or not user.is_active or not password_valid:
        return jsonify({"error": "The email or password is incorrect."}), 401

    lifetime = timedelta(days=7) if remember else timedelta(hours=12)
    token = secrets.token_urlsafe(48)
    now = _now()
    db.session.add(
        GreptileSession(
            user_id=user.id,
            token_hash=_token_hash(token),
            expires_at=now + lifetime,
            last_seen_at=now,
        )
    )
    user.last_login_at = now
    db.session.commit()

    response = jsonify({"user": _serialize_user(user), "expiresAt": (now + lifetime).isoformat().replace("+00:00", "Z")})
    return _set_session_cookie(response, token, int(lifetime.total_seconds()))


@greptile_auth.get("/session")
@require_session
def session_status():
    now = _now()
    if _as_utc(g.greptile_session.last_seen_at) <= now - timedelta(minutes=5):
        g.greptile_session.last_seen_at = now
        db.session.commit()
    return jsonify({"user": _serialize_user(g.greptile_user)})


@greptile_auth.post("/logout")
def logout():
    session = current_session()
    if session is not None:
        session.revoked_at = _now()
        db.session.commit()
    return _clear_session_cookie(jsonify({"ok": True}))
