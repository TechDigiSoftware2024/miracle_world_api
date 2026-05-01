-- Remove duplicate column; upcomingNetNextMonthPayment is the single source for next-month accruals.
-- Run once in Supabase SQL Editor after deploying the API that no longer reads or writes this column.

ALTER TABLE public.partners
  DROP COLUMN IF EXISTS "perMonthPendingAmount";
