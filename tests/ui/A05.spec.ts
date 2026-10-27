// A05 Adaptive questions (R11-R15). Ten issued slots maximum; urgent fixture interrupts intake.
import { expect, test } from "@playwright/test";
import { answerAll, answerCurrent, enterConcern, expectNoHorizontalOverflow, startSession } from "./support/journey";

test("intake issues at most ten questions then requires review", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await expect(page.getByText("Mock mode", { exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  const slots = await answerAll(page, (s) => (s === 3 ? "skip" : s === 5 ? "unknown" : "answer"));
  expect(slots).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  await expect(page).toHaveURL(/\/review$/);
  await expect(page.getByRole("heading", { name: "Your answers (10 questions asked)" })).toBeVisible();
  // Returning to the questions route cannot issue an eleventh prompt.
  await page.goto(page.url().replace(/review$/, "questions"));
  await expect(page).toHaveURL(/\/review$/);
});

test("simulated urgent answer interrupts intake and blocks routine screens", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  await answerCurrent(page, "answer");
  await expect(page.getByText("Question 2 of up to 10")).toBeVisible();
  await page.getByRole("button", { name: "Simulate urgent answer" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/urgent$`));
  await expect(page.getByRole("heading", { name: "Seek urgent help now" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  // Routine questions, review, guidance and summary cannot be reached for this case.
  await page.goto(`/app/cases/${caseId}/questions`);
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/urgent$`));
  await page.goto(`/app/cases/${caseId}/guidance`);
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/urgent$`));
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.getByRole("heading", { name: "Review required" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Download summary/ })).toHaveCount(0);
});

// #37: duration questions (R13). No bundled fixture issues one, so this test serves a test-only synthetic duration
// template by intercepting nextQuestion; the answer request is captured and answered as the API would.
test("a duration question takes an amount and an allowed unit, with field-specific errors", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  const rev = Number((await (await page.request.get(`/api/v1/cases/${caseId}`)).json()).case.revision);
  const question = {
    id: "00000000-0000-4000-8000-0000000000d1", case_id: caseId, slot: 2, template_id: "TEST-DURATION",
    pathway_version: "mock-fixture-1.0.0", issued_revision: rev, response_type: "duration",
    text: "How long has this been going on? (test-only template)", choices: [], required: false,
    reason: "Synthetic test template.", status: "active",
    constraints: { minimum: null, maximum: null, min_selections: null, max_selections: null, max_characters: null,
      lower_anchor: null, upper_anchor: null, allowed_units: ["days", "weeks"] },
  };
  // The same question until it is answered (the dev build's StrictMode may load it twice), then review.
  const bodies: unknown[] = [];
  await page.route(`**/api/v1/cases/${caseId}/questions/next`, async (route) => {
    await route.fulfill({ json: bodies.length === 0 ? { kind: "question", question, case_revision: rev }
      : { kind: "review_required", unresolved_gaps: [], case_revision: rev + 1 } });
  });
  await page.route(`**/api/v1/cases/${caseId}/answers/${question.id}`, async (route) => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({ json: { case_revision: rev + 1, next_action: "review" } });
  });
  await page.reload();
  await expect(page.getByRole("heading", { name: question.text })).toBeVisible();
  const amount = page.getByLabel("How long (number)");
  const unit = page.getByLabel("Unit");
  // Only the allowed units are offered, and nothing is pre-selected.
  await expect(unit.locator("option")).toHaveText(["Choose a unit", "Days", "Weeks"]);
  await expect(amount).toHaveValue("");
  await expect(unit).toHaveValue("");
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page.getByRole("alert")).toHaveText("Enter how long, as a number.");
  await expect(amount).toHaveAttribute("aria-invalid", "true");
  await expect(amount).toHaveAttribute("aria-describedby", "answer-error");
  await amount.fill("-2");
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page.getByRole("alert")).toHaveText("How long must be a number of 0 or more.");
  await amount.fill("2.5");
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page.getByRole("alert")).toHaveText("Choose a unit.");
  await expect(unit).toHaveAttribute("aria-invalid", "true");
  expect(bodies).toEqual([]);
  await expectNoHorizontalOverflow(page);
  await unit.selectOption("weeks");
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page).toHaveURL(/\/review$/);
  expect(bodies).toEqual([{ expected_revision: rev, status: "answered", value: { amount: 2.5, unit: "weeks" } }]);
});

test("a duration question can still be answered “Not sure”", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  const rev = Number((await (await page.request.get(`/api/v1/cases/${caseId}`)).json()).case.revision);
  const id = "00000000-0000-4000-8000-0000000000d2";
  const bodies: unknown[] = [];
  await page.route(`**/api/v1/cases/${caseId}/questions/next`, (route) => {
    return route.fulfill({ json: bodies.length === 0 ? { kind: "question", case_revision: rev, question: {
      id, case_id: caseId, slot: 2, template_id: "TEST-DURATION", pathway_version: "mock-fixture-1.0.0",
      issued_revision: rev, response_type: "duration", text: "Test-only duration question", choices: [],
      required: false, reason: "", status: "active", constraints: { minimum: null, maximum: null, min_selections: null,
        max_selections: null, max_characters: null, lower_anchor: null, upper_anchor: null, allowed_units: ["days"] } } }
      : { kind: "review_required", unresolved_gaps: [], case_revision: rev + 1 } });
  });
  await page.route(`**/api/v1/cases/${caseId}/answers/${id}`, (route) => {
    bodies.push(route.request().postDataJSON());
    return route.fulfill({ json: { case_revision: rev + 1, next_action: "review" } });
  });
  await page.reload();
  await page.getByRole("button", { name: "Not sure" }).click();
  await expect(page).toHaveURL(/\/review$/);
  expect(bodies).toEqual([{ expected_revision: rev, status: "unknown", value: null }]);
});

// QA 2026-10-22 (journey group).
test("#404 an answer error is tied to the answer, and the text answer is named by its question", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  const form = page.locator("form.card");
  const submitEmpty = async () => {
    await page.getByRole("button", { name: "Submit answer" }).click();
    await expect(page.locator("#answer-error")).toHaveText("Choose or enter an answer, or use “Not sure” or “Skip”.");
  };
  // Q1 single choice, Q3 scale, Q4 multiple choice: the group carries the error.
  for (const slot of [1, 2, 3, 4]) {
    await expect(page.getByText(`Question ${slot} of up to 10`)).toBeVisible();
    if (slot !== 2) {
      await submitEmpty();
      const group = form.locator("fieldset").first();
      await expect(group).toHaveAttribute("aria-invalid", "true");
      expect((await group.getAttribute("aria-describedby"))?.split(" ")).toContain("answer-error");
    }
    await answerCurrent(page, "answer");
  }
  // Q5 text: the field carries the error, and its name includes the question.
  await expect(page.getByText("Question 5 of up to 10")).toBeVisible();
  await submitEmpty();
  const text = page.getByRole("textbox", { name: "Your answer to: What have you already tried?" });
  await expect(text).toHaveAttribute("aria-invalid", "true");
  await expect(text).toHaveAttribute("aria-describedby", "answer-error");
  await text.fill("Rest");
  await expect(text).not.toHaveAttribute("aria-invalid", "true");
});
