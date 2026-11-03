# Proofline judge demonstration

## Important status

This is a **prepared, repeatable test plan**, not a report of a completed live investigation. The user confirmed the configured Supabase reference is disposable, but its database endpoint fails DNS resolution here, no database or Storage backup was verified, and search/LLM credentials are not configured. Do not create records in that project until connectivity and backup checks pass. Show only results actually returned by the app.

## Demonstration claim set

Use these products as user-entered test records. Do not describe the authored claim examples below as claims made by the manufacturers.

| Product | Test claim | Evidence to retrieve | Intended evidence question |
|---|---|---|---|
| Google Pixel 9 Pro | “This model receives seven years of OS and security updates, starting when it first became available on the Google Store in the US.” | [Google update policy](https://support.google.com/pixelphone/answer/4457705?hl=en-GB) | Manual review finds strong, model-matched first-party support. Confirm current wording, market, and model at runtime. |
| Google Pixel 9 | **Test-only authored claim:** “The device is waterproof at any depth for unlimited time.” | [Google Pixel 9 safety guide](https://support.google.com/pixelphone/answer/14958126?hl=en-GB) | Manual review finds a direct conflict: the source says IP68 under IEC 60529 but explicitly says the device is not waterproof, and resistance can diminish. Whether Proofline retrieves/classifies this correctly remains unverified. |
| Dyson V15 Detect | **Test-only authored claim:** “Removes 100% of airborne allergens from every room in one pass.” | [Dyson V15 Detect Pro specifications](https://www.dyson.com/commercial/vacuums/dyson-v15-detect); [Dyson V15 Detect product page](https://www.dyson.com/vacuum-cleaners/sticks/dyson-v15-stick) | Manual review finds insufficient evidence for room-level, one-pass, 100% removal. The cited filtration figure is 99.99% for particles as small as 0.3 microns; variant and test conditions matter. Do not call this contradicted solely because evidence is missing. |

These sources were manually inspected on 2026-11-01. See [Product evidence benchmark](PRODUCT_EVIDENCE_BENCHMARK.md) for scope and caveats. Accessibility through Proofline’s server-side fetcher must be checked again during the live demo. A source URL being known or reachable in a browser does not prove the application retrieved it.

## Preconditions

- Separate disposable Supabase judge-demo project reference confirmed in its dashboard.
- Database backup and private Storage backup created and integrity-checked; restore check complete on a separate disposable target.
- Migrations reviewed against the schema and migration ledger, then applied only to the isolated judge-demo project.
- `.env` points backend and workers to that project. `.env.local` points frontend Auth to the same project. No production credentials or data are present.
- `SEARCH_PROVIDER` and one provider key are configured locally. `LLM_API_KEY`, `LLM_MODEL`, and `LLM_BASE_URL` are configured for claim extraction/stance classification if that stage will be demonstrated.
- Seed one brand profile, one owner/editor user, one reviewer user, and the three test product records. Clearly label the two authored marketing statements as **test-only**.
- Start the backend and frontend with the commands in the root README. Start the product research worker from `backend/` with `python -m app.services.product_research_worker --poll-seconds 20`. Start monitoring only if that segment is included.

## 12-minute judge run

1. **Sign in (1 min):** use a demo account in the isolated project. Show the selected workspace and role.
2. **Product identity (1 min):** register each exact product model; confirm identity only after checking brand/model and market. Explain that confirmation is a user assertion, not automated identity proof.
3. **Research (2 min):** queue each investigation and wait for the research worker. Open the query and source records. Show actual counts, source access/extraction, model match, duplicate/cache state, and coverage. If a provider fails, show the error/unavailable status and do not substitute mock results.
4. **Source assessment (1 min):** show publisher, publication date when present, retrieval/access state, and authority/relevance/independence/freshness/directness signals. Explain that these are triage signals; an official source is not independent verification.
5. **Submission and evidence (2 min):** create a submission with the authored claim, upload a small text/PDF proof file marked `TEST ONLY`, link the exact product, and run review. Do not upload private or production evidence.
6. **Evidence Explorer (1 min):** inspect the finding, exact source passage, URL, product match, source signal, and any missing/contradictory evidence. Distinguish what the source says from the system’s interpretation.
7. **Visual and risk (1 min):** show palette screening only if it actually ran. For raster logo candidates, show the submitted and approved image previews with page/slide coordinates; every similarity match needs human review. DOCX/PDF/PPTX embedded font metadata and PDF/PPTX margins can be checked when their rules are configured. State the limits plainly: vector and page-composite logos, full-slide rendering, semantic layout intent, and inherited/theme typography are unsupported.
8. **Governance and human review (1 min):** show the persisted automated outcome, risk score, rationale, factors, policy version, then have the reviewer enter a reasoned decision. Do not equate the automated score with factual certainty.
9. **Report (1 min):** download the persisted submission’s PDF. Confirm product coverage, sources, findings, proof assessment, visual limitations, governance result, reviewer decision, and history appear in the document.
10. **Monitoring (1 min, optional):** register a public test page, run a check, show baseline then meaningful text or bounded HTML image change and stored re-review. Changed image assets can be compared against approved raster logos; removed assets are reported without visual comparison. No real customer URL. JavaScript-rendered changes are unsupported.

## What to say if a gate blocks the demo

- No provider configured: show `unavailable`, state that no research was performed, and stop the research claim.
- Source inaccessible or model unmatched: show the access/match limitation and leave the assessment inconclusive.
- Missing proof, product profile, or mandatory analysis stage: show the fail-closed hold. Do not manually relabel it as approved.
- Database, worker, or report error: record the actual error and mark that part of the workflow unverified.

## Startup commands

From the repository root:

```powershell
cd backend
uvicorn app.main:app --reload --port 8000
```

In a second PowerShell window from the repository root:

```powershell
npm run dev -- --host 127.0.0.1
```

In a third PowerShell window from the repository root:

```powershell
cd backend
python -m app.services.product_research_worker --poll-seconds 20
```

Only after the isolated database is verified and migrations are ready. Monitoring worker command: `python -m app.services.monitor_worker --poll-seconds 30`.
