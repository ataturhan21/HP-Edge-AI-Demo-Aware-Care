// A08 Sources (R21, R22, R25). No approved corpus: nothing is presented as sourced, and possible explanations are
// marked as general medical knowledge (ADR-015), never given an invented source; in mock mode the scripted explanation
// is marked scripted (#456, A08 rule 3).
import { expect, test } from "@playwright/test";
import { enterConcern, startSession, toGuidance } from "./support/journey";

// An interceptor still handling a request when a test ends must never fail the next test (#134).
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

test("sources state that no approved evidence is loaded", async ({ page }) => {
  await toGuidance(page);
  await page.getByRole("link", { name: "Sources" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Where the guidance comes from" })).toBeVisible();
  await expect(page.getByText("No approved evidence sources are loaded")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Statements in your guidance" })).toBeVisible();
});

test("a possible explanation is marked as general medical knowledge, with no cited source", async ({ page }) => {
  // A local result's explanation (#456: local wording unchanged). The suite runs in mock mode, so the published
  // guidance is shown as a local result here, as A07.spec does; A08 reads the origin from the guidance.
  await page.route(/\/api\/v1\/cases\/[^/]+\/guidance$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), model_manifest_id: "qwen3.6-35b-a3b-fp8@95a723d0-2026-10-15" } });
  });
  await toGuidance(page);
  await page.getByRole("link", { name: "Sources" }).click();
  await expect(page.getByText("Possible explanations come from general medical knowledge")).toBeVisible();
  const row = page.locator(".datum", { hasText: "Scripted illustrative explanation" });
  await expect(row).toContainText("General medical knowledge — no reviewed source");
  await expect(page.getByRole("link", { name: "Open cited source" })).toHaveCount(0);
});

test("#456 mock mode marks the scripted explanation as scripted, never as general medical knowledge", async ({ page }) => {
  await toGuidance(page);
  await page.getByRole("link", { name: "Sources" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Where the guidance comes from" })).toBeVisible();
  await expect(page.getByText("The possible explanation is scripted illustrative text for this synthetic demo")).toBeVisible();
  const row = page.locator(".datum", { hasText: "Scripted illustrative explanation" });
  await expect(row).toContainText("Scripted illustrative text — no AI model, no reviewed source");
  await expect(page.getByRole("main")).not.toContainText(/general medical knowledge/i);
  await expect(page.getByRole("link", { name: "Open cited source" })).toHaveCount(0);
});

test("sources for a case without current guidance send the user to review", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  await page.goto(`/app/cases/${caseId}/sources`);
  await expect(page.getByRole("heading", { name: "No current guidance" })).toBeVisible();
  await page.getByRole("link", { name: "Go to review" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/(review|questions)$`));
});
