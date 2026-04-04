-- Run in Supabase SQL Editor if the project already exists and lacks contact_queries.

CREATE TABLE IF NOT EXISTS contact_queries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contact_queries_created ON contact_queries ("createdAt" DESC);
