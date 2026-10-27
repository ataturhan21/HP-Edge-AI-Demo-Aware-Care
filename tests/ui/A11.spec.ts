// A11 Doctor details (R30, R31). Contact is a labeled simulation: no popup, no external request.
import { expect, test } from "@playwright/test";
import { guardNetwork, toGuidance } from "./support/journey";

test("simulated contact opens no site and books nothing", async ({ page, context }) => {
  const offenders = guardNetwork(page);
  await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await page.getByRole("button", { name: "Find matches" }).click();
  await page.getByRole("link", { name: "Inspect doctor" }).first().click();
  await expect(page.getByRole("heading", { name: "Why this doctor appears" })).toBeVisible();
  await expect(page.getByText("Fictional doctor", { exact: true })).toBeVisible();
  await expect(page.locator(".datum", { hasText: "Appointment availability" })).toContainText("Unknown");
  const pages = context.pages().length;
  await page.getByRole("button", { name: "Open contact or booking site" }).click();
  const dialog = page.getByRole("dialog", { name: "Simulated contact" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Nothing was sent, no appointment was booked, and no external site was opened.");
  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(dialog).toHaveCount(0);
  expect(context.pages().length).toBe(pages);
  expect(offenders).toEqual([]);
});

// #267: a doctor card is read with the search it was opened from; a replaced search's card is not shown.
test("doctor details are read with their search and survive a reload", async ({ page }) => {
  await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  const searched = page.waitForResponse((r) => r.url().includes("/provider-search") && r.status() === 200);
  const card = page.waitForRequest((r) => r.url().includes("/providers/"));
  await page.getByRole("button", { name: "Find matches" }).click();
  const searchId = (await (await searched).json()).id as string;
  expect(new URL((await card).url()).searchParams.get("search_id")).toBe(searchId);
  await page.getByRole("link", { name: "Inspect doctor" }).first().click();
  await expect(page).toHaveURL(new RegExp(`\\?search=${searchId}$`));
  await expect(page.getByRole("heading", { name: "Why this doctor appears" })).toBeVisible();
  const detailsUrl = page.url();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Why this doctor appears" })).toBeVisible();
  // A new search replaces the old one: the old card link is no longer current (409) and says so.
  await page.goto(detailsUrl.replace(/\/doctors\/.*/, "/preferences"));
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.getByRole("link", { name: "Inspect doctor" }).first()).toBeVisible();
  await page.goto(detailsUrl);
  await expect(page.getByRole("heading", { name: "This doctor is not in your current results" })).toBeVisible();
});
