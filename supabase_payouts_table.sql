-- Payouts (commissions, monthly income, extra income). Run in Supabase SQL Editor.
-- After creating, grant/RLS as needed for your project (this API uses service_role).

CREATE TABLE IF NOT EXISTS payouts (
    "payoutId" TEXT PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "recipientType" TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    status TEXT NOT NULL DEFAULT 'pending',
    "paymentMethod" TEXT NOT NULL,
    "transactionId" TEXT,
    "investmentId" TEXT,
    "payoutDate" TIMESTAMPTZ NOT NULL,
    remarks TEXT NOT NULL DEFAULT '',
    "payoutType" TEXT NOT NULL,
    "createdBy" TEXT NOT NULL,
    "createdByAdminId" TEXT,
    "levelDepth" INT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    CONSTRAINT payouts_recipient_type_chk CHECK ("recipientType" IN ('participant', 'partner')),
    CONSTRAINT payouts_level_depth_chk CHECK (
        "levelDepth" IS NULL OR ("levelDepth" >= 1 AND "levelDepth" <= 100)
    ),
    CONSTRAINT payouts_status_chk CHECK (
        status IN ('pending', 'processing', 'paid', 'failed', 'cancelled')
    ),
    CONSTRAINT payouts_method_chk CHECK ("paymentMethod" IN ('BANK', 'IMPS/NEFT', 'CASH')),
    CONSTRAINT payouts_type_chk CHECK (
        "payoutType" IN ('commission', 'monthly_income', 'extra_income')
    ),
    CONSTRAINT payouts_created_by_chk CHECK ("createdBy" IN ('admin', 'automatic'))
);

CREATE INDEX IF NOT EXISTS idx_payouts_user ON payouts ("userId");
CREATE INDEX IF NOT EXISTS idx_payouts_recipient_type ON payouts ("recipientType");
CREATE INDEX IF NOT EXISTS idx_payouts_status ON payouts (status);
CREATE INDEX IF NOT EXISTS idx_payouts_payout_date ON payouts ("payoutDate" DESC);
CREATE INDEX IF NOT EXISTS idx_payouts_investment ON payouts ("investmentId");
CREATE INDEX IF NOT EXISTS idx_payouts_created ON payouts ("createdAt" DESC);
CREATE INDEX IF NOT EXISTS idx_payouts_level_depth ON payouts ("levelDepth") WHERE "levelDepth" IS NOT NULL;

COMMENT ON COLUMN payouts."levelDepth" IS 'MLM level (1 = direct, 2+ downline) for partner commission payouts; NULL for participants or non-MLM rows.';
COMMENT ON TABLE payouts IS 'Payouts to participants or partners; search via API on admin/partner/participant routes.';
