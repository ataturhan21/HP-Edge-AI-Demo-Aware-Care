# ADR-014: The R34 privacy boundary — the LLM stays on the ZGX and no patient data leaves it

Status: **Accepted 2026-10-16** (issue #97), decided by the product owner. Affected IDs: R34 (T-R34-S01), the web
app shell (all screens), `tests/ui/support/journey.ts`.

## Context
R34 was accepted as: "Given normal use and failure paths, network inspection shows no raw health content, cloud
inference, remote fonts or third-party analytics." For the UI redesign (#98) the product owner set the boundary in
their own words on 2026-10-16:

> "requests can leave the device. only requirement is that llm will run locally on zgx and no patient data will
> leave zgx"

A remote font or other static asset carries no patient data, so the blanket "remote fonts" ban is stricter than the
owner's rule. Some third-party tools, however, would carry patient data even though they are "only" scripts.

## Decision
**Absolute:**
1. **The LLM runs only on the ZGX**, through ZRT. There is no cloud model and no cloud fallback (ADR-002 is
   unchanged).
2. **No patient data leaves the ZGX.** No case content, answers, guidance, record facts, case or session IDs, or
   API payload goes in any request to anything other than the Aware Care gateway on the device.

**Allowed:** static assets (fonts, stylesheets, scripts, icons, images) from named, reputable hosts:
- loaded with GET only, no cookies (`crossorigin` where needed), and no referrer;
- versions pinned, and Subresource Integrity on scripts and stylesheets;
- every page still renders, with system-font fallbacks, when the internet is unreachable, since the Nano may run on
  an isolated network.

**Still forbidden:** analytics, session replay, heat-mapping, error-reporting SaaS and any third-party script that
can read the page or its traffic. These capture page content, and here page content is patient data.

**The page:** it declares `<meta name="referrer" content="no-referrer">`, in addition to the gateway's
`Referrer-Policy: no-referrer`, so an allowed asset host never learns a case URL.

**The check:** `guardNetwork` (`tests/ui/support/journey.ts`) holds the allow-list (`ALLOWED_ASSET_HOSTS`). It fails
on:
- any off-device request to a host not on the list, any off-device non-GET request, and any request to `/api`;
- any off-device request whose URL, referrer or body carries a case or session identifier or a body at all;
- any request to a known analytics or session-replay host;
- any off-device resource that is not a font, stylesheet, script or image.

The list is empty while every asset is bundled; adding a host is a reviewed change to that file.

**R34's canonical clause becomes:** "Given normal use and failure paths, network inspection shows no patient content
or API payload leaving the device, no cloud inference, and no third-party analytics or session replay."

## Consequences
- **What this permits:** the redesign may use a remote font or icon set. It does not need to, so the first
  redesign bundles its typeface and the allow-list stays empty.
- **A hard line on third-party code:** it can never be a page-reading tool, however convenient.
- **Change record:** the wording change is CHG-DEV-PRIV-001 with a spec-lock refresh. R34 stays `planned`.
