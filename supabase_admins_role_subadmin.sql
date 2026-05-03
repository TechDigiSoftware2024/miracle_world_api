-- Add admin role fields for sub-admin access control.
-- Run this in Supabase SQL Editor once.

ALTER TABLE admins
ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'super_admin';

ALTER TABLE admins
ADD COLUMN IF NOT EXISTS "createdByAdminId" TEXT REFERENCES admins ("adminId") ON DELETE SET NULL;

UPDATE admins
SET role = 'super_admin'
WHERE role IS NULL OR role = '';

UPDATE admins
SET access_sections = 'all'
WHERE access_sections IS NULL OR btrim(access_sections) = '';

CREATE INDEX IF NOT EXISTS idx_admins_role ON admins (role);
