-- Run this in Supabase Dashboard > SQL Editor to create all tables.

CREATE TABLE IF NOT EXISTS admins (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "adminId" TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    mpin TEXT NOT NULL,
    access_sections TEXT NOT NULL DEFAULT 'all',
    status TEXT NOT NULL DEFAULT 'active',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS participants (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "investorId" TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    introducer TEXT NOT NULL,
    mpin TEXT NOT NULL,
    "profileImage" TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    "totalInvestment" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "offeredValues" TEXT,
    "lastVisit" TIMESTAMPTZ,
    "lastUpdated" TIMESTAMPTZ,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS partners (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "agentId" TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    introducer TEXT NOT NULL,
    mpin TEXT NOT NULL,
    "profileImage" TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    commission DOUBLE PRECISION NOT NULL DEFAULT 0,
    "selfCommission" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "selfProfit" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "generatedProfitByTeam" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "totalDeals" INT NOT NULL DEFAULT 0,
    "totalTeamMembers" INT NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_requests (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    phone TEXT NOT NULL,
    role TEXT NOT NULL,
    name TEXT NOT NULL,
    "introducerId" TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    message TEXT,
    pin TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    UNIQUE (phone, role)
);

CREATE TABLE IF NOT EXISTS token_blacklist (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    jti TEXT UNIQUE NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);
