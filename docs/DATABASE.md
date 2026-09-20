# Database Schema & Migrations — public.prospect_leads_google

## Schema & Tables

### `public.prospect_leads_google`
- **Primary Key**: `place_id` (TEXT)
- **Total Columns**: 37 columns
- **Indexes**: `idx_prospect_leads_google_whatsapp` (`whatsapp`), `idx_prospect_leads_google_cid` (`cid`)

### Commercial SDR Protected Fields (NEVER overwritten by Scraper)
The following 12 fields are protected during UPSERT via `ON CONFLICT (place_id) DO UPDATE`:
- `lead_status`
- `pipeline_stage`
- `followup_count`
- `followup_at`
- `followup_notes`
- `converted`
- `do_not_contact`
- `processing_status`
- `sdr_owner`
- `commercial_history`
- `appointments`
- `responses`

## Migrations Applied
1. `supabase/migrations/20260920153500_prospect_leads_google_persistence.sql` (Idempotent table and index creation)
2. `supabase/migrations/20260920161000_prospect_leads_google_rls.sql` (Row Level Security enabled, anon/authenticated direct access revoked)

## Row Level Security (RLS)
- `pg_class.relrowsecurity` = `true`
- Direct grants to `anon` and `authenticated` roles are **REVOKED**.
- Backend writer access is granted exclusively to `postgres` and `service_role`.
