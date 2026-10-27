# Frontend implementation boundary

The frontend is implemented: one `src/screens/<ID>.tsx` for each of the 25 IDs in ../../spec/screens.json (W06
Telemetry added by ADR-017), registered in src/routes.tsx. (At handoff, no production frontend existed and there were
24 IDs.) Keep that one-to-one mapping when changing screens. Keep native HTML controls, reusable components and all required states. Share components across screens instead of forcing one requirement per file. Run UI tests at tests/ui/<ID>.spec.ts from the repository root.

Vite development binds 127.0.0.1:5173. Proxy `/api` to http://127.0.0.1:8000 preserving the path; backend endpoints include /api/v1. Do not expose ZRT endpoint/credentials in frontend variables. Browser API calls use relative URLs. Normal presentation deployment uses trusted-network TLS; plain HTTP over an SSH development tunnel must not be represented as the final TLS deployment.

Read mockups/ references via ../../spec/mockups/README.md. Use the master token palette, local/system fonts, keyboard focus, semantic forms, 200% zoom and 360/768/1440 pixel checks. Keep health content out of localStorage, IndexedDB and service-worker caches. A screenshot is not an interactive implementation, and a hidden button is not authorization.

## Development build (CHG-DEV-APP-001)

```bash
cd apps/web
npm ci                  # install exact versions from package-lock.json
npm run gen:api         # regenerate src/api/schema.ts from ../../spec/api/openapi.json (do not hand-edit)
npm run typecheck
npm run dev             # Vite on 127.0.0.1:5173 (strictPort), /api proxied to 127.0.0.1:8000, prefix kept
```

Browse via the SSH tunnel at `http://127.0.0.1:15173` (forward local 15173 to Nano 127.0.0.1:5173).
`strictPort` makes Vite exit if 5173 is busy instead of moving ports. TypeScript is pinned to 5.x because
openapi-typescript 7 needs the TS 5 compiler API. Browser tests: `npm run test:ui` (Playwright; isolated stack on
127.0.0.1:18000 and one gateway on 15174 for both roles (#487: `/api` patient, `/presenter-api` presenter), served with
the gateway's Content-Security-Policy;
specs in `../../tests/ui/`, including the axe accessibility scan `a11y.spec.ts`). The device name comes from
`/aware-care-device.js` at run time (ADR-018; `public/aware-care-device.js` is the Nano default). See the root README
for details.
