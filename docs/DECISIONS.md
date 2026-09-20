# Architecture Decision Records (ADRs) — GRU-88

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

## ADR-005: Elimination of Runtime DDL
- **Status**: Accepted
- **Context**: Executing `CREATE TABLE` / `ALTER TABLE` inside application runtime creates permission bloat and migration drift.
- **Decision**: Remove all DDL from application runtime (`shadow/writer.go`). Schema creation is governed exclusively by versioned migration files in `supabase/migrations/`.

## ADR-006: Single Canonical Persistence Table
- **Status**: Accepted
- **Context**: Dual-writing to `public.leads` had no active consumers and suppressed error handling.
- **Decision**: Eliminate dual-write logic. Persist exclusively to `public.prospect_leads_google`.

## ADR-007: Non-Destructive Enrichment Protection
- **Status**: Accepted
- **Context**: Re-scraping places with partial data could overwrite existing enriched data with empty strings.
- **Decision**: Implement non-destructive UPSERT logic preserving existing non-empty attributes whenever newly scraped data is empty.

## ADR-008: Search-to-Lead Provenance before Database-First Read Path (GRU-88 Gate 1)
- **Status**: Accepted
- **Context**: Before serving lead search results from the database (database-first read path, cache, Redis, freshness), the system must explicitly know which leads belong to which search request and which search created a lead.
- **Decision**: Implement provenance tables `public.prospect_searches` and `public.prospect_search_leads` linking `search_id` to `place_id` incrementally during scraping. Database-first read path, Redis, cache-first, and freshness are postponed until Gate 1 is validated.

