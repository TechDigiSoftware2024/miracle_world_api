-- Bank details per app user (JWT `userId` = participants."participantId" or partners."partnerId").
-- Run in Supabase SQL Editor. There is no unified `users` table; `userId` is enforced in the API layer.

CREATE TABLE IF NOT EXISTS bank_details (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "holderName" TEXT NOT NULL,
    "bankName" TEXT NOT NULL,
    "accountNumber" TEXT NOT NULL,
    "ifscCode" TEXT NOT NULL,
    "upiId" TEXT NOT NULL DEFAULT '',
    "branchName" TEXT NOT NULL DEFAULT '',
    "accountType" TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Pending',
    "rejectionReason" TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    "verifiedBy" TEXT REFERENCES admins ("adminId") ON DELETE SET NULL,
    "verifiedAt" TIMESTAMPTZ,
    CONSTRAINT bank_details_status_chk CHECK (status IN ('Pending', 'Approved', 'Rejected')),
    CONSTRAINT bank_details_user_unique UNIQUE ("userId")
);

CREATE INDEX IF NOT EXISTS idx_bank_details_status ON bank_details (status);
CREATE INDEX IF NOT EXISTS idx_bank_details_created ON bank_details ("createdAt" DESC);
