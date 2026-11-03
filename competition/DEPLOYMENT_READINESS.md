# Deployment readiness

**Status: BLOCKED. No production configuration was changed and no deployment was made.**

## Development / judge-demo configuration

- Use a separately identified disposable Supabase project; record its non-secret project reference.
- Keep `DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, provider keys, and any JWT signing secret in the backend process environment or hosting secret store only.
- Frontend build may contain only `VITE_SUPABASE_URL`, the public anon/publishable key, and the API base URL. Never put service-role or provider keys in `VITE_*` variables.
- Scope `CORS_ORIGINS` to the local development origin or exact judge-demo origin.
- Use a private `submissions` bucket. Keep local storage outside any static web root.
- Keep research and monitoring workers as separate processes with isolated database credentials and least-required permissions.
- Test backups, restore, health/ready endpoint, authentication, RLS, API authorization, private report download, provider failure, worker retry, and cross-workspace access before a judge run.

## Production configuration review

| Control | Status | Required evidence |
|---|---|---|
| Production Supabase project and region | NOT VERIFIED | Owner confirms exact production project and access controls. |
| Production domain and TLS | NOT CONFIGURED | DNS, TLS, frontend origin, and OAuth callback verified. |
| CORS allowlist | NOT VERIFIED | Exact production origin only; no wildcard. |
| Database migrations and RLS | NOT VERIFIED | Reviewed migration plan, staging restore, schema/RLS inspection, and rollback/restore plan. |
| Auth provider settings | NOT VERIFIED | Email confirmation, password reset, OAuth credentials, allowed redirect URLs, and session expiry tested. |
| Secrets | NOT CONFIGURED | Managed secret store; rotation/revocation procedure; no secrets in frontend bundle or logs. |
| Object storage | NOT VERIFIED | Private bucket policies, object lifecycle, backup, download authorization, and retention tested. |
| Workers | NOT DEPLOYED | Dedicated runtime, concurrency, leases, retries, observability, and shutdown tested. |
| Backups and restore | NOT VERIFIED | Database and object backups plus successful isolated restore drill. |
| Health checks and monitoring | PARTIAL | `/api/health` and read-only `/api/health/ready` exist; alerting, dashboards, and incident routing are not configured. |
| Dependency/security scans | BLOCKED | Registry access required; current npm audit could not reach npm registry and pip-audit is absent. |

Production requires a separate explicit approval after a reviewable staging result. This checklist does not authorize or perform deployment.
