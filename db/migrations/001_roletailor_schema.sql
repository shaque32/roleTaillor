-- RoleTailorAI initial PostgreSQL migration. Run as a dedicated schema owner.
-- Request transactions must use a separate, non-BYPASSRLS role and set
-- app.organization_id with SET LOCAL after authenticating tenant membership.
BEGIN;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE SCHEMA roletailor;
SET LOCAL search_path = roletailor, public;

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL,
    password_hash text,
    full_name text NOT NULL,
    address jsonb,
    contact_number text,
    linkedin_url text,
    preferred_page_limit smallint NOT NULL DEFAULT 2 CHECK (preferred_page_limit > 0),
    industry_focus text,
    resume_tone text,
    ats_preference text,
    technical_depth text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_unique ON users (lower(email));

CREATE TABLE organizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    free_generation_limit integer NOT NULL DEFAULT 10 CHECK (free_generation_limit >= 0),
    stripe_customer_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE organization_members (
    organization_id uuid NOT NULL REFERENCES organizations(id),
    user_id uuid NOT NULL REFERENCES users(id),
    role text NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    joined_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, user_id)
);
CREATE INDEX organization_members_user_idx ON organization_members(user_id);

CREATE TABLE sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    device_label text,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (expires_at > created_at)
);

CREATE TABLE user_consents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose text NOT NULL,
    policy_version text NOT NULL,
    granted boolean NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX user_consents_latest_idx ON user_consents(user_id, purpose, recorded_at DESC);

CREATE TABLE templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    disabled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE template_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id uuid NOT NULL REFERENCES templates(id),
    version_number integer NOT NULL CHECK (version_number > 0),
    storage_key text NOT NULL,
    layout_metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (template_id, version_number)
);
ALTER TABLE users ADD COLUMN preferred_template_id uuid REFERENCES templates(id);

CREATE TABLE stored_files (
    organization_id uuid NOT NULL REFERENCES organizations(id),
    id uuid DEFAULT gen_random_uuid(),
    bucket text NOT NULL,
    object_key text NOT NULL,
    object_version text,
    original_filename text,
    media_type text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    sha256 text CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    scan_status text NOT NULL DEFAULT 'pending'
        CHECK (scan_status IN ('pending', 'clean', 'blocked', 'failed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    UNIQUE NULLS NOT DISTINCT (bucket, object_key, object_version)
);

CREATE TABLE resumes (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    owner_user_id uuid NOT NULL,
    name text NOT NULL,
    origin text NOT NULL CHECK (origin IN ('upload', 'guided')),
    created_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    PRIMARY KEY (organization_id, id),
    FOREIGN KEY (organization_id, owner_user_id)
        REFERENCES organization_members(organization_id, user_id)
);

CREATE TABLE resume_versions (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    resume_id uuid NOT NULL,
    version_number integer NOT NULL CHECK (version_number > 0),
    parent_version_id uuid,
    source_file_id uuid,
    template_version_id uuid REFERENCES template_versions(id),
    content jsonb NOT NULL DEFAULT '{}',
    layout_metadata jsonb NOT NULL DEFAULT '{}',
    extraction_findings jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    UNIQUE (organization_id, resume_id, version_number),
    UNIQUE (organization_id, resume_id, id),
    FOREIGN KEY (organization_id, resume_id) REFERENCES resumes(organization_id, id),
    FOREIGN KEY (organization_id, resume_id, parent_version_id)
        REFERENCES resume_versions(organization_id, resume_id, id),
    FOREIGN KEY (organization_id, source_file_id) REFERENCES stored_files(organization_id, id),
    CHECK (parent_version_id IS DISTINCT FROM id)
);

CREATE TABLE job_postings (
    organization_id uuid NOT NULL REFERENCES organizations(id),
    id uuid DEFAULT gen_random_uuid(),
    source_url text,
    title text,
    company text,
    description text,
    structured_requirements jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    CHECK (description IS NOT NULL OR source_url IS NOT NULL)
);

CREATE TABLE tailoring_workflows (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    requested_by uuid NOT NULL,
    source_resume_version_id uuid NOT NULL,
    job_posting_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'queued', 'running', 'paused', 'completed', 'failed', 'cancelled')),
    page_limit smallint NOT NULL DEFAULT 2 CHECK (page_limit > 0),
    draft_state jsonb NOT NULL DEFAULT '{}',
    paid_usage_accepted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    UNIQUE (organization_id, idempotency_key),
    FOREIGN KEY (organization_id, requested_by) REFERENCES organization_members(organization_id, user_id),
    FOREIGN KEY (organization_id, source_resume_version_id) REFERENCES resume_versions(organization_id, id),
    FOREIGN KEY (organization_id, job_posting_id) REFERENCES job_postings(organization_id, id)
);

CREATE TABLE generated_resumes (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    workflow_id uuid NOT NULL,
    iteration integer NOT NULL CHECK (iteration > 0),
    resume_version_id uuid NOT NULL,
    ats_score numeric(5,2) CHECK (ats_score BETWEEN 0 AND 100),
    job_alignment_score numeric(5,2) CHECK (job_alignment_score BETWEEN 0 AND 100),
    keyword_relevance_score numeric(5,2) CHECK (keyword_relevance_score BETWEEN 0 AND 100),
    formatting_score numeric(5,2) CHECK (formatting_score BETWEEN 0 AND 100),
    simulation_score numeric(5,2) CHECK (simulation_score BETWEEN 0 AND 100),
    simulated_feedback jsonb,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    UNIQUE (organization_id, workflow_id, iteration),
    FOREIGN KEY (organization_id, workflow_id) REFERENCES tailoring_workflows(organization_id, id),
    FOREIGN KEY (organization_id, resume_version_id) REFERENCES resume_versions(organization_id, id)
);

CREATE TABLE resume_changes (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    generated_resume_id uuid NOT NULL,
    block_path text NOT NULL,
    prior_text text,
    proposed_text text,
    reason text,
    prioritized_keywords text[] NOT NULL DEFAULT '{}',
    decision text NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending', 'accepted', 'rejected')),
    decided_at timestamptz,
    PRIMARY KEY (organization_id, id),
    FOREIGN KEY (organization_id, generated_resume_id) REFERENCES generated_resumes(organization_id, id)
);

CREATE TABLE resume_exports (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    resume_version_id uuid NOT NULL,
    file_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('docx', 'pdf', 'ats_report', 'feedback_report')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    FOREIGN KEY (organization_id, resume_version_id) REFERENCES resume_versions(organization_id, id),
    FOREIGN KEY (organization_id, file_id) REFERENCES stored_files(organization_id, id)
);

CREATE TABLE resume_share_links (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    export_id uuid NOT NULL,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    PRIMARY KEY (organization_id, id),
    FOREIGN KEY (organization_id, export_id) REFERENCES resume_exports(organization_id, id)
);

CREATE TABLE applications (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    job_posting_id uuid,
    resume_version_id uuid,
    company text NOT NULL,
    role_title text NOT NULL,
    status text NOT NULL DEFAULT 'saved'
        CHECK (status IN ('saved', 'applied', 'interviewing', 'offered', 'rejected', 'withdrawn', 'accepted')),
    applied_at timestamptz,
    reminder_at timestamptz,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    FOREIGN KEY (organization_id, user_id) REFERENCES organization_members(organization_id, user_id),
    FOREIGN KEY (organization_id, job_posting_id) REFERENCES job_postings(organization_id, id),
    FOREIGN KEY (organization_id, resume_version_id) REFERENCES resume_versions(organization_id, id)
);

CREATE TABLE ai_model_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    model_name text NOT NULL,
    revision text NOT NULL,
    capability_tier text NOT NULL CHECK (capability_tier IN ('low', 'medium', 'high')),
    embedding_dimensions integer CHECK (embedding_dimensions BETWEEN 1 AND 16000),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, model_name, revision),
    UNIQUE (id, embedding_dimensions)
);

CREATE TABLE prompt_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_key text NOT NULL,
    environment text NOT NULL,
    version_number integer NOT NULL CHECK (version_number > 0),
    template_text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (prompt_key, environment, version_number)
);

CREATE TABLE embeddings (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    resume_version_id uuid,
    job_posting_id uuid,
    model_version_id uuid NOT NULL,
    dimensions integer NOT NULL,
    segment_key text NOT NULL DEFAULT 'document',
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    embedding vector NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    CHECK (num_nonnulls(resume_version_id, job_posting_id) = 1),
    CHECK (public.vector_dims(embedding) = dimensions),
    FOREIGN KEY (model_version_id, dimensions) REFERENCES ai_model_versions(id, embedding_dimensions),
    FOREIGN KEY (organization_id, resume_version_id) REFERENCES resume_versions(organization_id, id),
    FOREIGN KEY (organization_id, job_posting_id) REFERENCES job_postings(organization_id, id),
    UNIQUE NULLS NOT DISTINCT
        (organization_id, model_version_id, resume_version_id, job_posting_id, segment_key, content_sha256)
);
-- Compare vectors within a single model revision. Add a partial, dimension-specific
-- ANN index when a production embedding model and search workload are selected.
CREATE INDEX embeddings_model_idx ON embeddings(organization_id, model_version_id);

CREATE TABLE ai_metrics (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    workflow_id uuid NOT NULL,
    model_version_id uuid NOT NULL REFERENCES ai_model_versions(id),
    prompt_version_id uuid REFERENCES prompt_versions(id),
    stage text NOT NULL,
    attempt integer NOT NULL CHECK (attempt > 0),
    status text NOT NULL CHECK (status IN ('succeeded', 'failed', 'timed_out', 'cached')),
    routing_reason text,
    trace_id text,
    latency_ms integer CHECK (latency_ms >= 0),
    input_tokens integer CHECK (input_tokens >= 0),
    output_tokens integer CHECK (output_tokens >= 0),
    estimated_cost_usd numeric(16,8) CHECK (estimated_cost_usd >= 0),
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    UNIQUE (organization_id, workflow_id, stage, attempt),
    FOREIGN KEY (organization_id, workflow_id) REFERENCES tailoring_workflows(organization_id, id)
);

CREATE TABLE validation_results (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    workflow_id uuid NOT NULL,
    ai_metric_id uuid,
    rule_key text NOT NULL,
    rule_version text NOT NULL,
    passed boolean NOT NULL,
    score numeric(5,2) CHECK (score BETWEEN 0 AND 100),
    threshold numeric(5,2) CHECK (threshold BETWEEN 0 AND 100),
    details jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    FOREIGN KEY (organization_id, workflow_id) REFERENCES tailoring_workflows(organization_id, id),
    FOREIGN KEY (organization_id, ai_metric_id) REFERENCES ai_metrics(organization_id, id)
);

CREATE TABLE subscriptions (
    organization_id uuid NOT NULL REFERENCES organizations(id),
    id uuid DEFAULT gen_random_uuid(),
    stripe_subscription_id text NOT NULL UNIQUE,
    stripe_price_id text NOT NULL,
    status text NOT NULL,
    current_period_end timestamptz,
    cancel_at_period_end boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id)
);

CREATE TABLE payments (
    organization_id uuid NOT NULL REFERENCES organizations(id),
    id uuid DEFAULT gen_random_uuid(),
    subscription_id uuid,
    stripe_payment_intent_id text NOT NULL UNIQUE,
    status text NOT NULL,
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    amount_minor bigint NOT NULL CHECK (amount_minor >= 0),
    refunded_minor bigint NOT NULL DEFAULT 0 CHECK (refunded_minor BETWEEN 0 AND amount_minor),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id),
    FOREIGN KEY (organization_id, subscription_id) REFERENCES subscriptions(organization_id, id)
);

CREATE TABLE stripe_webhook_events (
    event_id text PRIMARY KEY,
    event_type text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);

-- The billing service records a charge only after a successful initial generation.
-- It must serialize quota allocation per organization. Iterations share this row.
CREATE TABLE usage_tracking (
    organization_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    payment_id uuid,
    charge_type text NOT NULL CHECK (charge_type IN ('free', 'subscription', 'pay_per_use')),
    charged_at timestamptz NOT NULL DEFAULT now(),
    reversed_at timestamptz,
    PRIMARY KEY (organization_id, workflow_id),
    FOREIGN KEY (organization_id, workflow_id) REFERENCES tailoring_workflows(organization_id, id),
    FOREIGN KEY (organization_id, payment_id) REFERENCES payments(organization_id, id),
    CHECK ((charge_type = 'pay_per_use') = (payment_id IS NOT NULL))
);
CREATE INDEX usage_free_count_idx ON usage_tracking(organization_id)
    WHERE charge_type = 'free' AND reversed_at IS NULL;

CREATE TABLE notifications (
    organization_id uuid NOT NULL,
    id uuid DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    channel text NOT NULL CHECK (channel IN ('email', 'in_app')),
    kind text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    read_at timestamptz,
    PRIMARY KEY (organization_id, id),
    FOREIGN KEY (organization_id, user_id) REFERENCES organization_members(organization_id, user_id)
);

CREATE TABLE audit_logs (
    organization_id uuid NOT NULL REFERENCES organizations(id),
    id uuid DEFAULT gen_random_uuid(),
    actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_id uuid,
    correlation_id text,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, id)
);

CREATE INDEX workflows_dashboard_idx ON tailoring_workflows(organization_id, requested_by, created_at DESC);
CREATE INDEX applications_user_idx ON applications(organization_id, user_id, created_at DESC);
CREATE INDEX notifications_inbox_idx ON notifications(organization_id, user_id, created_at DESC);
CREATE INDEX audit_logs_time_idx ON audit_logs(organization_id, created_at DESC);

CREATE FUNCTION current_organization_id() RETURNS uuid
LANGUAGE sql STABLE
SET search_path = pg_catalog
AS $$
    SELECT nullif(current_setting('app.organization_id', true), '')::uuid
$$;

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON organizations
    USING (id = roletailor.current_organization_id());

DO $$
DECLARE
    tenant_table text;
BEGIN
    FOREACH tenant_table IN ARRAY ARRAY[
        'organization_members', 'stored_files', 'resumes', 'resume_versions',
        'job_postings', 'tailoring_workflows', 'generated_resumes', 'resume_changes',
        'resume_exports', 'resume_share_links', 'applications', 'embeddings',
        'ai_metrics', 'validation_results', 'subscriptions', 'payments',
        'usage_tracking', 'notifications', 'audit_logs'
    ]
    LOOP
        EXECUTE format('ALTER TABLE roletailor.%I ENABLE ROW LEVEL SECURITY', tenant_table);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON roletailor.%I
             USING (organization_id = roletailor.current_organization_id())',
            tenant_table
        );
    END LOOP;
END
$$;

-- Global identity, catalog and webhook tables require service-specific grants.
-- Tenant policy is organization-wide. User-level permissions belong to the API.
COMMIT;
