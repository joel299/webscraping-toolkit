# Architecture & System Boundaries — GRU-86

## Pipeline Overview

```
Gosom Scraper Engine
  └─► Scrapemate Result Pipeline
        └─► shadow.Writer (ResultWriter)
              ├─► ProspectLeadMapper (gmaps.Entry -> ProspectLead)
              ├─► PhoneNormalizer (NormalizePhoneBR: +55 67 99999-9999 -> 5567999999999)
              ├─► ProspectLeadValidator (PlaceID & PlaceName validation)
              └─► PostgreSQL pgxpool (Direct DSN via Secret File)
                    └─► public.prospect_leads_google (Canonical Lead Prospecting Table)
```

## Key Architectural Principles

1. **Incremental Shadow Persistence**: Leads are mapped, validated, and flushed in batches (interval: 5s, batch size: 10) directly during scraping without waiting for the job to complete.
2. **Shadow Mode Resiliency**: Database connection errors or network timeouts log sanitized alerts without exposing DSN secrets and DO NOT interrupt scraping, HTMX UI, Leaflet map, or CSV export.
3. **Runtime DDL Elimination (GATE 4)**: Migrations (`supabase/migrations/*.sql`) are the sole Source of Truth for database schemas. The application runtime writer only validates schema existence (`SELECT 1 FROM public.prospect_leads_google LIMIT 0`) without executing `CREATE TABLE` or `ALTER TABLE`.
4. **Single Canonical Table (GATE 6)**: Persistence is concentrated exclusively on `public.prospect_leads_google`. Unjustified dual-writing to `public.leads` was removed to prevent data drift and silent errors.
5. **Non-Destructive UPSERT (GATE 8)**: Re-scraping an existing lead updates basic information while strictly preserving existing commercial SDR fields (`lead_status`, `pipeline_stage`, `followup_count`, etc.) and non-empty enrichment data (`website`, `phone`, `whatsapp`, `emails`, `address`, `cid`).
6. **Isolated Parallel Execution**: GRU-84 baseline remains untouched on port `:8080`, while GRU-86 operates in parallel on port `:8086`.
