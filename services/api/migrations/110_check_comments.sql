-- Migration 110: a comment thread on a client's check.
--
-- client_check_comments: what people write about a check for a client ("waiting on the client's reply", "ordered the licence"), newest last. Tied to the client like the accepted-risk rows. The author is
-- kept as text (the email at the time) so the thread still reads after an account is removed. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_check_comments (
    id         BIGSERIAL    PRIMARY KEY,
    tenant_id  UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    key        VARCHAR(80)  NOT NULL,
    author     VARCHAR(200) NOT NULL,
    body       VARCHAR(1000) NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_client_check_comments_tenant_key ON client_check_comments (tenant_id, key, created_at);

ALTER TABLE client_check_comments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_check_comments;
CREATE POLICY tenant_isolation ON client_check_comments
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
