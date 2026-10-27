// O01 Runtime overview (R03, R37, R38; ADR-005 option A, amended by #487). The isolated stack runs one gateway on 15174
// for both roles: /api strips any presenter header and /presenter-api signs requests with a throwaway key
// (playwright.config.ts).
import { expect, test } from "@playwright/test";
import { ADDRESS, animationsSettled, guardNetwork, presenterAccessOff, startSessionOnly } from "./support/journey";

const PRESENTER = ADDRESS;
const PATIENT = ADDRESS;
const FORGED = `v1.0.${"0".repeat(32)}.${"0".repeat(64)}`;

// T-R03 cites this title. #487: "the patient site" is now a device whose gateway offers no presenter access (the
// presenter path refuses on its own, presenter-api-disabled.conf); the presenter tools then offer no session.
test("the patient site shows presenter tools as unauthorized and offers no presenter session", async ({ page }) => {
  await presenterAccessOff(page);
  await page.goto(`${PATIENT}/presenter/runtime`);
  await expect(page.getByText("Presenter authorization required")).toBeVisible();
  await expect(page.getByText(/Presenter access is not enabled on this device/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Start presenter session" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Back to the home page" })).toHaveAttribute("href", "/");
});

// #487: on the one address a guest session gives no presenter data: the presenter tools ask for a presenter session,
// which only the server issues through the presenter path.
test("with an active guest session, direct navigation to O01 stays unauthorized", async ({ page }) => {
  await startSessionOnly(page);
  await page.goto(`${PATIENT}/presenter/runtime`);
  await expect(page.getByText("Start a presenter session", { exact: true })).toBeVisible();
  await expect(page.getByText("Device inventory", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Mock mode: synthetic flow simulation")).toHaveCount(0);
});

test("a presenter on the presenter gateway sees runtime facts from the manifests", async ({ page }) => {
  const offenders = guardNetwork(page);
  await page.goto(`${PRESENTER}/presenter/runtime`);
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByText("Mock mode: synthetic flow simulation")).toBeVisible();
  const datum = (label: string) => page.locator(".datum", { has: page.getByText(label, { exact: true }) }).locator("b");
  await expect(datum("Mode")).toHaveText("mock");
  await expect(datum("Readiness")).toHaveText("ready");
  await expect(datum("Device inventory")).toHaveText("nano-observed-2026-10-22"); // #429: refreshed from the device
  await expect(datum("Model manifest")).toHaveText("Not configured");
  await expect(datum("Corpus")).toHaveText("None approved");
  // R37: nothing claims a connected runtime in mock mode.
  await expect(page.locator("main")).not.toContainText(/connected/i);
  expect(offenders).toEqual([]);
});

// #487: "the patient gateway" is the patient API path /api of the one address; it strips the header.
test("a forged presenter header sent to the patient gateway never yields presenter access", async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: PATIENT });
  await ctx.get("/api/v1/health/ready");
  const created = await ctx.post("/api/v1/sessions", {
    headers: { Origin: PATIENT, "Idempotency-Key": crypto.randomUUID(), "X-AwareCare-Presenter": FORGED },
    data: { mode: "guest", consent_version: "aware-care-demo-consent-1.0", adult_eligible: true },
  });
  expect(created.status()).toBe(201); // the gateway stripped the header: an ordinary guest session
  const runtime = await ctx.get("/api/v1/presenter/runtime", { headers: { "X-AwareCare-Presenter": FORGED } });
  expect(runtime.status()).toBe(403);
  expect((await runtime.json()).code).toBe("PRESENTER_REQUIRED");
  await ctx.dispose();
});

test("#428 #429 mock timings are labelled scripted with no inference time, and each runtime value says its source and time", async ({ page }) => {
  // A scripted guidance run first, so there is a timing sample.
  await page.goto(`${PRESENTER}/presenter/scenarios`);
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await page.getByRole("button", { name: "Run on HP ZGX Nano: Self-care guidance" }).click();
  await expect(page.getByRole("dialog")).toContainText("Self-care guidance is ready", { timeout: 30_000 }); // #548
  await page.goto(`${PRESENTER}/presenter/runtime`);
  const datum = (label: string) => page.locator(".datum", { has: page.getByText(label, { exact: true }) }).locator("b");
  // #428 (R38): no model runs in mock mode, so nothing reads as measured inference.
  await expect(page.getByRole("heading", { name: /^Scripted timings \(mock mode, median, \d+ samples\)$/ })).toBeVisible();
  await expect(page.getByText("Measured timings", { exact: false })).toHaveCount(0);
  await expect(page.getByText("No AI model runs in mock mode, so there is no inference time.", { exact: false })).toBeVisible();
  await expect(page.locator(".timing", { hasText: "Inference" })).toHaveCount(0);
  await expect(datum("Total")).not.toHaveText("Not measured");
  await expect(page.getByText(/^Newest sample finished \d{1,2} [A-Z][a-z]{2} \d{4}, \d{2}:\d{2}\.$/)).toBeVisible();
  // #429: the time of this observation, the inventory's date, and no serving runtime claimed in mock mode.
  await expect(page.getByText(/and the queue observed at \d{2}:\d{2}:\d{2}; reload the page to observe them again\./)).toBeVisible();
  await expect(datum("Inventory recorded")).toHaveText("22 Oct 2026");
  await expect(datum("Serving runtime")).toHaveText("None: mock mode runs no model");
});

test("#429 in local mode the serving runtime's versions come from the model manifest, with its qualification date", async ({ page }) => {
  await page.route("**/presenter-api/v1/presenter/runtime", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), mode: "local",
      model_manifest_id: "qwen3.6-35b-a3b-fp8@95a723d0-2026-10-15", runtime_version: "ZRT 0.43.0 (vllm 0.30.0)",
      runtime_qualified_on: "2026-10-19" } });
  });
  await page.goto(`${PRESENTER}/presenter/runtime`);
  await page.getByRole("button", { name: "Start presenter session" }).click();
  const datum = (label: string) => page.locator(".datum", { has: page.getByText(label, { exact: true }) }).locator("b");
  await expect(datum("Serving runtime")).toHaveText("ZRT 0.43.0 (vllm 0.30.0)");
  await expect(datum("Runtime qualified")).toHaveText("19 Oct 2026 (model manifest)");
  await expect(page.getByRole("heading", { name: /^Measured timings/ })).toBeVisible();
  await expect(page.getByText(/including whether ZRT serves the configured model/)).toBeVisible();
});

// #487 (ADR-005 amendment): the presenter API path of the one address creates a presenter session; the patient path
// /api with a forged header gives 403 PRESENTER_REQUIRED (above), so the role depends on the path the gateway signs.
test("#487 the presenter API path of the one address creates a presenter session", async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: ADDRESS });
  const ready = await ctx.get("/presenter-api/v1/health/ready");
  expect(ready.headers()["x-awarecare-gateway"]).toBe("presenter");
  expect((await ctx.get("/api/v1/health/ready")).headers()["x-awarecare-gateway"]).toBeUndefined();
  const created = await ctx.post("/presenter-api/v1/sessions", {
    headers: { Origin: ADDRESS, "Idempotency-Key": crypto.randomUUID() },
    data: { mode: "guest", consent_version: "aware-care-demo-consent-1.0", adult_eligible: true },
  });
  expect(created.status()).toBe(201);
  expect(created.headers()["set-cookie"]).toMatch(/awarecare_presenter=[^;]+;.*[Pp]ath=\/(;|$|\s)/);
  const runtime = await ctx.get("/presenter-api/v1/presenter/runtime");
  expect(runtime.status()).toBe(200);
  expect((await runtime.json()).mode).toBe("mock");
  // The same browser's presenter cookie is no authority on the patient path, even with a forged header.
  const viaPatient = await ctx.get("/api/v1/presenter/runtime", { headers: { "X-AwareCare-Presenter": FORGED } });
  expect([viaPatient.status(), (await viaPatient.json()).code]).toEqual([401, "SESSION_REQUIRED"]);
  await ctx.dispose();
});

// ── #548 the presenter's Logs view (O01 ?view=logs; getLogs) ──────────────────────────────────────────────────────────

type Page = import("@playwright/test").Page;
const LOGS = `${PRESENTER}/presenter/runtime?view=logs`;

async function presenterLogs(page: Page) {
  await page.goto(LOGS);
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Logs" })).toBeVisible();
}

const at = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();
const hour = () => `${new Date().toISOString().slice(0, 13)}:00:00Z`;
const entry = (over: Record<string, unknown>) => ({ precision: "exact", status: null, code: null, duration_ms: null,
  reasons: null, reason: null, detail: [], ...over });
/** A fixed LogsSnapshot (the server side is tests/acceptance/test_R38.py): one row of every level. */
const SNAPSHOT = () => ({
  observed_at: at(0), mode: "local", readiness: "ready", queue_depth: 0, active_jobs: 0, truncated: false,
  next_before: null as string | null, level_counts: { ok: 2, warn: 2, fail: 1, info: 1 }, total: 6,
  entries: [
    entry({ id: "error:1", at: at(1), level: "warn", kind: "error", source: "api_error", name: "GET /cases/{case_id}",
      status: "404", code: "NOT_FOUND", detail: [{ label: "request", value: "00000000-0000-4000-8000-000000000001" }] }),
    entry({ id: "job:2", at: at(2), level: "fail", kind: "job", source: "job", name: "guidance job", status: "failed",
      code: "OUTPUT_VALIDATION_FAILED", duration_ms: 21_480,
      reasons: ["1:prohibited_certainty/rules_out_risk@claims[0].text", "2:third_person@actions[0].rationale"],
      reason: "The first draft was rejected: a statement was judged to rule out a risk. Nothing was published.",
      detail: [{ label: "job", value: "11111111-1111-4111-8111-111111111111" }, { label: "inference ms", value: "20112.5" }] }),
    entry({ id: "job:3", at: at(3), level: "ok", kind: "job", source: "job", name: "scenario_prepare job",
      status: "succeeded", duration_ms: 14_200 }),
    entry({ id: "health:4", at: at(4), level: "info", kind: "health", source: "health", name: "readiness now",
      status: "ready" }),
    entry({ id: "model:5", at: hour(), precision: "hour", level: "ok", kind: "model", source: "model_call",
      name: "guidance", status: "ok", duration_ms: 9_800,
      detail: [{ label: "prompt tokens", value: "2048" }, { label: "completion tokens", value: "612" }] }),
    entry({ id: "event:6", at: hour(), precision: "hour", level: "warn", kind: "safety", source: "event",
      name: "urgent_interrupt", status: "urgent", code: "RED_FLAG_DESCRIBED" }),
  ],
});

type Route = import("@playwright/test").Route;
type Row = ReturnType<typeof SNAPSHOT>["entries"][number];
/**
 * #577: a fake getLogs over these rows that filters like the server (tests/acceptance/test_R38.py): level (repeatable),
 * kind and q over every row, level counts without the level filter, pages of `size` rows that `before` continues.
 */
function serveLogs(rows: Row[] = SNAPSHOT().entries, size = 500, asked: URL[] = []) {
  return (route: Route) => {
    const url = new URL(route.request().url());
    asked.push(url);
    const levels = url.searchParams.getAll("level");
    const kind = url.searchParams.get("kind");
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const r = rows as unknown as Record<string, unknown>[];
    const pool = r.filter((e) => (!kind || e.kind === kind) && (!q || JSON.stringify([e.name, e.status, e.code, e.kind,
      e.source, e.reason, e.reasons, e.detail]).toLowerCase().includes(q)));
    const level_counts: Record<string, number> = { ok: 0, warn: 0, fail: 0, info: 0 };
    for (const e of pool) level_counts[e.level as string] += 1;
    const match = pool.filter((e) => !levels.length || levels.includes(e.level as string));
    const from = Number(url.searchParams.get("before") ?? 0);
    const next = from + size < match.length ? String(from + size) : null;
    return route.fulfill({ json: { ...SNAPSHOT(), entries: match.slice(from, from + size), truncated: next !== null,
      next_before: next, level_counts, total: match.length } });
  };
}

test("#548 the Logs view: newest first, coloured by level with its word, filters, search and expandable rows", { tag: "@mobile" }, async ({ page }) => {
  await page.route("**/presenter-api/v1/presenter/logs*", serveLogs());
  await presenterLogs(page);
  await expect(page.getByRole("link", { name: "Logs" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("Readiness: ready")).toBeVisible();
  const rows = page.locator(".log-row");
  await expect(rows).toHaveCount(6);
  await expect(rows.locator(".log-name")).toHaveText(["GET /cases/{case_id}", "guidance job", "scenario_prepare job",
    "readiness now", "guidance", "urgent_interrupt"]);
  await expect(rows.locator(".log-level")).toHaveText(["WARN", "FAIL", "OK", "INFO", "OK", "WARN"]);
  await expect(rows.nth(0).locator(".log-time")).toHaveText(/^\d{2}:\d{2}:\d{2}$/);
  await expect(rows.nth(4).locator(".log-time")).toHaveText(/^\d{2}:xx$/); // kept to the hour only
  expect(await rows.locator(".log-time").first().evaluate((el) => getComputedStyle(el).fontFamily)).toMatch(/mono|Menlo|Consolas/i);
  // Colours: green OK, amber WARN, red FAIL, grey INFO, each word readable on its tint (WCAG AA 4.5:1).
  const colours = await page.evaluate(() => {
    const lum = (c: string) => {
      const [r, g, b] = (c.match(/\d+(\.\d+)?/g) ?? []).slice(0, 3).map((v) => Number(v) / 255)
        .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    return [...document.querySelectorAll<HTMLElement>(".log-level")].map((el) => {
      const s = getComputedStyle(el);
      const [a, b] = [lum(s.color), lum(s.backgroundColor)].sort((x, y) => y - x);
      return { text: el.textContent, color: s.color, ratio: (a + 0.05) / (b + 0.05),
        stripe: getComputedStyle(el.closest(".log-row")!).borderLeftColor };
    });
  });
  for (const c of colours) expect(c.ratio, `${c.text} contrast`).toBeGreaterThanOrEqual(4.5);
  const hue = (word: string) => colours.find((c) => c.text === word)!;
  expect(hue("OK").stripe).toBe("rgb(30, 142, 90)"); // --green
  expect(hue("WARN").stripe).toBe("rgb(194, 122, 18)"); // --amber
  expect(hue("FAIL").stripe).toBe("rgb(180, 35, 24)"); // --urgent
  expect(hue("INFO").stripe).toBe("rgb(91, 112, 131)"); // --slate
  // A row expands to its detail: the #538 rejection reasons, the job ID and timings.
  const failed = rows.nth(1).getByRole("button");
  await expect(failed).toHaveAttribute("aria-expanded", "false");
  await failed.click();
  await expect(failed).toHaveAttribute("aria-expanded", "true");
  await expect(rows.nth(1).locator(".log-reason")).toHaveText(/^The first draft was rejected/); // #550 plain words
  const detail = rows.nth(1).locator(".log-detail");
  await expect(detail).toContainText("1:prohibited_certainty/rules_out_risk@claims[0].text");
  await expect(detail).toContainText("2:third_person@actions[0].rationale");
  await expect(detail).toContainText("11111111-1111-4111-8111-111111111111");
  await failed.click();
  await expect(detail).toHaveCount(0);
  // Level filters (pressed buttons with counts), kind filter and text search.
  await page.getByRole("button", { name: /^OK/ }).click();
  await expect(page.getByRole("button", { name: /^OK/ })).toHaveAttribute("aria-pressed", "false");
  await expect(rows).toHaveCount(4);
  await page.getByRole("button", { name: /^OK/ }).click();
  await page.getByLabel("Kind").selectOption({ label: "Jobs" });
  await expect(rows.locator(".log-name")).toHaveText(["guidance job", "scenario_prepare job"]);
  await expect(page.getByRole("button", { name: /^Failures/ })).toContainText("1");
  await page.getByLabel("Kind").selectOption({ label: "All kinds" });
  await page.getByLabel("Search").fill("third_person");
  await expect(rows.locator(".log-name")).toHaveText(["guidance job"]);
  await page.getByLabel("Search").fill("nothing like this");
  await expect(page.getByText("No entries match these filters.")).toBeVisible();
  await page.getByLabel("Search").fill("");
  await expect(rows).toHaveCount(6);
  if (page.viewportSize()!.width <= 400) {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  }
});

test("#548 the Logs view refreshes every 5 s until paused, and copies the shown rows as text", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.clock.install();
  let reads = 0;
  const serve = serveLogs();
  await page.route("**/presenter-api/v1/presenter/logs*", (route) => {
    reads += 1;
    return serve(route);
  });
  await presenterLogs(page);
  await expect(page.locator(".log-row")).toHaveCount(6);
  const first = reads;
  await page.clock.runFor(5_100);
  await expect.poll(() => reads).toBe(first + 1);
  await page.getByRole("button", { name: "Pause auto-refresh" }).click();
  await expect(page.getByRole("button", { name: "Resume auto-refresh" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("status").filter({ hasText: "Auto-refresh paused." })).toBeVisible();
  await page.clock.runFor(16_000);
  expect(reads).toBe(first + 1); // paused: no reads
  await page.getByRole("button", { name: "Refresh now" }).click();
  await expect.poll(() => reads).toBe(first + 2);
  await page.getByRole("button", { name: "Resume auto-refresh" }).click();
  await page.clock.runFor(5_100);
  await expect.poll(() => reads).toBe(first + 3);
  // Copy as text: one line per shown row, filters applied.
  await page.getByLabel("Kind").selectOption({ label: "Jobs" });
  await page.getByRole("button", { name: "Copy as text" }).click();
  await expect(page.getByText("Copied 2 lines as text.")).toBeVisible();
  const text = await page.evaluate(() => navigator.clipboard.readText());
  const lines = text.split("\n");
  expect(lines).toHaveLength(3);
  expect(lines[0]).toMatch(/^Aware Care logs · local mode · readiness ready · observed /);
  expect(lines[1]).toMatch(/^\d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2} FAIL job {6}guidance job status=failed code=OUTPUT_VALIDATION_FAILED took=21\.5s reasons=1:prohibited_certainty\/rules_out_risk@claims\[0\]\.text,2:third_person@actions\[0\]\.rationale reason="The first draft was rejected: .+ Nothing was published\." job=1{8}-/);
  expect(lines[2]).toContain("OK   job      scenario_prepare job status=succeeded took=14.2s");
});

test("#577 the filters and search reach every kept row on the server, and Load older reads the next page", async ({ page }) => {
  // The failure is the oldest row, beyond the first page of two.
  const rows = SNAPSHOT().entries;
  const failure = rows.splice(1, 1)[0];
  rows.push(failure);
  const asked: URL[] = [];
  await page.route("**/presenter-api/v1/presenter/logs*", serveLogs(rows, 2, asked));
  await presenterLogs(page);
  const names = page.locator(".log-row .log-name");
  await expect(names).toHaveText(["GET /cases/{case_id}", "scenario_prepare job"]);
  await expect(page.getByText("Showing 2 of 6 (the newest).")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Failures/ })).toContainText("1"); // counted over every row
  // Load older appends the next page and pauses auto-refresh, which would drop it; the last page has no button.
  await page.getByRole("button", { name: "Load older" }).click();
  await expect(names).toHaveCount(4);
  await expect(page.getByRole("status").filter({ hasText: "Auto-refresh paused while older rows are shown." })).toBeVisible();
  await page.getByRole("button", { name: "Load older" }).click();
  await expect(names).toHaveCount(6);
  await expect(names.last()).toHaveText("guidance job");
  await expect(page.getByRole("button", { name: "Load older" })).toHaveCount(0);
  // Failures only: the server is asked for level=fail and finds the oldest row at once.
  await page.getByRole("button", { name: "Resume auto-refresh" }).click();
  for (const label of [/^Warnings/, /^OK/, /^Info/]) await page.getByRole("button", { name: label }).click();
  await expect(names).toHaveText(["guidance job"]);
  expect(asked.at(-1)!.searchParams.getAll("level")).toEqual(["fail"]);
  // The search goes to the server too.
  for (const label of [/^Warnings/, /^OK/, /^Info/]) await page.getByRole("button", { name: label }).click();
  await page.getByLabel("Search").fill("third_person");
  await expect(names).toHaveText(["guidance job"]);
  expect(asked.at(-1)!.searchParams.get("q")).toBe("third_person");
});

test.describe("#548 Logs from the real API", () => {
  test.use({ bypassCSP: true }); // only the test tool (axe) is injected
  test("#548 the Logs view shows this demo's real jobs and events, content-free and axe clean at 1440 and 360", { tag: "@mobile" }, async ({ page }) => {
    await page.goto(`${PRESENTER}/presenter/scenarios`);
    await page.getByRole("button", { name: "Start presenter session" }).click();
    await page.getByRole("button", { name: "Run on HP ZGX Nano: Self-care guidance" }).click();
    await expect(page.getByRole("dialog")).toContainText("Self-care guidance is ready", { timeout: 30_000 });
    await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
    await page.goto(LOGS);
    await expect(page.getByRole("heading", { level: 2, name: "Logs" })).toBeVisible();
    const names = page.locator(".log-row .log-name");
    await expect(names.filter({ hasText: /^scenario_prepare job$/ }).first()).toBeVisible();
    await expect(names.filter({ hasText: /^guidance job$/ }).first()).toBeVisible();
    await expect(names.filter({ hasText: /^scenario_loaded$/ }).first()).toBeVisible();
    await expect(names.filter({ hasText: /^session_started$/ }).first()).toBeVisible();
    // No session secret: a cookie, a CSRF token, a token hash or a bearer token. The content-free error code of a
    // refused write (CSRF_REJECTED, e.g. #610's old tab in another test on this stack) is a logged code, not a secret.
    await expect(page.locator("main")).not.toContainText(/cookie|csrf.?token|token_hash|Bearer/i);
    await page.addScriptTag({ path: require("node:path").join(__dirname, "../../apps/web/node_modules/axe-core/axe.min.js") });
    await animationsSettled(page);
    const violations = await page.evaluate(async () => {
      // @ts-expect-error axe is injected above
      const result = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] } });
      return result.violations.map((v: { id: string }) => v.id);
    });
    expect(violations).toEqual([]);
    await page.locator(".log-row").first().getByRole("button").click();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
