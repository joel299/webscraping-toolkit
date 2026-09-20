-- Migration: prospect_leads_google_rls.sql
-- Description: Enable Row Level Security (RLS) on public.prospect_leads_google and revoke direct access from anon/authenticated roles.
-- Version: 20260920161000

-- Ensure roles exist if running on vanilla PostgreSQL (e.g. CI container)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role;
    END IF;
END $$;

-- 1. Enable RLS on public.prospect_leads_google
ALTER TABLE public.prospect_leads_google ENABLE ROW LEVEL SECURITY;

-- 2. Revoke direct table grants from untrusted client roles (anon, authenticated)
REVOKE ALL ON TABLE public.prospect_leads_google FROM anon, authenticated;

-- 3. Grant least-privilege (SELECT, INSERT, UPDATE) to backend writer roles (postgres, service_role) - GATE 11
GRANT SELECT, INSERT, UPDATE ON TABLE public.prospect_leads_google TO postgres, service_role;

