-- Migration: 20260920231000_prospect_followup_google.sql
-- Description: Create prospect_followup_google table, indexes, RLS, and grants (GRU-89)

CREATE TABLE IF NOT EXISTS public.prospect_followup_google (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_followup INTEGER NOT NULL DEFAULT 1,
    followup_1_at TIMESTAMPTZ,
    followup_2_at TIMESTAMPTZ,
    followup_3_at TIMESTAMPTZ,
    followup_4_at TIMESTAMPTZ,
    followup_5_at TIMESTAMPTZ,
    followup_6_at TIMESTAMPTZ,
    followup_7_at TIMESTAMPTZ,
    followup_1_status TEXT DEFAULT 'pending',
    followup_2_status TEXT DEFAULT 'pending',
    followup_3_status TEXT DEFAULT 'pending',
    followup_4_status TEXT DEFAULT 'pending',
    followup_5_status TEXT DEFAULT 'pending',
    followup_6_status TEXT DEFAULT 'pending',
    followup_7_status TEXT DEFAULT 'pending',
    next_followup_at TIMESTAMPTZ,
    last_followup_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    paused_at TIMESTAMPTZ,
    error_message TEXT,
    processing_locked_at TIMESTAMPTZ,
    processing_attempts INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS prospect_followup_google_status_idx ON public.prospect_followup_google(status);
CREATE INDEX IF NOT EXISTS prospect_followup_google_next_idx ON public.prospect_followup_google(next_followup_at);
CREATE INDEX IF NOT EXISTS prospect_followup_google_processing_idx ON public.prospect_followup_google(status, next_followup_at);
CREATE UNIQUE INDEX IF NOT EXISTS prospect_followup_google_lead_unique ON public.prospect_followup_google(lead_id);
CREATE INDEX IF NOT EXISTS prospect_followup_google_lead_idx ON public.prospect_followup_google(lead_id);

-- RLS & Hardening
ALTER TABLE public.prospect_followup_google ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.prospect_followup_google FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.prospect_followup_google FROM public, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.prospect_followup_google TO postgres, service_role;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'prospect_followup_google' AND policyname = 'backend_prospect_followup_google_policy'
    ) THEN
        CREATE POLICY backend_prospect_followup_google_policy ON public.prospect_followup_google
            FOR ALL
            TO postgres, service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;
