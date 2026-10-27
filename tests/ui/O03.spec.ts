// O03 Demo scenarios (R37, R39, R40; ADR-005 option A, amended by #487). A guest cannot reach presenter operations by
// direct navigation or by tampering with browser-side state: the server decides the role on every request. One
// address (15174) serves both roles: presenter pages call /presenter-api, patient pages /api.
import { expect, test } from "@playwright/test";
// #188: the history action is named for the next step.
const RESUME = /^(Continue questions|Review answers|View guidance|View urgent help|View limits)$/;
import { ADDRESS, apiCalls, presenterAccessOff, startSessionOnly } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const FORGED = `v1.${Math.floor(Date.now() / 1000)}.${"0".repeat(32)}.${"0".repeat(64)}`;

test("with an active guest session, direct navigation to O03 stays unauthorized", async ({ page }) => {
  await startSessionOnly(page);
  await page.goto("/presenter/scenarios");
  await expect(page.getByRole("heading", { level: 1, name: "Demo scenarios" })).toBeVisible();
  // #487: the guest session gives no presenter data; the presenter tools ask for a presenter session.
  await expect(page.getByText("Start a presenter session", { exact: true })).toBeVisible();
  await expect(page.locator(".flow-card, .scenario-card")).toHaveCount(0);
});

test("hidden browser state cannot make a guest a presenter on any presenter operation", async ({ page }) => {
  await startSessionOnly(page);
  await page.goto("/presenter/scenarios");
  const results = await page.evaluate(async (forged) => {
    // Tamper with everything a client could control: storage flags and a forged gateway assertion.
    for (const store of [localStorage, sessionStorage]) {
      store.setItem("role", "presenter");
      store.setItem("awarecare_role", "presenter");
    }
    document.cookie = "role=presenter; path=/";
    const headers = { "X-AwareCare-Presenter": forged, "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() };
    const calls: [string, string, unknown][] = [
      ["GET", "/api/v1/presenter/runtime", undefined],
      ["GET", "/api/v1/presenter/controls", undefined],
      ["POST", "/api/v1/presenter/scenarios/urgent/load", { reset: true }],
      ["POST", "/api/v1/presenter/scenarios/urgent/load", { reset: false, urgency_input: "written" }], // #358
      ["POST", "/api/v1/presenter/reset", {}],
    ];
    const out: { path: string; status: number; code: string | null }[] = [];
    for (const [method, path, body] of calls) {
      const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
      const json = await r.json().catch(() => null);
      out.push({ path, status: r.status, code: json?.code ?? null });
    }
    return out;
  }, FORGED);
  for (const r of results) expect(r, r.path).toEqual({ path: r.path, status: 403, code: "PRESENTER_REQUIRED" });
  await page.reload();
  // #487: none of it counted: the presenter tools still ask for a presenter session and show no presenter data.
  await expect(page.getByText("Start a presenter session", { exact: true })).toBeVisible();
  await expect(page.locator(".flow-card, .scenario-card")).toHaveCount(0);
});

// #487: one address; the names say which role a step plays.
const PRESENTER = ADDRESS;
const PATIENT = ADDRESS;

async function presenterOn(page: import("@playwright/test").Page, path: string) {
  await page.goto(`${PRESENTER}${path}`);
  const start = page.getByRole("button", { name: "Start presenter session" });
  await start.click();
  // #336: return only once the session has started; navigating sooner can abort the start request.
  await expect(start).toBeHidden();
  // #358: the Scenarios page runs three flows; full journeys and the reset are on More scenarios.
  await expect(page.locator(".flow-card, .scenario-card").first()).toBeVisible();
}

const MORE = "/presenter/scenarios/more";

// T-R37-S01 cites this test by its title (#55 clause map, spec/acceptance.json): keep the title (#319). Since #315 the
// loaded scenario continues on the patient site in a tab opened at its first question.
test("a loaded scenario continues on the patient site while the presenter session stays; reset removes it", async ({ context }) => {
  const presenter = await context.newPage();
  await presenterOn(presenter, MORE); // #358: full journeys moved to More scenarios
  // T-R37-S01: fixture use is visibly synthetic on the presenter side, for every scenario.
  await expect(presenter.getByText("Synthetic fixtures.", { exact: false })).toBeVisible();
  for (const id of ["routine", "selfcare", "urgent", "unsupported", "nomatch", "failure"])
    await expect(presenter.getByText(`Scenario ${id} · synthetic`, { exact: true })).toBeVisible();
  // #315: one click opens the patient site at the case's first question; no trip through History.
  const opened = presenter.waitForEvent("popup");
  await presenter.getByRole("button", { name: "Load scenario: Find the right clinician" }).click();
  const tab = await opened;
  await expect(tab).toHaveURL(/^http:\/\/127\.0\.0\.1:15174\/app\/cases\/[0-9a-f-]+\/questions$/);
  await expect(tab.getByText("Question 1 of up to 10")).toBeVisible();
  await expect(presenter.getByText("Loaded: Find the right clinician")).toBeVisible();
  await expect(presenter.getByText("opened in the patient tab", { exact: false })).toBeVisible();
  await expect(presenter.getByText(/go to History/)).toHaveCount(0);
  const link = presenter.getByRole("link", { name: "Open on patient site" });
  await expect(link).toHaveAttribute("href", new URL(tab.url()).pathname);
  await expect(link).toHaveAttribute("target", "aware-care-patient");

  // The case is also in History, as before.
  const patient = await context.newPage(); // same browser: same cookie jar
  await patient.goto(`${PATIENT}/app/history`);
  const row = patient.locator("tbody tr");
  await expect(row).toHaveCount(1);
  await expect(row.getByRole("button", { name: RESUME })).toBeVisible();

  await presenter.goto(`${PRESENTER}/presenter/runtime`);
  await expect(presenter.locator(".datum", { has: presenter.getByText("Mode", { exact: true }) }).locator("b")).toHaveText("mock");

  await presenter.goto(`${PRESENTER}${MORE}`);
  await presenter.getByRole("button", { name: "Reset demo" }).click();
  await expect(presenter.getByText("Reset completed")).toBeVisible({ timeout: 15_000 });
  // #285: "Your session ended" is for a session this tab knew. The patient tab stays on History (it saw the session)
  // and opens the case in the app; that request finds the session ended.
  await row.getByRole("button", { name: RESUME }).click();
  await expect(patient.getByText("Your session ended")).toBeVisible();
});

test("a failed reset blocks a new demo until a reset succeeds", async ({ page }) => {
  await presenterOn(page, MORE);
  // The server reports the previous reset as failed (the O03 required exception): the load is refused, and since
  // CHG-DEV-API-007 (#425) the runtime snapshot says so too.
  await page.route("**/presenter-api/v1/presenter/scenarios/*/load", (route) =>
    route.fulfill({ status: 503, contentType: "application/json",
      body: JSON.stringify({ code: "RESET_FAILED", message: "The previous reset failed; repair it before loading a scenario.", retryable: false }) }));
  await page.route("**/presenter-api/v1/presenter/runtime", async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    await route.fulfill({ response, json: { ...json, demo: { ...json.demo, reset_status: "failed" } } });
  });
  await page.getByRole("button", { name: "Load scenario: Urgent interruption" }).click();
  await expect(page.getByText("New demo blocked: the last reset did not complete")).toBeVisible();
  for (const button of await page.getByRole("button", { name: /^Load scenario:/ }).all()) await expect(button).toBeDisabled();
  // #506: a runtime read may still be in its handler (route.fetch took 1.7 s in CI); unroute does not wait for it, so the
  // request fell through and the handler's fulfill threw "Route is already handled!". These are the page's only routes.
  await page.unrouteAll({ behavior: "wait" });
  await page.getByRole("button", { name: "Retry reset" }).click();
  await expect(page.getByText("Reset completed")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("New demo blocked")).toHaveCount(0);
  await page.getByRole("button", { name: "Load scenario: Urgent interruption" }).click();
  await expect(page.getByText("Loaded: Urgent interruption")).toBeVisible();
});

test("in local mode O03 explains the live scenarios and offers no scripted failure", async ({ page }) => {
  // ADR-016 (#113): the browser suite runs in mock mode, so the runtime snapshot is shown as local mode here; the
  // server side of local-mode loading is covered by tests/acceptance/test_R37.py.
  await page.route("**/presenter-api/v1/presenter/runtime", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), mode: "local" } });
  });
  await presenterOn(page, MORE);
  await expect(page.locator(".o03-line")).toHaveText("HP ZGX Nano · AI ready");
  await expect(page.getByText("the questions, the red-flag screen and the guidance run on the local AI of the HP ZGX Nano", { exact: false })).toBeVisible();
  for (const title of ["Find the right clinician", "Explore self-care guidance", "Urgent interruption", "Outside the demo scope", "No matching doctors"])
    await expect(page.getByRole("button", { name: `Load scenario: ${title}` })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Load scenario: Guidance unavailable" })).toBeDisabled();
  await expect(page.getByText("A forced failure would fake the local AI, so this scenario runs in mock mode only.")).toBeVisible();
  await expect(page.getByText("Live AI · full journey")).toBeVisible();
  await expect(page.getByText("Shorter intake")).toHaveCount(0); // mock-only tags are not shown in local mode
});

test("when the browser blocks the patient tab, O03 offers the link instead", async ({ page }) => {
  await page.addInitScript(() => {
    window.open = () => null;
  });
  await presenterOn(page, "/presenter/scenarios");
  // #358: a one-click flow still runs; #548: when its "Open the result" is blocked, the dialog and the card offer the
  // patient tab as a link.
  await page.getByRole("button", { name: "Run on HP ZGX Nano: Urgent warning sign" }).click();
  const box = page.getByRole("dialog");
  await box.getByRole("button", { name: "Open the result" }).click();
  await expect(box.getByText("The browser blocked the patient tab.")).toBeVisible();
  await expect(box.getByRole("link", { name: "Open the result in the patient tab" })).toHaveAttribute("href", /^\/app\/cases\/[0-9a-f-]+\/urgent$/);
  await box.getByRole("button", { name: "Close" }).click();
  const status = page.locator(".flow-card", { hasText: "Urgent warning sign" }).locator(".flow-status");
  await expect(status).toContainText("Ready: not shown yet");
  await expect(status.getByRole("link", { name: "Open in the patient tab" })).toHaveAttribute("href", /^\/app\/cases\/[0-9a-f-]+\/urgent$/);
  await page.goto(`${PRESENTER}${MORE}`);
  await page.getByRole("button", { name: "Load scenario: Urgent interruption" }).click();
  await expect(page.getByText("The browser did not open the patient tab")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open on patient site" }).first()).toHaveAttribute("href", /^\/app\/cases\/[0-9a-f-]+\/urgent$/);
});

test("#487 the patient tab opens the case on this same address, whatever the device script names", async ({ page }) => {
  // Before #487 the presenter gateway's device script named the patient site on another port. Now the patient pages are
  // on this address, so the link is a path on it, and no script value can send the patient tab elsewhere.
  await page.addInitScript(() => {
    window.open = () => null; // the link is then offered, and nothing is opened
  });
  await presenterOn(page, MORE);
  for (const script of [
    'window.AWARE_CARE_DEVICE = { name: "HP ZGX Nano", shortName: "ZGX Nano", origin: "http://example.invalid:18180" };',
    'window.AWARE_CARE_DEVICE = { name: "HP ZGX Nano", shortName: "ZGX Nano", patientOrigin: "javascript:alert(1)" };',
    'window.AWARE_CARE_DEVICE = { name: "HP ZGX Nano", shortName: "ZGX Nano" };',
  ]) {
    await page.route("**/aware-care-device.js", (route) => route.fulfill({ contentType: "application/javascript", body: script }));
    await page.goto(`${PRESENTER}${MORE}`); // the presenter session stays; the device script is read again
    await page.getByRole("button", { name: "Load scenario: Urgent interruption" }).click();
    await expect(page.getByText("The browser did not open the patient tab")).toBeVisible();
    const link = page.getByRole("link", { name: "Open on patient site" }).first();
    expect(await link.getAttribute("href"), script).toMatch(/^\/app\/cases\/[0-9a-f-]+\/urgent$/);
    await page.unroute("**/aware-care-device.js");
  }
});

// ── #326-#329 presenter flow ─────────────────────────────────────────────────────────────────────────────────────────

test("#487 without presenter access the presenter tools say so and lead back to the home page's choice", { tag: "@mobile" }, async ({ page }) => {
  await presenterAccessOff(page); // the gateway's presenter path refuses on its own (no key on the device)
  await page.goto(`${ADDRESS}/presenter/scenarios`);
  const gate = page.locator(".notice", { hasText: "Presenter authorization required" });
  await expect(gate).toBeVisible();
  await expect(gate).toContainText("Presenter access is not enabled on this device");
  await expect(gate).not.toContainText("18181");
  await expect(page.getByRole("button", { name: "Start presenter session" })).toHaveCount(0); // still no presenter access
  await gate.getByRole("link", { name: "Back to the home page" }).click();
  await expect(page).toHaveURL(`${ADDRESS}/`);
  await expect(page.getByRole("link", { name: /^(Start a new consultation|Continue consultation)$/ }).first()).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(page.viewportSize()!.width);
});

test("#328 the device status line refreshes every 15 s, and live journeys wait while the device is not ready", async ({ page }) => {
  // #358: one quiet line on both views; the flows and the live journeys wait, the no-AI journeys stay available.
  await page.clock.install();
  let readiness = "ready";
  await page.route("**/presenter-api/v1/presenter/runtime", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), readiness } });
  });
  await presenterOn(page, MORE);
  await expect(page.locator(".o03-line")).toHaveText("HP ZGX Nano · mock mode: scripted outcomes, no AI model");
  readiness = "degraded";
  await page.clock.fastForward(16_000);
  await expect(page.locator(".o03-line")).toContainText("HP ZGX Nano · service degraded (mock mode) · the flows wait until it is ready");
  await expect(page.getByText(/Live journeys wait until the device is Ready \(the device is Degraded\)/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Load scenario: Find the right clinician" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Load scenario: Urgent interruption" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Load scenario: Outside the demo scope" })).toBeEnabled();
});

// ── QA 2026-10-22 presenter findings (CHG-DEV-API-007) ──────────────────────────────────────────────────────────────

type Page = import("@playwright/test").Page;
type Context = import("@playwright/test").BrowserContext;
const DEVICE = "HP ZGX Nano";
const runButton = (page: Page, title: string) => page.getByRole("button", { name: `Run on ${DEVICE}: ${title}` });
const flowCard = (page: Page, title: string) =>
  page.locator(".flow-card", { has: page.getByRole("heading", { name: title, exact: true }) });
const flowStatus = (page: Page, title: string) => flowCard(page, title).locator(".flow-status");

/** #548: a flow's result opens in the patient tab only from the dialog's "Open the result" click; returns the tab. */
async function openResult(page: Page): Promise<Page> {
  const open = page.getByRole("dialog").getByRole("button", { name: "Open the result" });
  await expect(open).toBeVisible({ timeout: 30_000 });
  const popup = page.waitForEvent("popup");
  await open.click();
  return popup;
}

/** #548: close the progress dialog (the run goes on; its card shows it). */
async function closeDialog(page: Page) {
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

/** Click a presenter navigation link (behind the Menu button at 360 px). */
async function presenterNav(page: Page, name: string) {
  const nav = page.getByRole("navigation", { name: "Presenter" });
  const menu = nav.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await nav.getByRole("link", { name, exact: true }).click();
}

/** Keeps every quick flow's prepare job "running" for the page until the returned function is called. */
async function holdPrepare(page: Page): Promise<() => void> {
  let held = true;
  await page.route("**/v1/jobs/*", async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    await route.fulfill({ response, json: held && job.kind === "scenario_prepare"
      ? { ...job, status: "running", result_id: null, result_type: null, error_code: null, finished_at: null } : job });
  });
  return () => {
    held = false;
  };
}

/** Starts the Guidance flow with its prepare job held and closes its progress dialog (#548: no tab opens). */
async function startHeldGuidance(page: Page): Promise<void> {
  const polled = page.waitForRequest(/\/v1\/jobs\//);
  await runButton(page, "Guidance from the local AI").click();
  await polled; // the load answered and its prepare job is being followed
  await closeDialog(page);
  await expect(flowStatus(page, "Guidance from the local AI")).toContainText("Running the scripted outcome");
}

/** #548: a finished run's card offers "Open in the patient tab"; its click opens the result there. */
async function openFromCard(page: Page, title: string): Promise<Page> {
  const status = flowStatus(page, title);
  await expect(status).toContainText("Ready: not shown yet", { timeout: 30_000 });
  const popup = page.waitForEvent("popup");
  await status.getByRole("link", { name: "Open in the patient tab" }).click();
  return popup;
}

const endPresenterSession = (context: Context) => context.clearCookies({ name: "awarecare_presenter" });

test("#423 leaving Scenarios during a run keeps it going: back on Scenarios the card offers the result", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page, "/presenter/scenarios");
  const release = await holdPrepare(page);
  await startHeldGuidance(page);
  await presenterNav(page, "Runtime"); // leave the page while the device works
  await expect(page.getByRole("heading", { level: 1, name: "Runtime overview" })).toBeVisible();
  release();
  await presenterNav(page, "Scenarios");
  const tab = await openFromCard(page, "Guidance from the local AI");
  await expect(tab).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/guidance$/, { timeout: 30_000 });
  await expect(tab.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
  const status = flowStatus(page, "Guidance from the local AI");
  await expect(status).toContainText("Shown in the patient tab");
  await expect(status.getByRole("link", { name: "Show again" })).toHaveAttribute("href", new URL(tab.url()).pathname);
});

test("#423 a reload during a run picks it up again: its result still opens in the patient tab", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page, "/presenter/scenarios");
  const release = await holdPrepare(page);
  await startHeldGuidance(page);
  await page.reload();
  const status = flowStatus(page, "Guidance from the local AI");
  await expect(status).toContainText("Running the scripted outcome"); // the run is still shown after the reload
  release();
  const tab = await openFromCard(page, "Guidance from the local AI");
  await expect(tab).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/guidance$/, { timeout: 30_000 });
  await expect(tab.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
  await expect(status).toContainText("Shown in the patient tab");
  await expect(status.getByRole("link", { name: "Show again" })).toHaveAttribute("href", new URL(tab.url()).pathname);
  expect(context.pages()).toHaveLength(2); // the presenter page and the one patient tab
  await page.reload(); // a finished run stays shown after a reload too
  await expect(status.getByRole("link", { name: "Show again" })).toHaveAttribute("href", new URL(tab.url()).pathname);
});

test("#424 while a flow runs, Load scenario waits, so the flow never takes over a journey just loaded", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page, "/presenter/scenarios");
  const release = await holdPrepare(page);
  await startHeldGuidance(page);
  await presenterNav(page, "More scenarios");
  await expect(page.locator(".scenario-card")).toHaveCount(6);
  await expect(page.getByText("A quick flow is running", { exact: false })).toBeVisible();
  for (const button of await page.getByRole("button", { name: /^Load scenario:/ }).all()) await expect(button).toBeDisabled();
  release();
  await expect(page.getByRole("button", { name: "Load scenario: Urgent interruption" })).toBeEnabled({ timeout: 30_000 });
  await expect(page.getByText("A quick flow is running", { exact: false })).toHaveCount(0);
});

test("#422 a reset after the presenter session ended shows the presenter gate and claims nothing; the new session is not blocked", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page, MORE);
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Load scenario: Urgent interruption" }).click();
  await popup;
  await expect(page.getByText("Loaded: Urgent interruption")).toBeVisible();
  await endPresenterSession(context);
  await page.getByRole("button", { name: "Reset demo" }).click();
  const start = page.getByRole("button", { name: "Start presenter session" });
  await expect(start).toBeVisible();
  for (const claim of ["New demo blocked", "Reset completed", "did not complete", "SESSION_REQUIRED"])
    await expect(page.getByText(claim, { exact: false })).toHaveCount(0);
  await start.click();
  await expect(page.locator(".scenario-card")).toHaveCount(6);
  await expect(page.getByText("New demo blocked", { exact: false })).toHaveCount(0);
  for (const button of await page.getByRole("button", { name: /^Load scenario:/ }).all()) await expect(button).toBeEnabled();
});

test("#460 Run and Load with an ended presenter session show the presenter gate, not raw or misleading errors", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page, "/presenter/scenarios");
  await endPresenterSession(context);
  const popups: Page[] = [];
  page.on("popup", (p) => popups.push(p));
  await runButton(page, "Self-care guidance").click();
  await expect(page.getByRole("button", { name: "Start presenter session" })).toBeVisible();
  await expect(page.getByText(/SESSION_REQUIRED|the run failed/)).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(0); // the run ended without an outcome: its dialog closed
  expect(popups).toHaveLength(0); // #548: no tab was opened for it
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.locator(".flow-card")).toHaveCount(3);
  await expect(flowStatus(page, "Self-care guidance")).not.toContainText("Not shown");
  await page.goto(`${PRESENTER}${MORE}`);
  await expect(page.locator(".scenario-card")).toHaveCount(6);
  await endPresenterSession(context);
  await page.getByRole("button", { name: "Load scenario: Urgent interruption" }).click();
  await expect(page.getByRole("button", { name: "Start presenter session" })).toBeVisible();
  await expect(page.getByText("Your session has ended", { exact: false })).toHaveCount(0);
});

test("#425 a failed reset is shown from the server on every presenter view, also after a reload", async ({ page }) => {
  // The server reports the device's last reset as failed (tests/acceptance/test_R37.py covers the server side).
  let failed = true;
  await page.route("**/presenter-api/v1/presenter/runtime", async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    await route.fulfill({ response, json: failed
      ? { ...json, demo: { ...json.demo, reset_status: "failed", reset_finished_at: new Date().toISOString() } } : json });
  });
  await presenterOn(page, MORE);
  const banner = page.getByText("New demo blocked: the last reset did not complete");
  await expect(banner).toBeVisible();
  for (const button of await page.getByRole("button", { name: /^Load scenario:/ }).all()) await expect(button).toBeDisabled();
  await page.reload();
  await expect(banner).toBeVisible();
  await page.goto(`${PRESENTER}/presenter/scenarios`);
  await expect(banner).toBeVisible();
  for (const title of ["Guidance from the local AI", "Self-care guidance", "Urgent warning sign"]) {
    await expect(runButton(page, title)).toHaveAttribute("aria-disabled", "true");
    await expect(flowStatus(page, title)).toContainText("Waits until a reset succeeds");
  }
  failed = false;
  await page.getByRole("button", { name: "Retry reset" }).click(); // a real reset, which succeeds
  await expect(banner).toHaveCount(0, { timeout: 15_000 });
  await expect(runButton(page, "Urgent warning sign")).not.toHaveAttribute("aria-disabled", "true");
});

test("#426 Show again after the demo session ended says so on the card and leaves the patient tab where it is", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page, "/presenter/scenarios");
  await runButton(page, "Guidance from the local AI").click();
  const tab = await openResult(page);
  await expect(tab).toHaveURL(/\/guidance$/, { timeout: 30_000 });
  await expect(tab.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
  const shown = tab.url();
  // The demo patient session ends (as after 30 idle minutes, or End session in the patient tab).
  await tab.evaluate(async () => {
    const read = await fetch("/api/v1/settings", { credentials: "same-origin" });
    await fetch("/api/v1/sessions/current", { method: "DELETE", credentials: "same-origin",
      headers: { "X-CSRF-Token": read.headers.get("X-CSRF-Token") ?? "" } });
  });
  const status = flowStatus(page, "Guidance from the local AI");
  await status.getByRole("link", { name: "Show again" }).click();
  await expect(status).toContainText("Expired: run it again");
  await expect(status.getByRole("link")).toHaveCount(0);
  await expect(tab).toHaveURL(shown); // not sent to the consent page in front of the audience
  await expect(runButton(page, "Guidance from the local AI")).not.toHaveAttribute("aria-disabled", "true");
});

test("#426 a reset in a second presenter tab ends the first tab's runs and moves its patient tab off the old case", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page, "/presenter/scenarios");
  await runButton(page, "Urgent warning sign").click();
  const tab = await openResult(page);
  await expect(tab).toHaveURL(/\/urgent$/, { timeout: 30_000 });
  const second = await context.newPage(); // the same browser: its presenter session is already there
  await second.goto(`${PRESENTER}${MORE}`);
  await second.getByRole("button", { name: "Reset demo" }).click();
  await expect(second.getByText("Reset completed")).toBeVisible({ timeout: 15_000 });
  await page.bringToFront();
  await page.evaluate(() => window.dispatchEvent(new Event("focus"))); // the presenter returns to the first tab
  const status = flowStatus(page, "Urgent warning sign");
  await expect(status).not.toContainText("Shown in the patient tab");
  await expect(status.getByRole("link", { name: "Show again" })).toHaveCount(0);
  await expect(tab).toHaveURL(`${PATIENT}/app/start`); // the previous audience's case is no longer on show
});

test("#430 the Loaded banner says only what happened", async ({ page }) => {
  await page.addInitScript(() => {
    window.open = () => null;
  });
  await presenterOn(page, MORE);
  await page.getByRole("button", { name: "Load scenario: Find the right clinician" }).click();
  const loaded = page.locator(".notice", { hasText: "Loaded: Find the right clinician" });
  await expect(loaded).toBeVisible();
  await expect(loaded).not.toContainText("opened in the patient tab");
  await expect(loaded).toContainText("is ready on the patient site");
  await expect(page.getByText("The browser did not open the patient tab")).toBeVisible(); // its link opens it
  // Local mode: a branch that stops before the AI never claims the AI answers live.
  await page.route("**/presenter-api/v1/presenter/runtime", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), mode: "local" } });
  });
  await page.reload();
  await page.getByRole("button", { name: "Load scenario: Urgent interruption" }).click();
  const urgent = page.locator(".notice", { hasText: "Loaded: Urgent interruption" });
  await expect(urgent).toContainText("This branch stops before the AI.");
  await expect(urgent).not.toContainText("answers live");
  await page.getByRole("button", { name: "Load scenario: Explore self-care guidance" }).click();
  await expect(page.locator(".notice", { hasText: "Loaded: Explore self-care guidance" }))
    .toContainText(`The local AI on the ${DEVICE} answers live.`);
});

test("#443 while a flow runs, its button's accessible name contains the visible label", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page, "/presenter/scenarios");
  const release = await holdPrepare(page);
  await startHeldGuidance(page);
  const button = page.getByRole("button", { name: /^Running…/ });
  await expect(button).toHaveText("Running…");
  await expect(button).toHaveAccessibleName("Running… Guidance from the local AI");
  await expect(button).toHaveAttribute("aria-busy", "true");
  release();
  await expect(runButton(page, "Guidance from the local AI")).toHaveText(`Run on ${DEVICE}`, { timeout: 30_000 });
});

test("#462 flow cards: a sub-second step is not '0 s', the status has one pair of parentheses, Run buttons line up", async ({ context }, info) => {
  const page = await context.newPage();
  await presenterOn(page, "/presenter/scenarios");
  await runButton(page, "Self-care guidance").click();
  await (await openResult(page)).waitForURL(/\/guidance$/);
  await page.bringToFront();
  const status = flowStatus(page, "Self-care guidance");
  await expect(status).toContainText("Shown in the patient tab");
  const line = (await status.locator("p").innerText()).trim();
  expect(line).toMatch(/\(scripted outcome in mock mode, no AI model, (under 0\.1 s|\d+\.\d s|\d+ s)\)$/);
  expect(line).not.toMatch(/\b0 s\)/);
  expect(line.split("(").length - 1, line).toBe(1);
  // A failed run beside a finished one: different status lengths, the Run buttons still share one baseline.
  await page.route("**/presenter-api/v1/presenter/scenarios/urgent/load", (route) => route.fulfill({ status: 503,
    contentType: "application/json", body: JSON.stringify({ code: "RED_FLAG_SCREEN_UNAVAILABLE",
      message: "The local AI's warning-sign screen did not answer; nothing was created.", field_errors: [], retryable: true,
      request_id: "00000000-0000-4000-8000-000000000000" }) }));
  await runButton(page, "Urgent warning sign").click();
  await closeDialog(page);
  await expect(flowStatus(page, "Urgent warning sign")).toContainText("Not shown");
  if (info.project.name === "desktop-1440") {
    const tops = await Promise.all(["Guidance from the local AI", "Self-care guidance", "Urgent warning sign"]
      .map(async (title) => Math.round((await runButton(page, title).boundingBox())!.y)));
    expect(Math.max(...tops) - Math.min(...tops), tops.join(", ")).toBeLessThanOrEqual(1);
  }
});

test("#427 #487 the presenter shell's brand stays in the presenter tools; a patient page on the same address is a patient page", async ({ page }) => {
  await presenterOn(page, "/presenter/scenarios");
  await page.goto(`${PRESENTER}/presenter/runtime`);
  await page.getByRole("link", { name: /^HP Aware Care on .+, home$/ }).click();
  await expect(page).toHaveURL(`${PRESENTER}/presenter/scenarios`);
  // #487: the presenter toolbar leads to the home page's choice.
  await page.locator(".toolbar").getByRole("link", { name: "Home: patient or presenter" }).click();
  await expect(page).toHaveURL(`${ADDRESS}/`);
  await expect(page.getByRole("heading", { level: 2, name: "How would you like to use Aware Care?" })).toBeVisible();
  // A patient page on the same address works as a patient page: no "presenter address" notice, consent offered, and
  // its requests use the patient API only.
  const calls = apiCalls(page);
  await page.goto(`${PATIENT}/app/start`);
  await expect(page.getByRole("button", { name: "Accept and begin" })).toBeVisible();
  await expect(page.locator(".notice", { hasText: "This is the presenter address" })).toHaveCount(0);
  await page.goto(`${PATIENT}/help`);
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.locator("a", { hasText: /Start a new consultation|Continue consultation/ })).toHaveCount(1);
  await page.getByRole("link", { name: /^HP Aware Care on .+, home$/ }).click();
  await expect(page).toHaveURL(`${ADDRESS}/`);
  expect(calls.filter((c) => c.startsWith("/presenter-api/")), calls.join(", ")).toEqual([]);
});

test("#470 Telemetry from the presenter navigation keeps the presenter navigation", async ({ page }) => {
  await presenterOn(page, "/presenter/scenarios");
  await presenterNav(page, "Telemetry");
  await expect(page).toHaveURL(`${PRESENTER}/presenter/telemetry`);
  await expect(page.getByRole("heading", { level: 1, name: /usage, cost and privacy/ })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Presenter" });
  await expect(nav).toBeVisible();
  await expect(nav.locator(`.navlinks a[href="/presenter/scenarios"]`)).toHaveText("Scenarios");
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  await expect(page.locator("footer").getByRole("link", { name: /Telemetry/ })).toHaveAttribute("href", "/presenter/telemetry");
  await presenterNav(page, "Scenarios");
  await expect(page.locator(".flow-card")).toHaveCount(3);
});

const ORIGIN_REJECTED = { status: 403, contentType: "application/json", body: JSON.stringify({ code: "ORIGIN_REJECTED",
  message: "This request origin is not allowed.", field_errors: [], retryable: false,
  request_id: "00000000-0000-4000-8000-000000000000" }) };
const TUNNEL = "ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 <user>@<host>"; // #487: one tunnel, one port

test("#461 the presenter opened at localhost says to use the 127.0.0.1 address", async ({ page }) => {
  await page.goto("http://localhost:15174/presenter/scenarios");
  const help = page.locator(".notice", { hasText: "Open Aware Care at the address this device is set up for" });
  await expect(help).toContainText("This address will not work here"); // said up front at "localhost"
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(help).toContainText("The device did not accept this address");
  await expect(help.getByRole("link", { name: "http://127.0.0.1:15174/presenter/scenarios" }))
    .toHaveAttribute("href", "http://127.0.0.1:15174/presenter/scenarios");
  await expect(help.locator("code.cmd")).toHaveText(TUNNEL);
  await expect(page.getByText("This request origin is not allowed.")).toHaveCount(0);
});

test("#461 a refused patient-site address names the address the device is set up for, the tunnel and the settings", async ({ page }) => {
  // Another device reached through a tunnel at an address its deployment does not accept (a stubbed 403).
  await page.route("**/aware-care-device.js", (route) => route.fulfill({ contentType: "application/javascript",
    body: 'window.AWARE_CARE_DEVICE = { name: "HP ZGX Nano", shortName: "ZGX Nano", origin: "http://127.0.0.1:18180" };' }));
  await page.route("**/api/v1/sessions", (route) =>
    route.request().method() === "POST" ? route.fulfill(ORIGIN_REJECTED) : route.continue());
  await page.goto(`${PATIENT}/app/start`);
  await page.getByLabel("Yes, I am 18 or older").check();
  await page.getByLabel("I understand and accept these terms.").check();
  await page.getByRole("button", { name: "Accept and begin" }).click();
  const help = page.locator(".notice", { hasText: "Open Aware Care at the address this device is set up for" });
  await expect(help).toContainText(`The device did not accept this address (${PATIENT})`);
  await expect(help).toContainText("it accepts requests only from http://127.0.0.1:18180, for patients and presenters alike");
  await expect(help.getByRole("link", { name: "http://127.0.0.1:18180/app/start" })).toHaveAttribute("href", "http://127.0.0.1:18180/app/start");
  await expect(help.locator("code.cmd")).toHaveText(TUNNEL);
  for (const setting of ["--origin", "network.browser_origin"]) await expect(help).toContainText(setting);
  await expect(help).not.toContainText("presenter-origin"); // #487: one origin for both roles
  await expect(page.getByText("This request origin is not allowed.")).toHaveCount(0);
});
