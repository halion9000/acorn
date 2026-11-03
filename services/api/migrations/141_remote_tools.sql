-- Migration 141: remote management and remote access tools found on client devices (and the owner's decision about each).
--
-- remote_tool_rules: what the managing company decided about a tool. client_id is the all-zero id for "every client" (a real client id has a row only when that client differs); a row with a client_id is that client's own decision and wins over the general one (a client
--   that runs AnyDesk on purpose is "allowed" for it while it is "blocked" for everyone else). tenant_id is the managing company.
-- device_remote_tools: one row per tool found on a device, by the client's tenant. Only the matches are kept (never a device's whole software list). hostname_key is the lower-case name without a domain.
-- remote_tool_scans: when a client's devices were last scanned for these tools and how many were looked at, so "found on 12 of 80 computers" can be told from "nothing was looked at".
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS remote_tool_rules (
    tenant_id  UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    tool_key   VARCHAR(60)  NOT NULL,
    client_id  UUID         NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    verdict    VARCHAR(12)  NOT NULL CHECK (verdict IN ('allowed', 'blocked', 'unreviewed')),
    note       VARCHAR(400),
    decided_by UUID,
    decided_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, tool_key, client_id)
);

CREATE TABLE IF NOT EXISTS device_remote_tools (
    tenant_id    UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    hostname_key VARCHAR(255)  NOT NULL,
    tool_key     VARCHAR(60)   NOT NULL,
    hostname     VARCHAR(255)  NOT NULL,
    vendor       VARCHAR(40)   NOT NULL,
    version      VARCHAR(60),
    first_seen   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    last_seen    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, hostname_key, tool_key)
);
CREATE INDEX IF NOT EXISTS ix_device_remote_tools_tool ON device_remote_tools (tool_key);

CREATE TABLE IF NOT EXISTS remote_tool_scans (
    tenant_id       UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    vendor          VARCHAR(40)  NOT NULL,
    scanned_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    devices_scanned INTEGER      NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, vendor)
);

ALTER TABLE remote_tool_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON remote_tool_rules;
CREATE POLICY tenant_isolation ON remote_tool_rules
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE device_remote_tools ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON device_remote_tools;
CREATE POLICY tenant_isolation ON device_remote_tools
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE remote_tool_scans ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON remote_tool_scans;
CREATE POLICY tenant_isolation ON remote_tool_scans
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
