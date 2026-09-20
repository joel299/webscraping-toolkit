-- Migration: prospect_searches_rls.sql
-- Description: Idempotent RLS policies for prospect_searches and prospect_search_leads
-- Version: 20260920191000

-- 1. Enable & Force Row Level Security on prospect_searches
ALTER TABLE public.prospect_searches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.prospect_searches FORCE ROW LEVEL SECURITY;

-- 2. Enable & Force Row Level Security on prospect_search_leads
ALTER TABLE public.prospect_search_leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.prospect_search_leads FORCE ROW LEVEL SECURITY;

-- 3. Revoke direct access from public & anon
REVOKE ALL ON TABLE public.prospect_searches FROM public, anon;
REVOKE ALL ON TABLE public.prospect_search_leads FROM public, anon;

-- 4. Grant explicit operational permissions to postgres role
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.prospect_searches TO postgres;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.prospect_search_leads TO postgres;

-- 5. Create backend execution policies
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'prospect_searches' AND policyname = 'backend_prospect_searches_policy'
    ) THEN
        CREATE POLICY backend_prospect_searches_policy ON public.prospect_searches
            FOR ALL
            TO postgres
            USING (true)
            WITH CHECK (true);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'prospect_search_leads' AND policyname = 'backend_prospect_search_leads_policy'
    ) THEN
        CREATE POLICY backend_prospect_search_leads_policy ON public.prospect_search_leads
            FOR ALL
            TO postgres
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;
