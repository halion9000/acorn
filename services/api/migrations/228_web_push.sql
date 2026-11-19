-- Migration 228: web push for a critical alert (roadmap r7-af-39). One VAPID key per organization (the private half is stored encrypted by the credential vault) and one row per browser that turned notifications on.
-- last_alert_at is how far the sender has looked, so a critical alert is pushed once. Row-level security as in migration 081. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS push_keys (
    tenant_id         UUID         PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    public_key        TEXT         NOT NULL,
    private_key_enc   TEXT         NOT NULL,
    last_alert_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          UUID         PRIMARY KEY,
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    user_id     UUID         NOT NULL,
    endpoint    TEXT         NOT NULL,
    p256dh      TEXT         NOT NULL,
    auth        TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, endpoint)
);
CREATE INDEX IF NOT EXISTS push_subscriptions_tenant_idx ON push_subscriptions (tenant_id);

ALTER TABLE push_keys ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON push_keys;
CREATE POLICY tenant_isolation ON push_keys
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON push_subscriptions;
CREATE POLICY tenant_isolation ON push_subscriptions
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
