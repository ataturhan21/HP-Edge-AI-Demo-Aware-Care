// Form usability improvements of 2026-10-21 (#342, #344), from the usability walk of v0.11.0-demo.1 on the ZGX Nano
// and the ZGX Fury. #342: a failed submit on A03 and A01 shows an error summary at the top of the form, focused, with a
// link to each field, announced once. #344: A02 offers "Skip — continue without a profile" near the top, which hands
// A03 exactly the session context of an empty profile. Runs on the isolated mock stack at 1440x900 and 360x780.
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { animationsSettled, expectNoHorizontalOverflow, noRedFlags, serverStep, startSession, startSessionOnly } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const AXE = join(__dirname, "../../apps/web/node_modules/axe-core/axe.min.js");
const summary = (page: Page) => page.getByRole("group", { name: "Check these before you continue" });
const activeId = (page: Page) => page.evaluate(() => document.activeElement?.id ?? "");

/** The confirmed_context A03 sends when the case is created, after the given way on from A02. */
async function contextSent(page: Page, wayOn: () => Promise<void>) {
  await startSessionOnly(page);
  await wayOn();
  await expect(page).toHaveURL(/\/app\/new$/);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await noRedFlags(page);
  const request = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith("/api/v1/cases"));
  const created = serverStep(page, "POST", "/api/v1/cases", 201);
  await page.getByRole("button", { name: "Continue" }).click();
  const body = (await request).postDataJSON() as { confirmed_context: unknown[] };
  await created;
  return body.confirmed_context;
}

test("#342 A03: an empty Continue focuses an error summary at the top, with a link to each field", async ({ page }) => {
  await startSession(page);
  await page.getByRole("button", { name: "Continue" }).click();
  const box = summary(page);
  await expect(box).toBeFocused();
  await expect(box).toBeInViewport();
  // It sits at the top of the form, above the concern field.
  const [boxY, concernY] = await Promise.all([box, page.getByLabel("Main concern")].map((l) => l.evaluate((e) => e.getBoundingClientRect().top)));
  expect(boxY).toBeLessThan(concernY);
  await expect(box.getByRole("link")).toHaveText(["Describe your main concern", "Answer whether any warning signs apply to you"]);
  // The field messages stay; nothing else is announced as an alert (the focused summary is the one announcement).
  await expect(page.locator("#concern-error")).toHaveText("Describe your main concern to continue.");
  await expect(page.locator("#red-flags-error")).toHaveText("Tick the signs that apply, or choose “None of these apply”.");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(box).not.toHaveAttribute("aria-live");

  await box.getByRole("link", { name: "Answer whether any warning signs apply to you" }).click();
  expect(await activeId(page)).toBe("red-flags-first");
  await expect(page.locator("#red-flags-first")).toBeInViewport();
  await page.evaluate(() => window.scrollTo(0, 0));
  await box.getByRole("link", { name: "Describe your main concern" }).click();
  expect(await activeId(page)).toBe("concern");
  await expect(page.getByLabel("Main concern")).toBeInViewport();

  // Each problem closes as it is fixed; the summary goes when none is left.
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await expect(box.getByRole("link")).toHaveText(["Answer whether any warning signs apply to you"]);
  await noRedFlags(page);
  await expect(box).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/records$/);
});

test("#342 A03: each failed Continue moves focus back to the summary", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(summary(page)).toBeFocused();
  await expect(summary(page).getByRole("link")).toHaveText(["Answer whether any warning signs apply to you"]);
  await page.getByRole("button", { name: "Continue" }).focus();
  await page.keyboard.press("Enter");
  await expect(summary(page)).toBeFocused();
  await expect(summary(page)).toBeInViewport();
});

test("#342 A03: a description the server refuses as not a health matter focuses the summary", async ({ page }) => {
  await startSession(page);
  await page.route("**/api/v1/cases", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({ status: 422, contentType: "application/json", json: {
      code: "VALIDATION_FAILED", message: "Describe a health concern, for example a symptom and when it started.",
      field_errors: [{ field: "concern", code: "not_health_concern",
        message: "Describe a health concern, for example a symptom and when it started." }],
      retryable: false, request_id: "00000000-0000-4000-8000-000000000000" } });
  });
  await page.getByLabel("Main concern").fill("asdf qwer zxcv uiop");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  const box = summary(page);
  await expect(box).toBeFocused();
  await expect(box).toBeInViewport();
  await expect(page.locator("#concern-error")).toContainText("We could not find a health concern in this description.");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await box.getByRole("link", { name: "Describe a symptom or health question in your main concern" }).click();
  expect(await activeId(page)).toBe("concern");
  await page.getByLabel("Main concern").fill("A mild headache since Monday.");
  await expect(box).toHaveCount(0);
});

test("#342 A01: Accept and begin without answers focuses the summary; its links reach the age choice and the terms", async ({ page }) => {
  await page.goto("/app/start");
  await page.getByRole("button", { name: "Accept and begin" }).click();
  const box = summary(page);
  await expect(box).toBeFocused();
  await expect(box).toBeInViewport();
  await expect(box.getByRole("link")).toHaveText(["Answer whether you are 18 or older", "Tick “I understand and accept these terms.”"]);
  await expect(page.getByText("Confirm your age and accept the consent to continue.")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await box.getByRole("link", { name: "Answer whether you are 18 or older" }).click();
  expect(await activeId(page)).toBe("adult-yes");
  await box.getByRole("link", { name: "Tick “I understand and accept these terms.”" }).click();
  expect(await activeId(page)).toBe("consent");
  await expect(page.getByLabel("I understand and accept these terms.")).toBeInViewport();
  await expect(page.getByLabel("I understand and accept these terms.")).toHaveAttribute("aria-invalid", "true");

  await page.getByLabel("Yes, I am 18 or older").check();
  await expect(box.getByRole("link")).toHaveText(["Tick “I understand and accept these terms.”"]);
  // A second failed attempt moves focus to the summary again.
  await page.getByRole("button", { name: "Accept and begin" }).click();
  await expect(box).toBeFocused();
  await page.getByLabel("I understand and accept these terms.").check();
  await expect(box).toHaveCount(0);
  const created = serverStep(page, "POST", "/api/v1/sessions", 201);
  await page.getByRole("button", { name: "Accept and begin" }).click();
  await created;
  await expect(page).toHaveURL(/\/app\/profile$/);
});

test.describe("#342 axe", () => {
  // The gateway policy forbids injected scripts; only the test tool is injected (as in tests/ui/a11y.spec.ts).
  test.use({ bypassCSP: true });
  test("#342 A03 with the error summary showing passes axe (WCAG 2.1 AA and best practice)", async ({ page }) => {
    await startSession(page);
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(summary(page)).toBeFocused();
    await page.addScriptTag({ path: AXE });
    await animationsSettled(page);
    const violations = await page.evaluate(async () => {
      // @ts-expect-error axe is injected above
      const result = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] } });
      return result.violations.map((v: { id: string; nodes: { target: string[] }[] }) => `${v.id} ${v.nodes[0]?.target.join(" ")}`);
    });
    expect(violations).toEqual([]);
  });
});

test("#344 A02: Skip — continue without a profile sits near the top, above the fields, and the bottom button stays", async ({ page }) => {
  await startSessionOnly(page);
  const skip = page.getByRole("button", { name: "Skip — continue without a profile" });
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(skip).toBeInViewport();
  const [skipY, ageY] = await Promise.all([skip, page.getByLabel("Age in years")].map((l) => l.evaluate((e) => e.getBoundingClientRect().top)));
  expect(skipY).toBeLessThan(ageY);
  await expect(page.getByRole("button", { name: "Use for this session" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("#344 A02: Skip lands on A03 with the same session context as an empty profile", async ({ page }) => {
  const viaEmpty = await contextSent(page, () => page.getByRole("button", { name: "Use for this session" }).click());
  // A fresh guest session in the same browser: the session cookie goes, and the page reload drops in-memory state.
  await page.context().clearCookies();
  const viaSkip = await contextSent(page, () => page.getByRole("button", { name: "Skip — continue without a profile" }).click());
  expect(viaSkip).toEqual(viaEmpty);
  // Blank is unknown, never a negative fact.
  expect(viaSkip).toContainEqual(expect.objectContaining({ kind: "allergy_status", value: "unknown" }));
  expect(viaSkip).toContainEqual(expect.objectContaining({ kind: "age_years", value: null }));
});

test("#344 A02: Skip after entering details asks first; Keep my details stays, confirming drops them", async ({ page }) => {
  await startSessionOnly(page);
  await page.getByLabel("Age in years").fill("38");
  await page.getByRole("button", { name: "Skip — continue without a profile" }).click();
  const dialog = page.getByRole("dialog", { name: "Continue without a profile?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Keep my details" }).click();
  await expect(page).toHaveURL(/\/app\/profile$/);
  await expect(page.getByLabel("Age in years")).toHaveValue("38");
  await page.getByRole("button", { name: "Skip — continue without a profile" }).click();
  await dialog.getByRole("button", { name: "Continue without a profile" }).click();
  await expect(page).toHaveURL(/\/app\/new$/);
  // Back to the profile: the skipped details were not kept.
  await page.getByRole("button", { name: "Back to profile" }).click();
  await expect(page.getByLabel("Age in years")).toHaveValue("");
});
