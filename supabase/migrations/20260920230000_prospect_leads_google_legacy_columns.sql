-- Migration: 20260920230000_prospect_leads_google_legacy_columns.sql
-- Description: Add missing legacy columns, defaults, and indexes to prospect_leads_google for full schema parity (GRU-89)

ALTER TABLE public.prospect_leads_google
    ADD COLUMN IF NOT EXISTS id TEXT,
    ADD COLUMN IF NOT EXISTS total_score NUMERIC,
    ADD COLUMN IF NOT EXISTS reviews_count INTEGER,
    ADD COLUMN IF NOT EXISTS owner_name TEXT,
    ADD COLUMN IF NOT EXISTS administrator_name TEXT,
    ADD COLUMN IF NOT EXISTS legal_name TEXT,
    ADD COLUMN IF NOT EXISTS cnpj TEXT,
    ADD COLUMN IF NOT EXISTS instagram TEXT[] DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS facebook TEXT[] DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS linkedin TEXT[] DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'google_maps',
    ADD COLUMN IF NOT EXISTS source_category TEXT,
    ADD COLUMN IF NOT EXISTS source_city TEXT,
    ADD COLUMN IF NOT EXISTS source_state TEXT,
    ADD COLUMN IF NOT EXISTS google_maps_url TEXT,
    ADD COLUMN IF NOT EXISTS qualification_status TEXT DEFAULT 'prequalified',
    ADD COLUMN IF NOT EXISTS qualification_stage TEXT DEFAULT 'prequalified_needs_enrichment',
    ADD COLUMN IF NOT EXISTS lead_score INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS needs_enrichment BOOLEAN DEFAULT true,
    ADD COLUMN IF NOT EXISTS enrichment_complete BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS contact_ready BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS responded BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS followup_enabled BOOLEAN DEFAULT true,
    ADD COLUMN IF NOT EXISTS followup_stage INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_followups INTEGER DEFAULT 5,
    ADD COLUMN IF NOT EXISTS next_followup_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_followup_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_contact_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_response_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_message TEXT,
    ADD COLUMN IF NOT EXISTS last_message_direction TEXT,
    ADD COLUMN IF NOT EXISTS last_message_id TEXT,
    ADD COLUMN IF NOT EXISTS last_response TEXT,
    ADD COLUMN IF NOT EXISTS clickup_task_id TEXT,
    ADD COLUMN IF NOT EXISTS external_id TEXT,
    ADD COLUMN IF NOT EXISTS processing_locked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_attempts INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS processing_error TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'new',
    ADD COLUMN IF NOT EXISTS followup_current INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS followup_completed BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS followup_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS observed_category TEXT,
    ADD COLUMN IF NOT EXISTS v2_last_job_id UUID,
    ADD COLUMN IF NOT EXISTS v2_worker_label TEXT,
    ADD COLUMN IF NOT EXISTS persistence_verified BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS persistence_verified_at TIMESTAMPTZ;

-- Populate id column with place_id where null
UPDATE public.prospect_leads_google SET id = place_id WHERE id IS NULL;

-- Create Indexes
CREATE UNIQUE INDEX IF NOT EXISTS prospect_leads_google_whatsapp_unique 
    ON public.prospect_leads_google (whatsapp) 
    WHERE (whatsapp IS NOT NULL AND whatsapp <> '');

CREATE INDEX IF NOT EXISTS prospect_leads_google_status_idx 
    ON public.prospect_leads_google (status);

CREATE INDEX IF NOT EXISTS prospect_leads_google_next_followup_idx 
    ON public.prospect_leads_google (next_followup_at);

CREATE INDEX IF NOT EXISTS prospect_leads_google_followup_enabled_idx 
    ON public.prospect_leads_google (followup_enabled);

CREATE INDEX IF NOT EXISTS prospect_leads_google_contact_ready_idx 
    ON public.prospect_leads_google (contact_ready);

CREATE INDEX IF NOT EXISTS prospect_leads_google_category_idx 
    ON public.prospect_leads_google (source_category);

CREATE INDEX IF NOT EXISTS prospect_leads_google_created_at_idx 
    ON public.prospect_leads_google (created_at);

CREATE INDEX IF NOT EXISTS prospect_leads_google_v2_job_idx 
    ON public.prospect_leads_google (v2_last_job_id);

CREATE INDEX IF NOT EXISTS prospect_leads_google_source_identity_idx 
    ON public.prospect_leads_google (id);
