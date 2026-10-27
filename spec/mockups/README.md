# Aware Care screen and interaction references

Use `../screens.json` for the canonical 25 screen IDs (24 at handoff; W06 added by ADR-017), routes, module owners, requirements, screen paths and UI test paths. It is the only screen registry (ADR-019).

## What is included

- `original/`: the unchanged 71-file HealthGuide mockup package retrieved for this handoff, including 24 desktop PNGs, 24 mobile PNGs, 9 state PNGs, a 61-page PDF, self-contained HTML, source CSS/JS, registry, fixtures, historical QA outputs and the historical Sites prompt.
- `reference/Aware_Care_Interactive_Reference.html`: self-contained reference with the approved Aware Care name and ZRT-only integration label. Open it in a desktop browser. No server, inference, upload, account or network connection is required. No source-code export of the subsequently published Sites app is asserted.
- `reference/app.js` and `reference/theme.css`: corresponding editable reference source. These are design artifacts, not application source to copy wholesale into the prescribed backend architecture.
- `source-manifest.json`: SHA-256 hashes of the exact original reference files, for provenance.

## Authority and known differences

The current repository specification and runtime decisions govern the implementation. The original package is lower-priority visual/interaction evidence. Its historical `SITES_BUILD_PROMPT.txt` overrides applied only to a public, memory-only browser prototype. In particular, open presenter access, simulated saved mode, sample records, print-only export and simulated deletion do not satisfy the secure local backend requirements.

Original PNGs and PDF retain the legacy HealthGuide name. Do not duplicate that name into new Aware Care interfaces. No official HP brand approval is asserted by the working plus-symbol mark.

The master and later mock CSS have slightly different canvas/text/border/accent tokens. Use the reference to understand hierarchy and layout, and resolve token ownership through the current design decision before treating either palette as a required pixel baseline. Do not silently change behavioral contracts to match a screenshot.

The reference implements hash navigation so it works as a local file. The application must use the exact clean routes in `spec/screens.json`. The design selector intentionally seeds state for inspection; normal application navigation must enforce session, ownership and state guards.

## Clinical and runtime boundaries

All people, providers, plans, source cards and outcome text are fictional. The reference uses scenario fixtures and a scripted loading delay. Its guidance is not a clinician-reviewed pathway. Evidence IDs demonstrate layout and are not clinical sources. Clinical packages remain disabled until the separate review gates are satisfied.

The mockup's 900 ms delay is not measured inference latency. Screens showing Not connected/Not measured are correct for this reference. Use actual runtime data and timestamps for the eventual local application's presenter views.

A11 provider handoff opens an explicit simulation dialog. It does not book an appointment, contact a provider or define another screen. A12 is a visit preparation summary, not booking confirmation.

## Verification status

`original/QA_REPORT.txt` and JSON check files report historical checks of the original browser artifact. They do not verify the renamed reference, current Sites deployment, ZGX Nano, ZRT, authentication, clinical logic or backend implementation. Execute the repository's new acceptance plan against the implementation and label actual observations separately.
