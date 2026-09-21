-- Migration: 20260920232000_ia_chat_histories_prospect_google.sql
-- Description: Create ia_chat_histories_prospect_google table, sequence, RLS, and grants (GRU-89)

CREATE SEQUENCE IF NOT EXISTS public.ia_chat_histories_prospect_google_id_seq;

CREATE TABLE IF NOT EXISTS public.ia_chat_histories_prospect_google (
    id INTEGER PRIMARY KEY DEFAULT nextval('public.ia_chat_histories_prospect_google_id_seq'::regclass),
    session_id VARCHAR NOT NULL,
    message JSONB NOT NULL
);

ALTER SEQUENCE public.ia_chat_histories_prospect_google_id_seq OWNED BY public.ia_chat_histories_prospect_google.id;

-- Indexes
CREATE INDEX IF NOT EXISTS ia_chat_histories_prospect_google_session_idx ON public.ia_chat_histories_prospect_google(session_id);

-- RLS & Hardening
ALTER TABLE public.ia_chat_histories_prospect_google ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ia_chat_histories_prospect_google FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ia_chat_histories_prospect_google FROM public, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ia_chat_histories_prospect_google TO postgres, service_role;
GRANT USAGE, SELECT ON SEQUENCE public.ia_chat_histories_prospect_google_id_seq TO postgres, service_role;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'ia_chat_histories_prospect_google' AND policyname = 'backend_ia_chat_histories_prospect_google_policy'
    ) THEN
        CREATE POLICY backend_ia_chat_histories_prospect_google_policy ON public.ia_chat_histories_prospect_google
            FOR ALL
            TO postgres, service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;
