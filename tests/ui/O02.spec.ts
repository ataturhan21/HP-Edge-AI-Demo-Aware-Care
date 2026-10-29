// O02 Evidence and controls (R22, R23, R34, R38; ADR-005 option A). #487: one gateway on 15174 for both roles.
import { expect, test } from "@playwright/test";
import { startSessionOnly } from "./support/journey";

test("with an active guest session, direct navigation to O02 stays unauthorized", async ({ page }) => {
  await startSessionOnly(page);
  await page.goto("/presenter/controls");
  await expect(page.getByRole("heading", { level: 1, name: "Evidence and controls" })).toBeVisible();
  // #487: the guest session gives no presenter data; the presenter tools ask for a presenter session.
  await expect(page.getByText("Start a presenter session", { exact: true })).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(0);
});

test("a presenter sees every control with truthful unverified evidence", async ({ page }) => {
  await page.goto("http://127.0.0.1:15174/presenter/controls");
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Evidence and controls" })).toBeVisible();
  await expect(page.getByText(/controls are not verified/)).toBeVisible();
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(5);
  for (const row of await rows.all()) {
    await expect(row.locator("td").nth(0)).toHaveText("Unverified");
    await expect(row.locator("td").nth(1)).toHaveText("Not checked");
    await expect(row.locator("td").nth(2)).toHaveText("None recorded");
  }
  await expect(page.locator("main")).not.toContainText(/\bVerified\b/);
  await expect(page.getByText("No outbound requests recorded.", { exact: false })).toBeVisible();
  // #683 (owner decision, 28 Oct 2026): the page opens directly, but the presenter navigation has no Controls tab.
  const nav = page.getByRole("navigation", { name: "Presenter" });
  const menu = nav.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await expect(nav.getByRole("link", { name: "Runtime" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Controls" })).toHaveCount(0);
});
