-- Migrate fund_types: replace durationMonths + durationYears with duration (months only).
-- Run once in Supabase SQL Editor after backup.

ALTER TABLE fund_types ADD COLUMN IF NOT EXISTS "duration" INT;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'fund_types'
      AND column_name = 'durationMonths'
  ) THEN
    UPDATE fund_types
    SET "duration" = CASE
      WHEN "durationMonths" IS NULL AND "durationYears" IS NULL THEN NULL
      ELSE COALESCE("durationMonths", 0) + COALESCE("durationYears", 0) * 12
    END;
    ALTER TABLE fund_types DROP COLUMN "durationMonths";
    ALTER TABLE fund_types DROP COLUMN "durationYears";
  END IF;
END $$;
