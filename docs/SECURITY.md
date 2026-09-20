# Security & Secret Management Guidelines — GRU-86

## Zero Credential Leakage Policy
- DSN connection strings containing passwords are read server-side from secret files (`/run/secrets/prospect_database_url` or `/tmp/prospect_database_url`).
- Logger sanitizes DSN connection strings via regex (`SanitizeDSN`) replacing passwords with `*****`.
- Secret files, raw passwords, service role keys, and real `.env` files are strictly excluded from Git via `.gitignore`.

## Row Level Security (RLS) & Direct Client Access
- RLS is enabled on `public.prospect_leads_google` (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`).
- All table grants to untrusted client roles (`anon`, `authenticated`) are explicitly revoked (`REVOKE ALL ON TABLE ... FROM anon, authenticated`).
- Database access is strictly confined to server-side backend queries (`postgres`/`service_role`).

## Secret Scan Verification
A secret scan is performed prior to every commit using `git diff` and regex checks for high-entropy tokens and passwords.
