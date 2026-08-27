from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone

import fitz
from flask import Blueprint, Response, current_app, g, jsonify, request, send_file
from sqlalchemy import func
from werkzeug.utils import secure_filename

from .auth import require_session
from app.models import db
from .models import TaxGptCitation, TaxGptClient, TaxGptConversation, TaxGptDemoRequest, TaxGptDocument, TaxGptDraft, TaxGptMatrix, TaxGptMessage, TaxGptReview, TaxGptWorkflowRun
from .security import allow_request, subject_fingerprint
from .services import WORKFLOW_TEMPLATES, dumps, matrix_results, research_answer, review_findings, workflow_result, writer_content
from .validation import ValidationError, email, identifier, json_object, only_fields, text


taxgpt_api = Blueprint("taxgpt_api", __name__, url_prefix="/api/taxgpt")
ALLOWED_TYPES = {"application/pdf", "text/plain", "text/csv"}


def iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def conversation_json(row, include_messages=False):
    payload = {"id": str(row.id), "title": row.title, "kind": row.kind, "jurisdiction": row.jurisdiction, "clientId": str(row.client_id) if row.client_id else None, "createdAt": iso(row.created_at), "updatedAt": iso(row.updated_at)}
    if include_messages:
        payload["messages"] = [message_json(message) for message in row.messages if message.deleted_at is None]
    return payload


def message_json(row):
    return {"id": str(row.id), "role": row.role, "content": row.content, "feedback": row.feedback, "createdAt": iso(row.created_at), "citations": [{"id": str(c.id), "title": c.title, "publisher": c.publisher, "url": c.url, "excerpt": c.excerpt} for c in sorted(row.citations, key=lambda item: item.citation_order) if c.deleted_at is None]}


def client_json(row):
    return {"id": str(row.id), "name": row.name, "entityType": row.entity_type, "jurisdiction": row.jurisdiction, "taxYear": row.tax_year, "notes": row.notes, "documentCount": sum(1 for item in row.documents if item.deleted_at is None), "updatedAt": iso(row.updated_at)}


def document_json(row):
    return {"id": str(row.id), "clientId": str(row.client_id) if row.client_id else None, "filename": row.filename, "contentType": row.content_type, "sizeBytes": row.size_bytes, "status": row.status, "createdAt": iso(row.created_at)}


def owned(model, raw_id):
    return model.query.filter_by(id=identifier(raw_id), workspace_id=g.workspace_id, deleted_at=None).first()


@taxgpt_api.errorhandler(ValidationError)
def validation_error(error):
    return jsonify({"error": str(error)}), 400


@taxgpt_api.get("/health")
def health():
    return jsonify({"ok": True, "service": "taxgpt", "version": 1})


@taxgpt_api.post("/demo")
def request_demo():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"name", "email", "persona", "employees", "sourcePath", "website"})
    if data.get("website"):
        return jsonify({"accepted": True}), 201
    if not allow_request("demo", "public", limit=int(current_app.config.get("TAXGPT_DEMO_RATE_LIMIT", 5)), seconds=60):
        return jsonify({"error": "Too many demo requests. Try again in a minute."}), 429
    persona = data.get("persona")
    employees = str(data.get("employees", ""))
    if persona not in {"pro", "business", "individual"}:
        raise ValidationError("persona is invalid")
    if employees not in {"10", "50", "250", "251"}:
        raise ValidationError("employees is invalid")
    row = TaxGptDemoRequest(
        full_name=text(data.get("name"), "name", minimum=2, maximum=120),
        work_email=email(data.get("email")),
        persona=persona,
        employees=employees,
        source_path=text(data.get("sourcePath", "/demo"), "sourcePath", maximum=240),
        request_fingerprint=subject_fingerprint("demo"),
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"accepted": True, "requestId": str(row.id)}), 201


@taxgpt_api.get("/bootstrap")
@require_session
def bootstrap():
    clients = TaxGptClient.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(TaxGptClient.updated_at.desc()).limit(8).all()
    conversations = TaxGptConversation.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(TaxGptConversation.updated_at.desc()).limit(8).all()
    documents = TaxGptDocument.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(TaxGptDocument.created_at.desc()).limit(8).all()
    return jsonify({"user": {"displayName": g.taxgpt_user.display_name, "email": g.taxgpt_user.email}, "workspace": {"id": str(g.taxgpt_user.workspace.id), "name": g.taxgpt_user.workspace.name, "country": g.taxgpt_user.workspace.country}, "clients": [client_json(row) for row in clients], "conversations": [conversation_json(row) for row in conversations], "documents": [document_json(row) for row in documents]})


@taxgpt_api.post("/settings")
@require_session
def update_settings():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"displayName", "workspaceName", "country"})
    country = data.get("country")
    if country not in {"US", "CA"}:
        raise ValidationError("country must be US or CA")
    g.taxgpt_user.display_name = text(data.get("displayName"), "displayName", minimum=2, maximum=120)
    g.taxgpt_user.workspace.name = text(data.get("workspaceName"), "workspaceName", minimum=2, maximum=160)
    g.taxgpt_user.workspace.country = country
    db.session.commit()
    return jsonify({"user": {"displayName": g.taxgpt_user.display_name, "email": g.taxgpt_user.email}, "workspace": {"id": str(g.taxgpt_user.workspace.id), "name": g.taxgpt_user.workspace.name, "country": g.taxgpt_user.workspace.country}})


@taxgpt_api.get("/conversations")
@require_session
def conversations():
    kind = request.args.get("kind")
    query = TaxGptConversation.query.filter_by(workspace_id=g.workspace_id, deleted_at=None)
    if kind in {"research", "writer", "document"}:
        query = query.filter_by(kind=kind)
    return jsonify({"conversations": [conversation_json(row) for row in query.order_by(TaxGptConversation.updated_at.desc()).limit(100).all()]})


@taxgpt_api.get("/conversations/<conversation_id>")
@require_session
def conversation_detail(conversation_id):
    row = owned(TaxGptConversation, conversation_id)
    if not row:
        return jsonify({"error": "Conversation not found"}), 404
    return jsonify({"conversation": conversation_json(row, include_messages=True)})


@taxgpt_api.post("/research")
@require_session
def research():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"question", "conversationId", "jurisdiction", "clientId", "documentIds"})
    question = text(data.get("question"), "question", minimum=3, maximum=4000)
    jurisdiction = text(data.get("jurisdiction", "United States"), "jurisdiction", maximum=80)
    client_id = identifier(data["clientId"], "clientId") if data.get("clientId") else None
    client = TaxGptClient.query.filter_by(id=client_id, workspace_id=g.workspace_id, deleted_at=None).first() if client_id else None
    if client_id and not client:
        return jsonify({"error": "Client not found"}), 404
    document_ids = data.get("documentIds", [])
    if not isinstance(document_ids, list) or len(document_ids) > 10:
        raise ValidationError("documentIds must be a list of up to 10 identifiers")
    documents = []
    for raw_id in document_ids:
        document = owned(TaxGptDocument, raw_id)
        if not document:
            return jsonify({"error": "Document not found"}), 404
        documents.append(document)
    conversation = owned(TaxGptConversation, data["conversationId"]) if data.get("conversationId") else None
    if data.get("conversationId") and not conversation:
        return jsonify({"error": "Conversation not found"}), 404
    if conversation is None:
        conversation = TaxGptConversation(workspace_id=g.workspace_id, user_id=g.taxgpt_user.id, client_id=client_id, kind="research", title=question[:177] + ("…" if len(question) > 177 else ""), jurisdiction=jurisdiction)
        db.session.add(conversation)
        db.session.flush()
    user_message = TaxGptMessage(conversation_id=conversation.id, role="user", content=question)
    answer, citations = research_answer(question, jurisdiction, client, documents)
    assistant = TaxGptMessage(conversation_id=conversation.id, role="assistant", content=answer)
    db.session.add_all([user_message, assistant])
    db.session.flush()
    for order, citation in enumerate(citations):
        db.session.add(TaxGptCitation(message_id=assistant.id, citation_order=order, **citation))
    conversation.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"conversation": conversation_json(conversation), "message": message_json(assistant)})


@taxgpt_api.post("/messages/<message_id>/feedback")
@require_session
def feedback(message_id):
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"rating"})
    if data.get("rating") not in {-1, 1}:
        raise ValidationError("rating must be -1 or 1")
    row = TaxGptMessage.query.join(TaxGptConversation).filter(TaxGptMessage.id == identifier(message_id), TaxGptConversation.workspace_id == g.workspace_id, TaxGptMessage.deleted_at.is_(None)).first()
    if not row:
        return jsonify({"error": "Message not found"}), 404
    row.feedback = data["rating"]
    db.session.commit()
    return jsonify({"message": message_json(row)})


@taxgpt_api.get("/clients")
@require_session
def list_clients():
    search = request.args.get("search", "").strip()[:120]
    query = TaxGptClient.query.filter_by(workspace_id=g.workspace_id, deleted_at=None)
    if search:
        query = query.filter(func.lower(TaxGptClient.name).contains(search.lower()))
    return jsonify({"clients": [client_json(row) for row in query.order_by(TaxGptClient.updated_at.desc()).limit(200).all()]})


@taxgpt_api.post("/clients")
@require_session
def create_client():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"name", "entityType", "jurisdiction", "taxYear", "notes"})
    entity_type = data.get("entityType")
    if entity_type not in {"individual", "llc", "partnership", "s_corp", "c_corp", "trust", "nonprofit"}:
        raise ValidationError("entityType is invalid")
    tax_year = data.get("taxYear")
    if not isinstance(tax_year, int) or tax_year < 2000 or tax_year > datetime.now().year + 2:
        raise ValidationError("taxYear is invalid")
    notes = data.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 5000:
        raise ValidationError("notes must be text with at most 5000 characters")
    row = TaxGptClient(workspace_id=g.workspace_id, name=text(data.get("name"), "name", maximum=180), entity_type=entity_type, jurisdiction=text(data.get("jurisdiction"), "jurisdiction", maximum=80), tax_year=tax_year, notes=notes.strip())
    db.session.add(row)
    db.session.commit()
    return jsonify({"client": client_json(row)}), 201


@taxgpt_api.get("/documents")
@require_session
def list_documents():
    return jsonify({"documents": [document_json(row) for row in TaxGptDocument.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(TaxGptDocument.created_at.desc()).limit(200).all()]})


def extract_text(data: bytes, content_type: str):
    if content_type in {"text/plain", "text/csv"}:
        return data.decode("utf-8", errors="replace")[:200000]
    try:
        document = fitz.open(stream=data, filetype="pdf")
        if document.page_count > 100:
            raise ValidationError("PDF documents may contain at most 100 pages")
        return "\n".join(page.get_text() for page in document)[:200000]
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("The PDF could not be read") from exc


@taxgpt_api.post("/documents")
@require_session
def upload_document():
    file = request.files.get("file")
    if file is None or not file.filename:
        raise ValidationError("file is required")
    content_type = (file.mimetype or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise ValidationError("Only PDF, TXT, and CSV files are supported")
    filename = secure_filename(file.filename)[:255]
    if not filename:
        raise ValidationError("file must have a valid filename")
    data = file.read(current_app_max() + 1)
    if not data or len(data) > current_app_max():
        raise ValidationError("file must be between 1 byte and 10 MB")
    if content_type == "application/pdf" and not data.startswith(b"%PDF-"):
        raise ValidationError("The uploaded file is not a valid PDF")
    client_id = identifier(request.form.get("clientId"), "clientId") if request.form.get("clientId") else None
    if client_id and not TaxGptClient.query.filter_by(id=client_id, workspace_id=g.workspace_id, deleted_at=None).first():
        return jsonify({"error": "Client not found"}), 404
    row = TaxGptDocument(workspace_id=g.workspace_id, user_id=g.taxgpt_user.id, client_id=client_id, filename=filename, content_type=content_type, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), status="ready", extracted_text=extract_text(data, content_type), content_blob=data)
    db.session.add(row)
    db.session.commit()
    return jsonify({"document": document_json(row)}), 201


def current_app_max():
    from flask import current_app
    return min(int(current_app.config.get("TAXGPT_MAX_FILE_BYTES", 10 * 1024 * 1024)), 10 * 1024 * 1024)


@taxgpt_api.get("/documents/<document_id>/download")
@require_session
def download_document(document_id):
    row = owned(TaxGptDocument, document_id)
    if not row:
        return jsonify({"error": "Document not found"}), 404
    return send_file(io.BytesIO(row.content_blob), mimetype=row.content_type, as_attachment=True, download_name=row.filename, max_age=0)


@taxgpt_api.post("/writer")
@require_session
def writer():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"prompt", "draftType", "clientId", "documentIds"})
    draft_type = data.get("draftType")
    if draft_type not in {"memo", "client_email", "notice_response", "engagement_letter"}:
        raise ValidationError("draftType is invalid")
    prompt = text(data.get("prompt"), "prompt", minimum=3, maximum=4000)
    client = owned(TaxGptClient, data["clientId"]) if data.get("clientId") else None
    if data.get("clientId") and not client:
        return jsonify({"error": "Client not found"}), 404
    document_ids = data.get("documentIds", [])
    if not isinstance(document_ids, list) or len(document_ids) > 10:
        raise ValidationError("documentIds must be a list of up to 10 identifiers")
    documents = []
    for raw_id in document_ids:
        document = owned(TaxGptDocument, raw_id)
        if not document:
            return jsonify({"error": "Document not found"}), 404
        documents.append(document)
    title, content = writer_content(draft_type, prompt, client, documents)
    row = TaxGptDraft(workspace_id=g.workspace_id, user_id=g.taxgpt_user.id, client_id=client.id if client else None, draft_type=draft_type, title=title, prompt=prompt, content=content)
    db.session.add(row)
    db.session.commit()
    return jsonify({"draft": {"id": str(row.id), "title": row.title, "draftType": row.draft_type, "content": row.content, "clientId": str(row.client_id) if row.client_id else None, "createdAt": iso(row.created_at)}}), 201


@taxgpt_api.get("/drafts")
@require_session
def drafts():
    rows = TaxGptDraft.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(TaxGptDraft.updated_at.desc()).limit(100).all()
    return jsonify({"drafts": [{"id": str(row.id), "title": row.title, "draftType": row.draft_type, "content": row.content, "clientId": str(row.client_id) if row.client_id else None, "createdAt": iso(row.created_at)} for row in rows]})


@taxgpt_api.post("/matrix")
@require_session
def matrix():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"question", "jurisdictions"})
    question = text(data.get("question"), "question", minimum=3, maximum=1200)
    jurisdictions = data.get("jurisdictions")
    if not isinstance(jurisdictions, list) or not 2 <= len(jurisdictions) <= 20 or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in jurisdictions):
        raise ValidationError("jurisdictions must contain between 2 and 20 names")
    jurisdictions = list(dict.fromkeys(item.strip() for item in jurisdictions))
    results = matrix_results(question, jurisdictions)
    row = TaxGptMatrix(workspace_id=g.workspace_id, user_id=g.taxgpt_user.id, question=question, jurisdictions_json=dumps(jurisdictions), results_json=dumps(results))
    db.session.add(row)
    db.session.commit()
    return jsonify({"matrix": {"id": str(row.id), "question": row.question, "jurisdictions": jurisdictions, "results": results, "createdAt": iso(row.created_at)}}), 201


@taxgpt_api.post("/reviews")
@require_session
def create_review():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"documentId", "formType"})
    document = owned(TaxGptDocument, data.get("documentId"))
    if not document:
        return jsonify({"error": "Document not found"}), 404
    form_type = text(data.get("formType"), "formType", maximum=30)
    if form_type not in {"1040", "1065", "1120", "1120-S", "1041", "other"}:
        raise ValidationError("formType is invalid")
    findings = review_findings(document.filename, document.extracted_text, form_type)
    row = TaxGptReview(workspace_id=g.workspace_id, user_id=g.taxgpt_user.id, document_id=document.id, status="complete", form_type=form_type, findings_json=dumps(findings))
    db.session.add(row)
    db.session.commit()
    return jsonify({"review": {"id": str(row.id), "documentId": str(row.document_id), "formType": row.form_type, "status": row.status, "findings": findings, "createdAt": iso(row.created_at)}}), 201


@taxgpt_api.get("/reviews")
@require_session
def reviews():
    rows = TaxGptReview.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(TaxGptReview.created_at.desc()).limit(100).all()
    return jsonify({"reviews": [{"id": str(row.id), "documentId": str(row.document_id), "formType": row.form_type, "status": row.status, "findings": json.loads(row.findings_json), "createdAt": iso(row.created_at)} for row in rows]})


@taxgpt_api.post("/reviews/<review_id>/findings/<finding_id>/resolve")
@require_session
def resolve_review_finding(review_id, finding_id):
    data = json_object(request.get_json(silent=True))
    only_fields(data, set())
    row = owned(TaxGptReview, review_id)
    if not row:
        return jsonify({"error": "Review not found"}), 404
    findings = json.loads(row.findings_json)
    finding = next((item for item in findings if item.get("id") == finding_id), None)
    if finding is None:
        return jsonify({"error": "Finding not found"}), 404
    finding["status"] = "reviewed"
    row.findings_json = dumps(findings)
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"review": {"id": str(row.id), "documentId": str(row.document_id), "formType": row.form_type, "status": row.status, "findings": findings, "createdAt": iso(row.created_at)}})


def workflow_json(row):
    return {"id": str(row.id), "templateKey": row.template_key, "title": row.title, "status": row.status, "clientId": str(row.client_id) if row.client_id else None, "inputs": json.loads(row.inputs_json), "result": json.loads(row.result_json), "createdAt": iso(row.created_at), "completedAt": iso(row.completed_at)}


@taxgpt_api.get("/workflows/templates")
@require_session
def workflow_templates():
    return jsonify({"templates": WORKFLOW_TEMPLATES})


@taxgpt_api.get("/workflows/runs")
@require_session
def workflow_runs():
    rows = TaxGptWorkflowRun.query.filter_by(workspace_id=g.workspace_id, deleted_at=None).order_by(TaxGptWorkflowRun.created_at.desc()).limit(100).all()
    return jsonify({"runs": [workflow_json(row) for row in rows]})


@taxgpt_api.post("/workflows/runs")
@require_session
def create_workflow_run():
    data = json_object(request.get_json(silent=True))
    only_fields(data, {"templateKey", "clientId", "documentIds", "taxSoftware", "folderPath", "notes"})
    template_key = text(data.get("templateKey"), "templateKey", maximum=80)
    template = next((item for item in WORKFLOW_TEMPLATES if item["key"] == template_key), None)
    if not template:
        raise ValidationError("templateKey is invalid")
    client = owned(TaxGptClient, data["clientId"]) if data.get("clientId") else None
    if data.get("clientId") and not client:
        return jsonify({"error": "Client not found"}), 404
    document_ids = data.get("documentIds", [])
    if not isinstance(document_ids, list) or len(document_ids) > 20:
        raise ValidationError("documentIds must be a list of up to 20 identifiers")
    documents = []
    for raw_id in document_ids:
        document = owned(TaxGptDocument, raw_id)
        if not document:
            return jsonify({"error": "Document not found"}), 404
        documents.append(document)
    inputs = {
        "taxSoftware": text(data.get("taxSoftware", "Not specified"), "taxSoftware", maximum=120),
        "folderPath": text(data.get("folderPath", "Not specified"), "folderPath", maximum=500),
        "notes": text(data.get("notes", "No additional instructions"), "notes", maximum=2000),
        "documentIds": [str(document.id) for document in documents],
    }
    result = workflow_result(template, client, documents, inputs)
    row = TaxGptWorkflowRun(workspace_id=g.workspace_id, user_id=g.taxgpt_user.id, client_id=client.id if client else None, template_key=template_key, title=template["title"], status="review_required", inputs_json=dumps(inputs), result_json=dumps(result))
    db.session.add(row)
    db.session.commit()
    return jsonify({"run": workflow_json(row)}), 201


@taxgpt_api.post("/workflows/runs/<run_id>/complete")
@require_session
def complete_workflow_run(run_id):
    row = owned(TaxGptWorkflowRun, run_id)
    if not row:
        return jsonify({"error": "Workflow run not found"}), 404
    row.status = "complete"
    row.completed_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"run": workflow_json(row)})


@taxgpt_api.get("/export/matrix/<matrix_id>.csv")
@require_session
def export_matrix(matrix_id):
    row = owned(TaxGptMatrix, matrix_id)
    if not row:
        return jsonify({"error": "Matrix not found"}), 404
    lines = ["Jurisdiction,Summary,Filing Required,Authority"]
    for item in json.loads(row.results_json):
        escaped = ['"' + str(item[key]).replace('"', '""') + '"' for key in ("jurisdiction", "summary", "filingRequired", "authority")]
        lines.append(",".join(escaped))
    return Response("\n".join(lines), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=taxgpt-matrix.csv"})
