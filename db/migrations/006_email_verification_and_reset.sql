-- Email verification and password reset.
-- users.email_verified_at records when the address was last proven (a clicked link).
-- user_tokens holds the one-time tokens behind the emailed links. Only a SHA-256 hash of
-- each token is stored, so a copy of this table cannot be used to verify an address or
-- reset a password. Like sessions, the table is global (no tenant column, no RLS): a
-- link is used before any organization context exists.
BEGIN;

ALTER TABLE roletailor.users ADD COLUMN email_verified_at timestamptz;

CREATE TABLE roletailor.user_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES roletailor.users(id) ON DELETE CASCADE,
    purpose text NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
    token_hash text NOT NULL UNIQUE,
    -- The address the link was sent to. A token only counts while it is still the
    -- account's address.
    email text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX user_tokens_user_purpose_idx ON roletailor.user_tokens (user_id, purpose);
CREATE INDEX user_tokens_expires_idx ON roletailor.user_tokens (expires_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON roletailor.user_tokens TO rt_app;

COMMIT;
