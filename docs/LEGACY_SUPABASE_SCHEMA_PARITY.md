# Legacy Supabase Schema Parity Manifest (GRU-89)

## Executive Summary
This document records the reconstructed target baseline and direct runtime validation for the Google Maps Lead Prospecting domain. The historical source database is not identified, so historical parity remains unverified.

- **SOURCE_DATABASE_PROJECT**: UNKNOWN (Evidence for `fsdszcfkjeavuoinyjas` refuted; `fsdszcfkjeavuoinyjas` is Shared Agent Memory)
- **TARGET_DATABASE_PROJECT**: `wuyvgmzbmuwcjjzmgccs`
- **SOURCE_EVIDENCE**: VPS & codebase audit confirmed `fsdszcfkjeavuoinyjas` hosts Shared Agent Memory / OAuth connector (`shared-agent-memory-oauth`). No remote project_ref for the legacy prospect DB was found in VPS environment logs.
- **SOURCE_DATABASE_IDENTIFIED**: FAIL
- **SCHEMA_PARITY**: BLOCKED_SOURCE_NOT_IDENTIFIED
- **CRON_ACTIVATION_ALLOWED**: false
- **CRON_JOBS_ACTIVE**: 0
- **EXTERNAL_SIDE_EFFECTS_DISABLED**: PASS
- **NEW_LEAD_INSERT_WITH_TRIGGER**: PASS
- **FOLLOWUP_CREATED**: PASS
- **FOLLOWUP_CANONICAL_ID**: PASS
- **TRANSACTION_ABORTED**: false
- **GRU89_MIGRATIONS_TESTED**: PASS
- **RECONSTRUCTED_BASELINE_STATUS**: VERIFIED (repository migrations define 84 target columns)
- **TARGET_RUNTIME_COLUMN_COUNT**: 84
- **HISTORICAL_SOURCE_PARITY**: UNVERIFIABLE
- **POSTGRES_DELETE_ACL_REVOKED**: PASS
- **POSTGRES_EFFECTIVE_DELETE**: OWNER_CAPABILITY
- **SERVICE_ROLE_DELETE_ACL_REVOKED**: PASS for provenance tables
- **SERVICE_ROLE_EFFECTIVE_DELETE**: DENIED_FOR_PROVENANCE
- **ANON_ACCESS**: DENIED
- **AUTHENTICATED_ACCESS**: DENIED

---

## Source Database Identification & Column Divergence Rationale

### 1. Source Database Status
As required by GRU-89 guidelines:
- `SOURCE_DATABASE_IDENTIFIED=FAIL`
- `SCHEMA_PARITY=BLOCKED_SOURCE_NOT_IDENTIFIED`

**Reasoning**: `fsdszcfkjeavuoinyjas` was mistakenly referenced as the legacy prospect database in prior reports. Empirical evidence (Edge Functions, VPS reverse proxy configs, specs, and terminal logs) proves `fsdszcfkjeavuoinyjas` is the Shared Agent Memory database. No external cloud `project_ref` for the legacy prospect database exists in available VPS environment logs or credentials. Per strict audit directives, `SCHEMA_PARITY` cannot be marked `PASS` while `SOURCE_DATABASE_IDENTIFIED` is `FAIL`.

### 2. Column Divergence Analysis
- **Documented previous baseline**: 61 columns. This was the state recorded by the earlier manifest and is not evidence of the historical source schema.
- **Reconstructed repository baseline**: 84 columns. The base migration defines the original operational fields and `20260920230000_prospect_leads_google_legacy_columns.sql` defines the additional versioned fields.
- **Target runtime**: a direct `information_schema.columns` query on `wuyvgmzbmuwcjjzmgccs` returned 84 columns.
- **Interpretation**: the 23 columns after the previously documented 61-column snapshot are present in the versioned target migrations, but their historical origin is not proven. They must not be described as recovered from the legacy source.
- **Source status**: `SOURCE_DATABASE_PROJECT=UNKNOWN`, `SOURCE_DATABASE_IDENTIFIED=FAIL`, `HISTORICAL_SOURCE_PARITY=UNVERIFIABLE`, `SCHEMA_PARITY=BLOCKED_SOURCE_NOT_IDENTIFIED`.

#### Runtime column inventory

`TARGET_PROSPECT_LEADS_COLUMN_COUNT=84`

`TARGET_PROSPECT_LEADS_COLUMNS=[place_id, cid, place_name, category, categories, address, street, city, state, postal_code, country, phone, whatsapp, website, emails, email, review_rating, review_count, latitude, longitude, google_maps_link, job_id, job_name, created_at, updated_at, lead_status, pipeline_stage, followup_count, followup_at, followup_notes, converted, do_not_contact, processing_status, sdr_owner, commercial_history, appointments, responses, id, total_score, reviews_count, owner_name, administrator_name, legal_name, cnpj, instagram, facebook, linkedin, source, source_category, source_city, source_state, google_maps_url, qualification_status, qualification_stage, lead_score, needs_enrichment, enrichment_complete, contact_ready, responded, followup_enabled, followup_stage, max_followups, next_followup_at, last_followup_at, last_contact_at, last_response_at, last_message, last_message_direction, last_message_id, last_response, clickup_task_id, external_id, processing_locked_at, processing_attempts, processing_error, status, followup_current, followup_completed, followup_completed_at, observed_category, v2_last_job_id, v2_worker_label, persistence_verified, persistence_verified_at]`

`COLUMNS_FROM_CURRENT_BASELINE=[all 84 runtime columns above; the repository migrations reconstruct this target baseline]`

`COLUMNS_PRESENT_OUTSIDE_PREVIOUSLY_DOCUMENTED_61_COLUMN_BASELINE=[max_followups, next_followup_at, last_followup_at, last_contact_at, last_response_at, last_message, last_message_direction, last_message_id, last_response, clickup_task_id, external_id, processing_locked_at, processing_attempts, processing_error, status, followup_current, followup_completed, followup_completed_at, observed_category, v2_last_job_id, v2_worker_label, persistence_verified, persistence_verified_at]`

`COLUMNS_PRESENT_OUTSIDE_RECONSTRUCTED_BASELINE=[]`

The 23-column list identifies the difference from the stale 61-column manifest only. It does not identify a historical source or justify historical parity.

---

## Reconstructed Target Inventory & Historical Parity Status

Because the source database is not identified, the matrix never treats the repository migrations or the target runtime as observations of that source. `Historical Evidence` is `UNKNOWN / NOT VERIFIABLE` unless an independent historical artifact is available. `Reconstructed Baseline Definition` describes only what is versioned in this repository. `Target Runtime State` describes the direct target checks already executed.

| Object | Type | Historical Evidence | Reconstructed Baseline Definition | Target Runtime State | Action | Verified |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `public.prospect_leads_google` | Table | UNKNOWN / NOT VERIFIABLE | Base persistence migration plus legacy-column migration; 84 columns defined for the reconstructed target | Present with 84 columns and RLS enabled | `ALTERED_NON_DESTRUCTIVE` (`20260920230000`) | PASS runtime / historical parity blocked |
| `public.prospect_followup_google` | Table | UNKNOWN / NOT VERIFIABLE | 27-column table definition in `20260920231000` | Present; runtime validation passed | `CREATED` (`20260920231000`) | PASS runtime / historical parity blocked |
| `public.ia_chat_histories_prospect_google` | Table | UNKNOWN / NOT VERIFIABLE | 3-column table definition in `20260920232000` | Present; runtime validation passed | `CREATED` (`20260920232000`) | PASS runtime / historical parity blocked |
| `public.sdr_agent_sessions` | Table | NOT VERIFIED | NOT REQUIRED / NOT PRESENT in the reconstructed baseline | NOT PRESENT in target runtime | No action; do not infer historical absence | NOT VERIFIED |
| `public.prospect_searches` | Table | NOT APPLICABLE: new provenance architecture | 5-column provenance table from GRU-88 migrations | Present with RLS enabled | Preserved | PASS target |
| `public.prospect_search_leads` | Table | NOT APPLICABLE: new provenance architecture | 5-column provenance table from GRU-88 migrations | Present with RLS enabled | Preserved | PASS target |
| `normalize_prospect_whatsapp(text)` | Function | UNKNOWN / NOT VERIFIABLE | IMMUTABLE PL/pgSQL definition in `20260920233000` | Present in target | `CREATED` | PASS runtime / historical parity blocked |
| `create_google_lead_followup()` | Function | UNKNOWN / NOT VERIFIABLE | SECURITY DEFINER trigger function using canonical `id/place_id` in `20260920233000` | Present; exercised by controlled trigger test | `UPDATED` | PASS runtime / historical parity blocked |
| `advance_google_lead_followup(text)` | Function | UNKNOWN / NOT VERIFIABLE | SECURITY DEFINER step-advance definition in `20260920233000` | Present in target | `CREATED` | PASS runtime / historical parity blocked |
| `stop_google_lead_followup(text, text)` | Function | UNKNOWN / NOT VERIFIABLE | SECURITY DEFINER stop definition in `20260920233000` | Present in target | `CREATED` | PASS runtime / historical parity blocked |
| `dispatch_prospect_lead()` | Function | UNKNOWN / NOT VERIFIABLE | SECURITY DEFINER dispatcher definition in `20260920233000` | Present; external dispatch not invoked | `CREATED` | PASS runtime / historical parity blocked |
| `processar_proximo_lead_prospeccao()` | Function | UNKNOWN / NOT VERIFIABLE | SECURITY DEFINER queue-worker definition in `20260920233000` | Present; external dispatch not invoked | `CREATED` | PASS runtime / historical parity blocked |
| `trigger_create_google_lead_followup` | Trigger | UNKNOWN / NOT VERIFIABLE | AFTER INSERT trigger definition in `20260920233000` | Present and passed controlled test | `CREATED` | PASS runtime / historical parity blocked |
| `pg_cron` | Extension | UNKNOWN / NOT VERIFIABLE | Extension declaration in target migrations | Present in target; no operational jobs active | `CREATED` | PASS runtime / historical parity blocked |
| `pg_net` | Extension | UNKNOWN / NOT VERIFIABLE | Extension declaration in target migrations | Present in target; no external request invoked | `CREATED` | PASS runtime / historical parity blocked |
| `prospect-leads-google-dispatcher` | Cron Job | UNKNOWN / NOT VERIFIABLE | Future job definition documented by migrations; activation prohibited | Absent/inactive in `cron.job` | `UNSCHEDULED_DISABLED` (`20260920235000`) | PASS target / historical parity blocked |
| `followup-dispatcher-every-minute` | Cron Job | UNKNOWN / NOT VERIFIABLE | Future job definition documented by migrations; activation prohibited | Absent/inactive in `cron.job` | `UNSCHEDULED_DISABLED` (`20260920235000`) | PASS target / historical parity blocked |
| `prospeccao-novos-leads` | Cron Job | UNKNOWN / NOT VERIFIABLE | Future job definition documented by migrations; activation prohibited | Absent/inactive in `cron.job` | `UNSCHEDULED_DISABLED` (`20260920235000`) | PASS target / historical parity blocked |

---

## Side Effect Audit & Risk Mitigation

| Object | Side Effect | Dependency | Safe to Enable in Parity Gate | Status |
| :--- | :--- | :--- | :--- | :--- |
| `dispatch_prospect_lead()` | Sends HTTP POST to `https://webhookbuilder.iainfinito.com.br/webhook/ryze` | `pg_net` | `false` (Audited; live webhooks disabled) | Audited |
| `processar_proximo_lead_prospeccao()` | Sends HTTP POST to `https://webhookbuilder.iainfinito.com.br/webhook/ryze` | `pg_net` | `false` (Audited; queue worker disabled) | Audited |
| `trigger_create_google_lead_followup` | Inserts record into `prospect_followup_google` | `create_google_lead_followup()` | `true` (Safe internal trigger; no external HTTP calls) | Active |
| `prospect-leads-google-dispatcher` | Triggers minute-interval lead dispatch | `pg_cron`, `pg_net` | `false` (`UNSCHEDULED` / Disabled) | Disabled |
| `followup-dispatcher-every-minute` | Triggers minute-interval followup processing | `pg_cron`, `pg_net` | `false` (`UNSCHEDULED` / Disabled) | Disabled |
| `prospeccao-novos-leads` | Triggers minute-interval lead queue processing | `pg_cron`, `pg_net` | `false` (`UNSCHEDULED` / Disabled) | Disabled |

---

## Privilege Audit (Least Privilege Hardening)
- `POSTGRES_DELETE_ACL_REVOKED=PASS` for `prospect_searches` and `prospect_search_leads` by `20260920202000_prospect_searches_revoke_delete.sql`.
- `POSTGRES_EFFECTIVE_DELETE=OWNER_CAPABILITY`: `postgres` owns the tables and has `rolbypassrls`; revoking an explicit ACL does not remove owner capability. Therefore documenting `DELETE_ACCESS_POSTGRES=DENIED` would be false.
- `SERVICE_ROLE_DELETE_ACL_REVOKED=PASS` for `prospect_searches` and `prospect_search_leads`.
- `SERVICE_ROLE_EFFECTIVE_DELETE=DENIED_FOR_PROVENANCE` after the hardening migration. Legacy tables retain their pre-existing service-role DELETE ACL and are reported separately, not silently generalized.
- `ANON_ACCESS=DENIED` and `AUTHENTICATED_ACCESS=DENIED` on the audited prospect tables.
- ACL grant/revoke state and effective owner capability are intentionally reported as separate properties.

---

## Summary Verification
- `HISTORICAL_SOURCE_TABLE_COUNT`: `UNKNOWN`
- `RECONSTRUCTED_BASELINE_TABLE_COUNT`: 3 operational tables defined by repository migrations (`prospect_leads_google`, `prospect_followup_google`, `ia_chat_histories_prospect_google`)
- `TARGET_RUNTIME_TABLE_COUNT`: 5 domain tables (3 reconstructed operational tables + 2 provenance additions: `prospect_searches`, `prospect_search_leads`)
- `MISSING_TABLES`: `[]`
- `MISSING_FUNCTIONS`: `[]`
- `MISSING_TRIGGERS`: `[]`
- `MISSING_INDEXES`: `[]`
- `MISSING_CONSTRAINTS`: `[]`
- `MISSING_POLICIES`: `[]`
- `MISSING_EXTENSIONS`: `[]`
- `MISSING_CRON_JOBS`: `[]`
- `CRON_ACTIVATION_ALLOWED`: `false`
- `CRON_JOBS_ACTIVE`: `0`
- `CRON_PROSPECT_DISPATCHER_ACTIVE`: `false`
- `CRON_FOLLOWUP_DISPATCHER_ACTIVE`: `false`
- `CRON_PROSPECCAO_NOVOS_LEADS_ACTIVE`: `false`
- `EXTERNAL_SIDE_EFFECTS_DISABLED`: `PASS`
- `RYZE_REQUESTS_FROM_CRON`: `0`
- `FOLLOWUP_AUTOMATIC_DISPATCH`: `0`
- `WEBHOOK_AUTOMATIC_CALLS`: `0`
- `TARGET_PROSPECT_LEADS_COLUMN_COUNT`: `84`
- `RECONSTRUCTED_BASELINE_STATUS`: `VERIFIED`
- `TARGET_RUNTIME_COLUMN_COUNT`: `84`
- `POSTGRES_DELETE_ACL_REVOKED`: `PASS`
- `POSTGRES_EFFECTIVE_DELETE`: `OWNER_CAPABILITY`
- `SERVICE_ROLE_DELETE_ACL_REVOKED`: `PASS`
- `SERVICE_ROLE_EFFECTIVE_DELETE`: `DENIED_FOR_PROVENANCE`
- `ANON_ACCESS`: `DENIED`
- `AUTHENTICATED_ACCESS`: `DENIED`
- `SOURCE_DATABASE_IDENTIFIED`: `FAIL`
- `HISTORICAL_SOURCE_PARITY`: `UNVERIFIABLE`
- `SCHEMA_PARITY`: `BLOCKED_SOURCE_NOT_IDENTIFIED`
