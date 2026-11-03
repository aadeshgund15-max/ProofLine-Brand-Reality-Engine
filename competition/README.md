# Proofline competition package

This package is prepared for a Round 3 judging presentation. It is intentionally explicit about what the repository demonstrates locally and what still needs a live isolated environment.

- [Judge presentation](Proofline_Round3_Judges.pptx) — 15 editable slides covering the problem, product approach, architecture, workflow, evidence example, governance, security, limitations, readiness, and demo steps.
- [Competition readiness report](COMPETITION_READINESS.md) — capability status, security review scope, current test counts, and remaining gates.
- [Judge demo script](JUDGE_DEMO_SCRIPT.md) — 12-minute walk-through with three public product scenarios. Scenario claims are test inputs, not manufacturer quotations. No app records or reports have been created yet.
- [Product evidence benchmark](PRODUCT_EVIDENCE_BENCHMARK.md) — manually researched primary-source examples; clearly distinguished from app-generated findings.
- [Architecture diagram source](ARCHITECTURE.mmd) — editable Mermaid source.
- [Deployment readiness checklist](DEPLOYMENT_READINESS.md) — separate development/judge and production controls.
- [Production environment template](../.env.production.example) — blank placeholders only; real values belong in a managed secret store.

## Safe presentation claims

The deck presents architecture and features as implemented where supported by code and tests. It labels live retrieval, current persisted records, actual worker runs, database isolation, and produced demo reports as unverified or blocked. Do not present the public product examples as application-generated research until they have been created and retrieved in an isolated judge-demo project.

The slide deck was rendered and visually reviewed at full size. Its exported PPTX passed the first-party artifact integrity/import and layout checks; Windows denied the finalizer's hard-link step, so the validated draft was copied byte-for-byte to the deliverable. The copied file's SHA-256 is `0923F3D77AE3F15ADAC217143B79649D25C366096125CF4B61B05A6340B0CE23`.
