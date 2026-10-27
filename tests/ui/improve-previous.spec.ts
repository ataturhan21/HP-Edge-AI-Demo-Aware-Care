// Previous question on A05 (#357, CHG-DEV-API-005): from question 2 on the page offers "Previous question"; it shows
// the earlier issued question with its saved answer filled in, an unchanged answer returns to the current question
// without saving, a changed one is saved with saveAnswer and the later answers are kept (the issue order does not
// depend on answers). Mock stack, synthetic data, both viewports.
import { expect, test, type Page, type Request } from "@playwright/test";
import { answerAll, answerCurrent, enterConcern, expectNoHorizontalOverflow, serverStep, startSession } from "./support/journey";

const line = (page: Page) => page.getByText(/^Question \d+ of up to 10$/);
const previous = (page: Page) => page.getByRole("button", { name: "Previous question", exact: true });
const heading = (page: Page) => page.getByRole("heading", { level: 1 });

/** Collects every saveAnswer request body sent from now on. */
function answerWrites(page: Page): { url: string; body: Record<string, unknown> }[] {
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  page.on("request", (r: Request) => {
    if (r.method() === "PUT" && /\/api\/v1\/cases\/[^/]+\/answers\//.test(r.url())) writes.push({ url: r.url(), body: r.postDataJSON() });
  });
  return writes;
}

async function at(page: Page, slot: number) {
  await expect(line(page)).toHaveText(`Question ${slot} of up to 10`);
}

/** Q1 "One to four weeks ago", Q2 skipped; leaves the page on question 3. */
async function twoAnswered(page: Page) {
  await startSession(page);
  const caseId = await enterConcern(page);
  await at(page, 1);
  await page.getByRole("radio", { name: "One to four weeks ago" }).check();
  let next = serverStep(page, "POST", "/questions/next");
  await page.getByRole("button", { name: "Submit answer" }).click();
  await next;
  await at(page, 2);
  next = serverStep(page, "POST", "/questions/next");
  await answerCurrent(page, "skip");
  await next;
  await at(page, 3);
  return caseId;
}

test("#357 Previous question is offered from question 2 on, not on question 1", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await at(page, 1);
  await expect(page.getByRole("heading", { name: "When did this concern begin?" })).toBeVisible();
  await expect(previous(page)).toHaveCount(0);
  const next = serverStep(page, "POST", "/questions/next");
  await answerCurrent(page, "answer");
  await next;
  await at(page, 2);
  await expect(previous(page)).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("#357 Previous shows the earlier question with its saved answer; an unchanged answer returns without saving", async ({ page }) => {
  await twoAnswered(page);
  const writes = answerWrites(page);
  // Keyboard: the action is a native button; the heading of the shown question takes focus.
  await previous(page).focus();
  await page.keyboard.press("Enter");
  await at(page, 2);
  await expect(heading(page)).toHaveText("Has the pattern changed?");
  await expect(heading(page)).toBeFocused();
  await expect(page.getByText("You skipped this question.", { exact: false })).toBeVisible();
  await expect(page.locator("form.card input[type=radio]:checked")).toHaveCount(0);
  // Repeated Previous goes one more step back; the saved choice is filled in.
  await previous(page).click();
  await at(page, 1);
  await expect(heading(page)).toBeFocused();
  await expect(page.getByRole("radio", { name: "One to four weeks ago" })).toBeChecked();
  await expect(previous(page)).toHaveCount(0); // nothing before question 1
  await expect(page.getByText("Changing it keeps your later answers and the questions that follow.")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  // Submitting the unchanged answer only returns to the current question.
  await page.getByRole("button", { name: "Submit answer" }).click();
  await at(page, 3);
  await expect(heading(page)).toHaveText("How much does it affect your day?");
  await expect(heading(page)).toBeFocused();
  // Skip on the skipped question is unchanged too; "Back to question 3" returns without sending anything.
  await previous(page).click();
  await at(page, 2);
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await at(page, 3);
  await previous(page).click();
  await page.getByRole("button", { name: "Back to question 3" }).click();
  await at(page, 3);
  await expect(heading(page)).toBeFocused();
  expect(writes).toEqual([]);
});

test("#357 a changed earlier answer is saved; the current question keeps its unsent choice and nothing is asked again", async ({ page }) => {
  await twoAnswered(page);
  const writes = answerWrites(page);
  await page.locator('fieldset.scale input[value="6"]').check(); // chosen, not yet sent
  await previous(page).click();
  await at(page, 2);
  // Before saving, the page says what a change does to the later answers.
  await expect(page.getByText("Changing it keeps your later answers and the questions that follow.")).toBeVisible();
  await page.getByRole("radio", { name: "Worsening" }).check();
  const saved = serverStep(page, "PUT", "", 200);
  await page.getByRole("button", { name: "Submit answer" }).click();
  await saved;
  await at(page, 3);
  await expect(heading(page)).toBeFocused();
  await expect(page.locator('fieldset.scale input[value="6"]')).toBeChecked();
  expect(writes).toHaveLength(1);
  expect(writes[0].body).toMatchObject({ status: "answered", value: "Q02-O03" });
  // The saved change is what Previous shows now; question 1 still has its answer.
  await previous(page).click();
  await expect(page.getByRole("radio", { name: "Worsening" })).toBeChecked();
  await previous(page).click();
  await expect(page.getByRole("radio", { name: "One to four weeks ago" })).toBeChecked();
});

test("#357 the review page shows a changed answer and every later answer", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  for (const slot of [1, 2, 3]) {
    await at(page, slot);
    const next = serverStep(page, "POST", "/questions/next");
    await answerCurrent(page, "answer");
    await next;
  }
  await at(page, 4);
  await previous(page).click();
  await at(page, 3);
  await expect(page.locator('fieldset.scale input[value="4"]')).toBeChecked();
  await page.locator('fieldset.scale input[value="8"]').check();
  const next = serverStep(page, "POST", "/questions/next");
  await page.getByRole("button", { name: "Submit answer" }).click();
  await next;
  await at(page, 4);
  expect(await answerAll(page)).toEqual([4, 5, 6, 7, 8, 9, 10]);
  await expect(page.getByRole("heading", { name: "Your answers (10 questions asked)" })).toBeVisible();
  const row = (text: string) => page.locator(".datum").filter({ hasText: text });
  await expect(row("How much does it affect your day?")).toContainText("8 on a 0–10 scale");
  await expect(row("When did this concern begin?")).toContainText("Within the last week");
  await expect(row("Has the pattern changed?")).toContainText("Improving");
});

test("#357 a changed earlier answer with the synthetic urgent signal still routes to urgent help", async ({ page }) => {
  const caseId = await twoAnswered(page);
  await previous(page).click();
  await at(page, 2);
  await page.getByRole("button", { name: "Simulate urgent answer" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/urgent$`));
  await expect(page.getByRole("heading", { name: "Seek urgent help now" })).toBeVisible();
});

test("#357 measured: taps to correct the last answer, before (finish, then Change on review) and after (Previous)", async ({ page }, info) => {
  // After: on question 3, correct question 2's answer: Previous, choose, Submit.
  await twoAnswered(page);
  let taps = 0;
  await previous(page).click(); taps++;
  await page.getByRole("radio", { name: "Worsening" }).check(); taps++;
  const next = serverStep(page, "POST", "/questions/next");
  await page.getByRole("button", { name: "Submit answer" }).click(); taps++;
  await next;
  await at(page, 3);
  // Before (still possible): skip the 8 remaining questions with one tap each (the fewest), then Change, choose, Save.
  let before = 0;
  for (let slot = 3; slot <= 10; slot++) {
    await at(page, slot);
    const advanced = serverStep(page, "POST", "/questions/next");
    await answerCurrent(page, "skip"); before++;
    await advanced;
  }
  await expect(page.getByRole("heading", { name: "Review your case" })).toBeVisible();
  await page.getByRole("button", { name: "Change answer to Has the pattern changed?" }).click(); before++;
  await page.getByRole("radio", { name: "About the same" }).check(); before++;
  await page.getByRole("button", { name: "Save answer" }).click(); before++;
  await expect(page.getByText("Your change was saved. Please review again before continuing.")).toBeVisible();
  expect(taps).toBe(3);
  expect(before).toBe(11);
  info.annotations.push({ type: "taps", description: `after ${taps}; before ${before} (8 skips + Change, choose, Save)` });
});
