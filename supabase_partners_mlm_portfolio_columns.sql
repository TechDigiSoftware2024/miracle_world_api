-- Partner MLM / portfolio summary columns + rename commission → introducerCommission.
-- Run once in Supabase SQL Editor.

-- Rename legacy commission column (unquoted lowercase in older schemas).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'partners' AND column_name = 'commission'
  ) THEN
    ALTER TABLE public.partners RENAME COLUMN commission TO "introducerCommission";
  END IF;
END $$;

ALTER TABLE partners ADD COLUMN IF NOT EXISTS "portfolioAmount" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE partners ADD COLUMN IF NOT EXISTS "paidAmount" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE partners ADD COLUMN IF NOT EXISTS "pendingAmount" DOUBLE PRECISION NOT NULL DEFAULT 0;
-- perMonthPendingAmount removed (redundant with upcomingNetNextMonthPayment); drop via supabase_partners_drop_per_month_pending_amount.sql if present.
ALTER TABLE partners ADD COLUMN IF NOT EXISTS "participantInvestedTotal" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE partners ADD COLUMN IF NOT EXISTS "introducerCommissionAmount" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE partners ADD COLUMN IF NOT EXISTS "selfEarningAmount" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE partners ADD COLUMN IF NOT EXISTS "teamEarningAmount" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE partners ADD COLUMN IF NOT EXISTS "portfolioUpdatedAt" TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_investments_agent ON investments ("agentId");

-- snake_case schemas: after migrating partners, optionally run:
-- ALTER TABLE partners RENAME COLUMN commission TO introducer_commission;
