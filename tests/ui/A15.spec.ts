// A15 Urgent action (R15, R17). Public help without a session; restart requires a new case.
import { expect, test } from "@playwright/test";
import { answerAll, answerCurrent, enterConcern, expectNoHorizontalOverflow, startSession } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

test("urgent help is reachable without a session and discloses no case", async ({ page }) => {
  await page.goto("/app/cases/00000000-0000-4000-8000-000000000000/urgent");
  await expect(page.getByRole("heading", { name: "Seek urgent help now" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Seek urgent help (call 911)" })).toHaveAttribute("href", "tel:911");
  await expectNoHorizontalOverflow(page);
});

test("after an urgent interrupt a different case starts fresh", async ({ page }) => {
  await startSession(page);
  const urgentCase = await enterConcern(page);
  await page.getByRole("button", { name: "Simulate urgent answer" }).click();
  await expect(page.getByRole("heading", { name: "Seek urgent help now" })).toBeVisible();
  await page.getByRole("main").getByRole("link", { name: "Start a new consultation" }).click();
  const next = await enterConcern(page, "A different fictional concern.");
  expect(next).not.toBe(urgentCase);
  await answerCurrent(page, "answer");
  await expect(page.getByText("Question 2 of up to 10")).toBeVisible();
});

// general-adult-3 (#79): the local red-flag screen finds a red flag in the person's own words while guidance is
// generated. The job ends with RED_FLAG_DESCRIBED_<LEVEL> and the case is urgent; A07 routes to A15 with that level.
// Mock mode has no screen, so the job and case reads are rewritten to what the local API returns in that case.
const MESSAGES = {
  emergency: "Call 911 now or go to the nearest emergency department. Do not wait for this consultation.",
  urgent_clinician: "Contact a clinician or urgent care today. Do not wait for a routine appointment.",
};

async function describedRedFlag(page: import("@playwright/test").Page, errorCode: string) {
  await page.route("**/v1/jobs/*", async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    await route.fulfill({ response, json: { ...job, status: "failed", error_code: errorCode, result_id: null, result_type: null } });
  });
  await page.route(/\/api\/v1\/cases\/[^/]+$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const read = await response.json();
    await route.fulfill({ response, json: { ...read, case: { ...read.case, state: "urgent" },
      allowed_actions: ["view_urgent", "view_history", "delete"] } });
  });
}

for (const [code, level, title] of [
  ["RED_FLAG_DESCRIBED_EMERGENCY", "emergency", "Emergency"],
  ["RED_FLAG_DESCRIBED_URGENT_CLINICIAN", "urgent_clinician", "Urgent: today"],
] as const) {
  test(`a red flag described in the person's words (${level}) routes from guidance to urgent help`, async ({ page }) => {
    await startSession(page);
    const caseId = await enterConcern(page, "Back pain, and since this morning I cannot start to pee.");
    await answerAll(page);
    await page.getByLabel("I confirm this information is complete as far as I know.").check();
    await describedRedFlag(page, code);
    await page.getByRole("button", { name: "Generate guidance" }).click();
    await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/urgent$`), { timeout: 15_000 });
    await expect(page.getByRole("heading", { name: "Seek urgent help now" })).toBeVisible();
    await expect(page.getByText(title, { exact: true })).toBeVisible();
    await expect(page.getByText(MESSAGES[level])).toBeVisible();
    for (const h of ["Your guidance", "Possible explanations", "Guidance is unavailable right now"])
      await expect(page.getByRole("heading", { name: h })).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  });
}

test("an urgent case opened directly shows no level it was not given", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  await describedRedFlag(page, "RED_FLAG_DESCRIBED_EMERGENCY");
  await page.goto(`/app/cases/${caseId}/urgent`);
  await expect(page.getByRole("heading", { name: "Seek urgent help now" })).toBeVisible();
  await expect(page.getByText(MESSAGES.emergency)).toHaveCount(0);
  await expect(page.getByText(MESSAGES.urgent_clinician)).toHaveCount(0);
});

test("an urgent case reopened in a new tab shows its reviewed level and the end-session action", async ({ page, context }) => {
  // #116: a tab that did not create the session (a presenter scenario handoff, a reload, a later tab) still shows the
  // reviewed message read from the case, without any redirect.
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await page.getByRole("checkbox", { name: "A sudden, severe headache, the worst you have ever had" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  const url = page.url();
  const fresh = await context.newPage();
  await fresh.goto(url);
  await expect(fresh.getByRole("heading", { name: "Seek urgent help now" })).toBeVisible();
  await expect(fresh.getByText("Emergency", { exact: true })).toBeVisible();
  await expect(fresh.getByText(MESSAGES.emergency)).toBeVisible();
  await expect(fresh.getByRole("button", { name: /End session/ })).toBeVisible();
  await expect(fresh).toHaveURL(url); // no session redirect
  await fresh.reload();
  await expect(fresh.getByText("Emergency", { exact: true })).toBeVisible();
});

// #153 (ADR-003 amendment 3): in local mode the red-flag screen reads the concern when the case is created and when
// the concern is edited, so a written emergency interrupts intake at once. The case records the reviewed level
// (`urgent_level`), so a reload keeps the message. Mock mode has no screen, so the case responses are rewritten to what
// the local API returns in that case.
async function writtenRedFlag(page: import("@playwright/test").Page, level: "emergency" | "urgent_clinician",
                              method: "POST" | "PATCH") {
  const urgent = (c: Record<string, unknown>) => ({ ...c, state: "urgent", urgent_level: level });
  let screened = false;  // case reads are rewritten only after the screened create or edit
  await page.route(/\/api\/v1\/cases(\/[^/]+)?$/, async (route) => {
    const m = route.request().method();
    if (m === "GET" && screened) {
      const response = await route.fetch();
      const body = await response.json();
      return route.fulfill({ response, json: { ...body, case: urgent(body.case), allowed_actions: ["view_urgent", "view_history", "delete"] } });
    }
    if (m !== method) return route.continue();
    const response = await route.fetch();
    screened = true;
    await route.fulfill({ response, json: urgent(await response.json()) });
  });
}

for (const [level, title] of [["emergency", "Emergency"], ["urgent_clinician", "Urgent: today"]] as const) {
  test(`a warning sign written in the concern (${level}) goes to urgent help before any question`, async ({ page }) => {
    await startSession(page);
    await page.getByLabel("Main concern").fill("Crushing chest pain spreading to my left arm.");
    await page.getByRole("checkbox", { name: "None of these apply" }).check();
    await writtenRedFlag(page, level, "POST");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/urgent$/);
    await expect(page.getByText(title, { exact: true })).toBeVisible();
    await expect(page.getByText(MESSAGES[level])).toBeVisible();
    await expect(page.getByText(/Question 1 of up to 10/)).toHaveCount(0);
    await page.reload();  // the level comes from the case, not only from the previous screen
    await expect(page.getByText(MESSAGES[level])).toBeVisible();
  });
}

test("a warning sign written in an edited concern goes to urgent help from the review", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page, "A mild headache since Monday.");
  await answerAll(page);
  await writtenRedFlag(page, "emergency", "PATCH");
  await page.getByRole("button", { name: "Edit concern" }).click();
  await page.locator("#concern-edit").fill("Now the worst headache of my life; it came on suddenly.");
  await page.getByRole("button", { name: "Save change" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/urgent$`));
  await expect(page.getByText("Emergency", { exact: true })).toBeVisible();
  await expect(page.getByText(MESSAGES.emergency)).toBeVisible();
});
