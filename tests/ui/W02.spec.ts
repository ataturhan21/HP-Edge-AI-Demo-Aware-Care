// W02 How it works (R11). Describes the up-to-10 question flow; links to start.
import { expect, test } from "@playwright/test";

test("how it works describes the three steps", async ({ page }) => {
  await page.goto("/how-it-works");
  await expect(page.getByRole("heading", { level: 1, name: "Three steps to a clearer next step" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "2. Answer up to 10 questions" })).toBeVisible();
  await page.getByRole("main").getByRole("link", { name: /Start/ }).first().click();
  await expect(page).toHaveURL(/\/app\/start$/);
});
