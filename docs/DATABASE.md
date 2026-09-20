# Database Schema & Migrations — GRU-88

## Schema & Tables

### `public.prospect_leads_google`
- **Primary Key**: `place_id` (TEXT)
- **Total Columns**: 37 columns
- **Indexes**:
  - Primary Key: `prospect_leads_google_pkey` (`place_id`)
  - Partial Unique WhatsApp Index: `prospect_leads_google_whatsapp_unique` (`whatsapp` WHERE `whatsapp IS NOT NULL AND whatsapp != ''`)
  - Partial Unique CID Index: `prospect_leads_google_cid_unique` (`cid` WHERE `cid IS NOT NULL AND cid != ''`)
  - Search Indexes: `idx_prospect_leads_google_whatsapp`, `idx_prospect_leads_google_cid`

### `public.prospect_searches` (NEW in GRU-88)
- **Primary Key**: `id` (UUID, DEFAULT gen_random_uuid())
- **External Job Key**: `external_job_id` (TEXT, UNIQUE, NOT NULL)
- **Columns**: `id`, `external_job_id`, `query`, `location`, `requested_limit`, `status`, `created_at`, `started_at`, `completed_at`, `updated_at`, `error`
- **Constraints**: Check constraint on `status IN ('created', 'running', 'completed', 'failed')`
- **Indexes**: `idx_prospect_searches_job_id`, `idx_prospect_searches_status`, `idx_prospect_searches_created_at`

### `public.prospect_search_leads` (NEW in GRU-88)
- **Composite Primary Key**: `(search_id, place_id)`
- **Foreign Keys**:
  - `search_id` -> `public.prospect_searches(id) ON DELETE CASCADE`
  - `place_id` -> `public.prospect_leads_google(place_id) ON DELETE CASCADE`
- **Columns**: `search_id`, `place_id`, `discovered_at`, `result_order`, `created_at`
- **Indexes**: Primary key index on `(search_id, place_id)` and lookup index `idx_prospect_search_leads_place_id`

### Commercial SDR Protected Fields (NEVER overwritten by Scraper)
The following 12 fields are protected during UPSERT via `ON CONFLICT (place_id) DO UPDATE`:
- `lead_status`, `pipeline_stage`, `followup_count`, `followup_at`, `followup_notes`, `converted`, `do_not_contact`, `processing_status`, `sdr_owner`, `commercial_history`, `appointments`, `responses`

### Non-Destructive Enrichment Protection
When a lead is re-scraped, existing non-empty values for `website`, `phone`, `whatsapp`, `emails`, `email`, `address`, `cid`, and `google_maps_link` are preserved if the newly scraped result returns empty strings.

## Migrations (Source of Truth)
1. `supabase/migrations/20260920153500_prospect_leads_google_persistence.sql`: Idempotent schema, columns, and partial unique indexes.
2. `supabase/migrations/20260920161000_prospect_leads_google_rls.sql`: Row Level Security enabled, `anon`/`authenticated` direct access revoked.
3. `supabase/migrations/20260920190000_prospect_searches_provenance.sql`: Created `public.prospect_searches` and `public.prospect_search_leads` schemas, constraints, FKs, and indexes.
4. `supabase/migrations/20260920191000_prospect_searches_rls.sql`: Row Level Security enabled on both new tables, `anon`/`authenticated` direct access revoked, least-privilege `SELECT, INSERT, UPDATE, DELETE` granted to backend roles.

## Row Level Security (RLS) & Least Privilege
- RLS Status: Enabled on all tables (`relrowsecurity = true`, `relforcerowsecurity = true`).
- Direct client access: `anon` and `authenticated` roles are **REVOKED** (`DENIED`).
- Backend writer access: Least-privilege granted to `postgres` and `service_role`. No public client access exposed via Supabase.

