from __future__ import annotations

import csv
import io
import json
import math
import secrets
from datetime import datetime, timezone

from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.models import db
from .auth import require_session
from .models import (
    OpenmartApiKey, OpenmartBusiness, OpenmartExport, OpenmartInvitation,
    OpenmartLeadList, OpenmartLeadListItem, OpenmartSavedSearch, OpenmartSequence,
    OpenmartSequenceStep, OpenmartUsageEvent, OpenmartUser,
)
from .services import enrichment_for, key_hash, search_catalog
from .validation import ValidationError, email, identifier, json_object, only_fields, optional_text, text


openmart_api = Blueprint("openmart_api", __name__, url_prefix="/api/openmart")


def iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def owned(model, raw_id):
    try:
        row_id = identifier(raw_id)
    except ValidationError:
        return None
    return model.query.filter_by(id=row_id, workspace_id=g.workspace_id, deleted_at=None).first()


def business_json(row: OpenmartBusiness):
    return {
        "id": str(row.id), "externalId": row.external_id, "name": row.name, "category": row.category,
        "street": row.street, "city": row.city, "region": row.region, "country": row.country,
        "postalCode": row.postal_code, "website": row.website, "phone": row.phone,
        "companyEmail": row.company_email, "ownerName": row.owner_name, "ownerTitle": row.owner_title,
        "ownerEmail": row.owner_email, "ownerPhone": row.owner_phone, "rating": row.rating,
        "reviewCount": row.review_count, "employeeCount": row.employee_count,
        "revenueEstimate": row.revenue_estimate, "status": row.status, "isEnriched": row.is_enriched,
        "updatedAt": iso(row.updated_at),
    }


def list_json(row: OpenmartLeadList, include_items=False):
    active_items = [item for item in row.items if item.deleted_at is None]
    result = {
        "id": str(row.id), "name": row.name, "description": row.description,
        "recordCount": len(active_items), "createdAt": iso(row.created_at), "updatedAt": iso(row.updated_at),
    }
    if include_items:
        result["items"] = [
            {"id": str(item.id), "contactStatus": item.contact_status, "notes": item.notes, "business": business_json(item.business)}
            for item in active_items
        ]
    return result


def sequence_json(row: OpenmartSequence):
    return {
        "id": str(row.id), "name": row.name, "status": row.status,
        "leadListId": str(row.lead_list_id) if row.lead_list_id else None,
        "senderEmail": row.sender_email, "sentCount": row.sent_count, "replyCount": row.reply_count,
        "steps": [{"id": str(step.id), "order": step.step_order, "delayDays": step.delay_days, "subject": step.subject, "body": step.body} for step in row.steps if step.deleted_at is None],
        "createdAt": iso(row.created_at), "updatedAt": iso(row.updated_at),
    }


def log_usage(event_type: str, subject: str, credits_delta=0):
    db.session.add(OpenmartUsageEvent(workspace_id=g.workspace_id, user_id=g.openmart_user.id, event_type=event_type, subject=subject[:240], credits_delta=credits_delta))


@openmart_api.errorhandler(ValidationError)
def validation_error(error):
    return jsonify({"error": str(error)}), 400


@openmart_api.get("/health")
def health():
    return jsonify({"ok": True, "service": "openmart"})


@openmart_api.get("/bootstrap")
@require_session
def bootstrap():
    lists = OpenmartLeadList.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartLeadList.updated_at.desc()).limit(10).all()
    searches = OpenmartSavedSearch.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartSavedSearch.created_at.desc()).limit(6).all()
    sequences = OpenmartSequence.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartSequence.updated_at.desc()).limit(6).all()
    total_leads = db.session.query(func.count(OpenmartLeadListItem.id)).join(OpenmartLeadList).filter(OpenmartLeadList.workspace_id == g.workspace_id, OpenmartLeadListItem.deleted_at.is_(None), OpenmartLeadList.deleted_at.is_(None)).scalar() or 0
    enriched = OpenmartBusiness.query.filter_by(workspace_id=g.workspace_id, deleted_at=None, is_enriched=True).count()
    return jsonify({
        "user": {"id": str(g.openmart_user.id), "displayName": g.openmart_user.display_name, "email": g.openmart_user.email, "role": g.openmart_user.role},
        "workspace": {"id": str(g.openmart_user.workspace.id), "name": g.openmart_user.workspace.name, "plan": g.openmart_user.workspace.plan, "credits": g.openmart_user.workspace.credits_balance, "country": g.openmart_user.workspace.default_country},
        "stats": {"leadLists": len(lists), "savedLeads": int(total_leads), "enrichedLeads": enriched, "activeSequences": sum(1 for sequence in sequences if sequence.status == "active")},
        "lists": [list_json(row) for row in lists],
        "searches": [{"id": str(row.id), "query": row.search_query, "location": row.location, "resultCount": row.result_count, "createdAt": iso(row.created_at)} for row in searches],
        "sequences": [sequence_json(row) for row in sequences],
    })


def materialize_business(source):
    row = OpenmartBusiness.query.filter_by(workspace_id=g.workspace_id, external_id=source["external_id"], deleted_at=None).first()
    if row:
        return row
    row = OpenmartBusiness(
        workspace_id=g.workspace_id, external_id=source["external_id"], name=source["name"], category=source["category"],
        street=source["street"], city=source["city"], region=source["region"], country=source["country"], postal_code=source["postal_code"],
        website=source["website"], phone=source["phone"], owner_name=source["owner_name"], owner_title=source["owner_title"],
        rating=source["rating"], review_count=source["review_count"], employee_count=source["employee_count"], revenue_estimate=source["revenue_estimate"],
    )
    db.session.add(row)
    db.session.flush()
    return row


@openmart_api.post("/search")
@require_session
def search():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"query", "location", "filters", "limit"})
    query = text(data.get("query"), "query", minimum=2, maximum=240)
    location = optional_text(data.get("location", ""), "location", maximum=240)
    filters = data.get("filters", {})
    if not isinstance(filters, dict) or set(filters) - {"minimumRating", "minimumReviews", "maximumEmployees", "hasWebsite"}:
        raise ValidationError("filters are invalid")
    limit = data.get("limit", 50)
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValidationError("limit must be between 1 and 100")
    matches = search_catalog(query, location, filters, limit)
    rows = [materialize_business(source) for source in matches]
    saved = OpenmartSavedSearch(workspace_id=g.workspace_id, user_id=g.openmart_user.id, search_query=query, location=location, filters_json=json.dumps(filters, separators=(",", ":"), sort_keys=True), result_count=len(rows))
    db.session.add(saved)
    log_usage("search", f"{query} · {location or 'Any location'}")
    db.session.commit()
    return jsonify({"searchId": str(saved.id), "total": len(rows), "businesses": [business_json(row) for row in rows]})


@openmart_api.get("/businesses")
@require_session
def businesses():
    search_term = request.args.get("search", "").strip().lower()[:120]
    query = OpenmartBusiness.query.filter_by(workspace_id=g.workspace_id, deleted_at=None)
    if search_term:
        query = query.filter(func.lower(OpenmartBusiness.name).contains(search_term))
    return jsonify({"businesses": [business_json(row) for row in query.order_by(OpenmartBusiness.updated_at.desc()).limit(200).all()]})


@openmart_api.post("/businesses/<business_id>/enrich")
@require_session
def enrich_business(business_id):
    row = owned(OpenmartBusiness, business_id)
    if not row:
        return jsonify({"error": "Business not found"}), 404
    data = json_object(request.get_json(silent=True) or {})
    only_fields(data, {"fields"})
    fields = data.get("fields", ["companyEmail", "ownerEmail", "ownerPhone"])
    allowed = {"companyEmail": 1, "ownerEmail": 3, "ownerPhone": 8}
    if not isinstance(fields, list) or not fields or len(fields) > 3 or any(field not in allowed for field in fields):
        raise ValidationError("fields are invalid")
    values = enrichment_for(row)
    missing = [field for field in fields if not {"companyEmail": row.company_email, "ownerEmail": row.owner_email, "ownerPhone": row.owner_phone}[field]]
    cost = sum(allowed[field] for field in missing)
    if g.openmart_user.workspace.credits_balance < cost:
        return jsonify({"error": "Not enough credits", "creditsRequired": cost, "creditsAvailable": g.openmart_user.workspace.credits_balance}), 402
    if "companyEmail" in fields:
        row.company_email = values["company_email"]
    if "ownerEmail" in fields:
        row.owner_email = values["owner_email"]
    if "ownerPhone" in fields:
        row.owner_phone = values["owner_phone"]
    row.is_enriched = bool(row.company_email or row.owner_email or row.owner_phone)
    g.openmart_user.workspace.credits_balance -= cost
    log_usage("enrichment", row.name, -cost)
    db.session.commit()
    return jsonify({"business": business_json(row), "creditsUsed": cost, "creditsRemaining": g.openmart_user.workspace.credits_balance})


@openmart_api.get("/lists")
@require_session
def lists():
    rows = OpenmartLeadList.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartLeadList.updated_at.desc()).limit(200).all()
    return jsonify({"lists": [list_json(row) for row in rows]})


@openmart_api.post("/lists")
@require_session
def create_list():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"name", "description", "businessIds"})
    row = OpenmartLeadList(workspace_id=g.workspace_id, user_id=g.openmart_user.id, name=text(data.get("name"), "name", maximum=160), description=optional_text(data.get("description", ""), "description", maximum=800))
    db.session.add(row)
    db.session.flush()
    business_ids = data.get("businessIds", [])
    if not isinstance(business_ids, list) or len(business_ids) > 500:
        raise ValidationError("businessIds must be a list of up to 500 identifiers")
    seen = set()
    for raw_id in business_ids:
        business = owned(OpenmartBusiness, raw_id)
        if not business:
            return jsonify({"error": "Business not found"}), 404
        if business.id not in seen:
            db.session.add(OpenmartLeadListItem(lead_list_id=row.id, business_id=business.id))
            seen.add(business.id)
    log_usage("list_created", row.name)
    db.session.commit()
    return jsonify({"list": list_json(row, include_items=True)}), 201


@openmart_api.get("/lists/<list_id>")
@require_session
def list_detail(list_id):
    row = owned(OpenmartLeadList, list_id)
    if not row:
        return jsonify({"error": "Lead list not found"}), 404
    return jsonify({"list": list_json(row, include_items=True)})


@openmart_api.patch("/lists/<list_id>")
@require_session
def update_list(list_id):
    row = owned(OpenmartLeadList, list_id)
    if not row:
        return jsonify({"error": "Lead list not found"}), 404
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"name", "description"})
    if "name" in data:
        row.name = text(data["name"], "name", maximum=160)
    if "description" in data:
        row.description = optional_text(data["description"], "description", maximum=800)
    db.session.commit()
    return jsonify({"list": list_json(row, include_items=True)})


@openmart_api.delete("/lists/<list_id>")
@require_session
def delete_list(list_id):
    row = owned(OpenmartLeadList, list_id)
    if not row:
        return jsonify({"error": "Lead list not found"}), 404
    row.deleted_at = datetime.now(timezone.utc)
    for item in row.items:
        item.deleted_at = row.deleted_at
    db.session.commit()
    return jsonify({"ok": True})


@openmart_api.post("/lists/<list_id>/items")
@require_session
def add_list_items(list_id):
    row = owned(OpenmartLeadList, list_id)
    if not row:
        return jsonify({"error": "Lead list not found"}), 404
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"businessIds"})
    business_ids = data.get("businessIds")
    if not isinstance(business_ids, list) or not business_ids or len(business_ids) > 500:
        raise ValidationError("businessIds must contain between 1 and 500 identifiers")
    existing = {item.business_id for item in row.items if item.deleted_at is None}
    for raw_id in business_ids:
        business = owned(OpenmartBusiness, raw_id)
        if not business:
            return jsonify({"error": "Business not found"}), 404
        if business.id not in existing:
            db.session.add(OpenmartLeadListItem(lead_list_id=row.id, business_id=business.id))
            existing.add(business.id)
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"list": list_json(row, include_items=True)})


@openmart_api.patch("/lists/<list_id>/items/<item_id>")
@require_session
def update_list_item(list_id, item_id):
    row = owned(OpenmartLeadList, list_id)
    if not row:
        return jsonify({"error": "Lead list not found"}), 404
    item = OpenmartLeadListItem.query.filter_by(id=identifier(item_id), lead_list_id=row.id, deleted_at=None).first()
    if not item:
        return jsonify({"error": "Lead not found"}), 404
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"contactStatus", "notes"})
    if "contactStatus" in data:
        if data["contactStatus"] not in {"lead", "contacted", "replied", "qualified", "archived"}:
            raise ValidationError("contactStatus is invalid")
        item.contact_status = data["contactStatus"]
    if "notes" in data:
        item.notes = optional_text(data["notes"], "notes", maximum=2000)
    db.session.commit()
    return jsonify({"item": {"id": str(item.id), "contactStatus": item.contact_status, "notes": item.notes, "business": business_json(item.business)}})


@openmart_api.delete("/lists/<list_id>/items/<item_id>")
@require_session
def delete_list_item(list_id, item_id):
    row = owned(OpenmartLeadList, list_id)
    if not row:
        return jsonify({"error": "Lead list not found"}), 404
    item = OpenmartLeadListItem.query.filter_by(id=identifier(item_id), lead_list_id=row.id, deleted_at=None).first()
    if not item:
        return jsonify({"error": "Lead not found"}), 404
    item.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"ok": True})


@openmart_api.get("/exports")
@require_session
def exports():
    rows = OpenmartExport.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartExport.created_at.desc()).limit(100).all()
    return jsonify({"exports": [{"id": str(row.id), "filename": row.filename, "format": row.format, "rowCount": row.row_count, "leadListId": str(row.lead_list_id) if row.lead_list_id else None, "downloadUrl": f"/api/openmart/exports/{row.id}/download", "createdAt": iso(row.created_at)} for row in rows]})


@openmart_api.post("/exports")
@require_session
def create_export():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"leadListId", "format", "fields"})
    lead_list = owned(OpenmartLeadList, data.get("leadListId"))
    if not lead_list:
        return jsonify({"error": "Lead list not found"}), 404
    export_format = data.get("format", "csv")
    if export_format not in {"csv", "xlsx"}:
        raise ValidationError("format is invalid")
    allowed_fields = {"name", "category", "phone", "companyEmail", "ownerName", "ownerTitle", "ownerEmail", "ownerPhone", "website", "city", "region", "rating", "reviewCount", "employeeCount", "revenueEstimate"}
    fields = data.get("fields", ["name", "category", "phone", "companyEmail", "ownerName", "ownerEmail", "website", "city", "region"])
    if not isinstance(fields, list) or not fields or len(fields) > 15 or any(field not in allowed_fields for field in fields):
        raise ValidationError("fields are invalid")
    active_items = [item for item in lead_list.items if item.deleted_at is None]
    cost = math.ceil(len(active_items) / 20) if any(field in {"companyEmail", "ownerEmail", "ownerPhone"} for field in fields) else 0
    if g.openmart_user.workspace.credits_balance < cost:
        return jsonify({"error": "Not enough credits", "creditsRequired": cost, "creditsAvailable": g.openmart_user.workspace.credits_balance}), 402
    g.openmart_user.workspace.credits_balance -= cost
    safe_name = "".join(char.lower() if char.isalnum() else "-" for char in lead_list.name).strip("-") or "openmart-leads"
    row = OpenmartExport(workspace_id=g.workspace_id, user_id=g.openmart_user.id, lead_list_id=lead_list.id, filename=f"{safe_name}.{export_format}", format=export_format, fields_json=json.dumps(fields), row_count=len(active_items))
    db.session.add(row)
    log_usage("export", row.filename, -cost)
    db.session.commit()
    return jsonify({"export": {"id": str(row.id), "filename": row.filename, "format": row.format, "rowCount": row.row_count, "downloadUrl": f"/api/openmart/exports/{row.id}/download", "creditsUsed": cost, "creditsRemaining": g.openmart_user.workspace.credits_balance}}), 201


def csv_safe(value):
    rendered = "" if value is None else str(value)
    if rendered.startswith(("=", "+", "-", "@")):
        rendered = "'" + rendered
    return rendered


@openmart_api.get("/exports/<export_id>/download")
@require_session
def download_export(export_id):
    row = owned(OpenmartExport, export_id)
    if not row:
        return jsonify({"error": "Export not found"}), 404
    lead_list = owned(OpenmartLeadList, row.lead_list_id) if row.lead_list_id else None
    if not lead_list:
        return jsonify({"error": "Lead list not found"}), 404
    fields = json.loads(row.fields_json)
    attribute_map = {"companyEmail": "company_email", "ownerName": "owner_name", "ownerTitle": "owner_title", "ownerEmail": "owner_email", "ownerPhone": "owner_phone", "reviewCount": "review_count", "employeeCount": "employee_count", "revenueEstimate": "revenue_estimate"}
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(fields)
    for item in lead_list.items:
        if item.deleted_at is None:
            writer.writerow([csv_safe(getattr(item.business, attribute_map.get(field, field), "")) for field in fields])
    headers = {"Content-Disposition": f'attachment; filename="{row.filename.rsplit(".", 1)[0]}.csv"', "X-Content-Type-Options": "nosniff"}
    return Response(output.getvalue(), mimetype="text/csv", headers=headers)


@openmart_api.get("/sequences")
@require_session
def sequences():
    rows = OpenmartSequence.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartSequence.updated_at.desc()).limit(100).all()
    return jsonify({"sequences": [sequence_json(row) for row in rows]})


@openmart_api.post("/sequences")
@require_session
def create_sequence():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"name", "leadListId", "senderEmail", "steps"})
    lead_list = owned(OpenmartLeadList, data.get("leadListId")) if data.get("leadListId") else None
    if data.get("leadListId") and not lead_list:
        return jsonify({"error": "Lead list not found"}), 404
    sender = email(data["senderEmail"]) if data.get("senderEmail") else ""
    steps = data.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValidationError("steps must contain between 1 and 8 messages")
    row = OpenmartSequence(workspace_id=g.workspace_id, user_id=g.openmart_user.id, lead_list_id=lead_list.id if lead_list else None, name=text(data.get("name"), "name", maximum=180), sender_email=sender)
    db.session.add(row)
    db.session.flush()
    for index, raw_step in enumerate(steps, 1):
        if not isinstance(raw_step, dict):
            raise ValidationError("each step must be an object")
        only_fields(raw_step, {"delayDays", "subject", "body"})
        delay = raw_step.get("delayDays", 0)
        if not isinstance(delay, int) or delay < 0 or delay > 60:
            raise ValidationError("delayDays is invalid")
        db.session.add(OpenmartSequenceStep(sequence_id=row.id, step_order=index, delay_days=delay, subject=text(raw_step.get("subject"), "subject", maximum=240), body=text(raw_step.get("body"), "body", maximum=10000)))
    log_usage("sequence_created", row.name)
    db.session.commit()
    return jsonify({"sequence": sequence_json(row)}), 201


@openmart_api.post("/sequences/<sequence_id>/launch")
@require_session
def launch_sequence(sequence_id):
    row = owned(OpenmartSequence, sequence_id)
    if not row:
        return jsonify({"error": "Sequence not found"}), 404
    if not row.sender_email:
        return jsonify({"error": "Connect a sender email before launching"}), 409
    lead_list = owned(OpenmartLeadList, row.lead_list_id) if row.lead_list_id else None
    recipients = [item for item in lead_list.items if item.deleted_at is None and (item.business.owner_email or item.business.company_email)] if lead_list else []
    if not recipients:
        return jsonify({"error": "The selected list has no unlocked email recipients"}), 409
    row.status = "active"
    row.sent_count = len(recipients)
    log_usage("sequence_launched", row.name)
    db.session.commit()
    return jsonify({"sequence": sequence_json(row), "message": "Sequence queued locally; no external email was sent by this clone."})


@openmart_api.get("/api-keys")
@require_session
def api_keys():
    rows = OpenmartApiKey.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartApiKey.created_at.desc()).all()
    return jsonify({"apiKeys": [{"id": str(row.id), "name": row.name, "prefix": row.key_prefix, "lastUsedAt": iso(row.last_used_at), "revokedAt": iso(row.revoked_at), "createdAt": iso(row.created_at)} for row in rows]})


@openmart_api.post("/api-keys")
@require_session
def create_api_key():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"name"})
    token = f"om_live_{secrets.token_urlsafe(32)}"
    row = OpenmartApiKey(workspace_id=g.workspace_id, user_id=g.openmart_user.id, name=text(data.get("name"), "name", maximum=120), key_prefix=token[:14], key_hash=key_hash(token))
    db.session.add(row)
    log_usage("api_key_created", row.name)
    db.session.commit()
    return jsonify({"apiKey": {"id": str(row.id), "name": row.name, "prefix": row.key_prefix, "token": token, "createdAt": iso(row.created_at)}}), 201


@openmart_api.delete("/api-keys/<key_id>")
@require_session
def revoke_api_key(key_id):
    row = owned(OpenmartApiKey, key_id)
    if not row:
        return jsonify({"error": "API key not found"}), 404
    row.revoked_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"ok": True})


@openmart_api.get("/team")
@require_session
def team():
    users = OpenmartUser.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartUser.created_at).all()
    invitations = OpenmartInvitation.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartInvitation.created_at.desc()).all()
    return jsonify({
        "members": [{"id": str(user.id), "displayName": user.display_name, "email": user.email, "role": user.role, "active": user.is_active, "joinedAt": iso(user.created_at)} for user in users],
        "invitations": [{"id": str(invite.id), "email": invite.email, "role": invite.role, "status": invite.status, "createdAt": iso(invite.created_at)} for invite in invitations],
    })


@openmart_api.post("/team/invitations")
@require_session
def invite_member():
    if g.openmart_user.role not in {"owner", "admin"}:
        return jsonify({"error": "Administrator access required"}), 403
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"email", "role"})
    invited_email = email(data.get("email"))
    role = data.get("role", "member")
    if role not in {"admin", "member"}:
        raise ValidationError("role is invalid")
    if OpenmartUser.query.filter_by(workspace_id=g.workspace_id, email=invited_email, deleted_at=None).first():
        return jsonify({"error": "This person is already a member"}), 409
    existing = OpenmartInvitation.query.filter_by(workspace_id=g.workspace_id, email=invited_email, deleted_at=None).first()
    if existing:
        existing.role = role
        existing.status = "pending"
        row = existing
    else:
        row = OpenmartInvitation(workspace_id=g.workspace_id, invited_by_id=g.openmart_user.id, email=invited_email, role=role)
        db.session.add(row)
    log_usage("team_invitation", invited_email)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An invitation already exists"}), 409
    return jsonify({"invitation": {"id": str(row.id), "email": row.email, "role": row.role, "status": row.status, "createdAt": iso(row.created_at)}}), 201


@openmart_api.get("/settings")
@require_session
def settings():
    workspace = g.openmart_user.workspace
    return jsonify({"profile": {"displayName": g.openmart_user.display_name, "email": g.openmart_user.email}, "workspace": {"name": workspace.name, "plan": workspace.plan, "credits": workspace.credits_balance, "country": workspace.default_country}})


@openmart_api.patch("/settings")
@require_session
def update_settings():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"displayName", "workspaceName", "country"})
    if "displayName" in data:
        g.openmart_user.display_name = text(data["displayName"], "displayName", minimum=2, maximum=120)
    if "workspaceName" in data:
        g.openmart_user.workspace.name = text(data["workspaceName"], "workspaceName", minimum=2, maximum=160)
    if "country" in data:
        if data["country"] not in {"US", "CA", "GB", "AU"}:
            raise ValidationError("country is invalid")
        g.openmart_user.workspace.default_country = data["country"]
    db.session.commit()
    return settings()


@openmart_api.get("/activity")
@require_session
def activity():
    rows = OpenmartUsageEvent.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(OpenmartUsageEvent.created_at.desc()).limit(100).all()
    return jsonify({"events": [{"id": str(row.id), "type": row.event_type, "subject": row.subject, "creditsDelta": row.credits_delta, "createdAt": iso(row.created_at)} for row in rows]})
