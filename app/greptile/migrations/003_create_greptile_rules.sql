-- Additive PostgreSQL migration for persisted Greptile review rules.
CREATE TABLE IF NOT EXISTS greptile_rule (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES greptile_workspace(id) ON DELETE CASCADE,
  text VARCHAR(500) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone'
);

CREATE INDEX IF NOT EXISTS ix_greptile_rule_workspace_enabled ON greptile_rule(workspace_id, enabled);
CREATE INDEX IF NOT EXISTS ix_greptile_rule_deleted_at ON greptile_rule(deleted_at);
