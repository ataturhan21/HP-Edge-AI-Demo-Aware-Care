// Journey flow (CHG-DEV-UI-007): the doctor pages lead on to the visit summary and back to the guidance (#341), the
// steps that can be reopened are links in the step indicator, with a compact row on phones (#343), and the question
// page has one progress indicator on phones (#348). Mock stack, synthetic data, both viewports.
import { expect, test, type Locator, type Page } from "@playwright/test";
import { answerCurrent, enterConcern, expectNoHorizontalOverflow, startSession, toGuidance } from "./support/journey";

const phone = (page: Page) => page.viewportSize()!.width < 700;
const steps = (page: Page) => page.getByRole("navigation", { name: "Consultation steps" });
const next = (page: Page) => page.getByRole("navigation", { name: "Next steps" });

async function toMatches(page: Page, plan?: string) {
  const caseId = await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  if (plan) {
    await page.getByLabel("Insurance plan").selectOption(plan);
    await page.getByLabel("Require a verified match for this plan").check();
  }
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.getByRole("heading", { name: "Doctor matches" })).toBeVisible();
  return caseId;
}

async function expectPrimary(link: Locator) {
  await expect(link).toBeVisible();
  await expect(link).toHaveClass(/(^|\s)btn(\s|$)/);
  await expect(link).not.toHaveClass(/secondary/);
}

async function top(loc: Locator) {
  return Math.round(await loc.evaluate((el) => el.getBoundingClientRect().top + window.scrollY));
}

test("#341 A10 leads on to the visit summary (primary) and back to the guidance", async ({ page }) => {
  const caseId = await toMatches(page);
  await expect(page.locator("article").first()).toBeVisible();
  const summary = next(page).getByRole("link", { name: "Continue to visit summary", exact: true });
  await expectPrimary(summary);
  await expect(next(page).getByRole("link", { name: "Back to guidance", exact: true })).toBeVisible();
  await expect(next(page).getByRole("link", { name: "Change preferences", exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await summary.click();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/summary$`));
  await expect(page.getByRole("heading", { name: "Appointment summary" })).toBeVisible();
  await page.goBack();
  await next(page).getByRole("link", { name: "Back to guidance", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/guidance$`));
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
});

test("#341 A10 with no match keeps its recovery path and adds the same two ways on", async ({ page }) => {
  const caseId = await toMatches(page, "Demo Exclusive Plan");
  await expect(page.getByRole("heading", { name: "No doctors meet every requirement" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Make the plan a preference instead of a requirement." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Keep my requirements" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Change preferences yourself" })).toBeVisible();
  const summary = next(page).getByRole("link", { name: "Continue to visit summary", exact: true });
  await expectPrimary(summary);
  await expect(next(page).getByRole("link", { name: "Back to guidance", exact: true })).toHaveAttribute("href", `/app/cases/${caseId}/guidance`);
  await expectNoHorizontalOverflow(page);
  await summary.click();
  await expect(page.getByRole("heading", { name: "Appointment summary" })).toBeVisible();
});

test("#341 A11 leads on to a created PDF in 3 taps without browser Back, and keeps Back to matches", async ({ page }) => {
  const caseId = await toMatches(page);
  await page.getByRole("link", { name: "Inspect doctor" }).first().click();
  await expect(page.getByRole("heading", { name: "Why this doctor appears" })).toBeVisible();
  const ways = next(page);
  await expect(ways.getByRole("link", { name: "Back to matches", exact: true })).toHaveAttribute("href", `/app/cases/${caseId}/doctors`);
  await expect(ways.getByRole("link", { name: "Back to guidance", exact: true })).toHaveAttribute("href", `/app/cases/${caseId}/guidance`);
  // The contact simulation stays on the page.
  await expect(page.getByRole("button", { name: "Open contact or booking site" })).toBeVisible();
  const summary = ways.getByRole("link", { name: "Continue to visit summary", exact: true });
  await expectPrimary(summary);
  await expectNoHorizontalOverflow(page);
  // Taps from the doctor's details to a created PDF: Continue, I reviewed, Create PDF (before: 9, 3 of them Back).
  await summary.click();
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).click();
  await expect(page.getByRole("link", { name: /Download summary/ })).toBeVisible({ timeout: 30_000 });
});

test("#343 on the summary, Guidance and Find care are step links; finished earlier steps stay text", { tag: "@mobile" }, async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.getByRole("heading", { name: "Appointment summary" })).toBeVisible();
  const nav = steps(page);
  await expect(nav.getByRole("link")).toHaveCount(2);
  const guidance = nav.getByRole("link", { name: "Guidance", exact: true });
  const findCare = nav.getByRole("link", { name: "Find care", exact: true });
  await expect(guidance).toBeVisible();
  await expect(findCare).toBeVisible();
  await expect(guidance).toHaveAttribute("href", `/app/cases/${caseId}/guidance`);
  await expect(findCare).toHaveAttribute("href", `/app/cases/${caseId}/preferences`);
  // The current step is marked and not a link; steps that cannot be reopened are text.
  await expect(nav.locator('[aria-current="step"]')).toContainText("Summary");
  await expect(nav.locator('[aria-current="step"] a')).toHaveCount(0);
  for (const name of ["Profile", "Concern", "Records", "Questions", "Review", "Summary"])
    await expect(nav.getByRole("link", { name, exact: true })).toHaveCount(0);
  if (phone(page)) await expect(nav.locator(".journey-links")).toBeVisible(); // the compact row
  else await expect(nav.locator("ol").getByRole("link")).toHaveCount(2); // in the step list
  await expectNoHorizontalOverflow(page);
  // Every link is reachable by keyboard, with a visible focus ring.
  await page.locator("body").focus();
  let reached = false;
  for (let i = 0; i < 25 && !reached; i++) {
    await page.keyboard.press("Tab");
    reached = await guidance.evaluate((el) => el === document.activeElement);
  }
  expect(reached, "Guidance link reached by Tab").toBe(true);
  expect(await guidance.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe("none");
  await findCare.click();
  await expect(page.getByRole("heading", { name: "Doctor preferences" })).toBeVisible();
  // A09 keeps the links it was given (Guidance and Summary); Find care is now the current step.
  await expect(nav.locator('[aria-current="step"]')).toContainText("Find care");
  await nav.getByRole("link", { name: "Guidance", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
});

test("#343 on the guidance page the way to Find care is in the first screen at both widths", { tag: "@mobile" }, async ({ page }) => {
  await toGuidance(page);
  const nav = steps(page);
  await expect(nav.getByRole("link")).toHaveCount(2);
  const findCare = nav.getByRole("link", { name: "Find care", exact: true });
  await expect(findCare).toBeVisible();
  await expect(nav.getByRole("link", { name: "Summary", exact: true })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Guidance", exact: true })).toHaveCount(0); // current
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(await top(findCare)).toBeLessThan(page.viewportSize()!.height);
  await findCare.click();
  await expect(page.getByRole("heading", { name: "Doctor preferences" })).toBeVisible();
});

test("#343 before guidance exists no step is a link", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await expect(page.getByText(/^Question \d+ of up to 10$/)).toBeVisible();
  await expect(steps(page).locator('[aria-current="step"]')).toContainText("Questions");
  await expect(steps(page).getByRole("link")).toHaveCount(0);
});

test("#348 the question page shows one progress indicator", { tag: "@mobile" }, async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  const line = page.getByText(/^Question \d+ of up to 10$/);
  await expect(line).toHaveCount(1);
  await expect(line).toHaveText("Question 1 of up to 10");
  await expect(line).toBeVisible();
  const bars = page.locator(".journey-bar:visible, .progress:visible");
  if (phone(page)) {
    await expect(bars).toHaveCount(1);
    await expect(page.locator(".pagehead .eyebrow")).toHaveText("Step 4 of 8 · Question 1 of up to 10");
    await expect(page.locator(".journey-compact")).toBeHidden();
    // Screen readers still hear the step list, with the current step.
    await expect(steps(page).locator('[aria-current="step"]')).toContainText("Questions");
  } else {
    await expect(steps(page).locator("ol")).toBeVisible();
    await expect(steps(page).locator('[aria-current="step"]')).toContainText("Questions");
    await expect(page.locator(".pagehead .eyebrow")).toHaveText(/Question 1 of up to 10$/);
    await expect(page.locator(".pagehead .eyebrow .step-phone")).toBeHidden();
    await expect(bars).toHaveCount(1);
  }
  await answerCurrent(page, "answer");
  await expect(line).toHaveText("Question 2 of up to 10");
  await expect(bars).toHaveCount(1);
  await expectNoHorizontalOverflow(page);
});
