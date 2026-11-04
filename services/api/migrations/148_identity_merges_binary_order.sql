-- Migration 148: the identity_merges "sorted pair" check compares addresses the way the application does.
--
-- Migration 145 required address_a < address_b using the database's own text comparison (en_US and the like), which ignores punctuation at first: "ab@x.com" sorts before "a@x.com" there. The application
-- sorts each pair with a plain character-by-character comparison, so for such a pair the row it wrote was refused (a 500 on the Merge button). The check now uses the same plain comparison (COLLATE "C").
-- Every row already stored passes both orders, since it was written by the application. Idempotent: the old unnamed check (identity_merges_check) and a previous run's (identity_merges_sorted) are dropped first.

BEGIN;

ALTER TABLE identity_merges DROP CONSTRAINT IF EXISTS identity_merges_check;
ALTER TABLE identity_merges DROP CONSTRAINT IF EXISTS identity_merges_sorted;
ALTER TABLE identity_merges ADD CONSTRAINT identity_merges_sorted CHECK (address_a COLLATE "C" < address_b COLLATE "C");

COMMIT;
