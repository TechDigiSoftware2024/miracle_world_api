-- Nominees per app user (JWT `userId` = participants."participantId" or partners."partnerId").
-- Status workflow: Pending → Verified | Rejected (admin). Run in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS nominees (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "fullName" TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT '',
    "dateOfBirth" DATE,
    gender TEXT NOT NULL DEFAULT '',
    "phoneNumber" TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    "aadhaarNumber" TEXT NOT NULL DEFAULT '',
    "panNumber" TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    pincode TEXT NOT NULL DEFAULT '',
    "nomineeShare" NUMERIC(5, 2),
    "isMinor" BOOLEAN NOT NULL DEFAULT false,
    "guardianName" TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Pending',
    "rejectionReason" TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    "verifiedBy" TEXT REFERENCES admins ("adminId") ON DELETE SET NULL,
    "verifiedAt" TIMESTAMPTZ,
    CONSTRAINT nominees_status_chk CHECK (status IN ('Pending', 'Verified', 'Rejected'))
);

CREATE INDEX IF NOT EXISTS idx_nominees_user ON nominees ("userId");
CREATE INDEX IF NOT EXISTS idx_nominees_status ON nominees (status);
CREATE INDEX IF NOT EXISTS idx_nominees_created ON nominees ("createdAt" DESC);
