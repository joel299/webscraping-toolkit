# Security & Secret Management Guidelines — GRU-86

## Zero Credential Leakage Policy
- Supabase credentials are read server-side from `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` environment variables injected by Compose from the ignored `.env` file.
- The service role/secret key is used only by the Go backend for HTTPS/PostgREST calls. It must never be returned to the browser or committed.
- Secret files, raw passwords, service role keys, and real `.env` files are strictly excluded from Git via `.gitignore`.
- `.env.example` contains only non-sensitive placeholders.

## Row Level Security (RLS) & Least Privilege (GATE 11)
- RLS is enabled on `public.prospect_leads_google` (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`).
- All table grants to untrusted client roles (`anon`, `authenticated`) are explicitly revoked (`REVOKE ALL ON TABLE ... FROM anon, authenticated`).
- Backend writer permissions are restricted to the Supabase `service_role` and RLS policies defined in migrations.
- Runtime DDL permissions (`CREATE TABLE`, `ALTER TABLE`, `DROP`) are not required by the application runtime writer.

## Secret Scan Verification
A secret scan is performed prior to every commit using `git diff` and regex checks for high-entropy tokens and passwords.
`SECRET_SCAN=PASS` is a mandatory prerequisite for all release gates.
