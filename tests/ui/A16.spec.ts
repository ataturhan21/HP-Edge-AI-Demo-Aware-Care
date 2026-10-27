// A16 Service limits (R16, R17). Public explanation; no invented answer; restart and help actions.
import { expect, test } from "@playwright/test";
import { expectNoHorizontalOverflow } from "./support/journey";

test("service limits explain without inventing an answer", async ({ page }) => {
  await page.goto("/app/limits");
  await expect(page.getByRole("heading", { level: 1, name: "This concern is outside the demo scope" })).toBeVisible();
  await expect(page.getByText("No answer was invented")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.getByRole("link", { name: "Use reviewed alternative guidance" }).click();
  await expect(page).toHaveURL(/\/help$/);
  await page.goto("/app/limits");
  await page.getByRole("main").getByRole("link", { name: "Start a new consultation" }).click();
  await expect(page).toHaveURL(/\/app\/start$/);
});
