# Proofline — backend and local development (Round 3 work in progress)

Brand-governance API: approved brand facts and rules with immutable versions, content review with
evidence-linked findings, human decisions, an audit trail, and the **Brand Time Machine** (changing
an approved fact/rule flags only the content that recorded a dependency on it).

The repository includes a React/Vite workspace and a FastAPI/PostgreSQL backend. Round 3 functionality
is still in progress; see the verification status and limitations below before presenting it as complete.

## What was verified, and how

| Area | Status |
|---|---|
| Backend unit tests | **112 passed; 3 skipped** (two database-backed tests need `PROOFLINE_TEST_PSQL`; OCR integration needs the Tesseract executable) |
| Frontend typecheck, lint, tests, production build | **Passed locally; 4 frontend unit tests** |
| Migration 0003 plain-Postgres compatibility | Supabase-only RLS setup is capability-guarded; **not executed against a database in this environment** |
| SQL integration, migrations 0001–0009, Supabase RLS, workspace isolation against a real database | **Not verified in this pass**; the configured project could not be identified as the disposable development project |
| Live Tavily/Brave/LLM connectivity and end-to-end product research | **Not verified**; provider configuration is missing |

Caveats you should know about:
1. Database-backed tests truncate test tables and must only use a separately created disposable database. No database-writing test was run here.
2. Image OCR requires the system Tesseract executable; this environment does not have it, so the OCR-specific test is skipped and uploaded images report extraction failure when OCR cannot run.
3. No search or LLM provider was called live. Provider adapters are present, but current environment variables do not configure them.
4. No Round 3 migrations were applied and nothing was deployed or load-tested.

## Run it

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env     # fill in values; export them or use your process manager
```

**Database** (Supabase or any Postgres 14+):
```bash
DATABASE_URL=postgresql://... ./scripts/migrate.sh --supabase   # Supabase: also applies RLS + private bucket
DATABASE_URL=postgresql://... ./scripts/migrate.sh              # plain Postgres: skips 0002
```

**API**: `uvicorn app.main:app --reload --port 8000` (`GET /api/health` is liveness; `GET /api/health/ready` performs a read-only database readiness check)

**Auth modes**
- `AUTH_MODE=supabase`: the client signs in with Supabase Auth and sends its access token as `Authorization: Bearer`. Set
  `SUPABASE_URL` (+ `SUPABASE_JWT_SECRET` for legacy HS256 projects; asymmetric keys use JWKS automatically).
- `AUTH_MODE=local`: no Supabase. `POST /api/auth/signup|login` issue tokens (scrypt-hashed passwords, `LOCAL_JWT_SECRET` ≥ 32 chars).
  Uploads go to `STORAGE_DIR` (never served statically; downloads require workspace membership).

**Tests**
```bash
python -m unittest discover -s tests -t .              # unit tests (database tests skip themselves)
PROOFLINE_TEST_PSQL="host=/tmp port=5432 user=postgres dbname=proofline_test" python -m unittest discover -s tests -t .   # + database tests
```
These were run with `unittest`. The files are plain `unittest` classes, so `pytest` should also collect them, but that was not run.
Create a disposable test database first and apply the plain-Postgres migrations to it with `DATABASE_URL=<test-db> ./scripts/migrate.sh` from `backend/`. The database tests truncate tables. Never point them at a real or production database.

## Security model
- Every workspace route depends on `member_of(roles)`, which checks membership in the database per request; non-members get 404.
  Roles: `owner` (all, members), `editor` (library, submissions), `reviewer` (decisions, finding status). Everyone can run reviews.
- RLS (`0002`): browsers may only `select` rows of workspaces they belong to; there are no write policies, so writes can only come
  through the API's server connection. Service-role and provider keys are server-side only.
- Versions, decisions, evidence and audit events are immutable (database triggers reject UPDATE/DELETE).
- URL ingestion: http/https only, ports 80/443, no credentials, every resolved address must be public, connection pinned to the
  validated IP, redirects re-validated each hop (max 3), size and time limits.
- Uploads: type detected from content (not extension), extension must match, size limit, processing timeout, stored privately.
- Document text is untrusted: LLM prompts delimit it and declare it data; model output is schema-validated and any quote or
  fact/rule id that cannot be verified is discarded. Logs never include document text.

## How the pipeline stays honest
- Deterministic checks use only saved approved fact/rule versions; the exact versions used are stored per run.
- No LLM configured → semantic stage `unavailable`. No search configured → verification stage `unavailable`. The run is then
  `completed_with_warnings`, never plain `completed`.
- Search results are only attached as evidence if the (configured) LLM classifies them as supporting/contradicting **and** quotes
  text that really appears in the retrieved excerpt. Without an LLM, sources are stored as `unclassified` and the claim is
  `needs_human_review`. "No evidence found" is `insufficient_evidence`, never "false".
- Empty, failed or unsupported extraction cannot be reviewed (HTTP 409). Partial extraction can, and adds an
  `extraction_limitation` finding.
- If the deterministic stage crashes, nothing partial is saved and a `failed` run is recorded.

## Brand Time Machine
`finding_dependencies` records, per review run, each fact/rule version evaluated against the content (`violation`, `matched`, or
`applicable`). Editing a fact/rule creates version n+1 and, **in the same transaction**, creates `impact_records` for submissions
whose *current* version's *latest* run used the old version. Facts only count as dependencies when the content mentions the fact's
subject terms, so unrelated content is untouched. A rule applies to all content of its types, so a rule change flags everything that
was reviewed against it. A flag is cleared only by a human decision on a run started **after** the change.

## Brand fact semantics
`subject_terms` say where a fact appears. For `money`/`date`/`number` facts, sentences containing a term are scanned and any different
value is flagged (numeric dates are read as dd/mm/yyyy). For `text` facts, differing spelling/casing of the approved wording and any
listed term (a known wrong variant) are flagged.

## Known limitations
- Matching is lexical and sentence-based; paraphrases are only caught by the optional LLM stage.
- DOCX headers/footers, PPTX speaker notes and text inside images are not extracted (reported as warnings/partial). Scanned PDFs are
  reported as empty, not OCR'd. JavaScript-rendered pages are not executed.
- Review runs synchronously inside the request (provider calls hold a database connection). Move to a job queue before heavy use.
- Rate limiting is an in-memory per-process counter on review runs only.
- Round 3 is partially implemented. The current policy records deterministic risk and automated outcomes. Incomplete mandatory
  visual or proof-provenance stages produce `on_hold`; approved high-severity rule violations produce `rejected`. Search-provider
  excerpts are never enough to produce `approved`. Full source reliability and the remaining visual checks are still required,
  so automatic approval is not reachable in the current product flow.
- Phase 2 adds a private owner-managed image reference library, versioned palettes, and CIE76 dominant-color screening for image
  submissions. Logo matching, typography, layout, PDF-page, and slide checks remain unavailable; image results therefore stay
  partial and cannot authorize approval.
- Phase 3 adds workspace-scoped public URL registration, SSRF-safe text snapshots, change alerts, retry/backoff logs, and a
  background worker. Run a separate process from `backend/`: `python -m app.services.monitor_worker --poll-seconds 30`.
  Changed pages receive a deterministic/optional-provider re-review report, which remains on hold until mandatory proof and visual
  stages are available. Monitoring covers readable HTML and plain text; it does not render JavaScript or inspect page images.
- Product Intelligence adds a workspace-scoped product registry and a background research queue. Each run executes twelve
  category-focused queries through the configured Tavily or Brave provider, stores the query-to-source relationships, retrieves
  public pages through the SSRF-safe fetcher, detects duplicate content, and reuses successful page fetches for 24 hours. The
  profile records the user-supplied identity and source coverage; it does not synthesize verified specifications from raw pages.
  During submission review, readable pages from the latest research run are checked against each detected claim only when an
  exact model identifier or supplied official domain matched. Exact source passages and product research source IDs are saved in
  finding evidence. This is model-assisted triage, not independent proof. Domain classifications are candidates only. Source
  Source records now include versioned, explainable triage signals for authority candidates, independence, freshness, directness,
  methodology indicators, possible disclosures, and duplicate content. These rules do not verify source authority, certify a
  product, establish corroboration, or replace human review. Product identity must be confirmed by a user and a
  matching identifier or supplied official domain must appear in an inspected source for the research gate to complete.
  Run the worker from `backend/`: `python -m app.services.product_research_worker --poll-seconds 20`.

Search results are now followed by an SSRF-safe fetch and text extraction of each public page. Only passages verified within
that fetched text are classified as support or contradiction; a result snippet alone is stored as an access limitation and
requires human review. The source signal record is triage metadata; claim-level source reliability and corroboration remain
human-review responsibilities.

Apply migrations `0004_automated_decisions.sql` through `0009_source_quality_assessments.sql` before
using these endpoints. The app does not apply schema changes automatically.

---

## Merged project note

This original Round 2 backend handoff described its bundled frontend scaffold as having no pages. In the Desktop project, the integrated React frontend lives in the project root and is wired to these backend routes. See the root `README.md` for the combined setup instructions.
