-- Participant portfolio aggregates (recalculated by the API on investment / schedule / payout changes).
-- Run in Supabase SQL Editor.

ALTER TABLE participants
    ADD COLUMN IF NOT EXISTS "activeInvestmentsCount" INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "totalPrincipalAmount" NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "pendingScheduleAmount" NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "schedulePaidAmount" NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "payoutsPaidAmount" NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "totalPortfolioValue" NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "portfolioUpdatedAt" TIMESTAMPTZ;

COMMENT ON COLUMN participants."activeInvestmentsCount" IS 'Investments in Processing, Pending Approval, Active, or Matured.';
COMMENT ON COLUMN participants."totalPrincipalAmount" IS 'Sum of investedAmount; duplicate of totalInvestment when recalc runs.';
COMMENT ON COLUMN participants."pendingScheduleAmount" IS 'Sum of payment_schedules amounts (pending + due) for this participant.';
COMMENT ON COLUMN participants."schedulePaidAmount" IS 'Sum of payment_schedules amounts with status paid.';
COMMENT ON COLUMN participants."payoutsPaidAmount" IS 'Sum of payouts (recipient participant, status paid).';
COMMENT ON COLUMN participants."totalPortfolioValue" IS 'Principal + profit-weighted paid schedule + profit-weighted paid payouts (see API recalc).';
COMMENT ON COLUMN participants."portfolioUpdatedAt" IS 'When portfolio fields were last recalculated.';
