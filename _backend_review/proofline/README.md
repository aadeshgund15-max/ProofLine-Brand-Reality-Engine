# Proofline — backend (Round 2)

Brand-governance API: approved brand facts and rules with immutable versions, content review with
evidence-linked findings, human decisions, an audit trail, and the **Brand Time Machine** (changing
an approved fact/rule flags only the content that recorded a dependency on it).

**Scope of this delivery: the backend and database only.** `frontend/` contains just a project
scaffold and a typed API client (`src/api.ts`); there are no pages. Do not treat it as a UI.

## What was verified, and how

| Area | Status |
|---|---|
| Rule/fact checks, extraction (DOCX, PDF, PPTX, image OCR, HTML), SSRF guard, impact resolution, verification logic | **Unit-tested**, 70 tests passing |
| Full SQL layer on PostgreSQL 16: migration, versioning, review persistence, dependencies, impact queue, decisions, audit, immutability triggers, workspace isolation, roles, every file format through the real route + DB, URL ingestion, provider-failure paths | **18 database-backed tests passing** (see caveat 1) |
| Supabase RLS policies (`0002`) | Tested for read isolation and denied writes against a **stand-in** `auth.uid()`/`authenticated` role — not a real Supabase project |
| HTTP layer (FastAPI routing, `Depends`, JWT verification, multipart, Supabase JWKS/Storage calls, the real socket fetch transport, Tavily/Brave/LLM HTTP calls) | **Written, not executed.** FastAPI, SQLAlchemy, psycopg and httpx could not be installed where this was built |

Caveats you should know about:
1. The database tests call the real route functions and run the real SQL against a real Postgres, but through a test-only
   `psql` adapter (`tests/pg_harness.py`) and with throwaway stubs standing in for FastAPI/SQLAlchemy. Your first run with the
   real packages may surface integration errors (dependency injection, driver parameter adaptation, transaction handling).
2. PDF tests ran on the `pypdf` fallback; the preferred PyMuPDF path is untested.
3. OCR was tested with Tesseract 5.3 on generated images only. Real posters will vary; the app reports confidence and never marks
   weak OCR as complete.
4. No LLM or search provider was ever called live. Their parsing/validation is tested with fakes only.
5. Nothing has been deployed or load-tested.

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

**API**: `uvicorn app.main:app --reload --port 8000`  (health: `GET /api/health`)

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
Create the test database first and apply `0001_init.sql` to it. The database tests truncate its tables. Never point them at real data.

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
- Round 3 items (visual brand checks, continuous monitoring, multi-source risk scoring) are not implemented; the schema keeps
  source records, snapshots, hashes and dependency links so they can be added.
