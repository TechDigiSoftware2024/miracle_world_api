-- One-time migration if you already created tables with BIGINT `id` + investorId/agentId.
-- Backup data first. Run in SQL Editor in order; adjust if your live schema differs.

-- ─── admins ─────────────────────────────────────────────────────
ALTER TABLE admins DROP CONSTRAINT IF EXISTS admins_pkey;
ALTER TABLE admins DROP COLUMN IF EXISTS id;
ALTER TABLE admins ADD PRIMARY KEY ("adminId");

-- ─── participants ─────────────────────────────────────────────────
ALTER TABLE participants DROP CONSTRAINT IF EXISTS participants_pkey;
ALTER TABLE participants DROP COLUMN IF EXISTS id;
ALTER TABLE participants RENAME COLUMN "investorId" TO "participantId";
ALTER TABLE participants ADD PRIMARY KEY ("participantId");

-- ─── partners ─────────────────────────────────────────────────────
ALTER TABLE partners DROP CONSTRAINT IF EXISTS partners_pkey;
ALTER TABLE partners DROP COLUMN IF EXISTS id;
ALTER TABLE partners RENAME COLUMN "agentId" TO "partnerId";
ALTER TABLE partners ADD PRIMARY KEY ("partnerId");
