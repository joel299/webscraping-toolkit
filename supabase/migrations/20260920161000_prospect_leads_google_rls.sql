-- Migration: prospect_leads_google_rls.sql
-- Description: Enable Row Level Security (RLS) on public.prospect_leads_google and revoke direct access from anon/authenticated roles.
-- Version: 20260920161000

-- 1. Enable RLS on public.prospect_leads_google and public.leads
ALTER TABLE public.prospect_leads_google ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;

-- 2. Revoke direct table grants from untrusted client roles (anon, authenticated)
REVOKE ALL ON TABLE public.prospect_leads_google FROM anon, authenticated;
REVOKE ALL ON TABLE public.leads FROM anon, authenticated;

-- 3. Grant full privileges to backend writer roles (postgres, service_role)
GRANT ALL ON TABLE public.prospect_leads_google TO postgres, service_role;
GRANT ALL ON TABLE public.leads TO postgres, service_role;
