-- Isolated Openmart schema. Safe to run beside every existing product schema.
-- All tables, indexes, constraints, and foreign keys use the openmart_ prefix.
BEGIN;

CREATE TABLE IF NOT EXISTS openmart_rate_event (
  id UUID PRIMARY KEY, scope VARCHAR(40) NOT NULL, subject_hash VARCHAR(64) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS openmart_workspace (
  id UUID PRIMARY KEY, name VARCHAR(160) NOT NULL, plan VARCHAR(20) NOT NULL, credits_balance INTEGER NOT NULL,
  default_country VARCHAR(2) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
  deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT ck_openmart_workspace_plan CHECK (plan IN ('free','starter','pro','enterprise'))
);
CREATE TABLE IF NOT EXISTS openmart_user (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES openmart_workspace(id) ON DELETE CASCADE,
  email VARCHAR(254) NOT NULL, display_name VARCHAR(120) NOT NULL, password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(20) NOT NULL, is_active BOOLEAN NOT NULL, last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT uq_openmart_user_email UNIQUE (email),
  CONSTRAINT ck_openmart_user_role CHECK (role IN ('owner','admin','member'))
);
CREATE TABLE IF NOT EXISTS openmart_session (
  id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES openmart_user(id) ON DELETE CASCADE,
  token_hash VARCHAR(64) NOT NULL, expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ, last_seen_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT uq_openmart_session_token_hash UNIQUE (token_hash)
);
CREATE TABLE IF NOT EXISTS openmart_business (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES openmart_workspace(id) ON DELETE CASCADE,
  external_id VARCHAR(80) NOT NULL, name VARCHAR(180) NOT NULL, category VARCHAR(120) NOT NULL,
  street VARCHAR(240) NOT NULL, city VARCHAR(100) NOT NULL, region VARCHAR(100) NOT NULL, country VARCHAR(2) NOT NULL,
  postal_code VARCHAR(20) NOT NULL, website VARCHAR(500) NOT NULL, phone VARCHAR(40) NOT NULL,
  company_email VARCHAR(254) NOT NULL, owner_name VARCHAR(160) NOT NULL, owner_title VARCHAR(120) NOT NULL,
  owner_email VARCHAR(254) NOT NULL, owner_phone VARCHAR(40) NOT NULL, rating DOUBLE PRECISION NOT NULL,
  review_count INTEGER NOT NULL, employee_count INTEGER NOT NULL, revenue_estimate INTEGER NOT NULL,
  status VARCHAR(30) NOT NULL, is_enriched BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT uq_openmart_business_workspace_external UNIQUE (workspace_id, external_id)
);
CREATE TABLE IF NOT EXISTS openmart_lead_list (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES openmart_workspace(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES openmart_user(id) ON DELETE CASCADE, name VARCHAR(160) NOT NULL, description VARCHAR(800) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS openmart_lead_list_item (
  id UUID PRIMARY KEY, lead_list_id UUID NOT NULL REFERENCES openmart_lead_list(id) ON DELETE CASCADE,
  business_id UUID NOT NULL REFERENCES openmart_business(id) ON DELETE CASCADE, contact_status VARCHAR(20) NOT NULL,
  notes VARCHAR(2000) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
  deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT uq_openmart_list_business UNIQUE (lead_list_id, business_id),
  CONSTRAINT ck_openmart_item_status CHECK (contact_status IN ('lead','contacted','replied','qualified','archived'))
);
CREATE TABLE IF NOT EXISTS openmart_saved_search (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES openmart_workspace(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES openmart_user(id) ON DELETE CASCADE, query VARCHAR(240) NOT NULL,
  location VARCHAR(240) NOT NULL, filters_json TEXT NOT NULL, result_count INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS openmart_export (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES openmart_workspace(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES openmart_user(id) ON DELETE CASCADE,
  lead_list_id UUID REFERENCES openmart_lead_list(id) ON DELETE SET NULL, filename VARCHAR(255) NOT NULL,
  format VARCHAR(10) NOT NULL, fields_json TEXT NOT NULL, row_count INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT ck_openmart_export_format CHECK (format IN ('csv','xlsx'))
);
CREATE TABLE IF NOT EXISTS openmart_sequence (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES openmart_workspace(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES openmart_user(id) ON DELETE CASCADE,
  lead_list_id UUID REFERENCES openmart_lead_list(id) ON DELETE SET NULL, name VARCHAR(180) NOT NULL,
  status VARCHAR(20) NOT NULL, sender_email VARCHAR(254) NOT NULL, sent_count INTEGER NOT NULL, reply_count INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT ck_openmart_sequence_status CHECK (status IN ('draft','active','paused','completed'))
);
CREATE TABLE IF NOT EXISTS openmart_sequence_step (
  id UUID PRIMARY KEY, sequence_id UUID NOT NULL REFERENCES openmart_sequence(id) ON DELETE CASCADE,
  step_order INTEGER NOT NULL, delay_days INTEGER NOT NULL, subject VARCHAR(240) NOT NULL, body TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT uq_openmart_sequence_step_order UNIQUE (sequence_id, step_order)
);
CREATE TABLE IF NOT EXISTS openmart_api_key (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES openmart_workspace(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES openmart_user(id) ON DELETE CASCADE, name VARCHAR(120) NOT NULL,
  key_prefix VARCHAR(16) NOT NULL, key_hash VARCHAR(64) NOT NULL, last_used_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT uq_openmart_api_key_hash UNIQUE (key_hash)
);
CREATE TABLE IF NOT EXISTS openmart_usage_event (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES openmart_workspace(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES openmart_user(id) ON DELETE CASCADE, event_type VARCHAR(60) NOT NULL,
  subject VARCHAR(240) NOT NULL, credits_delta INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS openmart_invitation (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES openmart_workspace(id) ON DELETE CASCADE,
  invited_by_id UUID NOT NULL REFERENCES openmart_user(id) ON DELETE CASCADE, email VARCHAR(254) NOT NULL,
  role VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, source_system VARCHAR(40) NOT NULL,
  CONSTRAINT uq_openmart_invitation_workspace_email UNIQUE (workspace_id, email),
  CONSTRAINT ck_openmart_invitation_role CHECK (role IN ('admin','member')),
  CONSTRAINT ck_openmart_invitation_status CHECK (status IN ('pending','accepted','revoked'))
);

CREATE INDEX IF NOT EXISTS ix_openmart_rate_scope_subject_created ON openmart_rate_event(scope, subject_hash, created_at);
CREATE INDEX IF NOT EXISTS ix_openmart_user_workspace_id ON openmart_user(workspace_id);
CREATE INDEX IF NOT EXISTS ix_openmart_session_user_id ON openmart_session(user_id);
CREATE INDEX IF NOT EXISTS ix_openmart_session_expires_at ON openmart_session(expires_at);
CREATE INDEX IF NOT EXISTS ix_openmart_business_workspace_name ON openmart_business(workspace_id, name);
CREATE INDEX IF NOT EXISTS ix_openmart_list_workspace_updated ON openmart_lead_list(workspace_id, updated_at);
CREATE INDEX IF NOT EXISTS ix_openmart_lead_list_item_lead_list_id ON openmart_lead_list_item(lead_list_id);
CREATE INDEX IF NOT EXISTS ix_openmart_lead_list_item_business_id ON openmart_lead_list_item(business_id);
CREATE INDEX IF NOT EXISTS ix_openmart_saved_search_workspace_id ON openmart_saved_search(workspace_id);
CREATE INDEX IF NOT EXISTS ix_openmart_export_workspace_id ON openmart_export(workspace_id);
CREATE INDEX IF NOT EXISTS ix_openmart_sequence_workspace_id ON openmart_sequence(workspace_id);
CREATE INDEX IF NOT EXISTS ix_openmart_sequence_step_sequence_id ON openmart_sequence_step(sequence_id);
CREATE INDEX IF NOT EXISTS ix_openmart_api_key_workspace_id ON openmart_api_key(workspace_id);
CREATE INDEX IF NOT EXISTS ix_openmart_usage_workspace_created ON openmart_usage_event(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS ix_openmart_invitation_workspace_id ON openmart_invitation(workspace_id);
COMMIT;
