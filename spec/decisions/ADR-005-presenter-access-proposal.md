# ADR-005: Local authentication and presenter access

Status: **Accepted: option A for presenter access** (2026-10-14). The TLS and disk follow-ups below remain open. Nothing is implemented yet (#14).

Status amendment (2026-10-19, #293): "Nothing is implemented yet" was true on 2026-10-14. Option A has since been
implemented and deployed: the presenter assertion check in `apps/api/app/modules/access/presenter.py`, the presenter
gateway in `infra/deploy/presenter.conf.template` (since #487 `presenter-api.conf.template`, the presenter path of the one gateway) and `infra/deploy/presenter.js` (#14, CHG-DEV-M3-001), the separate
presenter cookie and the O02/O03 tools with scenario load and reset in `apps/api/app/modules/operations/scenarios.py`
(#24, CHG-DEV-M3-003), and live scenarios in local mode ([ADR-016](ADR-016-live-presenter-scenarios.md)). See
"Implementation notes" below. The TLS and disk follow-ups and saved patient accounts remain open.

Amendment (2026-10-22, #487, CHG-DEV-API-008): **from a port to a path.** The presenter gateway is no longer a second
listener on 8181; it is the path `/presenter-api/` of the one gateway on 8180, and the home page offers the patient or
presenter choice. See "Amendment: one address, presenter API by path" below; it supersedes the port-based wording of
this record where they differ (the "Gateways", "Key" and "Development and tests" rows, rule 3's "8180" and rule 6's
"second listener").

Date: proposed 2026-10-14 (#11), accepted 2026-10-14 (#14). Owner role: infrastructure lead (product.md D04).
Affected IDs: R03, R05, R10, R37, R38; O01–O03; M01, M12; createSession, getRuntime, getControls, loadScenario,
resetDemo. No ID, route, operation or schema changes are proposed.

## Decision (2026-10-14)
- **Accepted:** option **A, the SSH-gated presenter gateway**, for presenter access in milestone 3, under the rules in
  "Proposed rules for option A" below.
- **Decided by:** the repository admin (repository admin), recorded as the infrastructure-lead decision for this demo.
- **Accepted consequences:**
  - Presenter capability equals the ability to log in to the Nano over SSH and forward the presenter port. On
    2026-10-14 the Nano had four login accounts: the maintainer's account and three other user accounts.
  - Option A applies to SSH-tunnelled demos only; it is not a customer-network control.
  - Option A provides no saved patient accounts, so R05 and the saved paths of R10 and R06-S02 stay
    `SAVED_MODE_UNAVAILABLE`.
- **Still open (not decided):**
  - The control required before any customer-network demo: the proposal recommends C, or B behind TLS.
  - The disk-encryption choice under "TLS, cookies and disk".
  - Both must be decided before a customer-network demo. M3 itself uses synthetic data only, as all builds do today.
- **Next step:** implementation issue #14 (presenter gateway, assertion-based role assignment, O01).

## Implementation notes (#14, CHG-DEV-M3-001)
| Item | As built |
|---|---|
| Assertion | `X-AwareCare-Presenter: v1.<unix-seconds>.<32-hex nonce>.<HMAC-SHA256 hex>`; 60 s window. Signed in njs by the presenter gateway (`infra/deploy/presenter.js`); verified in `apps/api/app/modules/access/presenter.py`. |
| Session creation | A valid, **single-use** assertion (nonce kept in `presenter_nonces`) from a trusted loopback peer creates a presenter actor and session through the existing `createSession` body. A request with an invalid assertion header is refused (`403 PRESENTER_REQUIRED`) rather than silently becoming a patient session. |
| Every presenter request | `require_presenter` needs both the presenter role **and** a fresh valid assertion. Reason: browsers scope cookies by host, not port, so a presenter cookie from 18181 also reaches the patient gateway (18180). Without the per-request check that cookie would carry presenter authority there. This tightens rule 1 above; it does not loosen it. |
| Gateways | Patient gateway (8180) sets the header to empty. Presenter gateway (8181) overwrites any client value with a fresh assertion and adds `X-AwareCare-Gateway: presenter` to its API responses. That header is a UI hint only; the API authorizes. |
| Key | `nano_deploy.py presenter-key` creates `<data_root>/secrets/presenter.key` (64 hex characters, mode 600; never printed). It is mounted read-only at `/run/secrets/presenter.key` in both containers; the web container runs as the deploying user so it can read the file. No key means no presenter listener and no presenter access. |
| Development and tests | `vite.config.ts` strips the header by default and signs it only when `AWARECARE_PRESENTER_KEY_FILE` is set. The Playwright stack runs a presenter gateway on 15175 with a throwaway key. |
| Separate presenter cookie (M3.2, #24, CHG-DEV-M3-003) | Presenter sessions use the cookie `awarecare_presenter`; patient sessions use `awarecare_session`. The gateway decides which applies: a request with a valid assertion reads **only** the presenter cookie and accepts only a presenter session; any other request reads only the patient cookie and accepts only a patient session. One browser can therefore hold both: the presenter tab on 8181 and the patient tab on 8180. `loadScenario` hands the patient tab the synthetic demo session (patient cookie) without touching the presenter session. Presenter-owned reset jobs are polled through the presenter gateway. A presenter cookie without an assertion is not read at all (`401`). This replaces the earlier "use a separate browser profile" advice. |
| O02 and O03 (M3.2) | O02 shows every control with truthful "Unverified" evidence. O03 loads the six existing scenarios, resets, and blocks new demos after a failed or pending reset (the O03 required exception). ADR-006 (proposed) governs only the final rehearsal configuration. |

## Amendment: one address, presenter API by path (2026-10-22, #487, CHG-DEV-API-008)
**Request (maintainer):** different ports for patients and presenters are confusing; one home page with two choices,
patient or presenter.

**Decision:** one gateway, one port and one browser origin (8180, forwarded as 18180, origin `http://127.0.0.1:18180`).

| Item | As amended |
|---|---|
| Patient API | `/api/...`: the gateway sets `X-AwareCare-Presenter` to empty, exactly as the patient gateway did. A forged header there yields `403 PRESENTER_REQUIRED` (rule 3 now names the path, not port 8180). |
| Presenter API | `/presenter-api/...`: the gateway signs a fresh assertion exactly as the presenter gateway did (`infra/deploy/presenter.js`), proxies to the API's `/api/...` and adds `X-AwareCare-Gateway: presenter` to these responses only (`infra/deploy/presenter-api.conf.template`). Without presenter access the path answers `403 PRESENTER_REQUIRED` itself and never reaches the API (`presenter-api-disabled.conf`). |
| API trust rules | Unchanged: key file `<data_root>/secrets/presenter.key`, trusted loopback peer, 60 s freshness, single-use nonce for session creation, the per-request presenter check and the separate cookies. The API accepts one origin for both roles. |
| Cookies | Every API cookie is scoped to `/` (was `/api`), so the browser sends it to both prefixes, as it sent it to both ports before (browsers scope cookies by host, not port). The API still reads only the cookie of the verified role. |
| Browser | The role of a request follows its page: presenter pages (`/presenter/...`) call `/presenter-api`, every other page `/api`. The home page (W01, `/`) offers Patient (A01) and Presenter (O03). A presenter's patient tab opens `/app/...` on the same address in the patient role. |
| Deployment | `nano_deploy.py` enables the path when the key exists (`AWARECARE_PRESENTER_ENABLED=1`), opens no second port, and **refuses a presenter key when the gateway binds a non-loopback address** (`network.bind_host`, `--bind-host`); the container's `25-aware-care-presenter.sh` refuses the same on its own. `presenter_port`, `presenter_origin` and `--presenter-port`/`--presenter-origin` in older configurations and commands are read and ignored (named in the evidence). |
| Development and tests | `vite.config.ts` proxies `/api` (header stripped) and, with `AWARECARE_PRESENTER_KEY_FILE`, `/presenter-api` (signed); without a key `/presenter-api` answers like the disabled gateway. The Playwright stack runs one server on 15174. |

**Why this is security-equivalent under the accepted model.** ADR-005 accepted "presenter capability equals the
ability to log in to the Nano over SSH and forward the presenter port". Under the amendment it equals the ability to log
in over SSH and forward the one port. Who can do that is unchanged: the gateway still binds loopback only, so only an
SSH account holder can reach either path, and anyone who could forward 8180 before could equally forward 8181. What a
request can do is unchanged: the API grants the role only for a fresh, authentic, loopback-delivered assertion, which
only the gateway's presenter path adds; a client-supplied header is overwritten there and removed on `/api`. The
per-request check was introduced precisely because the presenter cookie already reached the patient gateway (same
host); the path split relies on the same check. Browsers already shared both cookies across the two ports, so scoping
them to `/` sends nothing to a place it did not reach before.

**Loopback guard.** Presenter access must never reach a network without the TLS / mTLS control that this ADR leaves
open ("Remaining decisions"). Because the presenter path now shares the patient listener, the deploy tool refuses any
deployment with a presenter key and a non-loopback bind before it pulls or stops anything, and the gateway container
enables the path only on a loopback bind. A future customer-network gateway must decide C (or B behind TLS) first.

## Problem
Presenter screens O01–O03 and their four operations already exist and enforce `require_presenter`. Nothing can
create a presenter session, so they always return `403 PRESENTER_REQUIRED`, and milestone 3 is blocked. The
specification requires the following:
- Role assignment comes from an **upstream local authentication layer**, never from the request body.
- No hardcoded presenter password, no URL-flag bypass and no demo login shortcut.
- Presenter access is separate from saved patient accounts.
- Presenter reset is limited to the owned demo context.
- `POST /sessions` cannot turn a guest into a presenter (product.md lines 434, 478, 647; ENG-05 "Identity boundary").

## Observed facts (2026-10-14)
- **Exposure:** the deployed stack is loopback-only (`127.0.0.1:8100` API, `127.0.0.1:8180` gateway) and reached
  through SSH port forwarding (port `<ssh-port>`). Only people with an SSH account on the Nano can reach it.
- **Cookies:** plain HTTP over the tunnel, using the documented development exception (`AWARECARE_COOKIE_SECURE=false`).
- **Disk:** the root filesystem (`nvme0n1p2`) is ext4 with **no encryption layer**. ENG-05 and `deployment.yaml`
  require disk encryption "where supported and verified before customer demo".

## Options for presenter identity

| Option | How it works | For | Against |
|---|---|---|---|
| **A. SSH-gated presenter gateway (recommended for M3)** | A second loopback-only gateway listener (for example `127.0.0.1:8181`) serves the same web build plus `/api`. It adds an HMAC-SHA256 presenter assertion (key in `<data_root>/secrets/presenter.key`, mode 600, never in Git or an image) to requests. The patient gateway on 8180 **strips** that header. `createSession` grants `role=presenter` only with a valid, fresh assertion on a loopback request, then issues the normal opaque cookie. | No passwords to store. Reuses the existing access boundary (SSH accounts) and existing operations. No new endpoint. Small and testable. | Identity is "anyone with SSH access who forwards 8181", not a named person. Not suitable for a shared customer network. |
| B. Local password accounts | Preprovisioned accounts with scrypt or Argon2 hashes in a server-only file. An authentication component outside the 31 operations performs login and hands an assertion to `createSession`. | Named identities; also serves saved patient accounts (R05/R10). | Needs a login surface the spec does not define. Password handling, lockout and rotation must be designed. More to review. |
| C. Mutual TLS client certificates at a TLS gateway | The gateway requires a client certificate issued to presenter devices. The verified certificate subject becomes the assertion. | Strong, no passwords, fits the future trusted-network TLS gateway. | Needs a CA, certificate issuance and the TLS gateway that ADR-005 has not decided. Heavier than M3 needs. |

**Recommendation:** adopt **A** now for milestone 3 on the SSH-tunnelled demo. Record that a customer-network
demonstration requires **C** (or B behind TLS) before the trusted-network gateway goes live. Keep saved patient
accounts (R05, R10 saved paths) **out of scope** until B or C is chosen. They stay `SAVED_MODE_UNAVAILABLE` and
their tests stay untestable, as today.

## Proposed rules for option A
1. **Assertion:** `v1.<unix-time>.<nonce>.<hmac>`, valid for 60 s, single use (nonce stored until expiry). The API
   accepts it only when the TCP peer is loopback and the header comes from the presenter gateway configuration.
2. **Session:** `createSession` with a valid assertion creates a presenter actor and session (`mode=guest`,
   `role=presenter`). Body fields still cannot assign role or actor (unchanged validation).
3. **Gateway:** the patient gateway removes the assertion header from every inbound request. A test proves a forged
   header on 8180 yields `403 PRESENTER_REQUIRED`.
4. **Scope:** presenter sessions follow guest expiry (30 min idle, 8 h absolute). Reset and scenario loading affect
   only the presenter's own synthetic context (existing `resetDemo` and `loadScenario` semantics).
5. **Audit:** presenter actions write content-free events (operation, outcome, presenter actor ID).
6. **Deployment:** `deploy-nano.yml` starts the second listener only when `secrets/presenter.key` exists. No key
   means no presenter access, which is the current behavior.

## TLS, cookies and disk (part of ADR-005, not needed for M3 on SSH)
- **TLS:** keep the SSH tunnel and the documented cookie exception for M3. Before any customer-network demo,
  decide the TLS gateway and certificate source (internal CA or HP-issued), and set `AWARECARE_COOKIE_SECURE=true`.
- **Disk:** the Nano's root filesystem is not encrypted. Choose one: (a) an encrypted volume (for example a LUKS
  file container) mounted for `<data_root>` only, (b) full-disk re-provisioning by IT, or (c) a documented exception
  for synthetic-only data with a hard gate before any real data. **Recommendation:** (a) before the customer demo;
  (c) is acceptable for M3, because all data is synthetic.

## Acceptance impact if A is accepted
- **Now testable:** R03-S02 (presenter rejects guests, including forged headers) and the presenter parts of
  R37-S01/S02 and R38.
- **Still blocked:** R05, the R10 saved paths and R06-S02.

## Remaining decisions
Option A was accepted on 2026-10-14 (see "Decision" above). Still to decide, before any customer-network
demonstration: the control that replaces A there (C, or B behind TLS) and the disk-encryption choice. Record each
as an amendment to this ADR.
