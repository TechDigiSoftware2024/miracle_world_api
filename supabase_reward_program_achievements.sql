-- Partner reward achievements (per program window / monthly slice).
-- Run in Supabase SQL Editor after reward_programs exists.

CREATE TABLE IF NOT EXISTS reward_program_achievements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "programId" BIGINT NOT NULL REFERENCES reward_programs (id) ON DELETE CASCADE,
    "partnerId" TEXT NOT NULL,
    "periodKey" TEXT NOT NULL,
    "periodStart" TIMESTAMPTZ NOT NULL,
    "periodEnd" TIMESTAMPTZ NOT NULL,
    "directPaidInPeriod" NUMERIC(14, 2) NOT NULL DEFAULT 0,
    "teamPaidInPeriod" NUMERIC(14, 2) NOT NULL DEFAULT 0,
    "qualifyingAmount" NUMERIC(14, 2) NOT NULL DEFAULT 0,
    "goalAmountRupees" NUMERIC(14, 2) NOT NULL DEFAULT 0,
    "goalReached" BOOLEAN NOT NULL DEFAULT false,
    "achievedAt" TIMESTAMPTZ,
    "computedAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT reward_achievements_period_key_chk CHECK (
        "periodKey" = 'FULL' OR "periodKey" ~ '^[0-9]{4}-[0-9]{2}$'
    ),
    CONSTRAINT reward_program_achievements_unique_slice UNIQUE ("programId", "partnerId", "periodKey")
);

CREATE INDEX IF NOT EXISTS idx_reward_achievements_program ON reward_program_achievements ("programId");
CREATE INDEX IF NOT EXISTS idx_reward_achievements_partner ON reward_program_achievements ("partnerId");
CREATE INDEX IF NOT EXISTS idx_reward_achievements_reached ON reward_program_achievements ("programId", "goalReached")
    WHERE "goalReached" = true;

COMMENT ON TABLE reward_program_achievements IS
    'Earned income vs reward program goals: paid commission in period (direct L0 / team L1+). Recompute when program dates/goals change.';
COMMENT ON COLUMN reward_program_achievements."periodKey" IS
    'FULL = ULTIMATE cumulative window; YYYY-MM = MONTHLY slice.';
