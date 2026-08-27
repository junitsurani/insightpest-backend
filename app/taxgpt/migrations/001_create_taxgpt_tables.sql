-- Independent TaxGPT schema. Safe to run alongside the existing backend.
-- Every object is isolated behind the taxgpt_ prefix.
BEGIN;
CREATE TABLE IF NOT EXISTS taxgpt_demo_request (
	id UUID NOT NULL,
	full_name VARCHAR(120) NOT NULL,
	work_email VARCHAR(254) NOT NULL,
	persona VARCHAR(20) NOT NULL,
	employees VARCHAR(10) NOT NULL,
	source_path VARCHAR(240) NOT NULL,
	request_fingerprint VARCHAR(64) NOT NULL,
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_taxgpt_demo_persona CHECK (persona IN ('pro', 'business', 'individual')),
	CONSTRAINT ck_taxgpt_demo_employees CHECK (employees IN ('10', '50', '250', '251')),
	CONSTRAINT ck_taxgpt_demo_status CHECK (status IN ('new', 'contacted', 'scheduled', 'closed'))
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_demo_request_deleted_at ON taxgpt_demo_request (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_demo_request_work_email ON taxgpt_demo_request (work_email);
CREATE INDEX IF NOT EXISTS ix_taxgpt_demo_created ON taxgpt_demo_request (created_at);
-- Upgrade an early TaxGPT prototype without dropping its demo submissions.
ALTER TABLE taxgpt_demo_request ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR(64);
UPDATE taxgpt_demo_request
SET request_fingerprint = md5(id::text || created_at::text) || md5(work_email || id::text)
WHERE request_fingerprint IS NULL;
ALTER TABLE taxgpt_demo_request ALTER COLUMN request_fingerprint SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_taxgpt_demo_request_request_fingerprint ON taxgpt_demo_request (request_fingerprint);
CREATE TABLE IF NOT EXISTS taxgpt_rate_event (
	id UUID NOT NULL,
	scope VARCHAR(40) NOT NULL,
	subject_hash VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_rate_event_deleted_at ON taxgpt_rate_event (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_rate_scope_subject_created ON taxgpt_rate_event (scope, subject_hash, created_at);
CREATE TABLE IF NOT EXISTS taxgpt_workspace (
	id UUID NOT NULL,
	name VARCHAR(160) NOT NULL,
	country VARCHAR(2) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_workspace_deleted_at ON taxgpt_workspace (deleted_at);
CREATE TABLE IF NOT EXISTS taxgpt_client (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	name VARCHAR(180) NOT NULL,
	entity_type VARCHAR(30) NOT NULL,
	jurisdiction VARCHAR(80) NOT NULL,
	tax_year INTEGER NOT NULL,
	notes TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_taxgpt_client_entity_type CHECK (entity_type IN ('individual', 'llc', 'partnership', 's_corp', 'c_corp', 'trust', 'nonprofit')),
	FOREIGN KEY(workspace_id) REFERENCES taxgpt_workspace (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_client_deleted_at ON taxgpt_client (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_client_workspace_name ON taxgpt_client (workspace_id, name);
CREATE TABLE IF NOT EXISTS taxgpt_user (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	email VARCHAR(254) NOT NULL,
	display_name VARCHAR(120) NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	role VARCHAR(20) NOT NULL,
	is_active BOOLEAN NOT NULL,
	last_login_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_taxgpt_user_email UNIQUE (email),
	FOREIGN KEY(workspace_id) REFERENCES taxgpt_workspace (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_user_deleted_at ON taxgpt_user (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_user_workspace_id ON taxgpt_user (workspace_id);
CREATE TABLE IF NOT EXISTS taxgpt_conversation (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	user_id UUID NOT NULL,
	client_id UUID,
	kind VARCHAR(20) NOT NULL,
	title VARCHAR(180) NOT NULL,
	jurisdiction VARCHAR(40) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_taxgpt_conversation_kind CHECK (kind IN ('research', 'writer', 'document')),
	FOREIGN KEY(workspace_id) REFERENCES taxgpt_workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES taxgpt_user (id) ON DELETE CASCADE,
	FOREIGN KEY(client_id) REFERENCES taxgpt_client (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_conversation_deleted_at ON taxgpt_conversation (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_conversation_workspace_updated ON taxgpt_conversation (workspace_id, updated_at);
CREATE TABLE IF NOT EXISTS taxgpt_document (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	user_id UUID NOT NULL,
	client_id UUID,
	filename VARCHAR(255) NOT NULL,
	content_type VARCHAR(100) NOT NULL,
	size_bytes INTEGER NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	status VARCHAR(20) NOT NULL,
	extracted_text TEXT NOT NULL,
	content_blob BYTEA NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_taxgpt_document_status CHECK (status IN ('processing', 'ready', 'failed')),
	FOREIGN KEY(workspace_id) REFERENCES taxgpt_workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES taxgpt_user (id) ON DELETE CASCADE,
	FOREIGN KEY(client_id) REFERENCES taxgpt_client (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_document_deleted_at ON taxgpt_document (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_document_workspace_created ON taxgpt_document (workspace_id, created_at);
CREATE TABLE IF NOT EXISTS taxgpt_draft (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	user_id UUID NOT NULL,
	client_id UUID,
	draft_type VARCHAR(30) NOT NULL,
	title VARCHAR(240) NOT NULL,
	prompt TEXT NOT NULL,
	content TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_taxgpt_draft_type CHECK (draft_type IN ('memo', 'client_email', 'notice_response', 'engagement_letter')),
	FOREIGN KEY(workspace_id) REFERENCES taxgpt_workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES taxgpt_user (id) ON DELETE CASCADE,
	FOREIGN KEY(client_id) REFERENCES taxgpt_client (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_draft_deleted_at ON taxgpt_draft (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_draft_workspace_id ON taxgpt_draft (workspace_id);
CREATE TABLE IF NOT EXISTS taxgpt_matrix (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	user_id UUID NOT NULL,
	question VARCHAR(1200) NOT NULL,
	jurisdictions_json TEXT NOT NULL,
	results_json TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id) REFERENCES taxgpt_workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES taxgpt_user (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_matrix_deleted_at ON taxgpt_matrix (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_matrix_workspace_id ON taxgpt_matrix (workspace_id);
CREATE TABLE IF NOT EXISTS taxgpt_session (
	id UUID NOT NULL,
	user_id UUID NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_taxgpt_session_token_hash UNIQUE (token_hash),
	FOREIGN KEY(user_id) REFERENCES taxgpt_user (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_session_deleted_at ON taxgpt_session (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_session_expires_at ON taxgpt_session (expires_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_session_user_id ON taxgpt_session (user_id);
CREATE TABLE IF NOT EXISTS taxgpt_workflow_run (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	user_id UUID NOT NULL,
	client_id UUID,
	template_key VARCHAR(80) NOT NULL,
	title VARCHAR(180) NOT NULL,
	status VARCHAR(30) NOT NULL,
	inputs_json TEXT NOT NULL,
	result_json TEXT NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_taxgpt_workflow_run_status CHECK (status IN ('review_required', 'complete')),
	FOREIGN KEY(workspace_id) REFERENCES taxgpt_workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES taxgpt_user (id) ON DELETE CASCADE,
	FOREIGN KEY(client_id) REFERENCES taxgpt_client (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_workflow_run_deleted_at ON taxgpt_workflow_run (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_workflow_workspace_created ON taxgpt_workflow_run (workspace_id, created_at);
CREATE TABLE IF NOT EXISTS taxgpt_message (
	id UUID NOT NULL,
	conversation_id UUID NOT NULL,
	role VARCHAR(20) NOT NULL,
	content TEXT NOT NULL,
	feedback SMALLINT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_taxgpt_message_role CHECK (role IN ('user', 'assistant')),
	CONSTRAINT ck_taxgpt_message_feedback CHECK (feedback IS NULL OR feedback IN (-1, 1)),
	FOREIGN KEY(conversation_id) REFERENCES taxgpt_conversation (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_message_conversation_id ON taxgpt_message (conversation_id);
CREATE INDEX IF NOT EXISTS ix_taxgpt_message_deleted_at ON taxgpt_message (deleted_at);
CREATE TABLE IF NOT EXISTS taxgpt_review (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	user_id UUID NOT NULL,
	document_id UUID NOT NULL,
	status VARCHAR(20) NOT NULL,
	form_type VARCHAR(30) NOT NULL,
	findings_json TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_taxgpt_review_status CHECK (status IN ('queued', 'reviewing', 'complete')),
	FOREIGN KEY(workspace_id) REFERENCES taxgpt_workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES taxgpt_user (id) ON DELETE CASCADE,
	FOREIGN KEY(document_id) REFERENCES taxgpt_document (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_review_deleted_at ON taxgpt_review (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_review_workspace_id ON taxgpt_review (workspace_id);
CREATE TABLE IF NOT EXISTS taxgpt_citation (
	id UUID NOT NULL,
	message_id UUID NOT NULL,
	title VARCHAR(240) NOT NULL,
	publisher VARCHAR(140) NOT NULL,
	url VARCHAR(700) NOT NULL,
	excerpt TEXT NOT NULL,
	citation_order INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	source_system VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(message_id) REFERENCES taxgpt_message (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_taxgpt_citation_deleted_at ON taxgpt_citation (deleted_at);
CREATE INDEX IF NOT EXISTS ix_taxgpt_citation_message_id ON taxgpt_citation (message_id);

COMMIT;
