-- Remove duplicate partner earnings columns; use selfEarningAmount / teamEarningAmount only.
-- API responses still expose selfProfit / generatedProfitByTeam as aliases (computed in app).
-- Run once in Supabase SQL Editor after deploying the API that no longer reads or writes these columns.

ALTER TABLE public.partners
  DROP COLUMN IF EXISTS "selfProfit";

ALTER TABLE public.partners
  DROP COLUMN IF EXISTS "generatedProfitByTeam";
