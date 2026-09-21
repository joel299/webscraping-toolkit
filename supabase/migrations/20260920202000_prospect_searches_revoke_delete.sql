-- Migration: 20260920202000_prospect_searches_revoke_delete.sql
-- Description: Revoke DELETE privileges on prospect_searches and prospect_search_leads for strict least privilege (GRU-88)

DO $$
BEGIN
    -- Revoke DELETE privilege on public.prospect_searches
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'prospect_searches'
    ) THEN
        REVOKE DELETE ON public.prospect_searches FROM postgres, service_role, anon, authenticated;
        GRANT SELECT, INSERT, UPDATE ON public.prospect_searches TO postgres, service_role;
    END IF;

    -- Revoke DELETE privilege on public.prospect_search_leads
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'prospect_search_leads'
    ) THEN
        REVOKE DELETE ON public.prospect_search_leads FROM postgres, service_role, anon, authenticated;
        GRANT SELECT, INSERT, UPDATE ON public.prospect_search_leads TO postgres, service_role;
    END IF;
END $$;
