# Security & Secret Management Guidelines — GRU-86

## Zero Credential Leakage Policy
- DSN connection strings containing passwords are read server-side from secret files (`/run/secrets/prospect_database_url`).
- In Docker / Container environments, secrets must be mounted as read-only volume mounts:
  `-v /caminho/secret:/run/secrets/prospect_database_url:ro`
- Logger sanitizes DSN connection strings via regex (`SanitizeDSN`) replacing passwords with `*****`.
- Secret files, raw passwords, service role keys, and real `.env` files are strictly excluded from Git via `.gitignore`.
- `.env.example` contains only non-sensitive placeholders.

## Row Level Security (RLS) & Least Privilege (GATE 11)
- RLS is enabled on `public.prospect_leads_google` (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`).
- All table grants to untrusted client roles (`anon`, `authenticated`) are explicitly revoked (`REVOKE ALL ON TABLE ... FROM anon, authenticated`).
- Backend writer permissions are restricted to least privilege:
  `GRANT SELECT, INSERT, UPDATE ON TABLE public.prospect_leads_google TO postgres, service_role;`
- Runtime DDL permissions (`CREATE TABLE`, `ALTER TABLE`, `DROP`) are not required by the application runtime writer.

## Secret Scan Verification
A secret scan is performed prior to every commit using `git diff` and regex checks for high-entropy tokens and passwords.
`SECRET_SCAN=PASS` is a mandatory prerequisite for all release gates.
