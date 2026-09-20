# Automated & E2E Testing Suite — GRU-88

## Test Categorization & Suite Organization

### 1. Unit Tests (`shadow/writer_test.go`)
- `TestNormalizePhoneBR`: Validates phone normalization converting BR numbers to `55 + DDD + number` (digits only).
- `TestSanitizeDSN`: Verifies regex masking of passwords in DSN connection strings.
- `TestLoadDSN`: Verifies loading DSN server-side from secret files.
- `TestNewDisabledWriter`: Ensures disabled writer initialization operates without errors.
- `TestProspectLeadMapperAndValidator`: Tests mapping of `gmaps.Entry` to `ProspectLead`, place_id identity fallbacks, and validator constraint rules.

### 2. Integration Tests (`shadow/integration_test.go`)
- `TestIntegrationScalingProgression`:
  - Applies real versioned SQL migration files (`20260920153500_prospect_leads_google_persistence.sql` and `20260920161000_prospect_leads_google_rls.sql`).
  - Validates 1 lead -> 5 leads -> 20 leads scaling progression.
  - Verifies phone BR normalization (20/20).
  - Verifies preservation of 12 commercial SDR fields during UPSERT.
  - Verifies Non-Destructive Enrichment Protection.
  - Verifies `Unchanged` metric increment (+1) when identical lead is re-scraped without modification.
- `TestSearchToLeadProvenanceScenarios`:
  - Applies real migration files (`20260920190000_prospect_searches_provenance.sql` and `20260920191000_prospect_searches_rls.sql`).
  - **TEST A**: 1 search + 1 lead -> `prospect_searches=1`, `prospect_search_leads=1`, `prospect_leads_google=1`.
  - **TEST B**: 1 search + 5 leads -> 5 relations in `prospect_search_leads`.
  - **TEST C**: 1 search + 20 leads -> 20 relations in `prospect_search_leads`.
  - **TEST D**: Same search + same lead duplicate insert -> 1 relation in `prospect_search_leads`.
  - **TEST E**: Search A + Lead X, Search B + Lead X -> 1 canonical lead in `prospect_leads_google`, 2 relations in `prospect_search_leads`.
  - **TEST F**: Pre-existing lead with commercial SDR state (`lead_status="QUALIFIED_MQL"`) scraped in new Search B -> Commercial state preserved.
- `TestShadowFallbackMode`: Confirms application graceful operation when database connection is unreachable or offline (shadow-fail mode tolerance).

### 3. CI Pipeline Integration (GitHub Actions)
- PostgreSQL 16 service container listening on port `5439:5432`.
- `go test -v -short ./...` for fast unit tests.
- `PROSPECT_DATABASE_URL="postgres://postgres:shadowpass@127.0.0.1:5439/prospects_db?sslmode=disable" go test -v ./shadow/...` for mandatory integration testing.

### 4. Acceptance Gate Metrics (Search to Lead Provenance Gate 1)
- `SEARCHES_CREATED`: 1
- `SEARCH_LEAD_LINKS`: 3
- `DUPLICATE_LINKS`: 0
- `CANONICAL_LEADS`: 3
- `UI_REGRESSION`: 0
- `MAP_REGRESSION`: 0

