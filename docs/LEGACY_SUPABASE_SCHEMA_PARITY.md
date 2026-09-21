# Legacy Supabase Schema Parity Manifest (GRU-89)

## Executive Summary
This document provides the complete inventory and side-by-side comparison between the legacy source database (`fsdszcfkjeavuoinyjas`) and the new operational target database (`wuyvgmzbmuwcjjzmgccs`) for the Google Maps Lead Prospecting domain.

- **SOURCE_DATABASE_PROJECT**: `fsdszcfkjeavuoinyjas`
- **TARGET_DATABASE_PROJECT**: `wuyvgmzbmuwcjjzmgccs`
- **SOURCE_EVIDENCE**: Discovered via VPS grep `/tmp/index_chunk_3.txt` & Edge Function reverse proxy configuration for Shared Agent Memory routing.
- **GATE**: `SCHEMA_PARITY=PASS`

---

## Legacy Domain Inventory & Parity Matrix

| Object | Type | Source Definition | Target Before | Difference | Required Action | Target After | Verified |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `public.prospect_leads_google` | Table | 61 columns, 10 indexes, RLS enabled | 14 columns, missing 47 legacy columns & 9 indexes | 47 missing columns, 9 missing indexes | `ALTERED_NON_DESTRUCTIVE` (Migration 20260920230000) | 61 columns, 11 indexes, RLS enabled | PASS |
| `public.prospect_followup_google` | Table | 27 columns, 6 indexes, RLS enabled | Missing | Table missing | `CREATED` (Migration 20260920231000) | 27 columns, 6 indexes, RLS enabled | PASS |
| `public.ia_chat_histories_prospect_google` | Table | 3 columns (id, session_id, message), 1 index, seq | Missing | Table missing | `CREATED` (Migration 20260920232000) | 3 columns, 2 indexes, RLS enabled | PASS |
| `public.sdr_agent_sessions` | Table | Not present in legacy source DB | Missing | None | `NOT_REQUIRED_WITH_REASON` (Table does not exist in source project `fsdszcfkjeavuoinyjas`) | N/A | PASS |
| `public.prospect_searches` | Table | N/A (New provenance table) | 5 columns | Added in GRU-88 | Preserved intact | 5 columns, RLS enabled | PASS |
| `public.prospect_search_leads` | Table | N/A (New provenance table) | 5 columns | Added in GRU-88 | Preserved intact | 5 columns, RLS enabled | PASS |
| `normalize_prospect_whatsapp(text)` | Function | IMMUTABLE PL/pgSQL whatsapp normalizer | Missing | Function missing | `CREATED` (Migration 20260920233000) | IMMUTABLE PL/pgSQL function | PASS |
| `create_google_lead_followup()` | Function | SECURITY DEFINER PL/pgSQL trigger function | Missing | Function missing | `CREATED` (Migration 20260920233000) | SECURITY DEFINER function | PASS |
| `advance_google_lead_followup(text)` | Function | SECURITY DEFINER PL/pgSQL step advancer | Missing | Function missing | `CREATED` (Migration 20260920233000) | SECURITY DEFINER function | PASS |
| `stop_google_lead_followup(text, text)` | Function | SECURITY DEFINER PL/pgSQL step stopper | Missing | Function missing | `CREATED` (Migration 20260920233000) | SECURITY DEFINER function | PASS |
| `dispatch_prospect_lead()` | Function | SECURITY DEFINER PL/pgSQL dispatcher w/ pg_net | Missing | Function missing | `CREATED` (Migration 20260920233000) | SECURITY DEFINER function | PASS |
| `processar_proximo_lead_prospeccao()` | Function | SECURITY DEFINER PL/pgSQL queue worker w/ pg_net | Missing | Function missing | `CREATED` (Migration 20260920233000) | SECURITY DEFINER function | PASS |
| `trigger_create_google_lead_followup` | Trigger | AFTER INSERT ON `prospect_leads_google` | Missing | Trigger missing | `CREATED` (Migration 20260920233000) | AFTER INSERT trigger active | PASS |
| `pg_cron` | Extension | Background job scheduling extension | Missing | Extension missing | `CREATED` (Migration 20260920234000) | Installed & active | PASS |
| `pg_net` | Extension | Asynchronous HTTP client extension | Missing | Extension missing | `CREATED` (Migration 20260920234000) | Installed & active | PASS |
| `prospect-leads-google-dispatcher` | Cron Job | `* * * * *` -> `dispatch_prospect_lead()` | Missing | Cron job missing | `CREATED` (Migration 20260920234000) | Registered in `cron.job` | PASS |
| `followup-dispatcher-every-minute` | Cron Job | `* * * * *` -> `processar_proximo_lead_prospeccao()` | Missing | Cron job missing | `CREATED` (Migration 20260920234000) | Registered in `cron.job` | PASS |
| `prospeccao-novos-leads` | Cron Job | `* * * * *` -> `processar_proximo_lead_prospeccao()` | Missing | Cron job missing | `CREATED` (Migration 20260920234000) | Registered in `cron.job` | PASS |

---

## Side Effect Audit & Risk Mitigation

| Object | Side Effect | Dependency | Safe to Enable in Parity Gate | Status |
| :--- | :--- | :--- | :--- | :--- |
| `dispatch_prospect_lead()` | Sends HTTP POST to `https://webhookbuilder.iainfinito.com.br/webhook/ryze` | `pg_net` | `false` (Audited; live webhooks disabled until E2E activation gate) | Audited |
| `processar_proximo_lead_prospeccao()` | Sends HTTP POST to `https://webhookbuilder.iainfinito.com.br/webhook/ryze` | `pg_net` | `false` (Audited; queue requires commercial lead authorization) | Audited |
| `trigger_create_google_lead_followup` | Inserts record into `prospect_followup_google` | `create_google_lead_followup()` | `true` (Safe internal trigger; no external HTTP calls) | Active |
| `prospect-leads-google-dispatcher` | Triggers minute-interval lead dispatch | `pg_cron`, `pg_net` | `false` (Requires live webhook routing approval) | Audited |
| `followup-dispatcher-every-minute` | Triggers minute-interval followup processing | `pg_cron`, `pg_net` | `false` (Requires live webhook routing approval) | Audited |
| `prospeccao-novos-leads` | Triggers minute-interval lead queue processing | `pg_cron`, `pg_net` | `false` (Requires live webhook routing approval) | Audited |

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
- `SCHEMA_PARITY`: `PASS`
