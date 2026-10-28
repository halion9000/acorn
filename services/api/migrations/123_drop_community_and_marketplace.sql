-- The Detection Catalog and the Marketplace are gone (the imported Sigma rules are rule packs now, and the shipped playbooks are the shared library the Playbooks page lists), so their two tables are
-- dropped: community_catalog_items (77 entries loaded from the shipped files, none installed by anyone) and marketplace_installs ("enabled" markers; one row at the time of removal). Rules a client
-- installed from the catalog before are ordinary rules and are not touched. Safe to run again.
DROP TABLE IF EXISTS community_catalog_items CASCADE;
DROP TABLE IF EXISTS marketplace_installs CASCADE;
