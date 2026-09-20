-- Migration: prospect_searches_provenance.sql
-- Description: Idempotent migration for prospect_searches and prospect_search_leads provenance tables
-- Version: 20260920190000

-- 1. prospect_searches: Represents a search request submitted by a user or runner
CREATE TABLE IF NOT EXISTS public.prospect_searches (
    search_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    job_name TEXT NOT NULL,
    query TEXT,
    location TEXT,
    category TEXT,
    requested_limit INT DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'created',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for prospect_searches
CREATE INDEX IF NOT EXISTS idx_prospect_searches_job_id ON public.prospect_searches(job_id);
CREATE INDEX IF NOT EXISTS idx_prospect_searches_status ON public.prospect_searches(status);

-- 2. prospect_search_leads: Join / Provenance table linking search requests to canonical prospect leads
CREATE TABLE IF NOT EXISTS public.prospect_search_leads (
    search_id TEXT NOT NULL REFERENCES public.prospect_searches(search_id) ON DELETE CASCADE,
    place_id TEXT NOT NULL REFERENCES public.prospect_leads_google(place_id) ON DELETE CASCADE,
    result_order INT DEFAULT 0,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (search_id, place_id)
);

-- Indexes for prospect_search_leads
CREATE INDEX IF NOT EXISTS idx_prospect_search_leads_place_id ON public.prospect_search_leads(place_id);
CREATE INDEX IF NOT EXISTS idx_prospect_search_leads_search_id ON public.prospect_search_leads(search_id);
