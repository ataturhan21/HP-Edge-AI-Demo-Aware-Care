// A12 Appointment summary (R32, R33, R35) plus the complete Milestone 1 synthetic journey:
// consent -> concern -> intake -> review/edit -> guidance -> filtered matches -> A11 simulated
// contact -> reviewed PDF export and download -> reset -> another case.
import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  answerAll, CONCERN, enterConcern, expectNoHorizontalOverflow, guardNetwork, startSession,
} from "./support/journey";

test("complete synthetic patient journey through export and reset", { tag: "@mobile" }, async ({ page }) => {
  const offenders = guardNetwork(page);
  // 1-2. Session, consent and concern.
  await startSession(page);
  const caseId = await enterConcern(page);
  // 3. Intake.
  expect(await answerAll(page)).toHaveLength(10);
  // 4. Review and edit.
  await page.getByRole("button", { name: "Change answer to How long does each episode last?" }).click();
  await page.getByLabel("One to four hours").check(); // #148: a different answer than answerAll gave, so the check below proves the save
  await page.getByRole("button", { name: "Save answer" }).click();
  await expect(page.locator(".datum", { hasText: "How long does each episode last?" })).toContainText("One to four hours");
  // 5. Guidance.
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Mock mode: scripted synthetic outcome")).toBeVisible();
  // 6. Filter and inspect explained matches.
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await page.getByLabel("Language", { exact: true }).selectOption("Spanish");
  await page.getByLabel("Require this language").check();
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.getByRole("heading", { name: "Doctor matches" })).toBeVisible();
  const cards = page.locator("article");
  await expect(cards.first()).toBeVisible();
  for (const card of await cards.all()) await expect(card).toContainText("Spanish");
  await cards.first().getByRole("link", { name: "Inspect doctor" }).click();
  // 7. A11 simulated contact.
  await page.getByRole("button", { name: "Open contact or booking site" }).click();
  await expect(page.getByRole("dialog", { name: "Simulated contact" })).toContainText("no appointment was booked");
  await page.getByRole("button", { name: "Close" }).click();
  // 8. Reviewed summary export and download.
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.getByRole("heading", { name: "Appointment summary" })).toBeVisible();
  await expect(page.getByLabel("Summary preview")).toContainText(CONCERN);
  await expect(page.getByLabel("Summary preview")).toContainText("One to four hours");
  await expect(page.getByRole("button", { name: "Create PDF" })).toBeDisabled();
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).click();
  const link = page.getByRole("link", { name: "Download summary (PDF)" });
  await expect(link).toBeVisible({ timeout: 15_000 });
  await expectNoHorizontalOverflow(page);
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  const bytes = readFileSync((await download.path())!);
  expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");
  expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  // 9. Reset, then start another case.
  await page.getByRole("button", { name: "End session and reset" }).click();
  await page.getByRole("dialog", { name: "End this demo session?" }).getByRole("button", { name: "End session and reset" }).click();
  await expect(page).toHaveURL(/\/app\/start$/);
  // #290: the deletion is reported as under way, not as finished.
  await expect(page.locator(".notice", { hasText: "Session ended" })).toContainText("are being deleted from this device");
  // The old case is gone server-side: a fresh session cannot reach it.
  await startSession(page);
  await page.goto(`/app/cases/${caseId}/review`);
  await expect(page.getByRole("heading", { name: "This consultation is not available" })).toBeVisible();
  await page.goto("/app/new");
  const second = await enterConcern(page, "A second fictional concern for the demo.");
  expect(second).not.toBe(caseId);
  await expect(page.getByText("Question 1 of up to 10")).toBeVisible();
  expect(offenders).toEqual([]);
});

test("start another case keeps the session and begins a fresh intake", async ({ page }) => {
  await startSession(page);
  const first = await enterConcern(page);
  await answerAll(page);
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("main").getByRole("link", { name: "Start a new consultation" }).click();
  await expect(page).toHaveURL(/\/app\/new$/);
  const second = await enterConcern(page, "Another fictional concern.");
  expect(second).not.toBe(first);
  await page.goto("/app/history");
  await expect(page.locator("tbody tr")).toHaveCount(2);
});
