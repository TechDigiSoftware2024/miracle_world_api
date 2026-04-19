-- Run in Supabase SQL Editor if the project already exists and lacks fund_types.

CREATE TABLE IF NOT EXISTS fund_types (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "fundName" TEXT NOT NULL,
    "minimumInvestmentAmount" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "maximumInvestmentAmount" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "isMaxInvestmentUnlimited" BOOLEAN NOT NULL DEFAULT false,
    "isROIFixed" BOOLEAN NOT NULL DEFAULT false,
    "fixedROI" DOUBLE PRECISION,
    "minimumROI" DOUBLE PRECISION,
    "maximumROI" DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'active',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    "durationType" TEXT NOT NULL DEFAULT '',
    "duration" INT,
    notes TEXT NOT NULL DEFAULT '',
    description JSONB NOT NULL DEFAULT '[]'::jsonb,
    "isProfitCapitalPerMonth" BOOLEAN NOT NULL DEFAULT false,
    "isSpecial" BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_fund_types_status ON fund_types (status);
CREATE INDEX IF NOT EXISTS idx_fund_types_created ON fund_types ("createdAt" DESC);
