-- Additive PostgreSQL migration for the Greptile bounded context.
-- Every object is namespaced; no legacy Paces table is altered or dropped.
CREATE TABLE IF NOT EXISTS greptile_workspace (
  id UUID PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone'
);

CREATE TABLE IF NOT EXISTS greptile_repository (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES greptile_workspace(id) ON DELETE CASCADE,
  provider VARCHAR(20) NOT NULL CHECK (provider IN ('github', 'gitlab')),
  owner VARCHAR(100) NOT NULL,
  name VARCHAR(100) NOT NULL,
  default_branch VARCHAR(120) NOT NULL DEFAULT 'main',
  status VARCHAR(20) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'indexing', 'ready', 'failed')),
  progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  last_indexed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone',
  CONSTRAINT uq_greptile_repository_identity UNIQUE (workspace_id, provider, owner, name)
);

CREATE TABLE IF NOT EXISTS greptile_conversation (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES greptile_workspace(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES greptile_repository(id) ON DELETE CASCADE,
  title VARCHAR(180) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone'
);

CREATE TABLE IF NOT EXISTS greptile_message (
  id UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES greptile_conversation(id) ON DELETE CASCADE,
  role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  duration_ms INTEGER NULL CHECK (duration_ms >= 0),
  feedback_rating SMALLINT NULL CHECK (feedback_rating IN (-1, 1)),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone'
);

CREATE TABLE IF NOT EXISTS greptile_citation (
  id UUID PRIMARY KEY,
  message_id UUID NOT NULL REFERENCES greptile_message(id) ON DELETE CASCADE,
  path VARCHAR(500) NOT NULL,
  start_line INTEGER NOT NULL CHECK (start_line > 0),
  end_line INTEGER NOT NULL CHECK (end_line >= start_line),
  excerpt TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone'
);

CREATE TABLE IF NOT EXISTS greptile_pull_request (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES greptile_workspace(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES greptile_repository(id) ON DELETE CASCADE,
  number INTEGER NOT NULL CHECK (number > 0),
  title VARCHAR(240) NOT NULL,
  author VARCHAR(100) NOT NULL,
  branch VARCHAR(160) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewing', 'issues_found', 'passed', 'closed')),
  issue_count INTEGER NOT NULL DEFAULT 0 CHECK (issue_count >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone',
  CONSTRAINT uq_greptile_pull_request_number UNIQUE (repository_id, number)
);

CREATE TABLE IF NOT EXISTS greptile_contact_lead (
  id UUID PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  email VARCHAR(254) NOT NULL,
  company VARCHAR(160) NOT NULL,
  message TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'qualified', 'closed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ NULL,
  source_system VARCHAR(40) NOT NULL DEFAULT 'greptile_clone'
);

CREATE INDEX IF NOT EXISTS ix_greptile_repository_workspace_status ON greptile_repository(workspace_id, status);
CREATE INDEX IF NOT EXISTS ix_greptile_conversation_workspace_updated ON greptile_conversation(workspace_id, updated_at);
CREATE INDEX IF NOT EXISTS ix_greptile_message_conversation_created ON greptile_message(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS ix_greptile_pull_request_repository_status ON greptile_pull_request(repository_id, status);
CREATE INDEX IF NOT EXISTS ix_greptile_repository_deleted_at ON greptile_repository(deleted_at);
CREATE INDEX IF NOT EXISTS ix_greptile_conversation_deleted_at ON greptile_conversation(deleted_at);
CREATE INDEX IF NOT EXISTS ix_greptile_message_deleted_at ON greptile_message(deleted_at);
CREATE INDEX IF NOT EXISTS ix_greptile_pull_request_deleted_at ON greptile_pull_request(deleted_at);
