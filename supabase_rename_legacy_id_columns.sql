-- Run once in Supabase Dashboard > SQL Editor if the API expects participantId/partnerId
-- but your tables still use investorId / agentId (fixes PostgREST error 42703).

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'participants' AND column_name = 'investorId'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'participants' AND column_name = 'participantId'
  ) THEN
    ALTER TABLE public.participants RENAME COLUMN "investorId" TO "participantId";
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'partners' AND column_name = 'agentId'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'partners' AND column_name = 'partnerId'
  ) THEN
    ALTER TABLE public.partners RENAME COLUMN "agentId" TO "partnerId";
  END IF;
END $$;
