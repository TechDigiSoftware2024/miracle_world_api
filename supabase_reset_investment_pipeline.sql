-- Destructive: remove all investment rows, payment schedule lines, and partner commission lines;
-- reset bigint identity columns for payment_schedules and partner_commission_schedules to start at 1.
-- Next app-generated investment id will be MWINV000001 (see app.utils.investment_id).
--
-- After running, call POST /admin/investments/reset-pipeline with { "truncateTables": false }
-- to recalc partner + participant portfolio columns only, or use { "truncateTables": true } once
-- this function exists (single call does truncate + full recalc).
--
-- Optional: clear or archive rows in public.payouts that reference removed investments
-- (payouts.investmentId is not FK-enforced; historical rows may become orphans).

CREATE OR REPLACE FUNCTION public.reset_investment_tables()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    TRUNCATE TABLE investments RESTART IDENTITY CASCADE;
END;
$$;

REVOKE ALL ON FUNCTION public.reset_investment_tables() FROM PUBLIC;
-- API uses the service_role key; PostgREST maps to this role.
GRANT EXECUTE ON FUNCTION public.reset_investment_tables() TO service_role;

COMMENT ON FUNCTION public.reset_investment_tables() IS
    'TRUNCATE investments (CASCADE to payment_schedules, partner_commission_schedules) and restart IDENTITY sequences.';
