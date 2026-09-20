# Architecture Decision Records (ADRs) — GRU-86

## ADR-001: Direct PostgreSQL TCP Connection over PostgREST
- **Status**: Accepted
- **Context**: Gosom scraper requires high-throughput batch flushes.
- **Decision**: Connect directly to Supabase via PostgreSQL TCP (`jackc/pgx/v5` driver) rather than HTTP PostgREST.

## ADR-002: Parallel Isolated Instance Deployment
- **Status**: Accepted
- **Context**: GRU-84 baseline must remain protected and untouched.
- **Decision**: Run GRU-84 baseline on port `:8080` and GRU-86 parallel instance on port `:8086`.

## ADR-003: Row Level Security & Server-Side Secret Management
- **Status**: Accepted
- **Context**: Direct browser access to Supabase is prohibited in Phase 1.
- **Decision**: Enable RLS, revoke `anon`/`authenticated` table grants, and read DSN server-side from `PROSPECT_DATABASE_URL_FILE`.

## ADR-004: Protection of Commercial SDR Pipeline Fields
- **Status**: Accepted
- **Context**: Commercial sales teams update lead status independently from scraping.
- **Decision**: Use `ON CONFLICT (place_id) DO UPDATE` targeting discovery fields only, leaving SDR pipeline fields untouched.
