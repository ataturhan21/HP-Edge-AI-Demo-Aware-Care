// W04 Privacy (R34-R36). Local processing, retention and controls; link to data settings.
import { expect, test } from "@playwright/test";
import { expectNoHorizontalOverflow } from "./support/journey";

test("privacy page explains handling and links to controls", async ({ page }) => {
  await page.goto("/privacy");
  await expect(page.getByRole("heading", { level: 1, name: "How your demo information is handled" })).toBeVisible();
  for (const h of ["Local processing", "Retention", "Downloads and links", "Your controls"])
    await expect(page.getByRole("heading", { name: h })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "Review data controls" })).toHaveAttribute("href", "/app/settings");
  // T-R33-S02: downloaded files are explicitly outside the server deletion promise.
  await expect(page.getByText("A PDF you download is saved on your own computer and is outside Aware Care’s deletion controls.", { exact: false })).toBeVisible();
});

test("#440 #471 the retention card names every kind of record kept, each with its period", async ({ page }) => {
  await page.goto("/privacy");
  const card = page.locator("section", { has: page.getByRole("heading", { name: "Retention" }) });
  await expect(card.locator("li", { hasText: "Guest information ends after 30 minutes idle or 8 hours" })).toBeVisible();
  await expect(card.locator("li", { hasText: "Summary downloads expire after 15 minutes" })).toBeVisible();
  await expect(card.locator("li", { hasText: "Operational events" })).toContainText("kept for 30 days");
  const jobs = card.locator("li", { hasText: "Job records" });
  await expect(jobs).toContainText("no health content");
  await expect(jobs).toContainText("When your session ends they lose any link to you and keep only the hour");
  await expect(jobs).toContainText("deleted after 30 days");
  await expect(card.locator("li", { hasText: "AI usage counts are kept for 90 days" })).toBeVisible();
  await expect(card.locator("li", { hasText: "a cleanup every 5 minutes" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
