-- Migration 238: a public share link for the trust center (Hal 2026-11-21: "eventually this will be public, so build in that fashion").
--
-- public_enabled is the off switch (off by default); public_token is the unguessable part of the link, made when the link is first switched on and replaced when a person asks for a new link (the old one stops
-- working at once). The token is looked up across organizations (a visitor has no sign-in), so it is unique over the whole table. Idempotent.

ALTER TABLE trust_center_settings ADD COLUMN IF NOT EXISTS public_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE trust_center_settings ADD COLUMN IF NOT EXISTS public_token TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS trust_center_public_token_idx ON trust_center_settings (public_token) WHERE public_token IS NOT NULL;
