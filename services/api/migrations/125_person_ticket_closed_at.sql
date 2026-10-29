-- person_tickets.closed_at: when the ticketing tool (HaloPSA) says the ticket was closed, so the identity page can say "closed 3 days ago". NULL while the ticket is open or when the tool does not say.
BEGIN;

ALTER TABLE person_tickets ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;

COMMIT;
