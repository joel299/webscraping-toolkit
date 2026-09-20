# Architecture & System Boundaries — GRU-88

## Pipeline Overview & Provenance

```
UI (Scrape Request)
  └─► RegisterSearch (prospect_searches)
        └─► Gosom Scraper Engine
              └─► Scrapemate Result Pipeline
                    └─► shadow.Writer (ResultWriter with SearchContext)
                          ├─► ProspectLeadMapper (gmaps.Entry -> ProspectLead)
                          ├─► PhoneNormalizer (NormalizePhoneBR)
                          ├─► ProspectLeadValidator
                          ├─► UPSERT public.prospect_leads_google (Canonical Lead)
                          └─► LinkLeadToSearch (public.prospect_search_leads [search_id <-> place_id])
```

## Key Architectural Principles

1. **Search to Lead Provenance (GATE 1)**: Every search request creates a `prospect_searches` record (`id`, `external_job_id`, `query`, `location`, `requested_limit`, `status`, `started_at`, `completed_at`). Every lead saved creates a relation in `prospect_search_leads` linking `search_id` to `place_id`.
2. **Incremental Shadow Persistence**: Leads and their search provenance links are mapped, validated, and flushed in batches during scraping without waiting for the job to complete.
3. **Shadow Mode Resiliency**: Database connection errors or network timeouts log sanitized alerts without exposing DSN secrets and DO NOT interrupt scraping, HTMX UI, Leaflet map, or CSV export.
4. **Runtime DDL Elimination**: Migrations (`supabase/migrations/*.sql`) are the sole Source of Truth for database schemas. The application runtime writer only validates schema existence without executing DDL.
5. **Single Canonical Lead Table**: Persistence is concentrated exclusively on `public.prospect_leads_google` as the canonical store, with `public.prospect_search_leads` holding the provenance relationship.
6. **Non-Destructive UPSERT**: Re-scraping an existing lead updates basic information while strictly preserving existing commercial SDR fields (`lead_status`, `pipeline_stage`, etc.) and existing non-empty enrichment attributes.
7. **Isolated Parallel Execution**: GRU-84 baseline remains untouched on port `:8080`, while GRU-86 / GRU-88 operates in parallel on port `:8086`.

