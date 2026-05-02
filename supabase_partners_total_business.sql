-- Group book: principal from investments where the agent is this partner or any downline partner.
-- Run in Supabase after portfolio columns exist.

ALTER TABLE public.partners
    ADD COLUMN IF NOT EXISTS "totalBusiness" DOUBLE PRECISION NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.partners."totalBusiness" IS
    'Sum of investedAmount (Active, Matured, Completed, Pending Approval) for investments whose agentId is this partner or any partner in their introducer downline tree.';
