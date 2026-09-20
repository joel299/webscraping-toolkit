# Architecture & System Boundaries — GRU-86

## Pipeline Overview

```
Gosom Scraper Engine
  └─► Scrapemate Result Pipeline
        └─► shadow.Writer (ResultWriter)
              ├─► NormalizePhoneBR (+55 67 99999-9999 -> 5567999999999)
              ├─► ProspectLeadValidator
              └─► PostgreSQL pgxpool (Direct TCP/5432)
                    ├─► public.prospect_leads_google (Primary)
                    └─► public.leads (Dual-Write Legacy)
```

## Key Architectural Principles
1. **Incremental Shadow Persistence**: Leads are flushed in batches (interval: 5s, batch size: 10) directly during scraping without waiting for the job to complete.
2. **Shadow Mode Resiliência**: Database connection errors or network timeouts log sanitized alerts without exposing DSN secrets and DO NOT interrupt scraping, HTMX UI, Leaflet map, or CSV export.
3. **Dual-Write Backward Compatibility**: Dual writes to both `public.prospect_leads_google` and `public.leads` table to support legacy integrations.
4. **Isolated Parallel Execution**: GRU-84 baseline remains intact on port `:8080`, while GRU-86 operates in parallel on port `:8086`.
