from __future__ import annotations

import json
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, Response, current_app, g, jsonify, request, stream_with_context
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.greptile.auth import require_session
from app.models import db
from .jobs import create_job, dispatch_job
from .models import AngleraEvent, AngleraJob, AngleraMember, AngleraProduct, AngleraSource, AngleraWorkspace
from .services import (
    accept_invitation, analytics_for_workspace, create_invitation, emit_event, ensure_owner, ensure_workspace,
    invitation_from_token,
    serialize_job, serialize_member, serialize_product, serialize_source, workspace_snapshot,
)
from .validation import (
    ValidationError, json_object, optional_text, require_bool, require_email, require_https_url,
    require_password, require_text, require_uuid, require_uuid_list,
)


anglera_api = Blueprint("anglera_api", __name__, url_prefix="/api/anglera")
_rate_windows: dict[str, deque[float]] = defaultdict(deque)
ROLE_LEVEL = {"Viewer": 0, "Editor": 1, "Admin": 2, "Owner": 3}


def rate_limit(limit: int, seconds: int):
    def decorator(handler):
        @wraps(handler)
        def wrapped(*args, **kwargs):
            key = f"{getattr(g, 'workspace_id', request.remote_addr)}:{request.endpoint}"
            now = time.monotonic()
            window = _rate_windows[key]
            while window and window[0] <= now - seconds:
                window.popleft()
            if len(window) >= limit:
                return jsonify({"error": "Too many requests"}), 429
            window.append(now)
            return handler(*args, **kwargs)
        return wrapped
    return decorator


def require_role(minimum: str):
    def decorator(handler):
        @wraps(handler)
        def wrapped(*args, **kwargs):
            ensure_workspace(g.workspace_id)
            member = ensure_owner(g.workspace_id, g.greptile_user)
            if member.status != "Active" or ROLE_LEVEL.get(member.role, -1) < ROLE_LEVEL[minimum]:
                return jsonify({"error": "You do not have permission to perform this action"}), 403
            g.anglera_member = member
            return handler(*args, **kwargs)
        return wrapped
    return decorator


def body(*allowed_fields: str) -> dict:
    return json_object(request.get_json(silent=True), *allowed_fields)


@anglera_api.errorhandler(ValidationError)
def handle_validation(error: ValidationError):
    db.session.rollback()
    return jsonify({"error": str(error)}), 400


@anglera_api.errorhandler(SQLAlchemyError)
def handle_database_error(_error: SQLAlchemyError):
    db.session.rollback()
    return jsonify({"error": "The request could not be completed"}), 500


@anglera_api.get("/health")
def health():
    return jsonify({"status": "ok", "service": "anglera", "realtime": "sse"})


@anglera_api.get("/workspace")
@require_session
@require_role("Viewer")
def get_workspace():
    return jsonify(workspace_snapshot(g.workspace_id))


@anglera_api.get("/analytics")
@require_session
@require_role("Viewer")
def get_analytics():
    try:
        days = int(request.args.get("days", "30"))
    except ValueError as exc:
        raise ValidationError("days must be 7, 30, or 90") from exc
    if days not in {7, 30, 90}:
        raise ValidationError("days must be 7, 30, or 90")
    return jsonify({"analytics": analytics_for_workspace(g.workspace_id, days)})


@anglera_api.post("/products/import")
@require_session
@require_role("Editor")
@rate_limit(20, 60)
def import_products():
    data = body("products", "idempotencyKey")
    raw_products = data.get("products")
    if not isinstance(raw_products, list) or not 1 <= len(raw_products) <= 5000:
        raise ValidationError("products must contain between 1 and 5000 rows")
    validated = []
    seen_skus = set()
    for index, raw in enumerate(raw_products):
        row = json_object(raw, "name", "sku", "image", "specification")
        name = require_text(row.get("name"), f"products[{index}].name", maximum=240)
        sku = require_text(row.get("sku"), f"products[{index}].sku", maximum=120).upper()
        if sku in seen_skus:
            raise ValidationError(f"products contains duplicate SKU: {sku}")
        seen_skus.add(sku)
        specification = optional_text(row.get("specification"), f"products[{index}].specification", maximum=5000, default="Awaiting enrichment")
        image = optional_text(row.get("image"), f"products[{index}].image", maximum=1000, default="/anglera-assets/products/dp4020.png")
        validated.append((name, sku, specification, image))
    existing_by_sku = {
        item.sku: item for item in AngleraProduct.query.filter(
            AngleraProduct.workspace_id == g.workspace_id,
            AngleraProduct.sku.in_(seen_skus),
        ).all()
    }
    imported = []
    for name, sku, specification, image in validated:
        product = existing_by_sku.get(sku)
        if product is None:
            product = AngleraProduct(workspace_id=g.workspace_id, sku=sku, name=name)
            db.session.add(product)
        product.deleted_at = None
        product.name = name
        product.image_url = image
        product.specification = specification
        product.status = "needs-review"
        product.confidence = 0
        product.source_count = max(1, product.source_count or 0)
        imported.append(product)
    try:
        db.session.flush()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValidationError("the import contains duplicate SKU values") from exc
    emit_event(g.workspace_id, "products.imported", "product", payload={"count": len(imported), "ids": [str(item.id) for item in imported]}, actor_user_id=g.greptile_user.id)
    db.session.commit()
    return jsonify({"products": [serialize_product(item) for item in imported], "workspace": workspace_snapshot(g.workspace_id)}), 201


@anglera_api.post("/products/delete")
@require_session
@require_role("Editor")
def delete_products():
    ids = require_uuid_list(body("ids").get("ids"), "ids", maximum=5000, allow_empty=False)
    products = AngleraProduct.query.filter(AngleraProduct.workspace_id == g.workspace_id, AngleraProduct.id.in_(ids), AngleraProduct.deleted_at.is_(None)).all()
    now = datetime.now(timezone.utc)
    for product in products:
        product.deleted_at = now
    emit_event(g.workspace_id, "products.deleted", "product", payload={"count": len(products), "ids": [str(item.id) for item in products]}, actor_user_id=g.greptile_user.id)
    db.session.commit()
    return jsonify({"ok": True, "deleted": len(products)})


def queue_job(kind: str):
    data = body("ids", "idempotencyKey")
    ids = require_uuid_list(data.get("ids"), "ids", maximum=5000)
    key = optional_text(data.get("idempotencyKey"), "idempotencyKey", maximum=80, default=secrets.token_urlsafe(18))
    if kind == "enrich-products":
        model = AngleraProduct
    else:
        model = AngleraSource
    if ids:
        count = model.query.filter(model.workspace_id == g.workspace_id, model.id.in_(ids), model.deleted_at.is_(None)).count()
        if count != len(ids):
            return jsonify({"error": "One or more records were not found"}), 404
    job, created = create_job(g.workspace_id, g.greptile_user.id, kind, {"ids": [str(item) for item in ids]}, key)
    if created:
        dispatch_job(job)
        db.session.refresh(job)
    return jsonify({"job": serialize_job(job)}), 202 if created else 200


@anglera_api.post("/products/enrich")
@require_session
@require_role("Editor")
@rate_limit(20, 60)
def enrich_products():
    return queue_job("enrich-products")


@anglera_api.post("/sources")
@require_session
@require_role("Editor")
@rate_limit(20, 60)
def create_source():
    data = body("name", "type", "location")
    name = require_text(data.get("name"), "name", maximum=120)
    source_type = require_text(data.get("type"), "type", maximum=30)
    if source_type not in {"Website", "Document", "Catalog feed"}:
        raise ValidationError("type must be Website, Document, or Catalog feed")
    location = require_https_url(data.get("location")) if source_type == "Website" else require_text(data.get("location"), "location", maximum=500)
    existing = AngleraSource.query.filter_by(workspace_id=g.workspace_id, location=location).first()
    if existing and existing.deleted_at is None:
        raise ValidationError("this source is already connected")
    source = existing or AngleraSource(workspace_id=g.workspace_id, name=name, source_type=source_type, location=location)
    if existing is None:
        db.session.add(source)
    source.deleted_at = None
    source.name = name
    source.source_type = source_type
    source.status = "Connected"
    source.last_error = None
    db.session.flush()
    emit_event(g.workspace_id, "source.created", "source", source.id, {"name": source.name}, g.greptile_user.id)
    db.session.commit()
    return jsonify({"source": serialize_source(source)}), 201


@anglera_api.post("/sources/sync")
@require_session
@require_role("Editor")
@rate_limit(20, 60)
def sync_sources():
    return queue_job("sync-sources")


@anglera_api.post("/invitations")
@require_session
@require_role("Admin")
@rate_limit(10, 3600)
def invite_member():
    email = require_email(body("email").get("email"))
    member, token = create_invitation(g.workspace_id, g.greptile_user.id, email)
    configured_origins = [item.strip() for item in os.getenv("FRONTEND_ORIGINS", "").split(",") if item.strip() and "*" not in item]
    base_url = (os.getenv("ANGLERA_FRONTEND_URL") or (configured_origins[0] if configured_origins else "http://127.0.0.1:3000")).rstrip("/")
    return jsonify({"member": serialize_member(member), "invitationUrl": f"{base_url}/login?invite={token}"}), 201


@anglera_api.get("/invitations/details")
@rate_limit(30, 60)
def invitation_details():
    token = require_text(request.args.get("token"), "token", minimum=20, maximum=200)
    member = invitation_from_token(token)
    workspace = db.session.get(AngleraWorkspace, member.workspace_id)
    return jsonify({"invitation": {"email": member.email, "workspaceName": workspace.name, "displayName": member.name}})


@anglera_api.post("/invitations/accept")
@rate_limit(10, 3600)
def accept_member_invitation():
    data = body("token", "displayName", "password")
    token = require_text(data.get("token"), "token", minimum=20, maximum=200)
    display_name = require_text(data.get("displayName"), "displayName", maximum=120)
    password = require_password(data.get("password"))
    member, user = accept_invitation(token, display_name, password)
    return jsonify({"member": serialize_member(member), "email": user.email}), 201


@anglera_api.patch("/members/<member_id>")
@require_session
@require_role("Admin")
def update_member(member_id: str):
    member = AngleraMember.query.filter_by(id=require_uuid(member_id, "memberId"), workspace_id=g.workspace_id, deleted_at=None).first()
    if member is None:
        return jsonify({"error": "Member not found"}), 404
    data = body("role")
    role = require_text(data.get("role"), "role", maximum=20)
    if role not in ROLE_LEVEL:
        raise ValidationError("role must be Owner, Admin, Editor, or Viewer")
    if member.role == "Owner" or role == "Owner":
        raise ValidationError("workspace ownership cannot be changed here")
    member.role = role
    emit_event(g.workspace_id, "member.role-updated", "member", member.id, {"role": role}, g.greptile_user.id)
    db.session.commit()
    return jsonify({"member": serialize_member(member)})


@anglera_api.delete("/members/<member_id>")
@require_session
@require_role("Admin")
def remove_member(member_id: str):
    member = AngleraMember.query.filter_by(id=require_uuid(member_id, "memberId"), workspace_id=g.workspace_id, deleted_at=None).first()
    if member is None:
        return jsonify({"error": "Member not found"}), 404
    if member.role == "Owner":
        raise ValidationError("the workspace owner cannot be removed")
    member.deleted_at = datetime.now(timezone.utc)
    member.invitation_token_hash = None
    emit_event(g.workspace_id, "member.removed", "member", member.id, {"email": member.email}, g.greptile_user.id)
    db.session.commit()
    return jsonify({"ok": True})


@anglera_api.patch("/settings")
@require_session
@require_role("Admin")
def update_settings():
    data = body("webSettings", "workspaceProfile")
    workspace = db.session.get(AngleraWorkspace, g.workspace_id)
    web = data.get("webSettings")
    if web is not None:
        web = json_object(web, "primaryDomain", "crawlDepth", "includePdfManuals", "respectRobots", "automaticEnrichment")
        workspace.primary_domain = require_https_url(web.get("primaryDomain"), "primaryDomain")
        crawl_depth = require_text(web.get("crawlDepth"), "crawlDepth", maximum=30)
        if crawl_depth not in {"product-only", "product-and-docs", "entire-site"}:
            raise ValidationError("crawlDepth is invalid")
        workspace.crawl_depth = crawl_depth
        workspace.include_pdf_manuals = require_bool(web.get("includePdfManuals"), "includePdfManuals")
        workspace.respect_robots = require_bool(web.get("respectRobots"), "respectRobots")
        workspace.automatic_enrichment = require_bool(web.get("automaticEnrichment"), "automaticEnrichment")
    profile = data.get("workspaceProfile")
    if profile is not None:
        profile = json_object(profile, "displayName", "workspaceName")
        workspace.name = require_text(profile.get("workspaceName"), "workspaceName", maximum=120)
        g.anglera_member.name = require_text(profile.get("displayName"), "displayName", maximum=120)
    emit_event(g.workspace_id, "workspace.settings-updated", "workspace", workspace.id, actor_user_id=g.greptile_user.id)
    db.session.commit()
    return jsonify({"workspace": workspace_snapshot(g.workspace_id)})


@anglera_api.get("/jobs/<job_id>")
@require_session
@require_role("Viewer")
def get_job(job_id: str):
    job = AngleraJob.query.filter_by(id=require_uuid(job_id, "jobId"), workspace_id=g.workspace_id, deleted_at=None).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"job": serialize_job(job)})


@anglera_api.get("/events")
@require_session
@require_role("Viewer")
def events():
    raw_cursor = request.headers.get("Last-Event-ID") or request.args.get("after", "0")
    try:
        cursor = max(0, int(raw_cursor))
    except ValueError as exc:
        raise ValidationError("event cursor must be an integer") from exc
    workspace_id = g.workspace_id

    @stream_with_context
    def generate():
        nonlocal cursor
        started = time.monotonic()
        last_heartbeat = 0.0
        while time.monotonic() - started < 55:
            rows = AngleraEvent.query.filter(AngleraEvent.workspace_id == workspace_id, AngleraEvent.id > cursor).order_by(AngleraEvent.id.asc()).limit(100).all()
            if rows:
                for event in rows:
                    cursor = int(event.id)
                    payload = {"id": cursor, "type": event.event_type, "entityType": event.entity_type, "entityId": event.entity_id, "payload": event.payload_json}
                    yield f"id: {cursor}\nevent: workspace\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
                db.session.remove()
            elif time.monotonic() - last_heartbeat >= 10:
                last_heartbeat = time.monotonic()
                yield ": heartbeat\n\n"
            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
