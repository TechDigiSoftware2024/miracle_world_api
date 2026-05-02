-- Reward programs and offers. Run in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS reward_programs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title TEXT NOT NULL,
    "achieverTitle" TEXT NOT NULL DEFAULT '',
    "programType" TEXT NOT NULL,
    "businessType" TEXT,
    "goalAmountValue" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "goalAmountUnit" TEXT NOT NULL DEFAULT 'LAKH',
    "startDate" TIMESTAMPTZ NOT NULL,
    "goalDays" INT NOT NULL CHECK ("goalDays" >= 0),
    "endDate" TIMESTAMPTZ NOT NULL,
    "activationDaysAfterGoal" INT,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    CONSTRAINT reward_programs_program_type_chk CHECK ("programType" IN ('MONTHLY', 'ULTIMATE')),
    CONSTRAINT reward_programs_business_type_chk CHECK (
        "businessType" IS NULL OR "businessType" IN ('DIRECT', 'TEAM')
    ),
    CONSTRAINT reward_programs_goal_unit_chk CHECK ("goalAmountUnit" IN ('LAKH', 'CRORE'))
);

CREATE INDEX IF NOT EXISTS idx_reward_programs_active ON reward_programs ("isActive");
CREATE INDEX IF NOT EXISTS idx_reward_programs_start ON reward_programs ("startDate" DESC);

CREATE TABLE IF NOT EXISTS reward_offers (
    id TEXT PRIMARY KEY,
    "programId" BIGINT NOT NULL REFERENCES reward_programs (id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    "imageUrl" TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_reward_offers_program ON reward_offers ("programId");

-- Achievements: see also supabase_reward_program_achievements.sql (same DDL).
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
