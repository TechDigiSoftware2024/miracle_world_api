-- Manual KYC (PAN or Aadhaar + document URL). One row per app user (JWT `userId`).
-- Run in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS manual_kyc (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "kycType" TEXT NOT NULL,
    "panNumber" TEXT NOT NULL DEFAULT '',
    "panFullName" TEXT NOT NULL DEFAULT '',
    "panDocumentUrl" TEXT NOT NULL DEFAULT '',
    "aadhaarNumber" TEXT NOT NULL DEFAULT '',
    "aadhaarFullName" TEXT NOT NULL DEFAULT '',
    "aadhaarDocumentUrl" TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Pending',
    "rejectionReason" TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    "verifiedBy" TEXT REFERENCES admins ("adminId") ON DELETE SET NULL,
    "verifiedAt" TIMESTAMPTZ,
    CONSTRAINT manual_kyc_type_chk CHECK ("kycType" IN ('PAN', 'AADHAAR')),
    CONSTRAINT manual_kyc_status_chk CHECK (status IN ('Pending', 'Verified', 'Rejected')),
    CONSTRAINT manual_kyc_user_unique UNIQUE ("userId")
);

CREATE INDEX IF NOT EXISTS idx_manual_kyc_status ON manual_kyc (status);
CREATE INDEX IF NOT EXISTS idx_manual_kyc_created ON manual_kyc ("createdAt" DESC);
