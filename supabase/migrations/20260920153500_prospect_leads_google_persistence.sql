-- Migration: prospect_leads_google_persistence.sql
-- Description: Idempotent migration for public.prospect_leads_google and public.leads for Gosom Google Maps Scraper
-- Version: 20260920153500

-- 1. Main Table: public.prospect_leads_google
CREATE TABLE IF NOT EXISTS public.prospect_leads_google (
    place_id TEXT PRIMARY KEY,
    cid TEXT,
    place_name TEXT NOT NULL,
    category TEXT,
    categories JSONB,
    address TEXT,
    street TEXT,
    city TEXT,
    state TEXT,
    postal_code TEXT,
    country TEXT,
    phone TEXT,
    whatsapp TEXT,
    website TEXT,
    emails JSONB,
    email TEXT,
    review_rating NUMERIC(3,2),
    review_count INT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    google_maps_link TEXT,
    job_id TEXT,
    job_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Commercial SDR Fields (Preserved on UPSERT)
    lead_status TEXT DEFAULT 'new',
    pipeline_stage TEXT DEFAULT 'prospect',
    followup_count INT DEFAULT 0,
    followup_at TIMESTAMPTZ,
    followup_notes TEXT,
    converted BOOLEAN DEFAULT FALSE,
    do_not_contact BOOLEAN DEFAULT FALSE,
    processing_status TEXT DEFAULT 'pending',
    sdr_owner TEXT,
    commercial_history JSONB DEFAULT '[]'::jsonb,
    appointments JSONB DEFAULT '[]'::jsonb,
    responses JSONB DEFAULT '[]'::jsonb
);

-- Ensure incremental columns exist if table was previously created with older schema
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS cid TEXT;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS categories JSONB;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS whatsapp TEXT;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS emails JSONB;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS job_id TEXT;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS job_name TEXT;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS lead_status TEXT DEFAULT 'new';
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS pipeline_stage TEXT DEFAULT 'prospect';
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS followup_count INT DEFAULT 0;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS followup_at TIMESTAMPTZ;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS followup_notes TEXT;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS converted BOOLEAN DEFAULT FALSE;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS do_not_contact BOOLEAN DEFAULT FALSE;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS processing_status TEXT DEFAULT 'pending';
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS sdr_owner TEXT;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS commercial_history JSONB DEFAULT '[]'::jsonb;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS appointments JSONB DEFAULT '[]'::jsonb;
ALTER TABLE public.prospect_leads_google ADD COLUMN IF NOT EXISTS responses JSONB DEFAULT '[]'::jsonb;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_prospect_leads_google_whatsapp ON public.prospect_leads_google(whatsapp);
CREATE INDEX IF NOT EXISTS idx_prospect_leads_google_cid ON public.prospect_leads_google(cid);

-- 2. Legacy Dual-Write Table: public.leads
CREATE TABLE IF NOT EXISTS public.leads (
    place_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT,
    categories JSONB,
    address TEXT,
    street TEXT,
    city TEXT,
    state TEXT,
    postal_code TEXT,
    country TEXT,
    phone TEXT,
    phone_normalized TEXT,
    website TEXT,
    emails JSONB,
    email TEXT,
    review_rating NUMERIC(3,2),
    review_count INT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    google_maps_link TEXT,
    job_id TEXT,
    job_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    lead_status TEXT DEFAULT 'new',
    pipeline_stage TEXT DEFAULT 'prospect',
    followup_count INT DEFAULT 0,
    followup_at TIMESTAMPTZ,
    followup_notes TEXT,
    converted BOOLEAN DEFAULT FALSE,
    do_not_contact BOOLEAN DEFAULT FALSE,
    processing_status TEXT DEFAULT 'pending',
    sdr_owner TEXT,
    commercial_history JSONB DEFAULT '[]'::jsonb,
    appointments JSONB DEFAULT '[]'::jsonb,
    responses JSONB DEFAULT '[]'::jsonb
);
