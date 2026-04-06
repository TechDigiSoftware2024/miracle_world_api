-- Run in Supabase SQL Editor if the project already exists and lacks properties.

CREATE TABLE IF NOT EXISTS properties (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    "type" TEXT NOT NULL,
    purpose TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL DEFAULT 0,
    area DOUBLE PRECISION NOT NULL DEFAULT 0,
    address TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    "zipCode" TEXT NOT NULL DEFAULT '',
    images JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'available',
    amenities JSONB,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updatedAt" TIMESTAMPTZ,
    CONSTRAINT properties_type_chk CHECK ("type" IN ('residential', 'commercial', 'land')),
    CONSTRAINT properties_purpose_chk CHECK (purpose IN ('rent', 'buy', 'sell')),
    CONSTRAINT properties_status_chk CHECK (status IN ('available', 'sold', 'pending'))
);

CREATE INDEX IF NOT EXISTS idx_properties_status ON properties (status);
CREATE INDEX IF NOT EXISTS idx_properties_type ON properties ("type");
CREATE INDEX IF NOT EXISTS idx_properties_city ON properties (city);
CREATE INDEX IF NOT EXISTS idx_properties_created ON properties ("createdAt" DESC);
