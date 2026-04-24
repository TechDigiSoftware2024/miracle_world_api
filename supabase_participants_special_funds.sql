-- Participant eligibility for special fund types + per-participant assignments.
-- Run once in Supabase SQL Editor on existing projects.

ALTER TABLE participants
  ADD COLUMN IF NOT EXISTS "isEligible" BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS participant_special_funds (
    "participantId" TEXT NOT NULL,
    "fundTypeId" BIGINT NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY ("participantId", "fundTypeId"),
    CONSTRAINT participant_special_funds_fund_fk
      FOREIGN KEY ("fundTypeId") REFERENCES fund_types (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_participant_special_funds_participant
  ON participant_special_funds ("participantId");

CREATE INDEX IF NOT EXISTS idx_participant_special_funds_fund
  ON participant_special_funds ("fundTypeId");
