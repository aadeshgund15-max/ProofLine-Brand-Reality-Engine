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

Each review stores an immutable automated governance result with a bounded risk score, policy version, and reason factors. Image palette screening and public-page monitoring are available in partial form; logo/layout analysis and proof provenance are still unavailable, so the fail-closed policy holds submissions rather than granting automatic approval. High-severity violations of approved brand rules are rejected. Apply migrations `0004`–`0008` before using the new APIs. Run the scheduled monitor separately with `python -m app.services.monitor_worker --poll-seconds 30` from `backend/`.

## Useful checks

- `npm run typecheck`
- `npm run lint`
- `npm test`
- `npm run build`
- Backend unit tests: `python -m unittest discover -s tests -t .` from `backend/` (database-backed tests are skipped unless `PROOFLINE_TEST_PSQL` is set; do not point that at a live database).


### Supabase database connection on Windows/IPv4 networks

The direct connection host (db.<project-ref>.supabase.co:5432) is IPv6-only by default. If the backend reports a database hostname resolution or connection failure, open **Supabase Dashboard → Connect**, copy the **Session pooler** connection string, and use it for DATABASE_URL in the project-root .env. Use the exact pooler host and port shown by Supabase; the shared session pooler is IPv4-compatible. Keep the password encoded as supplied and do not use a transaction-mode URL for this persistent FastAPI connection. Restart FastAPI after changing the variable. See [Supabase database connection options](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Product Intelligence

The Product Research workspace stores user-confirmed product identities, queues category-focused searches through the configured backend search provider, retrieves public pages through the SSRF-safe fetcher, and records query/source relationships, access outcomes, duplicate detection, 24-hour page reuse, and coverage counts. A source is used as product-specific evidence only when its inspected text matches the provided model identifier, or the product name when no model is supplied; an official domain alone is insufficient. When an LLM is configured, the profile stores only exact-quote-validated observations linked to inspected pages. These observations are source-bound, not independently verified specifications. Source assessments now persist explainable rule-based signals for authority candidates, relevance, independence, freshness, directness, methodology indicators, disclosure phrases, and duplicate content. Unknown signals stay unknown; assessments do not certify sources or verify claims. Product research is required by the approval gate. Apply migrations `0004`–`0009` before using these routes. Start the product worker separately with `python -m app.services.product_research_worker --poll-seconds 20` from `backend/`.

Set `SEARCH_PROVIDER=tavily` with `TAVILY_API_KEY`, or `SEARCH_PROVIDER=brave` with `BRAVE_API_KEY`, in the server-side root `.env` to enable product discovery and live claim searches. `LLM_API_KEY` and `LLM_MODEL` enable source-bound profile extraction, semantic claim discovery, and source-stance classification; without them, heuristic claim discovery remains available, the product profile stays inconclusive, and retrieved sources require human review. `MAX_CLAIMS_PER_REVIEW` sets the per-review claim lookup limit (default 50, hard cap 200) to bound provider usage; any truncation is reported in the review stage. The research queue limits each workspace to 20 runs per day and five concurrent jobs.

Submission details include a PDF report export assembled from persisted records. Empty or incomplete sections are called out rather than filled with inferred results. The report is a snapshot of Proofline records, not an independent verification certificate.

### Round 3 judge demo

1. Apply migrations `0001`–`0009` manually to a disposable Supabase project, configure `.env`/`.env.local`, and start FastAPI and Vite using the commands above. Keep credentials server-side.
2. In Product research, create a product with a distinctive exact model number and official website, confirm the identity, then queue research. In a second terminal run `cd backend` and `python -m app.services.product_research_worker --poll-seconds 20`.
3. Refresh the workspace and show the query records, discovered pages, access/extraction outcomes, identifier matching, source links, source assessment signals, cached-page status and actual coverage counts. Explain that the profile does not claim verified specs or internet-wide coverage.
4. Create a submission for the same brand profile, include a factual numeric claim, attach supporting proof, link the exact product and run review. Show the Product Intelligence and verification stages, claim-to-source comparison, exact retained passage and search provenance.
5. Show the automated decision rationale. Missing research, unreadable evidence, unclassified claims, conflicting claims and contradictions remain on hold. Rule-based source signals support reviewer triage; they do not certify reliability or automatically approve marketing.
