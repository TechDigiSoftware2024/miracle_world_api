-- Run once on existing DBs that already have investments_status_chk without Matured / old default.
-- Safe to run multiple times if you adjust DROP/ADD carefully.

ALTER TABLE investments DROP CONSTRAINT IF EXISTS investments_status_chk;

ALTER TABLE investments
    ADD CONSTRAINT investments_status_chk CHECK (
        status IN (
            'Processing',
            'Pending Approval',
            'Active',
            'Matured',
            'Completed'
        )
    );

-- Optional: align default for new rows (does not change existing rows).
ALTER TABLE investments
    ALTER COLUMN status SET DEFAULT 'Processing';
