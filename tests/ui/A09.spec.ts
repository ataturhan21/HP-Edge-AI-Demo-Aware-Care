// A09 Doctor preferences (R28, R29). Requirements filter; preferences only order. Fictional directory label.
import { expect, test } from "@playwright/test";
import { expectNoHorizontalOverflow, toGuidance } from "./support/journey";

test("required language is a hard filter and preferences are labeled fictional", async ({ page }) => {
  await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await expect(page.getByText("Fictional directory")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await expect(page.getByLabel("Require a verified match for this plan")).toHaveCount(0);
  await page.getByLabel("Insurance plan").selectOption("Demo Health PPO");
  await expect(page.getByLabel("Require a verified match for this plan")).not.toBeChecked();
  await page.getByLabel("Language", { exact: true }).selectOption("Spanish");
  await page.getByLabel("Require this language").check();
  await page.getByRole("button", { name: "Find matches" }).click();
  const cards = page.locator("article");
  await expect(cards.first()).toBeVisible();
  for (const card of await cards.all()) await expect(card).toContainText("Spanish");
  // Criteria are kept when returning to preferences.
  await page.getByRole("link", { name: "Change preferences" }).first().click();
  await expect(page.getByLabel("Language", { exact: true })).toHaveValue("Spanish");
  await expect(page.getByLabel("Require this language")).toBeChecked();
});
