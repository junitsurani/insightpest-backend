from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from hashlib import sha256

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import db
from .models import OpenmartSession, OpenmartUser, OpenmartWorkspace
from .security import allow_request
from .validation import ValidationError, email, json_object, only_fields, password, text


openmart_auth = Blueprint("openmart_auth", __name__, url_prefix="/api/openmart/auth")
SESSION_COOKIE = "openmart_session"


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def token_hash(token: str):
    return sha256(token.encode()).hexdigest()


def cookie_secure():
    configured = current_app.config.get("OPENMART_COOKIE_SECURE")
    if configured is not None:
        return bool(configured)
    proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    return request.is_secure or (current_app.config.get("OPENMART_TRUST_PROXY_HEADERS") and proto == "https")


def serialize_user(user: OpenmartUser):
    return {
        "id": str(user.id), "email": user.email, "displayName": user.display_name,
        "workspaceId": str(user.workspace_id), "workspaceName": user.workspace.name,
        "role": user.role, "plan": user.workspace.plan, "credits": user.workspace.credits_balance,
    }


def set_cookie(response, token: str, max_age: int):
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=cookie_secure(), samesite="Strict", path="/")
    return response


def clear_cookie(response):
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=cookie_secure(), samesite="Strict", path="/")
    return response


def current_session():
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or len(token) > 200:
        return None
    session = OpenmartSession.query.filter_by(token_hash=token_hash(token), revoked_at=None, deleted_at=None).first()
    if session is None or as_utc(session.expires_at) <= utcnow() or not session.user or not session.user.is_active or session.user.deleted_at:
        return None
    return session


def require_session(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        session = current_session()
        if session is None:
            return clear_cookie(jsonify({"error": "Authentication required"})), 401
        g.openmart_session = session
        g.openmart_user = session.user
        g.workspace_id = session.user.workspace_id
        return handler(*args, **kwargs)
    return wrapped


@openmart_auth.errorhandler(ValidationError)
def validation_error(error):
    return jsonify({"error": str(error)}), 400


def create_session(user: OpenmartUser, remember: bool):
    lifetime = timedelta(days=int(current_app.config.get("OPENMART_REMEMBER_DAYS", 7))) if remember else timedelta(hours=int(current_app.config.get("OPENMART_SESSION_HOURS", 12)))
    token = secrets.token_urlsafe(48)
    point = utcnow()
    db.session.add(OpenmartSession(user_id=user.id, token_hash=token_hash(token), expires_at=point + lifetime, last_seen_at=point))
    user.last_login_at = point
    db.session.commit()
    response = jsonify({"user": serialize_user(user), "expiresAt": (point + lifetime).isoformat().replace("+00:00", "Z")})
    return set_cookie(response, token, int(lifetime.total_seconds()))


@openmart_auth.post("/signup")
def signup():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"email", "password", "displayName", "workspaceName", "country", "remember"})
    user_email = email(data.get("email"))
    if not allow_request("signup", user_email, limit=int(current_app.config.get("OPENMART_AUTH_RATE_LIMIT", 10)), seconds=60):
        return jsonify({"error": "Too many attempts. Try again in a minute."}), 429
    if OpenmartUser.query.filter_by(email=user_email, deleted_at=None).first():
        return jsonify({"error": "An account already exists for this email."}), 409
    display_name = text(data.get("displayName"), "displayName", minimum=2, maximum=120)
    workspace_name = text(data.get("workspaceName") or f"{display_name}'s workspace", "workspaceName", minimum=2, maximum=160)
    user_password = password(data.get("password"))
    country = data.get("country", "US")
    if country not in {"US", "CA", "GB", "AU"}:
        raise ValidationError("country is invalid")
    remember = data.get("remember", True)
    if not isinstance(remember, bool):
        raise ValidationError("remember must be a boolean")
    workspace = OpenmartWorkspace(name=workspace_name, default_country=country)
    user = OpenmartUser(workspace=workspace, email=user_email, display_name=display_name, password_hash=generate_password_hash(user_password), role="owner")
    db.session.add_all([workspace, user])
    try:
        db.session.flush()
        response = create_session(user, remember)
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An account already exists for this email."}), 409
    response.status_code = 201
    return response


@openmart_auth.post("/login")
def login():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"email", "password", "remember"})
    user_email = email(data.get("email"))
    user_password = text(data.get("password"), "password", maximum=128)
    remember = data.get("remember", True)
    if not isinstance(remember, bool):
        raise ValidationError("remember must be a boolean")
    if not allow_request("login", user_email, limit=int(current_app.config.get("OPENMART_AUTH_RATE_LIMIT", 10)), seconds=60):
        return jsonify({"error": "Too many sign-in attempts. Try again in a minute."}), 429
    user = OpenmartUser.query.filter_by(email=user_email, deleted_at=None).first()
    stored = user.password_hash if user else current_app.config["OPENMART_DUMMY_PASSWORD_HASH"]
    valid = check_password_hash(stored, user_password)
    if user is None or not user.is_active or not valid:
        return jsonify({"error": "The email or password is incorrect."}), 401
    return create_session(user, remember)


@openmart_auth.get("/session")
@require_session
def session_status():
    if as_utc(g.openmart_session.last_seen_at) <= utcnow() - timedelta(minutes=5):
        g.openmart_session.last_seen_at = utcnow()
        db.session.commit()
    return jsonify({"user": serialize_user(g.openmart_user)})


@openmart_auth.post("/logout")
def logout():
    session = current_session()
    if session:
        session.revoked_at = utcnow()
        db.session.commit()
    return clear_cookie(jsonify({"ok": True}))
