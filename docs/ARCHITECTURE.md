# Architecture & System Boundaries — GRU-88

## Pipeline Overview & Provenance

```
UI (Scrape Request)
  └─► FindCompletedSearch (Check public.prospect_searches for cached matching completed search)
        ├─► [HIT] FetchLeadsForSearch (public.prospect_search_leads JOIN public.prospect_leads_google)
        │     └─► WriteLeadsToCSVFile -> Serve immediately from DB (<100ms) with zero visual/HTMX regression
        │
        └─► [MISS] RegisterSearch (public.prospect_searches)
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

1. **Feature Flag Scoping (`PROSPECT_READ_MODE`)**: Server-side configuration controlling DB read-path interception. Default `current` forces full execution via Gosom scraper -> shadow persistence -> provenance. Setting `database` enables DB-first cache read path.
2. **Global Leads Cache (`PROSPECT_CACHE_ENABLED`)**: Optional Redis acceleration for `GET /api/v1/leads` only. PostgreSQL remains the source of truth; Redis failures fall back to PostgreSQL, keys include pagination, TTL is 45 seconds, and populated keys are invalidated after successful persistence.
3. **Canonical Place ID Identity Linking (GATE 3)**: Lead identity resolution (place_id -> cid -> whatsapp) returns the exact `CanonicalPlaceID` created/updated in `public.prospect_leads_google`, ensuring `LinkLeadToSearch` links only valid canonical IDs.
4. **Search to Lead Provenance**: Every search request creates a `prospect_searches` record (`search_id`, `job_id`, `query`, `location`, `requested_limit`, `status`, `started_at`, `completed_at`). Every lead saved creates a relation in `prospect_search_leads` linking `search_id` to `canonical_place_id`.
5. **Incremental Shadow Persistence**: Leads and their search provenance links are mapped, validated, and flushed in batches during scraping without waiting for the job to complete.
6. **Shadow Mode Resiliency & Metric Error Tracking (GATE 4)**: Provenance link failures record sanitized log events and increment `ProvenanceFailed` without breaking scraper or UI.
7. **Runtime DDL Elimination**: Migrations (`supabase/migrations/*.sql`) are the sole Source of Truth for database schemas. The application runtime writer only validates schema existence without executing DDL.
8. **Single Canonical Lead Table**: Persistence is concentrated exclusively on `public.prospect_leads_google` as the canonical store, with `public.prospect_search_leads` holding the provenance relationship.
9. **Non-Destructive UPSERT**: Re-scraping an existing lead updates basic information while strictly preserving existing commercial SDR fields (`lead_status`, `pipeline_stage`, etc.) and existing non-empty enrichment attributes.
10. **Isolated Parallel Execution**: GRU-84 baseline remains untouched on port `:8080`, while GRU-88 operates in parallel on port `:8086`.

## Shadow Writer Lifecycle (GRU-92)

The web runner creates one `shadow.Writer` during runner construction and reuses it for database-first reads, search registration, result persistence, and status updates across jobs. `NewWriterFromEnv` is not called from individual jobs. The writer owns and closes the environment-created `pgxpool.Pool` during runner shutdown; writers created with `NewWriter(pool, ...)` borrow the caller-owned pool. `Close` is idempotent, and operations after close return `ErrWriterClosed`.
