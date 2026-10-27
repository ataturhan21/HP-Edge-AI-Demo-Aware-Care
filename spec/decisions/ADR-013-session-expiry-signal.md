# ADR-013: Report the session's current expiry in a response header

Status: **Accepted 2026-10-15** (issue #42). The maintainer delegated the backlog work ("complete some backlog items
perfectly"); the issue asked for this choice between options A, B and C. Owner role: technical lead. Affected IDs:
R36 (T-R36-S01), M01, M11; the patient app shell (A-screens).

## Context
- **The requirement:** T-R36-S01 requires guest expiry "with the specified 2-minute warning". The server ends a
  guest session at the earlier of 30 minutes without activity or 8 hours after it started.
- **Why the browser can't warn today:** the idle window slides with every authenticated request, and nothing reports
  the new value. `createSession` returns `expires_at` once, and `Case` responses carry it, but most requests (answers,
  jobs, settings) do not.
- **Why a client estimate is not enough:** it cannot know the 8-hour limit after a page reload. No operation returns
  the session's start time, so it could miss the warning before the absolute limit.

## Decision
**Option A:** every response to an authenticated request carries `X-Session-Expires-At`.
- **Value:** the session's expiry after that request, as ISO 8601 UTC, computed by the server
  (`security.effective_expiry`).
- **Where it is added:** by the transport layer, like `X-CSRF-Token`, so no operation changed.
- **Where it is absent:** on 401, and on `deleteSession`, which ends the session.
- **Documentation:** recorded in `spec/api/README.md` ("Declared wire refinements"). `openapi.json` is unchanged, as
  it is for `X-CSRF-Token`.

**The browser:**
- **Tracking:** it keeps the latest value together with the server's clock offset (from the `Date` header).
- **Warning:** the patient shell shows a dismissible warning 2 minutes before the end. "Stay signed in" makes one
  authenticated read, which slides the idle window. If the expiry does not move, the 8-hour limit applies, and the
  warning says the session cannot be extended.
- **After a page load:** the shell makes one authenticated read to learn the expiry. A 401 stays quiet there.
- **When it ends:** the warning says the session has ended, with "Start again".

**Rejected:**
- **B, a session-status operation:** it would change the stable 31-operation set.
- **C, a client-only estimate:** it can miss the 8-hour limit.

## Consequences
- **Data:** the header exposes only a time the session owner already receives in bodies. It is same-origin, and no
  CORS is configured.
- **The server stays authoritative:** a wrong client clock affects only when the warning shows, never when the
  session ends.
- **Saved sessions:** saved-account retention (7 or 30 days) stays out of scope until ADR-005 saved mode exists.

## Amendment (2026-10-21, #345, CHG-DEV-UI-006)
The ended-session action is named "Start a new consultation" (formerly "Start again"), the one name for every action
that starts a consultation. Its target (A01) and the expiry mechanism are unchanged.

## Amendment (2026-10-22, #399 and #409, CHG-DEV-APP-005)
- **Where the warning shows (#399, WCAG 2.2.1):** also on the public pages (W01-W06 and A01) while a guest session is
  open, because the app navigation links to Help and Telemetry. They learn the expiry from the authenticated resume
  check they already make (`listCases`, read quietly), so no extra request is made there.
- **Several tabs (#409):** the tabs of one browser share one session. Each tab tells the others the latest expiry it
  saw, with the server time of that response (a same-origin `BroadcastChannel`, memory only, two times and nothing
  else); a tab keeps the later expiry. So an idle tab does not warn about a session another tab keeps alive.
- **When it ends (#409):** "Your session has ended" is shown only after one quiet authenticated read returns 401. If the
  session is still open, that read reports its new expiry instead (the read is activity, as "Stay signed in" is).
- Unchanged: the header, its value, the limits (30 minutes idle, 8 hours) and the server's authority.

