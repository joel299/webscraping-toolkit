# Database Schema & Migrations — public.prospect_leads_google

## Schema & Tables

### `public.prospect_leads_google`
- **Primary Key**: `place_id` (TEXT)
- **Total Columns**: 37 columns
- **Indexes**:
  - Primary Key: `prospect_leads_google_pkey` (`place_id`)
  - Partial Unique WhatsApp Index: `prospect_leads_google_whatsapp_unique` (`whatsapp` WHERE `whatsapp IS NOT NULL AND whatsapp != ''`)
  - Partial Unique CID Index: `prospect_leads_google_cid_unique` (`cid` WHERE `cid IS NOT NULL AND cid != ''`)
  - Search Indexes: `idx_prospect_leads_google_whatsapp`, `idx_prospect_leads_google_cid`

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

### Non-Destructive Enrichment Protection (GATE 8)
When a lead is re-scraped, existing non-empty values for `website`, `phone`, `whatsapp`, `emails`, `email`, `address`, `cid`, and `google_maps_link` are preserved if the newly scraped result returns empty strings.

## Migrations (Source of Truth)
1. `supabase/migrations/20260920153500_prospect_leads_google_persistence.sql`: Idempotent schema, columns, and partial unique indexes.
2. `supabase/migrations/20260920161000_prospect_leads_google_rls.sql`: Row Level Security enabled, `anon`/`authenticated` direct access revoked, least-privilege `SELECT, INSERT, UPDATE` granted to backend writer.

## Row Level Security (RLS) & Least Privilege (GATE 11)
- RLS Status: Enabled (`relrowsecurity = true`)
- Direct client access: `anon` and `authenticated` roles are **REVOKED**.
- Backend writer access: Least-privilege (`SELECT, INSERT, UPDATE`) granted to `postgres` and `service_role`. No DDL or drop/delete capabilities.
