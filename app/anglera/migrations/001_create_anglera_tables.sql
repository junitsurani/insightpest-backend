-- Additive PostgreSQL migration for Anglera. No existing table is changed.
CREATE TABLE IF NOT EXISTS anglera_workspace (
  id UUID PRIMARY KEY, name VARCHAR(120) NOT NULL, primary_domain VARCHAR(500) NOT NULL,
  crawl_depth VARCHAR(30) NOT NULL, include_pdf_manuals BOOLEAN NOT NULL,
  respect_robots BOOLEAN NOT NULL, automatic_enrichment BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'anglera_clone'
);

CREATE TABLE IF NOT EXISTS anglera_product (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL, status VARCHAR(20) NOT NULL,
  name VARCHAR(240) NOT NULL, sku VARCHAR(120) NOT NULL, image_url VARCHAR(1000) NOT NULL,
  specification TEXT NOT NULL, source_count INTEGER NOT NULL, confidence INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'anglera_clone',
  CONSTRAINT uq_anglera_product_workspace_sku UNIQUE (workspace_id, sku),
  CONSTRAINT ck_anglera_product_status CHECK (status IN ('ready','processing','needs-review')),
  CONSTRAINT ck_anglera_product_confidence CHECK (confidence BETWEEN 0 AND 100),
  CONSTRAINT ck_anglera_product_source_count CHECK (source_count >= 0)
);

CREATE TABLE IF NOT EXISTS anglera_source (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL, name VARCHAR(120) NOT NULL,
  source_type VARCHAR(30) NOT NULL, location VARCHAR(500) NOT NULL, status VARCHAR(30) NOT NULL,
  record_count INTEGER NOT NULL, last_synced_at TIMESTAMPTZ NULL, last_error VARCHAR(500) NULL,
  content_text TEXT NULL, content_etag VARCHAR(160) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'anglera_clone',
  CONSTRAINT uq_anglera_source_workspace_location UNIQUE (workspace_id, location),
  CONSTRAINT ck_anglera_source_type CHECK (source_type IN ('Website','Document','Catalog feed')),
  CONSTRAINT ck_anglera_source_status CHECK (status IN ('Connected','Syncing','Needs attention')),
  CONSTRAINT ck_anglera_source_record_count CHECK (record_count >= 0)
);

CREATE TABLE IF NOT EXISTS anglera_member (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL, user_id UUID NULL,
  name VARCHAR(120) NOT NULL, email VARCHAR(254) NOT NULL, role VARCHAR(20) NOT NULL,
  status VARCHAR(20) NOT NULL, invited_by_user_id UUID NULL,
  invitation_token_hash VARCHAR(64) UNIQUE NULL, invitation_expires_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'anglera_clone',
  CONSTRAINT uq_anglera_member_workspace_email UNIQUE (workspace_id, email),
  CONSTRAINT ck_anglera_member_role CHECK (role IN ('Owner','Admin','Editor','Viewer')),
  CONSTRAINT ck_anglera_member_status CHECK (status IN ('Active','Invited'))
);

CREATE TABLE IF NOT EXISTS anglera_job (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL, requested_by_user_id UUID NOT NULL,
  kind VARCHAR(40) NOT NULL, status VARCHAR(20) NOT NULL, progress INTEGER NOT NULL,
  idempotency_key VARCHAR(80) NOT NULL, payload_json JSON NOT NULL,
  result_json JSON NULL, error_message VARCHAR(500) NULL,
  started_at TIMESTAMPTZ NULL, completed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'anglera_clone',
  CONSTRAINT uq_anglera_job_idempotency UNIQUE (workspace_id, idempotency_key),
  CONSTRAINT ck_anglera_job_kind CHECK (kind IN ('enrich-products','sync-sources')),
  CONSTRAINT ck_anglera_job_status CHECK (status IN ('queued','running','succeeded','failed')),
  CONSTRAINT ck_anglera_job_progress CHECK (progress BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS anglera_event (
  id BIGSERIAL PRIMARY KEY, workspace_id UUID NOT NULL, actor_user_id UUID NULL,
  event_type VARCHAR(80) NOT NULL, entity_type VARCHAR(40) NOT NULL,
  entity_id VARCHAR(80) NULL, payload_json JSON NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_anglera_product_workspace_status ON anglera_product(workspace_id,status);
CREATE INDEX IF NOT EXISTS ix_anglera_product_workspace_updated ON anglera_product(workspace_id,updated_at);
CREATE INDEX IF NOT EXISTS ix_anglera_source_workspace_status ON anglera_source(workspace_id,status);
CREATE INDEX IF NOT EXISTS ix_anglera_member_workspace_status ON anglera_member(workspace_id,status);
CREATE INDEX IF NOT EXISTS ix_anglera_job_workspace_status ON anglera_job(workspace_id,status);
CREATE INDEX IF NOT EXISTS ix_anglera_event_workspace_id ON anglera_event(workspace_id,id);
