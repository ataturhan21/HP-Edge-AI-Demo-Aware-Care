// W03 For healthcare (R37-R39). Outcomes are labeled not measured.
import { expect, test } from "@playwright/test";

test("healthcare page states outcomes are not measured", async ({ page }) => {
  await page.goto("/healthcare");
  await expect(page.getByRole("heading", { level: 1, name: "A bounded demonstration of local AI" })).toBeVisible();
  await expect(page.getByText("Outcomes are not measured")).toBeVisible();
});
