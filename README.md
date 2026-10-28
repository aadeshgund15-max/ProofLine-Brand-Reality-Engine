# Proofline

Proofline is a React/TypeScript frontend paired with the FastAPI backend and PostgreSQL/Supabase migrations in this project. The browser authenticates through Supabase Auth; FastAPI authorizes workspace data using the Supabase access token. The Supabase service role key and database credentials stay on the server.

## Configure local development

1. Create a Supabase project and apply the SQL migrations in `supabase/` (or use `backend/scripts/migrate.sh --supabase` with the backend setup described in `BACKEND_README.md`). Set the project database connection string.
2. In Supabase Auth, enable email confirmations and the Google provider. Configure Google OAuth credentials in Supabase, and allow your local frontend origin (`http://127.0.0.1:5173`) in Supabase's redirect URL settings. Google’s authorized redirect URI must be the callback URL shown in the Supabase provider settings.
3. Copy `.env.example` to the project root as `.env`. Fill in `DATABASE_URL`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` for FastAPI. Keep secrets out of Vite variables. For the frontend, copy `.env.example` to `.env.local` and set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (the public anon/publishable key); leave `VITE_API_BASE` blank when using the local Vite proxy.
4. From `backend/`, create a virtual environment, install `requirements.txt`, and run `uvicorn app.main:app --reload --port 8000`. The backend reads the project-root `.env` file as well as process environment variables.
5. From the project root, run `npm install` and `npm run dev`. Vite serves the frontend on `http://127.0.0.1:5173` and proxies `/api` requests to FastAPI at port 8000.

`AUTH_MODE=supabase` is required for verified email/password and Google sign-in. Supabase handles signup confirmation, resend, OAuth, session refresh, and callback return. The FastAPI `/api/auth/signup` and `/api/auth/login` endpoints are available only in `AUTH_MODE=local` and do not provide email verification or Google OAuth.

## Current frontend/backend wiring

The UI uses the implemented FastAPI routes under `/api`: workspaces/profiles/members, facts and rules with immutable versions, multipart text/file/URL submissions, review runs, findings, decisions, impact records, and audit history. Finding and decision permissions are enforced by the backend. Changing a fact/rule does not resolve impact records; content must be reviewed again and a human decision recorded.

No LLM or search credentials are included. The deterministic review can run without them; semantic/search stages report unavailable until configured. The supplied backend README documents additional extraction and deployment limitations.

## Useful checks

- `npm run typecheck`
- `npm run lint`
- `npm test`
- `npm run build`
- Backend unit tests: `python -m unittest discover -s tests -t .` from `backend/` (database-backed tests are skipped unless `PROOFLINE_TEST_PSQL` is set; do not point that at a live database).


### Supabase database connection on Windows/IPv4 networks

The direct connection host (db.<project-ref>.supabase.co:5432) is IPv6-only by default. If the backend reports a database hostname resolution or connection failure, open **Supabase Dashboard → Connect**, copy the **Session pooler** connection string, and use it for DATABASE_URL in the project-root .env. Use the exact pooler host and port shown by Supabase; the shared session pooler is IPv4-compatible. Keep the password encoded as supplied and do not use a transaction-mode URL for this persistent FastAPI connection. Restart FastAPI after changing the variable. See [Supabase database connection options](https://supabase.com/docs/guides/database/connecting-to-postgres).
