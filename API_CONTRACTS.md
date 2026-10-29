# Proofline API integration

The frontend talks to the FastAPI service under `/api` (local Vite proxy: port 8000). Supabase Auth is used for email confirmation and Google OAuth. The browser sends its Supabase access token as a bearer token. Server-only secrets (`DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, provider keys) must never use `VITE_` names.

## Implemented backend routes used by the frontend

- Auth/session: `GET /api/me`, `GET /api/workspaces`; Supabase handles signup, resend-confirmation, password sign-in, and Google OAuth in the browser SDK.
- Workspace setup: `POST /api/workspaces`; `/api/workspaces/{w}/profiles`, `/members`, `/dashboard`.
- Library: `/api/workspaces/{w}/facts`, `/facts/{id}`, `/rules`, `/rules/{id}`, plus `PUT` for immutable new versions; `/sources` for references.
- Submissions: multipart `POST /api/workspaces/{w}/submissions` and `/submissions/{id}/versions`; `GET /submissions`, `/submissions/{id}`, `/submission-versions/{id}`.
- Evidence: multipart `POST /api/workspaces/{w}/submission-versions/{v}/evidence` for private TXT/PDF/DOCX proof files; `GET /submission-versions/{v}/evidence` returns extraction status, warnings, segments, and extracted text.
- Reviews: `POST /submission-versions/{id}/review`, `GET /review-runs/{id}`, `GET /findings/{id}`, `PATCH /findings/{id}/status`, and `POST /submission-versions/{id}/decisions`.
- Impact/audit: `GET /impacts`, `GET /impacts/{id}`, and `GET /audit`.

The API enforces authorization per workspace and role. The frontend does not persist application records locally or fabricate records after API errors.

## Auth setup

Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` in `.env.local`. Set matching `SUPABASE_URL`, database credentials, and server-only service key in the root `.env`. Enable email confirmation and Google in Supabase Auth, configure the OAuth client secret only in Supabase, and add the frontend origin to Supabase's redirect allow list. For local development, use `http://127.0.0.1:5173/` as the return URL. The Google provider's callback URI is displayed in Supabase.

## Important backend behavior

- `/api/auth/signup` and `/api/auth/login` are local-mode-only; they are not used by this Supabase frontend.
- Decisions require a successful review run for the exact current submission version. Requesting changes or rejecting requires a comment.
- Impacts resolve through a review run started after the relevant change and a human decision; there is no dismiss-impact route.
- Upload extraction can be partial, empty, unsupported, or fail. The review API refuses unreviewable versions.
- A review requires at least one successfully processed evidence file for the exact submission version. Approval requires a complete evidence assessment; a reviewer explanation is required to override contradictory or insufficient evidence.
- Without configured LLM/search providers, those review stages are unavailable; the API reports warnings rather than claiming a complete verification.
