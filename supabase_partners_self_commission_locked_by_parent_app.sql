-- One-time partner-app rule: after a direct parent sets the child's self/intro via POST /partner/team/{child}/commission,
-- further attempts from the partner app are rejected until/unless an admin workflow resets this flag (optional future).
-- Admin APIs ignore this flag.

ALTER TABLE public.partners
    ADD COLUMN IF NOT EXISTS "selfCommissionLockedByParentApp" BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.partners."selfCommissionLockedByParentApp" IS
    'True once the direct introducer has saved child commission via partner app; blocks repeat POST /partner/team/{child}/commission.';
