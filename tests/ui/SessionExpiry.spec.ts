// #42 (R36; ADR-013): the guest session expiry warning in the patient shell. The page clock is controlled
// (page.clock) while the API runs on real time: the API reports the expiry in X-Session-Expires-At with its Date
// header, so the browser warns 2 minutes before the earlier of 30 minutes idle or 8 hours.
// #501: a response the page handles after a clock jump re-anchors it to the server's (real) time and undoes the jump,
// so every jump waits until the page has handled all its API reads (`apiSettled`), not just until a response arrived.
import { expect, test, type Page } from "@playwright/test";
import { ADDRESS, apiSettled, expectNoHorizontalOverflow, startSession, trackApi } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

async function startWithClock(page: Page) {
  await trackApi(page);
  await page.clock.install();
  await startSession(page);
  await expect(page.getByRole("heading", { name: "What would you like help with?" })).toBeVisible();
  await apiSettled(page);
}

const warning = (page: Page) => page.getByRole("alert").filter({ hasText: "Your session ends at" });

test("the warning appears 2 minutes before expiry and Stay signed in extends the session", async ({ page }) => {
  await startWithClock(page);
  await page.clock.fastForward("27:00");
  await expect(warning(page)).toHaveCount(0); // 3 minutes left: no warning yet
  await page.clock.fastForward("01:30");
  await expect(warning(page)).toBeVisible();
  await expect(warning(page)).toContainText("guest sessions end after 30 minutes without activity");
  const stay = page.waitForResponse((r) => r.url().endsWith("/api/v1/settings") && r.request().method() === "GET");
  await warning(page).getByRole("button", { name: "Stay signed in" }).click();
  expect((await stay).headers()["x-session-expires-at"]).toBeTruthy();
  await expect(warning(page)).toHaveCount(0); // the idle window moved on: 30 minutes again
  await page.clock.fastForward("02:00");
  await expect(warning(page)).toHaveCount(0);
});

test("at the 8-hour limit the warning says the session cannot be extended", async ({ page }) => {
  let lastExpiry = "";
  page.on("response", (r) => { const h = r.headers()["x-session-expires-at"]; if (h) lastExpiry = h; });
  await startWithClock(page);
  expect(lastExpiry).not.toBe("");
  await page.clock.fastForward("28:30");
  await expect(warning(page)).toBeVisible();
  // The API answers but cannot move the expiry: the absolute limit applies (simulated, as the server clock is real).
  await page.route("**/api/v1/settings", async (route) => {
    const real = await route.fetch();
    const fakeNow = await page.evaluate(() => Date.now());
    await route.fulfill({ response: real, headers: { ...real.headers(), "x-session-expires-at": lastExpiry,
      date: new Date(fakeNow).toUTCString() } });
  });
  await warning(page).getByRole("button", { name: "Stay signed in" }).click();
  await expect(warning(page)).toContainText("reached its 8-hour limit and cannot be extended");
  await expect(warning(page).getByRole("button", { name: "Stay signed in" })).toHaveCount(0);
});

test("the warning can be dismissed, and the end is still shown when it comes", async ({ page }) => {
  await startWithClock(page);
  await page.clock.fastForward("28:30");
  await expect(warning(page)).toBeVisible();
  await warning(page).getByRole("button", { name: "Dismiss" }).click();
  await expect(warning(page)).toHaveCount(0);
  // #409: the end is shown once the server confirms it (simulated, as the server clock is real).
  await page.route("**/api/v1/settings", (route) => route.fulfill({ status: 401, contentType: "application/json",
    json: { code: "SESSION_REQUIRED", message: "Your session has ended. Start again to continue.", field_errors: [],
      retryable: false, request_id: "00000000-0000-4000-8000-000000000000" } }));
  await page.clock.fastForward("02:00");
  const ended = page.getByRole("alert").filter({ hasText: "Your session has ended" });
  await expect(ended).toBeVisible();
  await expect(ended.getByRole("link", { name: "Start a new consultation" })).toHaveAttribute("href", "/app/start");
});

test("public pages show no session warning without a session", async ({ page }) => {
  await page.clock.install();
  await page.goto("/help");
  await page.clock.fastForward("40:00");
  await expect(page.getByText("Your session ends at")).toHaveCount(0);
  await expect(page.getByText("Your session has ended")).toHaveCount(0);
});

/** Waits for the next response that reports the session's expiry (the page has then learned it). */
const expiryLearned = (page: Page) => page.waitForResponse((r) => Boolean(r.headers()["x-session-expires-at"]));

test("#399 Help, Telemetry and Privacy warn too while a guest session is open", async ({ page }) => {
  await startWithClock(page);
  for (const path of ["/help", "/telemetry", "/privacy"]) {
    const learned = expiryLearned(page); // public pages learn it from their resume check
    await page.goto(path);
    await learned;
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await apiSettled(page);
    await page.clock.fastForward("28:30");
    await expect(warning(page), path).toBeVisible();
    const stay = page.waitForResponse((r) => r.url().endsWith("/api/v1/settings") && r.request().method() === "GET");
    await warning(page).getByRole("button", { name: "Stay signed in" }).click();
    expect((await stay).headers()["x-session-expires-at"]).toBeTruthy();
    await expect(warning(page)).toHaveCount(0);
  }
  // From the app navigation to Help (no page load): the warning still comes there. Opening Help is activity (its
  // resume check), so the session's new end is the one warned about.
  const learned = expiryLearned(page);
  await page.goto("/app/history");
  await learned;
  await apiSettled(page); // #501: the probe, the resume check and the case list all report the expiry
  await page.clock.fastForward("28:30");
  await expect(warning(page)).toBeVisible();
  const menu = page.getByRole("banner").getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  const resumed = expiryLearned(page);
  await page.getByRole("banner").getByRole("link", { name: "Help", exact: true }).click();
  await expect(page).toHaveURL(/\/help$/);
  await resumed;
  await apiSettled(page);
  await page.clock.fastForward("28:30");
  await expect(warning(page)).toBeVisible();
});

test("#409 an idle second tab follows the session another tab keeps open", async ({ page, context }) => {
  await trackApi(page);
  await startSession(page); // tab A, on real time
  await apiSettled(page);
  const b = await context.newPage();
  await trackApi(b);
  await b.clock.install();
  const learned = b.waitForResponse((r) => r.url().endsWith("/api/v1/settings") && r.request().method() === "GET");
  await b.goto("/app/history");
  await learned;
  await apiSettled(b);
  await b.clock.fastForward("28:30"); // tab B alone: 1:30 left as far as it knows
  await expect(warning(b)).toBeVisible();
  // Tab A works on: the session's new expiry reaches tab B, which stops warning.
  const read = page.waitForResponse((r) => r.url().endsWith("/api/v1/cases") && r.request().method() === "GET");
  await page.goto("/app/history");
  await read;
  await expect(warning(b)).toHaveCount(0);
  await apiSettled(page); // tab A has handled, and told the other tabs, every read before tab B's clock moves on
  await b.clock.fastForward("02:00");
  await expect(b.getByText("Your session has ended")).toHaveCount(0);
  // Past what tab B knows, it asks the server first; the session is open, so it never says it ended.
  await b.clock.fastForward("30:00");
  await b.waitForTimeout(1000);
  await expect(b.getByText("Your session has ended")).toHaveCount(0);
  await expect(b).toHaveURL(/\/app\/history$/);
  await expect(warning(b)).toHaveCount(0);
});

test("after a page reload the shell learns the expiry again and still warns", async ({ page }) => {
  await startWithClock(page);
  const probe = page.waitForResponse((r) => r.url().endsWith("/api/v1/settings") && r.request().method() === "GET");
  await page.reload();
  expect((await probe).headers()["x-session-expires-at"]).toBeTruthy();
  await apiSettled(page);
  await page.clock.fastForward("28:30");
  await expect(warning(page)).toBeVisible();
});

// #586: the check after the expiry this tab knew gets no answer (a network failure, status 0): that is not the server
// saying the session ended. The page says it cannot confirm the session right now and asks again until the server
// answers: a live session (200) clears the notice, only a 401 says the session has ended.
const unconfirmed = (page: Page) => page.getByRole("status").filter({ hasText: "We can't confirm your session right now" });
const ended = (page: Page) => page.getByRole("alert").filter({ hasText: "Your session has ended" });

/** Past the expiry this tab knew, with the session check failing in the network (no response, status 0). */
async function pastExpiryOffline(page: Page) {
  await startWithClock(page);
  await page.route("**/api/v1/settings", (route) => route.abort("internetdisconnected"));
  const probe = page.waitForEvent("requestfailed", (r) => r.url().endsWith("/api/v1/settings"));
  await page.clock.fastForward("30:30");
  await probe;
  await expect(unconfirmed(page)).toBeVisible();
  await expect(unconfirmed(page)).toContainText("could not check with Aware Care whether your session is still open");
  await expect(page.getByText("Your session has ended")).toHaveCount(0);
  await expect(page.locator('a[href="/app/start"]')).toHaveCount(0); // no advice to start again
  await expectNoHorizontalOverflow(page);
  await apiSettled(page); // the failed check was handled, so the next check is scheduled
  await page.unroute("**/api/v1/settings");
}

test("#586 @mobile a session check without an answer is not an ended session, and a live 200 clears it", async ({ page }) => {
  await pastExpiryOffline(page);
  // The session is open on the server all along: an independent real read answers 200.
  expect((await page.request.get("/api/v1/settings")).status()).toBe(200);
  // The page asks again by itself once the server can answer, and learns the session's new expiry.
  const asked = page.waitForResponse((r) => r.url().endsWith("/api/v1/settings") && r.request().method() === "GET");
  await page.clock.fastForward("00:15");
  expect((await asked).status()).toBe(200);
  await expect(unconfirmed(page)).toHaveCount(0);
  await expect(page.getByText("Your session has ended")).toHaveCount(0);
  await expect(warning(page)).toHaveCount(0);
  await expect(page).toHaveURL(/\/app\/new$/);
  await expect(page.getByRole("heading", { name: "What would you like help with?" })).toBeVisible();
});

test("#586 @mobile after a check without an answer, a real 401 says the session has ended", async ({ page }) => {
  await pastExpiryOffline(page);
  // The session really ends on the server (as End session would): its own read and DELETE, outside the page.
  const token = (await page.request.get("/api/v1/settings")).headers()["x-csrf-token"];
  expect(token).toBeTruthy();
  const end = await page.request.delete("/api/v1/sessions/current", { headers: { Origin: ADDRESS, "X-CSRF-Token": token } });
  expect(end.status()).toBe(202);
  const asked = page.waitForResponse((r) => r.url().endsWith("/api/v1/settings") && r.request().method() === "GET");
  await unconfirmed(page).getByRole("button", { name: "Check now" }).click();
  expect((await asked).status()).toBe(401);
  await expect(ended(page)).toBeVisible();
  await expect(ended(page).getByRole("link", { name: "Start a new consultation" })).toHaveAttribute("href", "/app/start");
  await expect(unconfirmed(page)).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});
