-- Migration 189: the trust center (Secureframe parity plan).
--
-- trust_center_settings: what an organization (or one of its clients) shows its own customers about its security, behind sign-in for now: a headline, an about text, a contact address, which frameworks to show
-- (their control health is worked out when the page is read), which policies to list (by name, with when each was last reviewed) and a list of documents (a name and a link). One row per organization. Row-level
-- security (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS trust_center_settings (
    tenant_id      UUID          PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    enabled        BOOLEAN       NOT NULL DEFAULT false,
    headline       VARCHAR(200)  NOT NULL DEFAULT '',
    about          TEXT          NOT NULL DEFAULT '',
    contact_email  VARCHAR(320),
    frameworks     JSONB         NOT NULL DEFAULT '[]'::jsonb,
    policy_ids     JSONB         NOT NULL DEFAULT '[]'::jsonb,
    documents      JSONB         NOT NULL DEFAULT '[]'::jsonb,
    updated_by     VARCHAR(320),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

ALTER TABLE trust_center_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON trust_center_settings;
CREATE POLICY tenant_isolation ON trust_center_settings
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
