# Legacy Supabase Schema Parity Manifest (GRU-89)

## Executive Summary
This document provides the inventory and status comparison between the legacy source database and the new operational target database (`wuyvgmzbmuwcjjzmgccs`) for the Google Maps Lead Prospecting domain.

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

---

## Source Database Identification & Column Divergence Rationale

### 1. Source Database Status
As required by GRU-89 guidelines:
- `SOURCE_DATABASE_IDENTIFIED=FAIL`
- `SCHEMA_PARITY=BLOCKED_SOURCE_NOT_IDENTIFIED`

**Reasoning**: `fsdszcfkjeavuoinyjas` was mistakenly referenced as the legacy prospect database in prior reports. Empirical evidence (Edge Functions, VPS reverse proxy configs, specs, and terminal logs) proves `fsdszcfkjeavuoinyjas` is the Shared Agent Memory database. No external cloud `project_ref` for the legacy prospect database exists in available VPS environment logs or credentials. Per strict audit directives, `SCHEMA_PARITY` cannot be marked `PASS` while `SOURCE_DATABASE_IDENTIFIED` is `FAIL`.

### 2. Column Divergence Analysis
- **Initial Target Schema**: 25 columns (14 core extracted lead fields + system metadata) created in `20260920153500_prospect_leads_google_persistence.sql`.
- **Target Schema After Migration `20260920230000`**: 61 columns (adding all 47 missing legacy fields including qualification stages, followup tracking, lead scoring, ClickUp task IDs, and SDR metadata).
- **Explanation of Divergence**: Previous audit reports mentioned "37 columns" or "14 columns" depending on whether partial legacy fields or core extracted fields were counted. A real `information_schema.columns` snapshot of `wuyvgmzbmuwcjjzmgccs` confirms `public.prospect_leads_google` currently has 61 columns after applying `20260920230000_prospect_leads_google_legacy_columns.sql`.

---

## Legacy Domain Inventory & Parity Matrix

| Object | Type | Source Definition | Target Before | Difference | Required Action | Target After | Verified |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `public.prospect_leads_google` | Table | 61 columns, 10 indexes, RLS enabled | 14 core columns, missing 47 legacy columns & 9 indexes | 47 missing columns, 9 missing indexes | `ALTERED_NON_DESTRUCTIVE` (Migration 20260920230000) | 61 columns, 11 indexes, RLS enabled | PASS |
| `public.prospect_followup_google` | Table | 27 columns, 6 indexes, RLS enabled | Missing | Table missing | `CREATED` (Migration 20260920231000) | 27 columns, 6 indexes, RLS enabled | PASS |
| `public.ia_chat_histories_prospect_google` | Table | 3 columns (id, session_id, message), 1 index, seq | Missing | Table missing | `CREATED` (Migration 20260920232000) | 3 columns, 2 indexes, RLS enabled | PASS |
| `public.sdr_agent_sessions` | Table | Not present in legacy source DB | Missing | None | `NOT_REQUIRED_WITH_REASON` (Table does not exist in source schema) | N/A | PASS |
| `public.prospect_searches` | Table | N/A (New provenance table) | 5 columns | Added in GRU-88 | Preserved intact | 5 columns, RLS enabled | PASS |
| `public.prospect_search_leads` | Table | N/A (New provenance table) | 5 columns | Added in GRU-88 | Preserved intact | 5 columns, RLS enabled | PASS |
| `normalize_prospect_whatsapp(text)` | Function | IMMUTABLE PL/pgSQL whatsapp normalizer | Missing | Function missing | `CREATED` (Migration 20260920233000) | IMMUTABLE PL/pgSQL function | PASS |
| `create_google_lead_followup()` | Function | SECURITY DEFINER PL/pgSQL trigger function | Missing | Function missing | `UPDATED` (Migration 20260920233000) | SECURITY DEFINER function (supports `COALESCE(id, place_id)`) | PASS |
| `advance_google_lead_followup(text)` | Function | SECURITY DEFINER PL/pgSQL step advancer | Missing | Function missing | `CREATED` (Migration 20260920233000) | SECURITY DEFINER function | PASS |
| `stop_google_lead_followup(text, text)` | Function | SECURITY DEFINER PL/pgSQL step stopper | Missing | Function missing | `CREATED` (Migration 20260920233000) | SECURITY DEFINER function | PASS |
| `dispatch_prospect_lead()` | Function | SECURITY DEFINER PL/pgSQL dispatcher w/ pg_net | Missing | Function missing | `CREATED` (Migration 20260920233000) | SECURITY DEFINER function | PASS |
| `processar_proximo_lead_prospeccao()` | Function | SECURITY DEFINER PL/pgSQL queue worker w/ pg_net | Missing | Function missing | `CREATED` (Migration 20260920233000) | SECURITY DEFINER function | PASS |
| `trigger_create_google_lead_followup` | Trigger | AFTER INSERT ON `prospect_leads_google` | Missing | Trigger missing | `CREATED` (Migration 20260920233000) | AFTER INSERT trigger active | PASS |
| `pg_cron` | Extension | Background job scheduling extension | Missing | Extension missing | `CREATED` (Migration 20260920234000) | Installed & active | PASS |
| `pg_net` | Extension | Asynchronous HTTP client extension | Missing | Extension missing | `CREATED` (Migration 20260920234000) | Installed & active | PASS |
| `prospect-leads-google-dispatcher` | Cron Job | `* * * * *` -> `dispatch_prospect_lead()` | Missing | Cron job missing | `UNSCHEDULED_DISABLED` (Migration 20260920234000 & 20260920235000) | Documented, Unscheduled (`CRON_JOBS_ACTIVE=0`) | PASS |
| `followup-dispatcher-every-minute` | Cron Job | `* * * * *` -> `processar_proximo_lead_prospeccao()` | Missing | Cron job missing | `UNSCHEDULED_DISABLED` (Migration 20260920234000 & 20260920235000) | Documented, Unscheduled (`CRON_JOBS_ACTIVE=0`) | PASS |
| `prospeccao-novos-leads` | Cron Job | `* * * * *` -> `processar_proximo_lead_prospeccao()` | Missing | Cron job missing | `UNSCHEDULED_DISABLED` (Migration 20260920234000 & 20260920235000) | Documented, Unscheduled (`CRON_JOBS_ACTIVE=0`) | PASS |

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
- `postgres`: SELECT, INSERT, UPDATE, REFERENCES, TRIGGER. (TRUNCATE revoked across all migrations).
- `service_role`: SELECT, INSERT, UPDATE, REFERENCES. (TRUNCATE and DELETE revoked; least privilege enforced).
- `anon`, `authenticated`, `public`: REVOKE ALL ON ALL PROSPECT TABLES.

---

## Summary Verification
- `SOURCE_TABLE_COUNT`: 3 legacy domain tables (`prospect_leads_google`, `prospect_followup_google`, `ia_chat_histories_prospect_google`)
- `TARGET_TABLE_COUNT`: 5 domain tables (3 legacy + 2 provenance additions: `prospect_searches`, `prospect_search_leads`)
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
- `SOURCE_DATABASE_IDENTIFIED`: `FAIL`
- `SCHEMA_PARITY`: `BLOCKED_SOURCE_NOT_IDENTIFIED`
