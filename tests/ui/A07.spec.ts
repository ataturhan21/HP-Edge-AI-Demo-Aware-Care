// A07 Your guidance (R14, R24, R37). Structured, labeled mock output; limited-information outcome.
import { expect, test, type Page } from "@playwright/test";
// #188: the history action is named for the next step.
const RESUME = /^(Continue questions|Review answers|View guidance|View urgent help|View limits)$/;
import { answerAll, enterConcern, expectNoHorizontalOverflow, startSession, toGuidance } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

test("structured synthetic guidance is labeled as mock output", async ({ page }) => {
  await toGuidance(page);
  await expect(page.getByText("Mock mode: scripted synthetic outcome")).toBeVisible();
  for (const h of ["Possible explanations", "Questions to ask a clinician", "When to seek help sooner", "Limits of this result"])
    await expect(page.getByRole("heading", { name: h })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Routine clinician visit" })).toBeVisible();
  await expect(page.getByText("Limited information", { exact: true })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test("the result always shows a possible explanation, never a blank card", async ({ page }) => {
  // ADR-015 (#105): explanations come from general medical knowledge; mock mode shows a scripted, labeled one.
  await toGuidance(page);
  const card = page.locator("section.card", { has: page.getByRole("heading", { name: "Possible explanations" }) });
  await expect(card).toContainText("Scripted illustrative explanation");
  await expect(card).not.toContainText("Not shown without approved sources");
  await expect(card).not.toContainText("No possible explanations are shown");
  // #456: in mock mode the limit says the explanation is scripted; it never claims general medical knowledge.
  const limits = page.locator("section.card", { has: page.getByRole("heading", { name: "Limits of this result" }) });
  await expect(limits.locator("li", { hasText: "The possible explanation is scripted illustrative text" })).toBeVisible();
  await expect(limits).not.toContainText(/general medical knowledge/i);
  // #105 criterion 4: the origin is stated on the card itself; mock mode says scripted, never "AI".
  await expect(card.getByTestId("explanations-origin")).toHaveText(
    "Scripted illustrative explanation for this synthetic demo, not from an AI model or reviewed sources.");
});

test("limited-information outcome when every question is skipped", async ({ page }) => {
  await toGuidance(page, () => "skip");
  await expect(page.getByText("Limited information", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Not determined" })).toBeVisible();
  await expect(page.getByText(/Self-care/)).toHaveCount(0);
  await expect(page.locator("li", { hasText: "Not answered:" })).toHaveCount(10);
});

test("partial gaps are flagged without self-care reassurance", async ({ page }) => {
  await toGuidance(page, (s) => (s === 2 || s === 6 ? "unknown" : "answer"));
  await expect(page.getByText("Limited information", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Routine clinician visit" })).toBeVisible();
  await expect(page.locator("li", { hasText: "Not answered:" })).toHaveCount(2);
});

test("retained links to a previous revision's guidance and export are refused after a clinical edit", async ({ page }) => {
  // T-R09-S02: the browser keeps the old guidance URL and an export link; a clinical edit (here from another tab
  // of the same session) makes them stale, and neither the route nor the API presents them as current.
  const caseId = await toGuidance(page);
  const guidanceUrl = page.url();
  const exportId = await page.evaluate(async (id) => {
    const read = await fetch(`/api/v1/cases/${id}`, { credentials: "same-origin" });
    const csrf = read.headers.get("X-CSRF-Token") ?? "";
    const rev = (await read.json()).case.revision;
    const headers = { "Content-Type": "application/json", "X-CSRF-Token": csrf };
    const job = await (await fetch(`/api/v1/cases/${id}/exports`, { method: "POST", credentials: "same-origin",
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ expected_revision: rev, user_reviewed: true }) })).json();
    let done = job;
    for (let i = 0; i < 100 && !["succeeded", "failed"].includes(done.status); i++) {
      await new Promise((r) => setTimeout(r, 100));
      done = await (await fetch(`/api/v1/jobs/${job.id}`, { credentials: "same-origin" })).json();
    }
    const edit = await fetch(`/api/v1/cases/${id}`, { method: "PATCH", credentials: "same-origin", headers,
      body: JSON.stringify({ expected_revision: rev, concern: "Edited in another tab." }) });
    if (!edit.ok) throw new Error(`edit failed ${edit.status}`);
    return done.result_id as string;
  }, caseId);
  expect(exportId).toBeTruthy();
  await page.goto(guidanceUrl);
  // The route guard sends the stale guidance link to the case's current step; no old guidance is rendered.
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/review$`));
  await expect(page.getByRole("heading", { level: 1, name: "Review your case" })).toBeVisible();
  await expect(page.getByText("Edited in another tab.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your guidance" })).toHaveCount(0);
  await expect(page.getByText("Possible explanations")).toHaveCount(0);
  const download = await page.request.get(`/api/v1/exports/${exportId}/download`);
  expect([404, 409]).toContain(download.status());
  expect((await download.body()).subarray(0, 5).toString()).not.toBe("%PDF-");
});

test("a failed generation shows the reviewed fallback, no partial result, and keeps the answers", async ({ context }) => {
  // The presenter loads the scripted failure scenario; the same browser continues it on the patient site (O03).
  const presenter = await context.newPage();
  await presenter.goto("http://127.0.0.1:15174/presenter/scenarios/more"); // #358: full journeys
  await presenter.getByRole("button", { name: "Start presenter session" }).click();
  await presenter.getByRole("button", { name: "Load scenario: Guidance unavailable" }).click();
  // #688: the journey opens in this window, as the Demo patient; its History lists the demo patient's case.
  await expect(presenter).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/questions$/);
  const page = presenter;
  const guidanceReads: number[] = [];
  page.on("response", (r) => {
    if (r.request().method() === "GET" && new URL(r.url()).pathname.endsWith("/guidance")) guidanceReads.push(r.status());
  });
  await page.goto("http://127.0.0.1:15174/app/history");
  await page.locator("tbody tr").getByRole("button", { name: RESUME }).click();
  await answerAll(page);
  const answers = await page.locator(".datum").allTextContents();
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Guidance is unavailable right now" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("This is a service problem, not a finding about your health. Your answers are kept.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  for (const h of ["Your guidance", "Possible explanations", "Questions to ask a clinician"])
    await expect(page.getByRole("heading", { name: h })).toHaveCount(0);
  await expect(page.getByText("Mock mode: scripted synthetic outcome")).toHaveCount(0);
  expect(guidanceReads.filter((s) => s === 200)).toEqual([]);
  // The explicit retry returns to review with every answer as it was.
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page).toHaveURL(/\/review$/);
  await expect(page.getByRole("heading", { name: "Review your case" })).toBeVisible();
  expect(await page.locator(".datum").allTextContents()).toEqual(answers);
});

test("an empty explanations list shows an honest empty state, not a blank card", async ({ page }) => {
  // #103: should the list ever be empty (ADR-015 makes explanations mandatory), the card must say so.
  await page.route(/\/api\/v1\/cases\/[^/]+\/guidance$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, possible_explanations: [] } });
  });
  await toGuidance(page);
  const card = page.locator("section.card", { has: page.getByRole("heading", { name: "Possible explanations" }) });
  await expect(card).toContainText("No possible explanations are shown for this result.");
  await expect(card).toContainText("Ask a clinician what could be causing it.");
});

test("a local result labels its explanations as the AI's general medical knowledge on the card", async ({ page }) => {
  // #105 criterion 4. The suite runs in mock mode, so the published guidance is shown as a local result here.
  await page.route(/\/api\/v1\/cases\/[^/]+\/guidance$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), model_manifest_id: "qwen3.6-35b-a3b-fp8@95a723d0-2026-10-15" } });
  });
  await toGuidance(page);
  const card = page.locator("section.card", { has: page.getByRole("heading", { name: "Possible explanations" }) });
  await expect(card.getByTestId("explanations-origin")).toHaveText(
    "From the AI's general medical knowledge, not checked against reviewed sources. It can be wrong and is not a diagnosis.");
  await expect(card).not.toContainText("Scripted illustrative explanation for this synthetic demo");
});

// QA 2026-10-22 (journey group).
const CASE_READ = /\/api\/v1\/cases\/[0-9a-f-]{36}$/;

/** Answers every case read as `state` (with its allowed actions), as if the server were at that step. */
async function caseReadAs(page: Page, state: string, extra: Record<string, unknown> = {}, actions?: string[]) {
  await page.route(CASE_READ, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, case: { ...body.case, state, ...extra },
      allowed_actions: actions ?? body.allowed_actions } });
  });
}

test("#415 the preparing and failed views offer no 'Back to review' that loops back here", async ({ page }) => {
  const caseId = await toGuidance(page);
  await caseReadAs(page, "generating");
  await page.goto(`/app/cases/${caseId}/guidance`);
  await expect(page.getByRole("heading", { name: "Preparing your guidance" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to review" })).toHaveCount(0);
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await caseReadAs(page, "limited", { limited_reason: "generation_failed_recoverable" }, ["view_limits", "retry", "view_history", "delete"]);
  await page.goto(`/app/cases/${caseId}/guidance`);
  await expect(page.getByRole("heading", { name: "Guidance is unavailable right now" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to review" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByText("Retry shows your answers for review again; then generate guidance.")).toBeVisible();
});

test("#453 the guidance wait counts from when the job started, also after a reload", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  await answerAll(page);
  const startedAt = new Date(Date.now() - 20_000).toISOString();
  const JOB = /\/api\/v1\/jobs\/[0-9a-f-]{36}$/;
  // The job keeps running, and started 20 s ago.
  await page.route(JOB, async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    await route.fulfill({ response, json: { ...job, status: "running", result_id: null, result_type: null,
      finished_at: null, created_at: startedAt } });
  });
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Preparing your guidance" })).toBeVisible();
  const elapsed = page.locator(".generating-elapsed");
  await expect(elapsed).toHaveText(/^([2-9]\d|\d{3,}) s$/);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Preparing your guidance" })).toBeVisible();
  await expect(elapsed).toHaveText(/^([2-9]\d|\d{3,}) s$/);
  await expect(page.getByText("Taking a little longer than usual. It is still working.")).toBeVisible();
  // Back from another page, without the job in the page's state: the case's change into generating is the start.
  await page.unrouteAll({ behavior: "wait" }); // #506: a job poll may still be in the handler (the page's only route)
  await caseReadAs(page, "generating", { updated_at: startedAt });
  await page.goto(`/app/cases/${caseId}/guidance`);
  await expect(page.getByRole("heading", { name: "Preparing your guidance" })).toBeVisible();
  await expect(elapsed).toHaveText(/^([2-9]\d|\d{3,}) s$/);
});
