from __future__ import annotations

import threading
import uuid

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.models import db
from .models import AngleraJob, AngleraProduct, AngleraSource
from .services import emit_event, enrich_product, serialize_job, sync_remote_source, utcnow


def create_job(workspace_id: uuid.UUID, user_id: uuid.UUID, kind: str, payload: dict, idempotency_key: str) -> tuple[AngleraJob, bool]:
    existing = AngleraJob.query.filter_by(workspace_id=workspace_id, idempotency_key=idempotency_key, deleted_at=None).first()
    if existing:
        return existing, False
    job = AngleraJob(
        workspace_id=workspace_id, requested_by_user_id=user_id, kind=kind,
        payload_json=payload, idempotency_key=idempotency_key,
    )
    db.session.add(job)
    try:
        db.session.flush()
        emit_event(workspace_id, "job.queued", "job", job.id, {"job": serialize_job(job)}, user_id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = AngleraJob.query.filter_by(workspace_id=workspace_id, idempotency_key=idempotency_key, deleted_at=None).first()
        if existing is None:
            raise
        return existing, False
    return job, True


def _selected_products(job: AngleraJob) -> list[AngleraProduct]:
    query = AngleraProduct.query.filter_by(workspace_id=job.workspace_id, deleted_at=None)
    raw_ids = job.payload_json.get("ids", [])
    if raw_ids:
        query = query.filter(AngleraProduct.id.in_([uuid.UUID(value) for value in raw_ids]))
    return query.order_by(AngleraProduct.created_at.asc()).all()


def _selected_sources(job: AngleraJob) -> list[AngleraSource]:
    query = AngleraSource.query.filter_by(workspace_id=job.workspace_id, deleted_at=None)
    raw_ids = job.payload_json.get("ids", [])
    if raw_ids:
        query = query.filter(AngleraSource.id.in_([uuid.UUID(value) for value in raw_ids]))
    return query.order_by(AngleraSource.created_at.asc()).all()


def _run_enrichment(job: AngleraJob) -> dict:
    products = _selected_products(job)
    sources = AngleraSource.query.filter_by(workspace_id=job.workspace_id, deleted_at=None).all()
    for product in products:
        product.status = "processing"
    emit_event(job.workspace_id, "products.processing", "product", payload={"ids": [str(item.id) for item in products]}, actor_user_id=job.requested_by_user_id)
    db.session.commit()
    ready = 0
    review = 0
    for index, product in enumerate(products, start=1):
        result = enrich_product(product, sources)
        ready += result["status"] == "ready"
        review += result["status"] != "ready"
        job.progress = round(index * 100 / max(1, len(products)))
        emit_event(job.workspace_id, "product.enriched", "product", product.id, {"status": product.status, "confidence": product.confidence}, job.requested_by_user_id)
        db.session.commit()
    return {"processed": len(products), "ready": ready, "needsReview": review}


def _run_source_sync(job: AngleraJob) -> dict:
    sources = _selected_sources(job)
    for source in sources:
        source.status = "Syncing"
        source.last_error = None
    emit_event(job.workspace_id, "sources.syncing", "source", payload={"ids": [str(item.id) for item in sources]}, actor_user_id=job.requested_by_user_id)
    db.session.commit()
    connected = 0
    failed = 0
    for index, source in enumerate(sources, start=1):
        try:
            result = sync_remote_source(source)
            connected += 1
            emit_event(job.workspace_id, "source.synced", "source", source.id, result, job.requested_by_user_id)
        except Exception as exc:  # Each connector failure is isolated and persisted.
            source.status = "Needs attention"
            source.last_error = str(exc)[:500]
            failed += 1
            emit_event(job.workspace_id, "source.failed", "source", source.id, {"error": source.last_error}, job.requested_by_user_id)
        job.progress = round(index * 100 / max(1, len(sources)))
        db.session.commit()
    return {"processed": len(sources), "connected": connected, "failed": failed}


def run_job(job_id: uuid.UUID) -> None:
    job = db.session.get(AngleraJob, job_id)
    if job is None or job.status not in {"queued", "running"}:
        return
    try:
        job.status = "running"
        job.started_at = job.started_at or utcnow()
        emit_event(job.workspace_id, "job.running", "job", job.id, {"kind": job.kind}, job.requested_by_user_id)
        db.session.commit()
        if job.kind == "enrich-products":
            result = _run_enrichment(job)
        elif job.kind == "sync-sources":
            result = _run_source_sync(job)
        else:
            raise ValueError("Unsupported Anglera job kind")
        job.status = "succeeded"
        job.progress = 100
        job.result_json = result
        job.completed_at = utcnow()
        emit_event(job.workspace_id, "job.succeeded", "job", job.id, {"job": serialize_job(job)}, job.requested_by_user_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        job = db.session.get(AngleraJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error_message = "The background operation could not be completed."
            job.completed_at = utcnow()
            emit_event(job.workspace_id, "job.failed", "job", job.id, {"job": serialize_job(job)}, job.requested_by_user_id)
            db.session.commit()


def dispatch_job(job: AngleraJob) -> None:
    app = current_app._get_current_object()
    if app.config.get("ANGLERA_RUN_JOBS_INLINE", False):
        run_job(job.id)
        return

    def target() -> None:
        with app.app_context():
            try:
                run_job(job.id)
            finally:
                db.session.remove()

    threading.Thread(target=target, name=f"anglera-{job.kind}-{job.id}", daemon=True).start()
