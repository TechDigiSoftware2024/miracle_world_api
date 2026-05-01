-- Partner commission accrual lines per investment × month × beneficiary (upline chain).
-- Run in Supabase SQL Editor after investments exist.

CREATE TABLE IF NOT EXISTS partner_commission_schedules (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "investmentId" TEXT NOT NULL REFERENCES investments ("investmentId") ON DELETE CASCADE,
    "monthNumber" INT NOT NULL,
    "payoutDate" TIMESTAMPTZ NOT NULL,
    "beneficiaryPartnerId" TEXT NOT NULL,
    "sourcePartnerId" TEXT NOT NULL DEFAULT '',
    level INT NOT NULL DEFAULT 0 CHECK (level >= 0 AND level <= 100),
    "ratePercent" NUMERIC(8, 4) NOT NULL DEFAULT 0,
    amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    CONSTRAINT partner_commission_schedules_status_chk CHECK (
        status IN ('paid', 'due', 'pending')
    )
);

CREATE INDEX IF NOT EXISTS idx_partner_commission_schedules_investment
    ON partner_commission_schedules ("investmentId");

CREATE INDEX IF NOT EXISTS idx_partner_commission_schedules_beneficiary_date
    ON partner_commission_schedules ("beneficiaryPartnerId", "payoutDate");

CREATE INDEX IF NOT EXISTS idx_partner_commission_schedules_payout
    ON partner_commission_schedules ("payoutDate");
