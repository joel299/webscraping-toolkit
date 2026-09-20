# Automated & E2E Testing Suite — GRU-86

## Test Categorization & Suite Organization

### 1. Unit Tests (`shadow/writer_test.go`)
- `TestNormalizePhoneBR`: Validates phone normalization converting BR numbers to `55 + DDD + number` (digits only).
- `TestSanitizeDSN`: Verifies regex masking of passwords in DSN connection strings.
- `TestLoadDSN`: Verifies loading DSN server-side from secret files.
- `TestNewDisabledWriter`: Ensures disabled writer initialization operates without errors.
- `TestProspectLeadMapperAndValidator`: Tests mapping of `gmaps.Entry` to `ProspectLead`, place_id identity fallbacks, and validator constraint rules.

### 2. Integration Tests (`shadow/integration_test.go`)
- `TestIntegrationScalingProgression`:
  - Applies real versioned SQL migration files (`supabase/migrations/20260920153500_prospect_leads_google_persistence.sql` and `20260920161000_prospect_leads_google_rls.sql`) against a clean test PostgreSQL database.
  - Validates 1 lead -> 5 leads -> 20 leads scaling progression.
  - Verifies phone BR normalization (20/20).
  - Verifies preservation of 12 commercial SDR fields during UPSERT.
  - Verifies Non-Destructive Enrichment Protection: empty values on re-scrape do not overwrite existing website, phone, whatsapp, email, address, or CID.
  - Verifies `Unchanged` metric increment (+1) when identical lead is re-scraped without modification.
- `TestShadowFallbackMode`: Confirms application graceful operation when database connection is unreachable or offline (shadow-fail mode tolerance).

### 3. CI Pipeline Integration (GitHub Actions)
- PostgreSQL 16 service container listening on port `5439:5432`.
- `go test -v -short ./...` for fast unit tests.
- `PROSPECT_DATABASE_URL="postgres://postgres:shadowpass@127.0.0.1:5439/prospects_db?sslmode=disable" go test -v ./shadow/...` for mandatory integration testing without skips.

### 4. Acceptance Gate Metrics (Live Server Validation)
- `SEARCH_LEADS_CAPTURED`: 54
- `SEARCH_LEADS_PERSISTED`: 54
- `PERSISTENCE_MATCH`: PASS
- `COMMERCIAL_STATE_PRESERVED`: true
- `HTMX_ERRORS`: 0
- `ACCEPTANCE_TEST`: PASS
