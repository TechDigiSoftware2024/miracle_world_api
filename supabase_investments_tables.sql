-- Investments & payment schedules. Run in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS investments (
    "investmentId" TEXT PRIMARY KEY,
    "participantId" TEXT NOT NULL,
    "agentId" TEXT NOT NULL DEFAULT '',
    "fundId" TEXT NOT NULL DEFAULT '',
    "fundName" TEXT NOT NULL DEFAULT '',
    "investedAmount" NUMERIC(12, 2) NOT NULL DEFAULT 0,
    "roiPercentage" NUMERIC(5, 2) NOT NULL DEFAULT 0,
    "durationMonths" INT NOT NULL CHECK ("durationMonths" >= 0),
    "investmentDate" TIMESTAMPTZ NOT NULL,
    "nextPayoutDate" TIMESTAMPTZ,
    "monthlyPayout" NUMERIC(12, 2) NOT NULL DEFAULT 0,
    "isProfitCapitalPerMonth" BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL DEFAULT 'Processing',
    "investmentStartDate" TIMESTAMPTZ,
    "investmentDoc" TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    CONSTRAINT investments_status_chk CHECK (
        status IN (
            'Processing',
            'Pending Approval',
            'Active',
            'Matured',
            'Completed'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_investments_participant ON investments ("participantId");
CREATE INDEX IF NOT EXISTS idx_investments_status ON investments (status);
CREATE INDEX IF NOT EXISTS idx_investments_created ON investments ("createdAt" DESC);

CREATE TABLE IF NOT EXISTS payment_schedules (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "investmentId" TEXT NOT NULL REFERENCES investments ("investmentId") ON DELETE CASCADE,
    "monthNumber" INT NOT NULL,
    "payoutDate" TIMESTAMPTZ NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    CONSTRAINT payment_schedules_line_status_chk CHECK (status IN ('paid', 'due', 'pending'))
);

CREATE INDEX IF NOT EXISTS idx_payment_schedules_investment ON payment_schedules ("investmentId");
CREATE INDEX IF NOT EXISTS idx_payment_schedules_payout ON payment_schedules ("payoutDate");
