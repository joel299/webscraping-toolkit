# Automated & E2E Acceptance Testing — GRU-86

## Unit & Integration Test Suite (`shadow/`)

### Test Coverage
1. `TestIntegrationScalingProgression`: Validates 1 lead -> 5 leads -> 20 leads progression against live PostgreSQL database with 0 duplicates.
2. `TestShadowFallbackMode`: Confirms application graceful operation when database connection fails (shadow mode tolerance).
3. `TestNormalizePhoneBR`: Validates phone normalization converting BR phones to `55 + DDD + number` (digits only).
4. `TestSanitizeDSN`: Verifies regex masking of passwords in DSN connection strings.
5. `TestLoadDSN`: Verifies loading DSN server-side from secret files.

### Acceptance Gate Test Metrics
- `SEARCH_LEADS_CAPTURED`: 54
- `SEARCH_LEADS_PERSISTED`: 54
- `PERSISTENCE_MATCH`: PASS
- `COMMERCIAL_STATE_PRESERVED`: true
- `HTMX_ERRORS`: 0
- `ACCEPTANCE_TEST`: PASS
