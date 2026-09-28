-- Migration 002: change the default region_targets for newly-created users to an India-first split.
-- Existing user rows are intentionally NOT backfilled (would silently override real customization).
-- statement
ALTER TABLE users ALTER COLUMN region_targets SET DEFAULT '{"india": 70, "international": 30}'::jsonb;
