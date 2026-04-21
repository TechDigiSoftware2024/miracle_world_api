-- Add pro-rata metadata to payment schedule lines. Run once on existing DBs.

ALTER TABLE payment_schedules
    ADD COLUMN IF NOT EXISTS "lineType" TEXT NOT NULL DEFAULT 'full';

ALTER TABLE payment_schedules
    ADD COLUMN IF NOT EXISTS "isProrata" BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE payment_schedules
    ADD COLUMN IF NOT EXISTS "daysCount" INT;

ALTER TABLE payment_schedules
    ADD COLUMN IF NOT EXISTS "perDayAmount" NUMERIC(10, 2);

ALTER TABLE payment_schedules DROP CONSTRAINT IF EXISTS payment_schedules_line_type_chk;

ALTER TABLE payment_schedules
    ADD CONSTRAINT payment_schedules_line_type_chk CHECK (
        "lineType" IN ('full', 'prorata', 'adjustment')
    );
