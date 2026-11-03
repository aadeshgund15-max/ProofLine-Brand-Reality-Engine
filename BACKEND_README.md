# Proofline — backend and local development (Round 3 work in progress)

Brand-governance API: approved brand facts and rules with immutable versions, content review with
evidence-linked findings, human decisions, an audit trail, and the **Brand Time Machine** (changing
an approved fact/rule flags only the content that recorded a dependency on it).

The repository includes a React/Vite workspace and a FastAPI/PostgreSQL backend. Round 3 functionality
is still in progress; see the verification status and limitations below before presenting it as complete.

## What was verified, and how

| Area | Status |
|---|---|
| Backend unit tests | **146 passed; 3 skipped (149 total)** in the latest local run (two database-backed test groups require a reachable disposable database; OCR integration needs the Tesseract executable) |
| Frontend typecheck, lint, tests, production build | **Passed locally; 7 frontend tests** |
| Migration 0003 plain-Postgres compatibility | Supabase-only RLS setup is capability-guarded; **not executed against a database in this environment** |
| SQL integration, migrations 0001–0009, Supabase RLS, workspace isolation against a real database | **Not verified**; the running backend now reports database readiness. The ledger lists only 0001 and 0002, while `submission_evidence` exists without a 0003 ledger entry. Later route dependencies are missing, and backups are not verified |
| Live Tavily/Brave/LLM connectivity and end-to-end product research | **Not verified**; provider configuration is missing |
| Dependency vulnerability audit | **Blocked**; npm audit could not reach registry.npmjs.org in this environment; pip-audit is unavailable |

Caveats you should know about:
1. Database-backed tests truncate test tables and must only use a separately created disposable database. No database-writing test was run here.
2. Image OCR requires the system Tesseract executable; this environment does not have it, so the OCR-specific test is skipped and uploaded images report extraction failure when OCR cannot run.
3. No search or LLM provider was called live. Provider adapters are present, but current environment variables do not configure them.
4. No Round 3 migrations were applied and nothing was deployed or load-tested.
5. [DEVELOPMENT_BACKUP.md](DEVELOPMENT_BACKUP.md) documents a development backup and isolated restore-check procedure for PostgreSQL and private Supabase Storage. The required export/restore tools were unavailable here, so no backup was created or restore verified.
6. The report-renderer regression test checks product research coverage, source-triage caveats, reviewer decisions, and revision/audit history. A PDF report from live database records has not been tested.
7. Evidence-file keyword overlap is recorded only as `partially_supported` and requires human review. It is never treated as proof of truth or falsity.

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

**API**: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` (`GET /api/health` is liveness; `GET /api/health/ready` performs a read-only database readiness check). The explicit IPv4 bind matches Vite's local API proxy.

**Auth modes**
- `AUTH_MODE=supabase`: the client signs in with Supabase Auth and sends its access token as `Authorization: Bearer`. Set
  `SUPABASE_URL` (+ `SUPABASE_JWT_SECRET` for legacy HS256 projects; asymmetric keys use JWKS automatically).
- `AUTH_MODE=local`: no Supabase. `POST /api/auth/signup|login` issue tokens (scrypt-hashed passwords, `LOCAL_JWT_SECRET` ≥ 32 chars).
  Uploads go to `STORAGE_DIR` (never served statically; downloads require workspace membership).

**Tests**
```bash
python -m unittest discover -s tests -t .              # unit tests (database tests skip themselves)
# Only after independently verifying this is a disposable test database:
$env:PROOFLINE_TEST_PSQL = "host=localhost port=5432 user=proofline dbname=proofline_test"
$env:PROOFLINE_ALLOW_DESTRUCTIVE_TESTS = "YES_I_CREATED_A_DISPOSABLE_TEST_DATABASE"
python -m unittest discover -s tests -t .              # + database tests, including table truncation
```
The test harness refuses to connect unless the explicit acknowledgement is present and the configured database name contains `test`. Supply any password through a protected PostgreSQL password file, not in the connection variable or shell history. These were run with `unittest`. The files are plain `unittest` classes, so `pytest` should also collect them, but that was not run.
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
- Governance risk weights can be overridden with server-only `PROOFLINE_GOVERNANCE_POLICY_JSON`, for example
  `{"version":"policy-2026-11","weights":{"missing_user_proof":40,"contradicted_claim":55}}`. Allowed weight keys and
  ranges are validated in `app/core/governance.py`; invalid configuration fails the review rather than silently using defaults.
  The safety outcome rules remain fail-closed. Every stored automated decision records the selected policy version.
- Phase 2 adds a private owner-managed image reference library, versioned palettes, and configurable CIE76 dominant-color screening
  for image submissions and the first ten rendered pages of uploaded PDFs. Candidate color regions retain page/image coordinates.
  Approved raster logos are compared against separate raster image objects in PDF/PPTX files with a 64-bit perceptual hash; likely
  matches, aspect changes, rotation, and mirroring are sent to human review, never auto-approved. DOCX/PDF/PPTX font metadata and
  page/slide margin bounds can be checked against server-configured rules. Theme-inherited fonts, vector or page-composite logos,
  semantic layout intent, full-slide color rendering, and general logo misuse detection remain unavailable.
- Phase 3 adds workspace-scoped public URL registration, SSRF-safe text snapshots, bounded hashes of up to eight publicly
  referenced HTML image assets, change alerts, retry/backoff logs, and a background worker. Run a separate process from
  `backend/`: `python -m app.services.monitor_worker --poll-seconds 30`. A complete pair of image manifests is required before
  an asset difference is reported; failed asset fetches remain unknown. Changed current images are compared with approved raster
  logos and the candidate comparison is stored with the deterministic/optional-provider text re-review report. Removed images
  cannot be visually inspected after removal. The review remains on hold until mandatory proof and visual stages are complete;
  monitoring does not render JavaScript or decide whether changed image assets comply with brand rules.
- Product Intelligence adds a workspace-scoped product registry and a background research queue. Each run executes twelve
  category-focused queries through the configured Tavily or Brave provider, stores the query-to-source relationships, retrieves
  public pages through the SSRF-safe fetcher, detects duplicate content, and reuses successful page fetches for 24 hours. The
  profile records the user-supplied identity and source coverage; it does not synthesize verified specifications from raw pages.
  During submission review, readable pages from the latest research run are checked against each detected claim only when an
  exact model identifier or supplied official domain matched. Exact source passages and product research source IDs are saved in
  finding evidence. This is model-assisted triage, not independent proof. Domain classifications are candidates only. Product source
  records include versioned, explainable triage signals for authority candidates, independence, freshness, directness,
  methodology indicators, possible disclosures, and duplicate content. These rules do not verify source authority, certify a
  product, establish corroboration, or replace human review. Product identity must be confirmed by a user and a
  matching identifier or supplied official domain must appear in an inspected source for the research gate to complete.
  Run the worker from `backend/`: `python -m app.services.product_research_worker --poll-seconds 20`.

Search results are now followed by an SSRF-safe fetch and text extraction of each public page. Only passages verified within
that fetched text are classified as support or contradiction; a result snippet alone is stored as an access limitation and
requires human review. The source signal record is triage metadata; claim-level source reliability and corroboration remain
human-review responsibilities.

On a project where `0001`–`0003` are already applied, apply unapplied migrations `0004`–`0009` before
using these endpoints. A new disposable project starts with `0001`; inspect its platform compatibility and
migration ledger before applying the ordered sequence. The app does not apply schema changes automatically.

---

## Merged project note

This original Round 2 backend handoff described its bundled frontend scaffold as having no pages. In the Desktop project, the integrated React frontend lives in the project root and is wired to these backend routes. See the root `README.md` for the combined setup instructions.
