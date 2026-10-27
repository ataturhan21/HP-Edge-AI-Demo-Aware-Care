// Speed improvements of 2026-10-19 (#202-#204, #206, #207), measured by the requests the browser makes.
import { expect, test, type Page, type Request } from "@playwright/test";
import { answerAll, apiSettled, enterConcern, startSession, trackApi } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

/** Every /api request the page makes, in order, with its start time (ms since the test began). */
function apiLog(page: Page) {
  const t0 = Date.now();
  const log: { method: string; path: string; at: number }[] = [];
  page.on("request", (r: Request) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api/")) log.push({ method: r.method(), path: u.pathname.replace(/[0-9a-f-]{36}/g, "{id}"), at: Date.now() - t0 });
  });
  return log;
}

// #526: asserted on the page clock and by request concurrency, never by elapsed time. The app waits 400 ms after each
// read was handled, so a wall-clock gap also holds the read's round trip, which grows under load.
test("#202 #203 a finished guidance job is read within a short interval, then the case and result together", async ({ page }) => {
  await trackApi(page);
  await page.clock.install();
  // The delays the page schedules (on the controlled clock): the next read is due once the 400 ms wait is scheduled.
  await page.addInitScript(() => {
    const w = window as unknown as { __delays: number[] };
    const schedule = window.setTimeout;
    w.__delays = [];
    window.setTimeout = ((fn: TimerHandler, ms?: number, ...args: unknown[]) => {
      w.__delays.push(ms ?? 0);
      return schedule(fn, ms, ...args);
    }) as typeof window.setTimeout;
  });
  const waits = () => page.evaluate(() => (window as unknown as { __delays: number[] }).__delays.filter((d) => d === 400).length);
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  let reads = 0;
  await page.route("**/v1/jobs/*", async (route) => {
    const read = ++reads; // counted when the page asks, before the round trip
    const response = await route.fetch();
    const job = await response.json();
    if (read < 4) return route.fulfill({ response, json: { ...job, status: "running", result_id: null, result_type: null } });
    return route.fulfill({ response, json: job });
  });
  // #203: once the job has succeeded, hold the case read and the guidance read until both were requested. Read one
  // after the other, the second is never requested and the wait below fails.
  const held: string[] = [];
  let releaseBoth = () => {};
  const both = new Promise<void>((resolve) => (releaseBoth = resolve));
  await page.route(/\/api\/v1\/cases\/[0-9a-f-]{36}(\/guidance)?$/, async (route) => {
    if (reads < 4 || route.request().method() !== "GET") return route.fallback();
    held.push(new URL(route.request().url()).pathname.replace(/[0-9a-f-]{36}/g, "{id}"));
    if (held.length === 2) releaseBoth();
    await both;
    return route.fallback();
  });
  const log = apiLog(page);
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1000));
  await page.evaluate(() => ((window as unknown as { __delays: number[] }).__delays.length = 0));
  await page.getByRole("button", { name: "Generate guidance" }).click();
  // #202: each next read starts 400 ms after the previous one was handled, not earlier and not later.
  for (let read = 1; read < 4; read++) {
    await apiSettled(page, "/v1/jobs/");
    await expect.poll(waits, { message: `the 400 ms wait after read ${read} is scheduled` }).toBe(read);
    expect(reads).toBe(read);
    await page.clock.runFor(399);
    await apiSettled(page);
    expect(reads, `no read ${read + 1} before 400 ms`).toBe(read);
    await page.clock.runFor(1);
    await expect.poll(() => reads, { message: `read ${read + 1} at 400 ms` }).toBe(read + 1);
  }
  await expect.poll(() => [...held].sort()).toEqual(["/api/v1/cases/{id}", "/api/v1/cases/{id}/guidance"]);
  await page.clock.resume();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 15_000 });
  // Once each, and nothing else read between the succeeded job read and the two.
  const calls = log.filter((r) => r.method === "GET").map((r) => r.path);
  const lastJob = calls.lastIndexOf("/api/v1/jobs/{id}");
  expect(calls.filter((c) => c === "/api/v1/jobs/{id}")).toHaveLength(4);
  expect(calls.slice(lastJob + 1, lastJob + 3).sort()).toEqual(["/api/v1/cases/{id}", "/api/v1/cases/{id}/guidance"]);
  expect(calls.slice(lastJob + 1).filter((c) => c.startsWith("/api/v1/cases/"))).toHaveLength(2);
});

test("#204 an answer saves and asks for the next question without reading the case in between", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await expect(page.getByText("Question 1 of up to 10", { exact: true })).toBeVisible();
  const log = apiLog(page);
  await page.locator("form.card input[type=radio]").first().check();
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page.getByText("Question 2 of up to 10", { exact: true })).toBeVisible();
  expect(log.map((r) => `${r.method} ${r.path}`)).toEqual([
    "PUT /api/v1/cases/{id}/answers/{id}",
    "POST /api/v1/cases/{id}/questions/next",
  ]);
});

test("#206 patient and public pages load without the telemetry or presenter code, which loads on demand", async ({ page }) => {
  const scripts: string[] = [];
  page.on("request", (r) => {
    if (r.resourceType() === "script") scripts.push(new URL(r.url()).pathname);
  });
  await startSession(page);
  await enterConcern(page);
  expect(scripts.filter((s) => /\/assets\/(W06|O0[123])-/.test(s))).toEqual([]);
  await page.locator("footer").getByRole("link", { name: /Telemetry/ }).click(); // in-app navigation, every width
  await expect(page.getByRole("heading", { level: 1 })).toContainText("usage, cost and privacy");
  expect(scripts.some((s) => /\/assets\/W06-[\w-]+\.js$/.test(s))).toBe(true);
});

test("#207 the Latin font is preloaded from the page and used without a second download", async ({ page }) => {
  const fonts: string[] = [];
  page.on("request", (r) => {
    if (r.resourceType() === "font") fonts.push(new URL(r.url()).pathname);
  });
  await page.goto("/");
  const href = await page.locator('link[rel="preload"][as="font"]').getAttribute("href");
  expect(href).toMatch(/^\/assets\/inter-latin-wght-normal-[\w-]+\.woff2$/);
  await page.evaluate(() => document.fonts.ready);
  expect(fonts.filter((f) => f === href)).toHaveLength(1);
  expect(await page.evaluate(() => document.fonts.check('16px "Inter Variable"'))).toBe(true);
});
