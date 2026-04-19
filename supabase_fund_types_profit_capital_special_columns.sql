-- Add profit+capital-per-month and special flags to existing fund_types. Run once in Supabase SQL Editor.

ALTER TABLE fund_types
    ADD COLUMN IF NOT EXISTS "isProfitCapitalPerMonth" BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE fund_types
    ADD COLUMN IF NOT EXISTS "isSpecial" BOOLEAN NOT NULL DEFAULT false;
