-- Migration 132: the stock Live Oak holds for clients, replacing the SharePoint inventory lists.
--
-- inventory_items: one row per thing held. Each row belongs to a tenant: the client's own tenant when it is held for that client, and Live Oak's own tenant when it is not (stock, or a customer that could not be matched
-- to a client yet; ``customer_name`` keeps the name as it was written). Putting a client's items under the client's tenant is what lets a client portal show a client only its own items later, with the same row-level
-- security that already separates every other client's data.
--   kind: 'stock' (parts, drives, batteries, workstations held for clients) or 'nuc' (the NUCs, listed by site, with their own columns).
--   status: 'checked_in' (here with us), 'checked_out' (at a client or with a person), 'offline' (known to be down), 'retired' (archived or decommissioned).
--   person: who has it (the lists call it Person or Deployed To; "spare" is kept as written). ninja_url: the NinjaOne device page the list carried, which links the item to the machine.
--   external_ref: the id the item had in the SharePoint list it was imported from, so importing the same list again updates instead of duplicating.
-- inventory_events: every movement and change, newest first by `at`: who, when, which person had it and which ticket.
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS inventory_items (
    id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    kind          VARCHAR(10)   NOT NULL DEFAULT 'stock' CHECK (kind IN ('stock', 'nuc')),
    customer_name VARCHAR(200),
    name          VARCHAR(300)  NOT NULL,
    category      VARCHAR(80),
    serial        VARCHAR(100),
    model         VARCHAR(200),
    manufacturer  VARCHAR(100),
    quantity      INTEGER       NOT NULL DEFAULT 1 CHECK (quantity >= 0),
    status        VARCHAR(12)   NOT NULL DEFAULT 'checked_in' CHECK (status IN ('checked_in', 'checked_out', 'offline', 'retired')),
    site          VARCHAR(200),
    person        VARCHAR(200),
    part_no       VARCHAR(60),
    has_charger   BOOLEAN,
    cpu           VARCHAR(200),
    memory        VARCHAR(60),
    storage       VARCHAR(60),
    ninja_url     VARCHAR(500),
    accounting_treatment VARCHAR(120),
    deployed_at   DATE,
    redeployed_at DATE,
    checked_out_at DATE,
    checked_in_at DATE,
    notes         TEXT,
    tags          JSONB         NOT NULL DEFAULT '[]'::jsonb,
    ticket_url    VARCHAR(500),
    source        VARCHAR(12)   NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'csv')),
    external_ref  VARCHAR(60),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_inventory_items_tenant_kind ON inventory_items (tenant_id, kind);
CREATE INDEX IF NOT EXISTS ix_inventory_items_serial ON inventory_items (lower(serial)) WHERE serial IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_items_external ON inventory_items (tenant_id, kind, external_ref) WHERE external_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS inventory_events (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    item_id    UUID         NOT NULL REFERENCES inventory_items (id) ON DELETE CASCADE,
    at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    event      VARCHAR(20)  NOT NULL CHECK (event IN ('created', 'updated', 'checked_out', 'checked_in', 'retired', 'moved')),
    actor      VARCHAR(320),
    person     VARCHAR(200),
    ticket_url VARCHAR(500),
    note       TEXT
);

CREATE INDEX IF NOT EXISTS ix_inventory_events_item ON inventory_events (item_id, at DESC);

ALTER TABLE inventory_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON inventory_items;
CREATE POLICY tenant_isolation ON inventory_items
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE inventory_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON inventory_events;
CREATE POLICY tenant_isolation ON inventory_events
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
