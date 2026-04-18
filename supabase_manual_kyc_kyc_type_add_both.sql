-- If `manual_kyc` already exists with only PAN/AADHAAR, run this once in Supabase SQL Editor.

ALTER TABLE manual_kyc DROP CONSTRAINT IF EXISTS manual_kyc_type_chk;
ALTER TABLE manual_kyc
    ADD CONSTRAINT manual_kyc_type_chk CHECK ("kycType" IN ('PAN', 'AADHAAR', 'Both'));
