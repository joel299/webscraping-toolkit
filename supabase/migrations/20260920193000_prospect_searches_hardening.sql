-- Migration: prospect_searches_hardening.sql
-- Description: Revoke authenticated access, enforce least privilege (SELECT, INSERT, UPDATE), and add status CHECK constraint
-- Version: 20260920193000

-- 1. Revoke ALL permissions on public.prospect_searches and public.prospect_search_leads for public, anon, and authenticated roles
REVOKE ALL ON public.prospect_searches FROM public, anon, authenticated;
REVOKE ALL ON public.prospect_search_leads FROM public, anon, authenticated;

-- 2. Grant least-privilege (SELECT, INSERT, UPDATE) to backend service roles ONLY
GRANT SELECT, INSERT, UPDATE ON public.prospect_searches TO postgres, service_role;
GRANT SELECT, INSERT, UPDATE ON public.prospect_search_leads TO postgres, service_role;

-- 3. Add CHECK constraint for status on public.prospect_searches
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'prospect_searches_status_check'
    ) THEN
        ALTER TABLE public.prospect_searches 
        ADD CONSTRAINT prospect_searches_status_check 
        CHECK (status IN ('created', 'running', 'completed', 'failed'));
    END IF;
END $$;
