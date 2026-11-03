# Product evidence benchmark (manual source review)

**Review date:** 2026-11-01
**Status:** Manually inspected public manufacturer sources for demo planning. These are not Proofline-generated findings, live app records, or a substitute for running the configured research workflow. The local search and LLM providers are not configured.

This benchmark checks source scope, identity, authority, independence, freshness, and relevance. Manufacturer sources have high first-party authority for published specifications, but are not independent corroboration of their own claims. The app must retain unknown where it cannot establish a signal.

| Product and exact test statement | Source and observed support | Manual outcome and limits |
|---|---|---|
| **Google Pixel 9 Pro** — “This model receives seven years of OS and security updates, starting when it first became available on the Google Store in the US.” | [Google Pixel software update policy](https://support.google.com/pixelphone/answer/4457705?hl=en-GB) lists Pixel 9 Pro under Pixel 8 and later and states seven years of OS and security updates starting at first US Google Store availability. | **Strong first-party support**, exact model match, official source, retrieved 2026-11-01. Region and start-date conditions are part of the claim. Not independently corroborated. |
| **Google Pixel 9** — “The device is waterproof at any depth for unlimited time.” | [Google Pixel 9 safety and regulatory guide](https://support.google.com/pixelphone/answer/14958126?hl=en-GB) says the device is designed to comply with IP68 under IEC 60529 when it leaves the factory, but is not dustproof or waterproof; resistance can diminish with wear, repair, disassembly, or damage. | **Contradicted as phrased.** The official IP68 qualification does not mean unlimited depth or duration, and Google explicitly says the device is not waterproof. First-party, model-matched; not independent. |
| **Dyson V15 Detect** — “Removes 100% of airborne allergens from every room in one pass.” | [Dyson V15 Detect Pro product page](https://www.dyson.com/commercial/vacuums/dyson-v15-detect) describes whole-machine filtration trapping 99.99% of particles as small as 0.3 microns, plus particle counting and suction adaptation. Dyson’s [V15 Detect product page](https://www.dyson.com/vacuum-cleaners/sticks/dyson-v15-stick) describes detection and counting of picked-up dust. | **Insufficient evidence for the broad test statement.** The cited specifications concern filtration and particles handled by the vacuum; they do not establish 100% allergen removal across room air, every room, or a single pass. The Pro specification may not describe every V15 Detect variant. Manufacturer source only; no independent study retrieved for this benchmark. |

## Source signal notes

- **Authority:** each source is the product manufacturer’s official support/product material. This is authoritative for its published specification and safety language, not independent test evidence.
- **Independence:** the sources are all first-party. No source diversity or independent corroboration is claimed.
- **Freshness:** pages were retrieved on the review date above. The Dyson technical specification is variant- and test-condition-dependent; its 0.3 micron filtration figure should not be generalized to all V15 variants or use conditions.
- **Identity and relevance:** Pixel sources name the exact Pixel 9 models. Dyson sources name V15 Detect or V15 Detect Pro; variant match must be checked against any registered SKU. The Dyson evidence is relevant to filtration but does not answer the entire room-level, one-pass claim.
- **App verification:** product registration, source retrieval by Proofline, research coverage, claim classification, governance, reports, and persisted records have **not** been exercised because the database endpoint is unreachable and provider configuration is missing.
