// A02 Health profile (R04-R06). Session-only context; unknown is not "none"; saving needs an account.
import { expect, test } from "@playwright/test";
import { answerAll, noRedFlags, startSessionOnly } from "./support/journey";

test("unknown allergies and skipped fields reach review as unknown", async ({ page }) => {
  await startSessionOnly(page);
  await expect(page.getByRole("button", { name: "Save to profile" })).toBeDisabled();
  await expect(page.getByLabel("Unknown")).toBeChecked();
  await page.getByLabel("Age in years").fill("38");
  await page.getByRole("button", { name: "Use for this session" }).click();
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Skip and continue" }).click();
  await answerAll(page);
  const profile = page.locator("section", { hasText: "Profile details for this session" });
  await expect(profile.locator(".datum", { hasText: "Allergies" })).toContainText("Unknown");
  await expect(profile.locator(".datum", { hasText: "Age" })).toContainText("38");
  await expect(profile.locator(".datum", { hasText: "Current medications" })).toContainText("Unknown");
});

test("reported allergies require a value and invalid age is explained", async ({ page }) => {
  await startSessionOnly(page);
  await page.getByLabel("Age in years").fill("12");
  await page.getByLabel("I have allergies to report").check();
  await page.getByRole("button", { name: "Use for this session" }).click();
  await expect(page.getByText("Enter a whole number from 18 to 130, or leave it blank if unknown.")).toBeVisible();
  await expect(page.getByText("Enter at least one allergy, or choose another option.")).toBeVisible();
  await expect(page).toHaveURL(/\/app\/profile$/);
});

// QA 2026-10-22 (journey group).
test("#410 leaving with unsaved entries asks first, in the app and on reload", async ({ page }) => {
  await startSessionOnly(page);
  await page.getByLabel("Relevant history").fill("Synthetic migraine history");
  await page.getByLabel("Age in years").fill("44");
  await expect(page.getByText("You have unsaved changes on this page.")).toBeVisible();
  const history = page.getByRole("banner").getByRole("link", { name: "History" });
  const openMenu = async () => {
    const menu = page.getByRole("banner").getByRole("button", { name: "Menu" });
    if ((await menu.isVisible()) && (await menu.getAttribute("aria-expanded")) === "false") await menu.click();
  };
  await openMenu();
  await history.click();
  const dialog = page.getByRole("dialog", { name: "Leave without using your details?" });
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(/\/app\/profile$/);
  await dialog.getByRole("button", { name: "Stay on this page" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("Relevant history")).toHaveValue("Synthetic migraine history");
  // The browser's own confirmation guards a reload or close.
  const asked = new Promise<string>((resolve) => page.once("dialog", async (d) => { resolve(d.type()); await d.dismiss(); }));
  void page.reload().catch(() => undefined);
  expect(await asked).toBe("beforeunload");
  await expect(page.getByLabel("Relevant history")).toHaveValue("Synthetic migraine history");
  await openMenu();
  await history.click();
  await page.getByRole("dialog").getByRole("button", { name: "Leave this page" }).click();
  await expect(page).toHaveURL(/\/app\/history$/);
  // Using the details is not leaving them: no question is asked.
  await page.goto("/app/profile");
  await page.getByLabel("Age in years").fill("44");
  await page.getByRole("button", { name: "Use for this session" }).click();
  await expect(page).toHaveURL(/\/app\/new$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("#451 the age takes a whole number in digits only", async ({ page }) => {
  await startSessionOnly(page);
  for (const typed of ["0x1A", "1e2", "25.0", "+30", "3O"]) {
    await page.getByLabel("Age in years").fill(typed);
    await page.getByRole("button", { name: "Use for this session" }).click();
    await expect(page.getByText("Enter a whole number from 18 to 130, or leave it blank if unknown.")).toBeVisible();
    await expect(page).toHaveURL(/\/app\/profile$/);
  }
  await page.getByLabel("Age in years").fill(" 26 ");
  await page.getByRole("button", { name: "Use for this session" }).click();
  await expect(page).toHaveURL(/\/app\/new$/);
});
