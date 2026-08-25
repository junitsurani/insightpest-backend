-- Additive PostgreSQL migration for real repository indexing and codebase audits.
-- No existing Paces or Greptile table is altered or removed.
CREATE TABLE IF NOT EXISTS greptile_repository_snapshot (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES greptile_workspace(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES greptile_repository(id) ON DELETE CASCADE,
  remote_url VARCHAR(500) NOT NULL,
  commit_sha VARCHAR(64) NULL,
  default_branch VARCHAR(120) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'indexing' CHECK (status IN ('indexing', 'ready', 'failed')),
  file_count INTEGER NOT NULL DEFAULT 0 CHECK (file_count >= 0),
  indexed_file_count INTEGER NOT NULL DEFAULT 0 CHECK (indexed_file_count >= 0),
  total_bytes INTEGER NOT NULL DEFAULT 0 CHECK (total_bytes >= 0),
  error_message VARCHAR(500) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone'
);

CREATE TABLE IF NOT EXISTS greptile_code_file (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES greptile_workspace(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES greptile_repository(id) ON DELETE CASCADE,
  snapshot_id UUID NOT NULL REFERENCES greptile_repository_snapshot(id) ON DELETE CASCADE,
  path VARCHAR(500) NOT NULL,
  language VARCHAR(60) NOT NULL DEFAULT 'text',
  source_sha VARCHAR(64) NULL,
  size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
  line_count INTEGER NOT NULL CHECK (line_count >= 0),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone',
  CONSTRAINT uq_greptile_code_file_snapshot_path UNIQUE (snapshot_id, path)
);

CREATE TABLE IF NOT EXISTS greptile_audit_run (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES greptile_workspace(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES greptile_repository(id) ON DELETE CASCADE,
  snapshot_id UUID NULL REFERENCES greptile_repository_snapshot(id) ON DELETE SET NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'complete', 'failed')),
  score INTEGER NULL CHECK (score BETWEEN 0 AND 100),
  summary TEXT NULL,
  model VARCHAR(120) NOT NULL DEFAULT 'static',
  llm_status VARCHAR(40) NOT NULL DEFAULT 'not_started',
  file_count INTEGER NOT NULL DEFAULT 0 CHECK (file_count >= 0),
  completed_at TIMESTAMPTZ NULL,
  error_message VARCHAR(500) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone'
);

CREATE TABLE IF NOT EXISTS greptile_audit_finding (
  id UUID PRIMARY KEY,
  audit_id UUID NOT NULL REFERENCES greptile_audit_run(id) ON DELETE CASCADE,
  path VARCHAR(500) NOT NULL,
  start_line INTEGER NOT NULL CHECK (start_line > 0),
  end_line INTEGER NOT NULL CHECK (end_line >= start_line),
  severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
  category VARCHAR(80) NOT NULL,
  title VARCHAR(240) NOT NULL,
  description TEXT NOT NULL,
  recommendation TEXT NOT NULL,
  evidence TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone'
);

CREATE INDEX IF NOT EXISTS ix_greptile_snapshot_repository_created ON greptile_repository_snapshot(repository_id, created_at);
CREATE INDEX IF NOT EXISTS ix_greptile_snapshot_deleted_at ON greptile_repository_snapshot(deleted_at);
CREATE INDEX IF NOT EXISTS ix_greptile_code_file_repository_path ON greptile_code_file(repository_id, path);
CREATE INDEX IF NOT EXISTS ix_greptile_code_file_deleted_at ON greptile_code_file(deleted_at);
CREATE INDEX IF NOT EXISTS ix_greptile_audit_repository_created ON greptile_audit_run(repository_id, created_at);
CREATE INDEX IF NOT EXISTS ix_greptile_audit_run_deleted_at ON greptile_audit_run(deleted_at);
CREATE INDEX IF NOT EXISTS ix_greptile_audit_finding_audit_severity ON greptile_audit_finding(audit_id, severity);
CREATE INDEX IF NOT EXISTS ix_greptile_audit_finding_deleted_at ON greptile_audit_finding(deleted_at);
