// Shared browser helpers for tests/ui (registered in spec/traceability.yaml).
// They drive only the real UI against the isolated mock-mode stack in apps/web/playwright.config.ts.
import { expect, type Page } from "@playwright/test";

export const CONCERN = "I have recurring headaches after long workdays. I would like to understand the next step.";

/**
 * R34 (ADR-014): the only hosts an off-device request may reach, for static assets (GET of a font, stylesheet,
 * script or image). Empty while every asset is bundled; adding a host is a reviewed change to this list.
 */
export const ALLOWED_ASSET_HOSTS: readonly string[] = [];
const ANALYTICS = /(google-analytics|googletagmanager|doubleclick|segment\.(io|com)|mixpanel|amplitude|hotjar|fullstory|clarity\.ms|logrocket|heap(analytics)?\.|sentry|datadoghq|newrelic|nr-data|bugsnag|smartlook|mouseflow|posthog)/i;
const IDENTIFIER = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\/app\/cases\//i;
const ASSET_TYPES = new Set(["font", "stylesheet", "script", "image"]);

/**
 * Collects every request that breaks the R34 boundary (ADR-014): the LLM stays on the device and no patient data
 * leaves it. Requests to the loopback test gateways are the device itself. Anything else must be a GET of a static
 * asset from an allowed host, carry no body, no case or session identifier in its URL or referrer, and never reach
 * /api or an analytics or session-replay host.
 */
export function guardNetwork(page: Page): string[] {
  const offenders: string[] = [];
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (url.protocol.startsWith("data") || url.protocol.startsWith("blob")) return;
    const local = url.hostname === "127.0.0.1" && (url.port === "15174" || url.port === "");
    if (local) return;
    const reasons: string[] = [];
    if (!ALLOWED_ASSET_HOSTS.includes(url.hostname)) reasons.push("host not allowed");
    if (req.method() !== "GET") reasons.push(`method ${req.method()}`);
    if (url.pathname.startsWith("/api")) reasons.push("API path");
    if (ANALYTICS.test(url.hostname)) reasons.push("analytics or session replay");
    if (!ASSET_TYPES.has(req.resourceType())) reasons.push(`resource ${req.resourceType()}`);
    if (req.postData()) reasons.push("request body");
    if (IDENTIFIER.test(req.url()) || IDENTIFIER.test(req.headers()["referer"] ?? "")) reasons.push("case or session identifier");
    if (reasons.length) offenders.push(`${req.url()} (${reasons.join(", ")})`);
  });
  return offenders;
}

/** #487: the one test address of both roles (playwright.config.ts): /api is the patient API, /presenter-api the
 *  presenter API (signed by the test gateway with a throwaway key). */
export const ADDRESS = "http://127.0.0.1:15174";

/** #487: a device without presenter access. The gateway answers /presenter-api itself with 403 PRESENTER_REQUIRED and
 *  no X-AwareCare-Gateway hint (infra/deploy/presenter-api-disabled.conf); nothing reaches the API. */
export async function presenterAccessOff(page: Page) {
  await page.route("**/presenter-api/**", (route) => route.fulfill({
    status: 403, contentType: "application/json", headers: { "Cache-Control": "no-store" },
    body: JSON.stringify({ code: "PRESENTER_REQUIRED", message: "Presenter access is not enabled on this device.",
      field_errors: [], retryable: false }),
  }));
}

/** #487: the API paths a page requests, in order (patient /api/... and presenter /presenter-api/...). */
export function apiCalls(page: Page): string[] {
  const calls: string[] = [];
  page.on("request", (req) => {
    const path = new URL(req.url()).pathname;
    if (path.startsWith("/api/") || path.startsWith("/presenter-api/")) calls.push(path);
  });
  return calls;
}

export async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "horizontal page overflow").toBeLessThanOrEqual(0);
}

/**
 * Waits for the server response that a UI step depends on, instead of giving the whole request chain Playwright's
 * default 5 s (issues #16, #31). Create the wait before the action that triggers the request.
 */
export function serverStep(page: Page, method: string, pathEnd: string, status?: number) {
  return page.waitForResponse(
    (r) => r.request().method() === method && new URL(r.url()).pathname.endsWith(pathEnd)
      && (status === undefined || r.status() === status),
    { timeout: 45_000 },
  );
}

/**
 * #501: tests that control the page clock (page.clock) while the API runs on real time. Every authenticated response
 * re-anchors the page to the server's clock: it carries the session expiry with the server's Date (SessionExpiry in
 * api/client.ts), which also times the guidance wait (A07). A response the page handles AFTER a clock jump therefore
 * undoes the jump: the page reads "30 minutes left" again, or "0 s waited". `waitForResponse` resolves when the
 * response reaches the browser, before the page's own code has handled it, and a page often has several such reads in
 * flight (on /app/history: the session probe, the header's resume check and the case list).
 *
 * `trackApi` (call before the page loads) counts each API fetch of the page until the page's code has run on its
 * response: the count drops one task after the fetch settles, after the page's own continuation. `apiSettled` waits
 * until none is left (on two reads in a row), and with `path` until at least one response for it was handled. Jump
 * the clock only after `apiSettled`.
 */
export async function trackApi(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __awareCareApi?: { pending: number; handled: string[] } };
    if (w.__awareCareApi) return;
    const state = (w.__awareCareApi = { pending: 0, handled: [] as string[] });
    // A task after the page's own continuation; MessageChannel is not one of the timers page.clock controls.
    const channel = new MessageChannel();
    const queue: (() => void)[] = [];
    channel.port1.onmessage = () => queue.shift()?.();
    const later = (fn: () => void) => {
      queue.push(fn);
      channel.port2.postMessage(null);
    };
    const original = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url, location.href);
      if (!/^\/(api|presenter-api)\/v1\//.test(url.pathname)) return original(input, init);
      state.pending++;
      const response = original(input, init);
      response.then(
        () => later(() => { state.pending--; state.handled.push(url.pathname); }),
        () => later(() => { state.pending--; }),
      );
      return response;
    };
  });
}

export async function apiSettled(page: Page, path?: string) {
  let last = "";
  await expect.poll(async () => {
    const now = await page.evaluate((p) => {
      const t = (window as unknown as { __awareCareApi?: { pending: number; handled: string[] } }).__awareCareApi;
      if (!t) return "untracked: call trackApi before the page loads";
      const seen = p === undefined || t.handled.some((h) => h.includes(p));
      return `${t.pending}:${t.handled.length}:${seen}`;
    }, path).catch(() => "navigating");
    const settled = now === last && now.startsWith("0:") && now.endsWith(":true");
    last = now;
    return settled ? "settled" : now;
  }, { message: "the page's API reads were handled", intervals: [50] }).toBe("settled");
}

/** Consent only; leaves the browser on A02. */
export async function startSessionOnly(page: Page) {
  await page.goto("/app/start");
  await page.getByLabel("Yes, I am 18 or older").check();
  await page.getByLabel("I understand and accept these terms.").check();
  // A01 may retry once after fetching readiness (pre-session nonce); wait for the successful creation.
  const created = serverStep(page, "POST", "/api/v1/sessions", 201);
  await page.getByRole("button", { name: "Accept and begin" }).click();
  await created;
  await expect(page).toHaveURL(/\/app\/profile$/);
}

export async function startSession(page: Page) {
  await startSessionOnly(page);
  await page.getByRole("button", { name: "Use for this session" }).click();
  await expect(page).toHaveURL(/\/app\/new$/);
}

/** Answers the A03 red-flag checklist (ADR-003) with "None of these apply". */
export async function noRedFlags(page: Page) {
  await page.getByRole("checkbox", { name: "None of these apply" }).check();
}

export async function enterConcern(page: Page, concern = CONCERN): Promise<string> {
  await page.getByLabel("Main concern").fill(concern);
  await noRedFlags(page);
  const created = serverStep(page, "POST", "/api/v1/cases", 201);
  await page.getByRole("button", { name: "Continue" }).click();
  await created;
  await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/records$/);
  const caseId = page.url().split("/cases/")[1].split("/")[0];
  // A05 reads the case and asks for the first question; wait for that answer before handing over.
  const firstQuestion = serverStep(page, "POST", "/questions/next");
  await page.getByRole("button", { name: "Skip and continue" }).click();
  expect((await firstQuestion).ok(), "first question request").toBe(true);
  await expect(page).toHaveURL(/\/questions$/);
  return caseId;
}

export type Strategy = (slot: number) => "answer" | "unknown" | "skip";

/** Answers the issued question shown on A05 according to its response type. */
/**
 * #506: waits until A05 shows a question that is open for an answer and returns its slot, or null once the case is on
 * review (A06). After Submit, A05 keeps the answered question on screen, its Submit button busy ("Working…"), while it
 * saves the answer and asks for the next question, so the heading alone does not say whether that question is still
 * open. A step that read it then answered the old question again, or waited for a response that had already come
 * (intuitive2 #228 in CI). An enabled "Submit answer" means no answer is being sent.
 */
export async function openQuestion(page: Page): Promise<number | null> {
  const submit = page.getByRole("button", { name: "Submit answer" });
  const review = page.getByRole("heading", { name: "Review your case" });
  await expect(submit.or(review)).toBeVisible();
  if (await review.count()) {
    await expect(page).toHaveURL(/\/review$/);
    return null;
  }
  await expect(submit).toBeEnabled();
  return Number((await page.getByText(/^Question \d+ of up to 10$/).textContent())!.match(/Question (\d+)/)![1]);
}

export async function answerCurrent(page: Page, how: "answer" | "unknown" | "skip") {
  const form = page.locator("form.card");
  expect(await openQuestion(page), "a question open for an answer").not.toBeNull();
  await expect(form.locator("input, select, textarea").first()).toBeVisible();
  if (how === "unknown") {
    // #185: a question that offers "Not sure" as a choice shows no separate button; the choice is the answer.
    const button = page.getByRole("button", { name: "Not sure" });
    if (await button.count()) return button.click();
    await form.getByRole("radio", { name: "Not sure" }).check();
    return page.getByRole("button", { name: "Submit answer" }).click();
  }
  if (how === "skip") return page.getByRole("button", { name: "Skip", exact: true }).click();
  // #228: a scale is a radio group of values; the journey answers 4, as it did with the old dropdown.
  if (await form.locator("fieldset.scale").count()) await form.locator('fieldset.scale input[value="4"]').check();
  else if (await form.locator("input[type=radio]").count()) await form.locator("input[type=radio]").first().check();
  else if (await form.locator("input[type=checkbox]").count()) await form.locator("input[type=checkbox]").first().check();
  else await form.locator("textarea").fill("No changes yet.");
  await page.getByRole("button", { name: "Submit answer" }).click();
}

/** Answers until the server requires review; returns the issued slot numbers seen. */
export async function answerAll(page: Page, strategy: Strategy = () => "answer"): Promise<number[]> {
  const slots: number[] = [];
  for (let guard = 0; guard < 11; guard++) {
    const head = page.getByText(/^Question \d+ of up to 10$/);
    const slot = await openQuestion(page); // #506: never the question whose answer a caller just sent
    if (slot === null) return slots;
    slots.push(slot);
    // A05 saves the answer, re-reads the case and then asks for the next question; only that last
    // response changes the page. Wait for it (bounded by the test timeout) instead of giving the whole
    // three-request chain a fixed 5 s, which flaked on slow CI runners (issue #16).
    const advanced = serverStep(page, "POST", "/questions/next");
    await answerCurrent(page, strategy(slot));
    expect((await advanced).ok(), "next question request").toBe(true);
    await expect(head.filter({ hasText: `Question ${slot} of` })).toHaveCount(0);
  }
  await expect(page).toHaveURL(/\/review$/);
  return slots;
}

export async function confirmAndGenerate(page: Page) {
  await expect(page.getByRole("heading", { name: "Review your case" })).toBeVisible();
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page).toHaveURL(/\/guidance$/);
  // #506: exact, since "Preparing your guidance" (the wait) contains it; a substring match returned before the result.
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 15_000 });
}

export async function toGuidance(page: Page, strategy?: Strategy): Promise<string> {
  await startSession(page);
  const caseId = await enterConcern(page);
  await answerAll(page, strategy);
  await confirmAndGenerate(page);
  return caseId;
}

/**
 * #604: waits until every finite CSS animation and transition on the page has finished (infinite ones, such as a
 * spinner, are left running). Call it right before an axe scan: an entrance fade (`.notice` and `.modal` rise from
 * opacity 0) still running makes axe measure blended text colours, so `color-contrast` failed now and then under CI
 * load (`/telemetry` "div > strong" in a11y.spec.ts; the flow dialog in improve-quick-flows.spec.ts:421).
 */
export async function animationsSettled(page: Page) {
  await page.evaluate(() => Promise.all(document.getAnimations()
    .filter((a) => Number.isFinite(a.effect?.getComputedTiming().endTime as number))
    .map((a) => a.finished.then(() => undefined, () => undefined))));
}
