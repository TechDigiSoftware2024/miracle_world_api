-- Add MLM level depth to existing payouts table. Run in Supabase SQL Editor if payouts already exists.

ALTER TABLE payouts
    ADD COLUMN IF NOT EXISTS "levelDepth" INT;

ALTER TABLE payouts DROP CONSTRAINT IF EXISTS payouts_level_depth_chk;
ALTER TABLE payouts
    ADD CONSTRAINT payouts_level_depth_chk CHECK (
        "levelDepth" IS NULL OR ("levelDepth" >= 1 AND "levelDepth" <= 100)
    );

CREATE INDEX IF NOT EXISTS idx_payouts_level_depth ON payouts ("levelDepth") WHERE "levelDepth" IS NOT NULL;

COMMENT ON COLUMN payouts."levelDepth" IS 'MLM level (1 = direct, 2+ downline) for partner commission payouts; NULL for participants or non-MLM rows.';
