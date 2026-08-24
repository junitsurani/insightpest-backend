-- Additive PostgreSQL migration for Greptile users and opaque sessions.
-- Existing Paces and Greptile data is not altered or removed.
CREATE TABLE IF NOT EXISTS greptile_user (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES greptile_workspace(id) ON DELETE CASCADE,
  email VARCHAR(254) NOT NULL,
  display_name VARCHAR(120) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone',
  CONSTRAINT uq_greptile_user_email UNIQUE (email)
);

CREATE TABLE IF NOT EXISTS greptile_session (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES greptile_user(id) ON DELETE CASCADE,
  token_hash VARCHAR(64) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ NULL,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone',
  CONSTRAINT uq_greptile_session_token_hash UNIQUE (token_hash)
);

CREATE INDEX IF NOT EXISTS ix_greptile_user_workspace_active ON greptile_user(workspace_id, is_active);
CREATE INDEX IF NOT EXISTS ix_greptile_user_deleted_at ON greptile_user(deleted_at);
CREATE INDEX IF NOT EXISTS ix_greptile_session_user_expires ON greptile_session(user_id, expires_at);
CREATE INDEX IF NOT EXISTS ix_greptile_session_deleted_at ON greptile_session(deleted_at);
