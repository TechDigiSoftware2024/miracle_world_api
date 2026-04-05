-- Run this in Supabase Dashboard > SQL Editor to create all tables.
-- String IDs (MWA / MWP / MWCP prefixes) are the primary keys for admins, participants, partners.
-- If you already have the old schema (BIGINT id + investorId/agentId), run
-- supabase_migration_bigint_pk_to_string_pk.sql instead of this file, or drop the old tables first.

CREATE TABLE IF NOT EXISTS admins (
    "adminId" TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    mpin TEXT NOT NULL,
    access_sections TEXT NOT NULL DEFAULT 'all',
    status TEXT NOT NULL DEFAULT 'active',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS participants (
    "participantId" TEXT PRIMARY KEY,
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
    "partnerId" TEXT PRIMARY KEY,
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

-- Public "Contact us" form submissions (mirrors mobile Firestore contact_queries).
CREATE TABLE IF NOT EXISTS contact_queries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contact_queries_created ON contact_queries ("createdAt" DESC);

-- Singleton row (id = 1): company branding + default introducer IDs for the app.
CREATE TABLE IF NOT EXISTS app_settings (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    "defaultPartnerId" TEXT NOT NULL DEFAULT '',
    "defaultParticipantId" TEXT NOT NULL DEFAULT '',
    "companyName" TEXT NOT NULL DEFAULT '',
    "companyEmail" TEXT NOT NULL DEFAULT '',
    "companyPhone" TEXT NOT NULL DEFAULT '',
    "companyAddress" TEXT NOT NULL DEFAULT '',
    "updatedAt" TIMESTAMPTZ,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO app_settings (
    id,
    "defaultPartnerId",
    "defaultParticipantId",
    "companyName",
    "companyEmail",
    "companyPhone",
    "companyAddress"
) VALUES (
    1,
    'MWCP000001',
    'MWP000001',
    'Miracle World Real Estate LLP',
    'info@miracleworldllp.com',
    '+91 6204599636',
    '906-907, Gera Imperium Alpha, Pune'
)
ON CONFLICT (id) DO NOTHING;

-- ─── Indexes (PK and UNIQUE already index those columns) ─────────
-- Login: filter by phone + mpin on every auth request.
CREATE INDEX IF NOT EXISTS idx_admins_phone_mpin ON admins (phone, mpin);
CREATE INDEX IF NOT EXISTS idx_participants_phone_mpin ON participants (phone, mpin);
CREATE INDEX IF NOT EXISTS idx_partners_phone_mpin ON partners (phone, mpin);

-- Requests: UNIQUE(phone, role) already supports lookups by phone.
-- Extra indexes for status queues and introducer reporting.
CREATE INDEX IF NOT EXISTS idx_user_requests_status ON user_requests (status);
CREATE INDEX IF NOT EXISTS idx_user_requests_status_id ON user_requests (status, id);
CREATE INDEX IF NOT EXISTS idx_user_requests_introducer ON user_requests ("introducerId");

-- Directory / reporting: who introduced whom (introducer holds partner or participant id).
CREATE INDEX IF NOT EXISTS idx_participants_introducer ON participants (introducer);
CREATE INDEX IF NOT EXISTS idx_partners_introducer ON partners (introducer);

-- Optional filters (e.g. active-only lists).
CREATE INDEX IF NOT EXISTS idx_participants_status ON participants (status);
CREATE INDEX IF NOT EXISTS idx_partners_status ON partners (status);
CREATE INDEX IF NOT EXISTS idx_admins_status ON admins (status);
