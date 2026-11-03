# Proofline

Proofline is a React/TypeScript frontend paired with the FastAPI backend and PostgreSQL/Supabase migrations in this project. The browser authenticates through Supabase Auth; FastAPI authorizes workspace data using the Supabase access token. The Supabase service role key and database credentials stay on the server.

## Configure local development

1. The configured Supabase project reference was confirmed by the user as disposable, and the running backend reports database readiness. Its migration ledger lists only `0001_init.sql` and `0002_rls_supabase.sql`. Migration 0003's tables, indexes, triggers, and policies exist but its ledger entry is missing; verify its column definitions and constraints before reconciling it. No database or private Storage backup is verified. Do not apply SQL migrations in `supabase/` (or run `backend/scripts/migrate.sh --supabase`) until backups are verified and migration 0003 is reconciled. See [DEVELOPMENT_BACKUP.md](DEVELOPMENT_BACKUP.md).
2. In Supabase Auth, enable email confirmations and the Google provider. Configure Google OAuth credentials in Supabase, and allow your local frontend origin (`http://127.0.0.1:5173`) in Supabase's redirect URL settings. Google’s authorized redirect URI must be the callback URL shown in the Supabase provider settings.
3. Copy `.env.example` to the project root as `.env`. Fill in `DATABASE_URL`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` for FastAPI. Keep secrets out of Vite variables. For the frontend, copy `.env.example` to `.env.local` and set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (the public anon/publishable key); leave `VITE_API_BASE` blank when using the local Vite proxy.
4. From `backend/`, create a virtual environment, install `requirements.txt`, and run `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`. The backend reads the project-root `.env` file as well as process environment variables.
5. From the project root, run `npm install` and `npm run dev`. Vite serves the frontend on `http://127.0.0.1:5173` and proxies `/api` requests to FastAPI at port 8000.

`AUTH_MODE=supabase` is required for verified email/password and Google sign-in. Supabase handles signup confirmation, resend, OAuth, session refresh, and callback return. The FastAPI `/api/auth/signup` and `/api/auth/login` endpoints are available only in `AUTH_MODE=local` and do not provide email verification or Google OAuth.

## Current frontend/backend wiring

The UI uses the implemented FastAPI routes under `/api`: workspaces, user-created brand profiles, members, registered reference sources, versioned facts/rules, multipart text/file/URL submissions, review runs, findings, decisions, impact records, and audit history. Brand-specific records are scoped to the active profile. New facts and rules are drafts; backend owner checks control approval. Finding and decision permissions are enforced by the backend. Changing a fact/rule does not resolve impact records; content must be reviewed again and a human decision recorded. Settings shows provider/runtime configuration without exposing credential values; provider probes remain explicit because they can make external requests.

No LLM or search credentials are included. The deterministic review can run without them; semantic/search stages report unavailable until configured. The supplied backend README documents additional extraction and deployment limitations.

Evidence-file keyword overlap is treated only as partial evidence that needs human review. It cannot mark a claim supported or contradicted on its own. Search-based claim classifications require an exact retrieved passage and a configured LLM; missing providers remain unavailable. See [feature verification matrix](FEATURE_VERIFICATION_MATRIX.md) for verified scope and blockers.

## Visual review configuration

Proofline can compare approved raster logos with separate embedded raster images in PDF and PPTX submissions. Similarity, image rotation/mirroring, and aspect-ratio differences produce review candidates with page/slide coordinates; they do not establish identity and never authorize approval automatically. Palette tolerance is configurable with `PROOFLINE_VISUAL_DELTA_E_THRESHOLD` and `PROOFLINE_VISUAL_COVERAGE_THRESHOLD`. Typography and margin checks can be enabled with `PROOFLINE_APPROVED_FONT_FAMILIES`, `PROOFLINE_FONT_MIN_SIZE_PT`, `PROOFLINE_FONT_MAX_SIZE_PT`, and `PROOFLINE_LAYOUT_MIN_MARGIN_INCHES`. These are server-side settings. Missing settings leave the corresponding check explicitly unavailable. See `.env.example` for defaults.

Each review stores an immutable automated governance result with a bounded risk score, policy version, and reason factors. Palette screening covers uploaded images and up to ten rendered PDF pages; embedded raster logo candidates in PDFs and PowerPoints are compared with approved references; DOCX/PDF/PPTX font and PDF/PPTX margin checks run when their server-side rules are configured. These remain human-review checks: page-composite/vector logos, full-slide rendering, semantic layout intent, and proof provenance are not established. Incomplete mandatory stages keep submissions on hold. High-severity approved brand-rule violations are rejected. Apply migrations `0001`–`0009` only after confirming the target project and verifying database and Storage backups; for an existing project, apply only migrations not in its ledger. The connected disposable project has not had its database or Storage backups verified, and migration 0003 requires object-by-object reconciliation because its evidence table exists without a ledger record. Run the scheduled monitor separately with `python -m app.services.monitor_worker --poll-seconds 30` from `backend/` after the schema and backups are verified.
Governance weights and the recorded policy version can be configured server-side with `PROOFLINE_GOVERNANCE_POLICY_JSON` and `PROOFLINE_GOVERNANCE_POLICY_VERSION`; invalid policy configuration fails closed. See `BACKEND_README.md` for the schema and allowed keys.

## Useful checks

- `npm run typecheck`
- `npm run lint`
- `npm test`
- `npm run build`
- Backend unit tests: `python -m unittest discover -s tests -t .` from `backend/` (database-backed tests require both `PROOFLINE_TEST_PSQL` and explicit disposable-database acknowledgement; they truncate test tables and must never target a live database).


### Supabase database connection on Windows/IPv4 networks

The direct connection host (db.<project-ref>.supabase.co:5432) is IPv6-only by default. If the backend reports a database hostname resolution or connection failure, open **Supabase Dashboard → Connect**, copy the **Session pooler** connection string, and use it for DATABASE_URL in the project-root .env. Use the exact pooler host and port shown by Supabase; the shared session pooler is IPv4-compatible. Keep the password encoded as supplied and do not use a transaction-mode URL for this persistent FastAPI connection. Restart FastAPI after changing the variable. See [Supabase database connection options](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Product Intelligence

The Product Research workspace stores user-confirmed product identities, queues category-focused searches through the configured backend search provider, retrieves public pages through the SSRF-safe fetcher, and records query/source relationships, access outcomes, duplicate detection, 24-hour page reuse, and coverage counts. Coverage distinguishes searches attempted, results found, accessible pages, product-matched pages, and source-bound observations. A source is used as product-specific evidence only when its inspected text matches the provided model identifier, or the product name when no model is supplied; an official domain alone is insufficient. When an LLM is configured, the profile stores only exact-quote-validated observations linked to inspected pages. These observations are source-bound, not independently verified specifications. Source assessments now persist explainable rule-based signals for authority candidates, relevance, independence, freshness, directness, methodology indicators, disclosure phrases, and duplicate content. Unknown signals stay unknown; assessments do not certify sources or verify claims. Product research is required by the approval gate. Apply migrations `0004`–`0009` before using these routes. Start the product worker separately with `python -m app.services.product_research_worker --poll-seconds 20` from `backend/`.

Set `SEARCH_PROVIDER=tavily` with `TAVILY_API_KEY`, or `SEARCH_PROVIDER=brave` with `BRAVE_API_KEY`, in the server-side root `.env` to enable product discovery and live claim searches. `LLM_API_KEY` and `LLM_MODEL` enable source-bound profile extraction, semantic claim discovery, and source-stance classification; without them, heuristic claim discovery remains available, the product profile stays inconclusive, and retrieved sources require human review. `MAX_CLAIMS_PER_REVIEW` sets the per-review claim lookup limit (default 50, hard cap 200) to bound provider usage; any truncation is reported in the review stage. The research queue limits each workspace to 20 runs per day and five concurrent jobs.

Submission details include a PDF report export assembled from persisted records. Empty or incomplete sections are called out rather than filled with inferred results. The report is a snapshot of Proofline records, not an independent verification certificate.

### Round 3 judge demo

1. Use only a verified disposable Supabase project. Back it up, confirm its migration history, and apply the required unapplied migrations `0001`–`0009` (a new project starts at `0001`; never blindly reapply them to an existing project). Configure `.env`/`.env.local`, and start FastAPI and Vite using the commands above. Keep credentials server-side.
2. In Product research, create a product with a distinctive exact model number and official website, confirm the identity, then queue research. In a second terminal run `cd backend` and `python -m app.services.product_research_worker --poll-seconds 20`.
3. Refresh the workspace and show the query records, discovered pages, access/extraction outcomes, identifier matching, source links, source assessment signals, cached-page status and actual coverage counts. Explain that the profile does not claim verified specs or internet-wide coverage.
4. Create a submission for the same brand profile, include a factual numeric claim, attach supporting proof, link the exact product and run review. Show the Product Intelligence and verification stages, claim-to-source comparison, exact retained passage and search provenance.
5. Show the automated decision rationale. Missing research, unreadable evidence, unclassified claims, conflicting claims and contradictions remain on hold. Rule-based source signals support reviewer triage; they do not certify reliability or automatically approve marketing.
