-- Upcoming scheduled income for the next calendar month (UTC), recalculated by the API on portfolio recalc.
-- Run in Supabase SQL Editor.

ALTER TABLE participants
    ADD COLUMN IF NOT EXISTS "upcomingNetNextMonthPayment" NUMERIC(14, 2) NOT NULL DEFAULT 0;

ALTER TABLE partners
    ADD COLUMN IF NOT EXISTS "upcomingNetNextMonthPayment" NUMERIC(14, 2) NOT NULL DEFAULT 0;

COMMENT ON COLUMN participants."upcomingNetNextMonthPayment" IS
    'Sum of payment_schedules (pending+due) with payoutDate in next UTC calendar month for this participant.';
COMMENT ON COLUMN partners."upcomingNetNextMonthPayment" IS
    'Sum of partner_commission_schedules (pending+due) with payoutDate in next UTC month: direct (level 0) + team/upline (level >= 1), beneficiary = this partner.';
