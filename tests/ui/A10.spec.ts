// A10 Doctor matches (R28-R30). Explained fictional matches; strict filter no-match with explicit recovery.
import { expect, test } from "@playwright/test";
import { expectNoHorizontalOverflow, toGuidance } from "./support/journey";

test("explained fictional matches in deterministic order", async ({ page }) => {
  await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await page.getByLabel("Insurance plan").selectOption("Demo Health PPO");
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.getByRole("heading", { name: "Doctor matches" })).toBeVisible();
  const cards = page.locator("article");
  await expect(cards).toHaveCount(3);
  for (let i = 0; i < 3; i++) await expect(cards.locator("h2").nth(i)).not.toHaveText(/^Match \d/); // names load per card
  const first = await cards.locator("h2").allTextContents();
  await expect(cards.first().getByText("Fictional doctor", { exact: true })).toBeVisible();
  await expect(cards.first().getByRole("heading", { name: "Confirmed" })).toBeVisible();
  await expect(cards.first().getByRole("heading", { name: "Unknown" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  // Same criteria again: same order (R30).
  await page.getByRole("link", { name: "Change preferences" }).first().click();
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.locator("article h2")).toHaveText(first);
});

test("required plan with no matching provider offers only an explicit filter change", async ({ page }) => {
  await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await page.getByLabel("Insurance plan").selectOption("Demo Exclusive Plan");
  await page.getByLabel("Require a verified match for this plan").check();
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.getByRole("heading", { name: "No doctors meet every requirement" })).toBeVisible();
  await expect(page.locator("article")).toHaveCount(0);
  // Every candidate fits the other filters but none has a verified plan record: disclosed, not ranked (T-R29-S01).
  await expect(page.getByRole("heading", { name: "Not shown: a required detail is not verified" })).toBeVisible();
  await expect(page.locator("section[aria-labelledby=excluded-heading] li")).toHaveCount(3);
  await expect(page.getByText("Dr. Sam Patel is not shown as a match: Required plan Demo Exclusive Plan not verified: participation unknown.", { exact: false })).toBeVisible();
  const accept = page.getByRole("button", { name: "Make the plan a preference instead of a requirement." });
  await expect(accept).toHaveCount(1);
  // Declining sends nothing and keeps the filter and the empty result (T-R29-S02).
  const searches: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/provider-search")) searches.push(r.postData() ?? "");
  });
  await page.getByRole("button", { name: "Keep my requirements" }).click();
  await expect(page.getByRole("status").filter({ hasText: "You kept your requirements, so no doctors are shown." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Keep my requirements" })).toHaveCount(0);
  await expect(page.locator("article")).toHaveCount(0);
  expect(searches).toEqual([]);
  // Only the explicit acceptance searches again, with the changed criteria.
  await accept.click();
  await expect(page.locator("article").first()).toBeVisible();
  expect(searches).toHaveLength(1);
  expect(JSON.parse(searches[0]).criteria).toMatchObject({ exact_plan_id: "Demo Exclusive Plan", required_verified_plan: false });
  await expect(page.getByRole("heading", { name: "Not shown: a required detail is not verified" })).toHaveCount(0);
});

test("a required plan ranks only verified doctors and discloses the unverified one", async ({ page }) => {
  await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await page.getByLabel("Insurance plan").selectOption("Demo Health PPO");
  await page.getByLabel("Require a verified match for this plan").check();
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.locator("article")).toHaveCount(2);
  await expect(page.locator("article h2").filter({ hasText: /\S/ })).toHaveCount(2);
  await expect(page.locator("article", { hasText: "Dr. Sam Patel" })).toHaveCount(0);
  const excluded = page.locator("section[aria-labelledby=excluded-heading]");
  await expect(excluded.locator("li")).toHaveCount(1);
  await expect(excluded).toContainText("Dr. Sam Patel is not shown as a match: Required plan Demo Health PPO not verified: participation unknown.");
  await expect(excluded.getByRole("link")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});
