-- Run in Supabase SQL Editor if the project already exists and lacks app_settings.

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
