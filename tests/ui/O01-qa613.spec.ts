// QA bug hunt #613, the presenter Logs view (O01 ?view=logs).
// #615: Load older keeps keyboard focus: it stays on the button while the page loads and moves to the first row loaded
// (WCAG 2.4.3; the app's rule since #402 that focus never falls to the page body).
// #616: the search takes at most the 100 characters the server accepts (getLogs q, logs.MAX_QUERY), so the rows shown
// always match it instead of the previous request's rows under a refusal that a refresh never fixes.
import { expect, test, type Page, type Route } from "@playwright/test";

const at = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();
const row = (i: number) => ({ id: `event:${i}`, at: at(i), precision: "exact", level: "ok", kind: "session",
  source: "event", name: `session_started ${i}`, status: "succeeded", code: null, duration_ms: 5, reasons: null,
  reason: null, detail: [] });

/** Four rows in pages of two; each page answers after 300 ms, so the loading state can be observed. */
function twoPages(route: Route) {
  const before = new URL(route.request().url()).searchParams.get("before");
  const from = before ? Number(before) : 0;
  const next = from + 2 < 4 ? String(from + 2) : null;
  return new Promise((done) => setTimeout(done, 300)).then(() => route.fulfill({ json: {
    observed_at: at(0), mode: "mock", readiness: "ready", queue_depth: 0, active_jobs: 0, truncated: next !== null,
    next_before: next, level_counts: { ok: 4, warn: 0, fail: 0, info: 0 }, total: 4,
    entries: [row(from + 1), row(from + 2)] } }));
}

async function presenterLogs(page: Page) {
  await page.goto("/presenter/runtime?view=logs");
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Logs" })).toBeVisible();
}

const focused = (page: Page) => page.evaluate(() => {
  const el = document.activeElement as HTMLElement | null;
  return `${el?.tagName} ${(el?.textContent ?? "").replace(/\s+/g, " ").trim()}`;
});

test("#615 Load older keeps keyboard focus: on the button while loading, then on the first row it loaded", async ({ page }) => {
  await page.route("**/presenter-api/v1/presenter/logs*", twoPages);
  await presenterLogs(page);
  const more = page.locator(".logs-more button"); // "Load older", then "Loading older rows…"
  await expect(more).toHaveText("Load older");
  await more.focus();
  await page.keyboard.press("Enter");
  await expect(more).toHaveText("Loading older rows…");
  expect(await focused(page)).toMatch(/^BUTTON Loading older rows/);
  await expect(page.locator(".log-row")).toHaveCount(4);
  // the last page: the button is gone and focus is on the first older row, not the page body
  await expect(more).toHaveCount(0);
  expect(await focused(page)).toMatch(/^BUTTON .*session_started 3/);
  await page.keyboard.press("Tab");
  expect(await focused(page)).toMatch(/^BUTTON .*session_started 4/);
});

test("#616 the search takes at most the 100 characters the server accepts, so the rows shown match it", async ({ page }) => {
  await presenterLogs(page);
  await expect(page.locator(".log-row").first()).toBeVisible();
  const search = page.getByLabel("Search");
  const asked = page.waitForResponse((r) => r.url().includes("/presenter/logs") && r.url().includes("q="));
  await search.fill("x".repeat(150));
  const response = await asked;
  expect(response.status()).toBe(200);
  expect(new URL(response.url()).searchParams.get("q")).toHaveLength(100);
  await expect(search).toHaveValue("x".repeat(100));
  await expect(page.getByText("No entries match these filters.")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
