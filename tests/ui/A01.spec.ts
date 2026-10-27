// A01 Start and consent (R01, R02). Consent is required; decline and under-age route to A16.
import { expect, test } from "@playwright/test";
import { expectNoHorizontalOverflow, guardNetwork, startSession } from "./support/journey";

test("consent is required before a session starts", async ({ page }) => {
  const offenders = guardNetwork(page);
  await page.goto("/app/start");
  await expectNoHorizontalOverflow(page);
  await page.getByRole("button", { name: "Accept and begin" }).click();
  // #342: the message stays above the buttons; the focused error summary announces it (tests/ui/improve-forms.spec.ts).
  await expect(page.locator("#consent-error")).toHaveText("Confirm your age and accept the consent to continue.");
  await expect(page).toHaveURL(/\/app\/start$/);
  await startSession(page);
  expect(offenders).toEqual([]);
});

test("decline routes to service limits without creating a session", async ({ page }) => {
  await page.goto("/app/start");
  await page.getByRole("button", { name: "Decline" }).click();
  await expect(page).toHaveURL(/\/app\/limits$/);
  await expect(page.getByRole("heading", { name: "You chose not to continue" })).toBeVisible();
  // No session exists: a protected route sends the user back to start.
  await page.goto("/app/history");
  await expect(page).toHaveURL(/\/app\/start$/);
});

test("under-age eligibility routes to service limits", async ({ page }) => {
  await page.goto("/app/start");
  await page.getByLabel("No", { exact: true }).check();
  await page.getByRole("button", { name: "Accept and begin" }).click();
  await expect(page.getByRole("heading", { name: "This demonstration is for adults" })).toBeVisible();
});
