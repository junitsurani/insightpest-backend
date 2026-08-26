from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.greptile.models import GreptileUser
from app.models import db
from .models import AngleraEvent, AngleraJob, AngleraMember, AngleraProduct, AngleraSource, AngleraWorkspace
from .validation import ValidationError, assert_public_hostname, require_https_url


DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_IMAGE = "/anglera-assets/products/dp4020.png"

DEMO_PRODUCTS = [
    ('8.5" Cultivator Hoe Weeding Blade, WA400MP', "1913L5-4", "SPEED: 970 SPM for powerful, efficient weeding—6.5 times faster than manual cultivation.", 3),
    ('24" Hedge Trimmer Blade Assembly, GNU01', "1914E7-7", "APPLICATIONS: Designed for controlled, efficient cutting in wet and dense hedges.", 3),
    ("Water Supply Attachment Kit", "191X01-4", "COMPATIBILITY: For use with Makita Multi-Cutter model PC01 and approved water systems.", 2),
    ('1-5/8" Multi-Cutter Blade', "198603-3", "DURABILITY: Carbide construction delivers clean cuts and dependable service life.", 2),
    ("40V max XGT® 4.0Ah High Power Battery", "BL4040F", "CONVENIENCE: Battery charge level with four bright green L.E.D. indicators.", 4),
    ("40V max ConnectX™ Brushless Backpack Blower", "CBU04Z", "POWER: Makita-built brushless motor delivers the power of a 64cc gas backpack blower.", 5),
    ("18V LXT® Lithium-Ion Sub-Compact Brushless Combo Kit", "CX203SYBXRJ", 'DRIVER-DRILL: Compact 5-7/8" design weighs only 2.8 lbs. for reduced fatigue.', 4),
    ("18V LXT® Lithium-Ion Sub-Compact Brushless Combo Kit", "CX203SYBXRM", 'IMPACT DRIVER: Compact 5-1/4" design balances power, control and comfort.', 4),
    ('1/2" Drill', "DP4020", "VERSATILITY: Variable speed (0–3,000 RPM) for controlled drilling in a wide variety of materials.", 6),
    ('1/2" Drill with Keyless Chuck', "DP4021", 'COMFORT: 3/8" steel and 1" wood drilling capacity with a large trigger switch.', 5),
    ('40V max XGT® Brushless Cordless 3/8" Metal Hole Puncher', "GPP01ZK", 'CAPACITY: Maximum metal plate thickness of 3/8" in general steel.', 3),
    ("18V LXT® Brushless Cordless Impact Driver", "XDT19Z", "CONTROL: Four speed settings provide fastening control for demanding jobs.", 4),
    ("18V LXT® Compact Reciprocating Saw", "XRJ08Z", "PERFORMANCE: Brushless motor delivers 0–3,100 strokes per minute for faster cutting.", 3),
    ("40V max XGT® Cordless Circular Saw", "GSH01Z", "PRECISION: Bevel capacity from 0°–56° with positive stops at 22.5° and 45°.", 4),
    ("18V LXT® Lithium-Ion 5.0Ah Battery", "BL1850B", "RUN TIME: Up to 65% more run time per charge than the 3.0Ah battery.", 3),
    ("18V LXT® Brushless Angle Grinder", "XAG25Z", "SAFETY: Active Feedback-sensing Technology turns the motor off if rotation is forced to stop.", 4),
    ("40V max XGT® Brushless Hammer Driver-Drill", "GPH01Z", "TORQUE: 1,250 in.lbs. of max torque with an all-metal two-speed transmission.", 5),
]

PRODUCT_IMAGES = {
    "1913L5-4": "/anglera-assets/products/1913l5-4.png",
    "1914E7-7": "/anglera-assets/products/1914e7-7.png",
    "191X01-4": "/anglera-assets/products/191x01-4.png",
    "198603-3": "/anglera-assets/products/198603-3.png",
    "BL4040F": "/anglera-assets/products/bl4040f.png",
    "CBU04Z": "/anglera-assets/products/cbu04z.png",
    "CX203SYBXRJ": "/anglera-assets/products/cx203sybxrj.png",
    "CX203SYBXRM": "/anglera-assets/products/cx203sybxrm.png",
    "DP4020": "/anglera-assets/products/dp4020.png",
    "DP4021": "/anglera-assets/products/dp4021.png",
    "GPP01ZK": "/anglera-assets/products/gpp01zk.png",
    "XDT19Z": "/anglera-assets/products/xdt19z.png",
    "XRJ08Z": "/anglera-assets/products/xrj08z.png",
    "GSH01Z": "/anglera-assets/products/gsh01z.png",
    "BL1850B": "/anglera-assets/products/bl1850b.png",
    "XAG25Z": "/anglera-assets/products/xag25z.png",
    "GPH01Z": "/anglera-assets/products/gph01z.png",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00", "Z")


def relative_time(value: datetime | None) -> str:
    if value is None:
        return "Never"
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    seconds = max(0, int((utcnow() - aware).total_seconds()))
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def emit_event(workspace_id: uuid.UUID, event_type: str, entity_type: str, entity_id: object = None, payload: dict | None = None, actor_user_id: uuid.UUID | None = None) -> AngleraEvent:
    event = AngleraEvent(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        payload_json=payload or {},
    )
    db.session.add(event)
    return event


def ensure_workspace(workspace_id: uuid.UUID, *, name: str = "Anglera Demo Workspace") -> AngleraWorkspace:
    workspace = db.session.get(AngleraWorkspace, workspace_id)
    if workspace is not None and workspace.deleted_at is None:
        return workspace
    workspace = AngleraWorkspace(id=workspace_id, name=name)
    db.session.add(workspace)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        workspace = db.session.get(AngleraWorkspace, workspace_id)
        if workspace is None:
            raise
    return workspace


def ensure_owner(workspace_id: uuid.UUID, user) -> AngleraMember:
    member = AngleraMember.query.filter_by(workspace_id=workspace_id, email=user.email.lower(), deleted_at=None).first()
    if member:
        if member.status != "Active" or member.user_id != user.id:
            member.status = "Active"
            member.user_id = user.id
            member.invitation_token_hash = None
            member.invitation_expires_at = None
            db.session.commit()
        return member
    member = AngleraMember(
        workspace_id=workspace_id,
        user_id=user.id,
        name=user.display_name,
        email=user.email.lower(),
        role="Owner" if AngleraMember.query.filter_by(workspace_id=workspace_id, deleted_at=None).count() == 0 else "Editor",
        status="Active",
    )
    db.session.add(member)
    db.session.commit()
    return member


def seed_demo_workspace(user=None) -> None:
    workspace = ensure_workspace(DEFAULT_WORKSPACE_ID)
    if user is not None:
        ensure_owner(workspace.id, user)
    demo_products = {
        product.sku: product
        for product in AngleraProduct.query.filter_by(workspace_id=workspace.id, deleted_at=None).all()
    }
    for index, (name, sku, specification, source_count) in enumerate(DEMO_PRODUCTS):
        image = PRODUCT_IMAGES.get(sku, DEFAULT_IMAGE)
        product = demo_products.get(sku)
        if product is None:
            db.session.add(AngleraProduct(
                workspace_id=workspace.id, name=name, sku=sku, specification=specification,
                image_url=image, source_count=source_count,
                confidence=94 + (index % 6), status="ready",
            ))
        elif product.source_system == "anglera_clone" and product.image_url != image:
            # Reconcile the deterministic demo catalog without touching user imports.
            product.image_url = image
    if AngleraSource.query.filter_by(workspace_id=workspace.id, deleted_at=None).count() == 0:
        now = utcnow()
        db.session.add_all([
            AngleraSource(workspace_id=workspace.id, name="Makita product website", source_type="Website", location="https://www.makitatools.com/products", status="Connected", record_count=17, last_synced_at=now),
            AngleraSource(workspace_id=workspace.id, name="Product manuals", source_type="Document", location="17 PDF manuals", status="Connected", record_count=17, last_synced_at=now),
            AngleraSource(workspace_id=workspace.id, name="Master catalog", source_type="Catalog feed", location="anglera-demo-products.csv", status="Connected", record_count=17, last_synced_at=now),
        ])
    db.session.commit()


def serialize_product(product: AngleraProduct) -> dict:
    return {
        "id": str(product.id), "status": product.status, "name": product.name, "sku": product.sku,
        "image": product.image_url, "specification": product.specification,
        "sourceCount": product.source_count, "confidence": product.confidence,
        "updatedAt": relative_time(product.updated_at), "updatedAtIso": iso(product.updated_at),
    }


def serialize_source(source: AngleraSource) -> dict:
    return {
        "id": str(source.id), "name": source.name, "type": source.source_type,
        "location": source.location, "status": source.status, "records": source.record_count,
        "lastSync": relative_time(source.last_synced_at), "lastSyncIso": iso(source.last_synced_at),
        "lastError": source.last_error,
    }


def serialize_member(member: AngleraMember) -> dict:
    return {
        "id": str(member.id), "name": member.name, "email": member.email, "role": member.role,
        "status": member.status, "createdAt": relative_time(member.created_at),
        "createdAtIso": iso(member.created_at),
    }


def serialize_job(job: AngleraJob) -> dict:
    return {
        "id": str(job.id), "kind": job.kind, "status": job.status, "progress": job.progress,
        "result": job.result_json, "error": job.error_message,
        "createdAt": iso(job.created_at), "startedAt": iso(job.started_at), "completedAt": iso(job.completed_at),
    }


def analytics_for_workspace(workspace_id: uuid.UUID, days: int = 30) -> dict:
    products = AngleraProduct.query.filter_by(workspace_id=workspace_id, deleted_at=None).all()
    sources = AngleraSource.query.filter_by(workspace_id=workspace_id, deleted_at=None).all()
    ready = sum(item.status == "ready" for item in products)
    completeness = round(sum(item.confidence for item in products) / len(products)) if products else 0
    since = utcnow() - timedelta(days=days)
    activity = AngleraEvent.query.filter(AngleraEvent.workspace_id == workspace_id, AngleraEvent.created_at >= since).count()
    return {
        "periodDays": days, "completeness": completeness, "readyProducts": ready,
        "totalProducts": len(products), "fieldsEnriched": ready * 12,
        "sourceCoverage": sum(item.status == "Connected" for item in sources),
        "activityCount": activity,
        "fieldGroups": [
            {"label": "Specifications", "value": completeness},
            {"label": "Product identity", "value": 100 if products else 0},
            {"label": "Images", "value": round(100 * sum(bool(item.image_url) for item in products) / len(products)) if products else 0},
            {"label": "Descriptions", "value": round(100 * sum(item.specification != "Awaiting enrichment" for item in products) / len(products)) if products else 0},
            {"label": "Source evidence", "value": round(100 * sum(item.source_count > 0 for item in products) / len(products)) if products else 0},
        ],
    }


def workspace_snapshot(workspace_id: uuid.UUID) -> dict:
    workspace = db.session.get(AngleraWorkspace, workspace_id)
    products = AngleraProduct.query.filter_by(workspace_id=workspace_id, deleted_at=None).order_by(AngleraProduct.created_at.asc()).all()
    sources = AngleraSource.query.filter_by(workspace_id=workspace_id, deleted_at=None).order_by(AngleraSource.created_at.asc()).all()
    members = AngleraMember.query.filter_by(workspace_id=workspace_id, deleted_at=None).order_by(AngleraMember.created_at.asc()).all()
    latest_event = db.session.query(db.func.max(AngleraEvent.id)).filter_by(workspace_id=workspace_id).scalar() or 0
    return {
        "products": [serialize_product(item) for item in products],
        "sources": [serialize_source(item) for item in sources],
        "members": [serialize_member(item) for item in members],
        "webSettings": {
            "primaryDomain": workspace.primary_domain,
            "crawlDepth": workspace.crawl_depth,
            "includePdfManuals": workspace.include_pdf_manuals,
            "respectRobots": workspace.respect_robots,
            "automaticEnrichment": workspace.automatic_enrichment,
        },
        "workspaceProfile": {"displayName": next((item.name for item in members if item.role == "Owner"), "Anglera User"), "workspaceName": workspace.name},
        "analytics": analytics_for_workspace(workspace_id),
        "eventCursor": int(latest_event),
    }


def create_invitation(workspace_id: uuid.UUID, actor_user_id: uuid.UUID, email: str) -> tuple[AngleraMember, str | None]:
    existing = AngleraMember.query.filter_by(workspace_id=workspace_id, email=email).first()
    if existing and existing.deleted_at is None:
        raise ValidationError("that person is already a member or has a pending invitation")
    token = secrets.token_urlsafe(32)
    name = re.sub(r"[._-]+", " ", email.split("@", 1)[0]).title()
    if existing:
        member = existing
        member.deleted_at = None
        member.name = name
        member.role = "Editor"
        member.status = "Invited"
    else:
        member = AngleraMember(workspace_id=workspace_id, name=name, email=email, role="Editor", status="Invited")
        db.session.add(member)
    member.invited_by_user_id = actor_user_id
    member.invitation_token_hash = hashlib.sha256(token.encode()).hexdigest()
    member.invitation_expires_at = utcnow() + timedelta(days=7)
    db.session.flush()
    emit_event(workspace_id, "member.invited", "member", member.id, {"email": email}, actor_user_id)
    db.session.commit()
    return member, token


def invitation_from_token(token: str) -> AngleraMember:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    member = AngleraMember.query.filter_by(invitation_token_hash=token_hash, status="Invited", deleted_at=None).first()
    if member is None or member.invitation_expires_at is None:
        raise ValidationError("this invitation is invalid or has already been used")
    expires = member.invitation_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= utcnow():
        raise ValidationError("this invitation has expired")
    return member


def accept_invitation(token: str, display_name: str, password: str) -> tuple[AngleraMember, GreptileUser]:
    member = invitation_from_token(token)
    user = GreptileUser.query.filter_by(email=member.email, deleted_at=None).first()
    if user is not None and user.workspace_id != member.workspace_id:
        raise ValidationError("an account with this email belongs to another workspace")
    if user is None:
        if not 8 <= len(password) <= 128:
            raise ValidationError("password must be between 8 and 128 characters")
        user = GreptileUser(
            workspace_id=member.workspace_id,
            email=member.email,
            display_name=display_name,
            password_hash=generate_password_hash(password),
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
    member.user_id = user.id
    member.name = display_name
    member.status = "Active"
    member.invitation_token_hash = None
    member.invitation_expires_at = None
    emit_event(member.workspace_id, "member.joined", "member", member.id, {"email": member.email}, user.id)
    db.session.commit()
    return member, user


def _visible_text(content: str) -> str:
    content = re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>", " ", content)
    content = re.sub(r"(?s)<[^>]+>", " ", content)
    return " ".join(html.unescape(content).split())[:100_000]


def sync_remote_source(source: AngleraSource) -> dict:
    if source.source_type != "Website":
        source.status = "Connected"
        source.last_synced_at = utcnow()
        source.last_error = None
        return {"records": source.record_count, "changed": False}
    url = require_https_url(source.location)
    assert_public_hostname(url)
    response = requests.get(
        url, timeout=(5, 15), allow_redirects=False,
        headers={"User-Agent": "AngleraCatalogBot/1.0 (+catalog enrichment; contact workspace owner)", "Accept": "text/html,application/xhtml+xml"},
        stream=True,
    )
    try:
        if 300 <= response.status_code < 400:
            raise ValidationError("source redirects are not followed; save its final HTTPS URL")
        if response.status_code >= 400:
            raise ValidationError(f"source returned HTTP {response.status_code}")
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise ValidationError("website source did not return HTML")
        content_length = int(response.headers.get("Content-Length", "0") or 0)
        if content_length > 1_000_000:
            raise ValidationError("website source is larger than 1 MB")
        chunks = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            chunks.extend(chunk)
            if len(chunks) > 1_000_000:
                raise ValidationError("website source is larger than 1 MB")
        raw = bytes(chunks)
    finally:
        response.close()
    text = _visible_text(raw.decode(response.encoding or "utf-8", errors="replace"))
    digest = hashlib.sha256(raw).hexdigest()
    changed = digest != source.content_etag
    source.content_text = text
    source.content_etag = digest
    source.record_count = max(source.record_count, len(re.findall(r'(?i)"@type"\s*:\s*"Product"', raw.decode(errors="ignore"))))
    source.status = "Connected"
    source.last_synced_at = utcnow()
    source.last_error = None
    return {"records": source.record_count, "changed": changed, "host": urlparse(url).hostname}


def enrich_product(product: AngleraProduct, sources: list[AngleraSource]) -> dict:
    evidence = [source for source in sources if source.status == "Connected" and source.deleted_at is None]
    matching_text = next((source.content_text or "" for source in evidence if source.content_text and product.sku.lower() in source.content_text.lower()), "")
    if product.specification.strip().lower() in {"", "awaiting enrichment"} and matching_text:
        position = matching_text.lower().find(product.sku.lower())
        snippet = matching_text[max(0, position - 120): position + 380].strip()
        product.specification = snippet if len(snippet) >= 20 else product.specification
    fields = [bool(product.name), bool(product.sku), bool(product.image_url), product.specification.strip().lower() not in {"", "awaiting enrichment"}]
    confidence = min(99, round(100 * sum(fields) / len(fields)) + min(9, len(evidence) * 2))
    product.source_count = max(product.source_count, len(evidence))
    product.confidence = confidence
    product.status = "ready" if all(fields) else "needs-review"
    return {"status": product.status, "confidence": confidence, "matchedSourceText": bool(matching_text)}
