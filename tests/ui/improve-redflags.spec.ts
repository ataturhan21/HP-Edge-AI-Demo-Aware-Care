// Warning-sign checklist on A03 (#355, maintainer decision 2026-10-21: "add it to the top and group signs"). "None of
// these apply" is the first control of the question, and the reviewed signs sit under short body-system headings
// below it, all visible. Presentation only: wording, levels and IDs come unchanged from the reviewed package
// (content/pathways/general-adult-4/red-flags.json). Runs on the isolated mock stack at 1440x900 and 360x780.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Locator } from "@playwright/test";
import { animationsSettled, startSession } from "./support/journey";

const ROOT = join(__dirname, "../..");
const AXE = join(ROOT, "apps/web/node_modules/axe-core/axe.min.js");
type Flag = { id: string; level: string; text: string };
const PACKAGE = JSON.parse(readFileSync(join(ROOT, "content/pathways/general-adult-4/red-flags.json"), "utf8")) as {
  none_label: string; red_flags: Flag[];
};
const REVIEWED_IDS = PACKAGE.red_flags.map((f) => f.id);

/** The group mapping as written in RedFlags.tsx (the one place it lives), read from its markers. */
function groupsInSource(): { id: string; title: string; ids: string[] }[] {
  const source = readFileSync(join(ROOT, "apps/web/src/components/RedFlags.tsx"), "utf8");
  const match = /\/\* sign-groups:begin \*\/(.*?)\/\* sign-groups:end \*\//s.exec(source);
  expect(match, "RedFlags.tsx has a sign-groups block").not.toBeNull();
  return JSON.parse(match![1]);
}

const top = (l: Locator) => l.evaluate((e) => (e.closest("label") ?? e).getBoundingClientRect().top + window.scrollY);
const none = (page: import("@playwright/test").Page) => page.getByRole("checkbox", { name: PACKAGE.none_label });
const question = (page: import("@playwright/test").Page) => page.getByRole("group", { name: "Do any of these apply to you right now?" });

test("#355 every reviewed sign is in exactly one group, and no group names an unknown sign", () => {
  const groups = groupsInSource();
  const all = groups.flatMap((g) => g.ids);
  expect([...all].sort()).toEqual([...REVIEWED_IDS].sort());
  expect(new Set(all).size).toBe(all.length);
  for (const g of groups) {
    expect(g.ids.length).toBeGreaterThan(0);
    expect(g.title.length).toBeLessThanOrEqual(40); // short headings
    // Within a group the reviewed order is kept.
    expect(g.ids).toEqual([...g.ids].sort((a, b) => REVIEWED_IDS.indexOf(a) - REVIEWED_IDS.indexOf(b)));
  }
});

test("#355 'None of these apply' is the one exclusive control, first in the question, above every sign", { tag: "@mobile" }, async ({ page }, info) => {
  await startSession(page);
  await expect(none(page)).toHaveCount(1);
  await expect(page.getByRole("link", { name: /Go to “None of these apply”/ })).toHaveCount(0); // #214 link no longer needed
  // The first checkbox of the question is the exclusive choice.
  await expect(question(page).getByRole("checkbox").first()).toHaveAccessibleName(PACKAGE.none_label);
  const [legendY, noneY, firstSignY] = await Promise.all([
    top(question(page).locator("legend")), top(none(page)), top(page.locator('input[name="red-flags"]').first())]);
  expect(noneY).toBeLessThan(firstSignY);
  // Right below the question and its hint: on the same screen as the question's title (before #355: 2,291 px at
  // 1440 and 3,232 px at 360 on this stack, after all signs).
  expect(noneY - legendY).toBeLessThan(info.project.name === "mobile-360" ? 260 : 160);
  expect(noneY).toBeLessThan(info.project.name === "mobile-360" ? 1200 : 1000);
  // Scrolled to the question, the exclusive choice is in the first screen.
  await question(page).locator("legend").evaluate((e) => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 16));
  await expect(none(page)).toBeInViewport();
});

test("#355 the signs sit under short body-system headings, all visible, with the reviewed wording", async ({ page }) => {
  await startSession(page);
  const groups = groupsInSource();
  const named = question(page).getByRole("group");
  await expect(named).toHaveCount(groups.length);
  for (const [i, g] of groups.entries()) {
    const group = named.nth(i);
    await expect(group).toHaveAccessibleName(g.title);
    await expect(group.getByRole("heading", { level: 2 })).toHaveText(g.title);
    const boxes = group.getByRole("checkbox");
    expect(await boxes.evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value))).toEqual(g.ids);
    for (const id of g.ids) {
      const flag = PACKAGE.red_flags.find((f) => f.id === id)!;
      const label = group.locator("label", { has: page.locator(`input[value="${id}"]`) });
      await expect(label).toHaveText(flag.text); // exactly the reviewed wording
      await expect(label).toBeVisible();
    }
  }
  // All reviewed signs, each once, nothing else ticked by name.
  const values = await page.locator('input[name="red-flags"]').evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value));
  expect([...values].sort()).toEqual([...REVIEWED_IDS].sort());
});

test("#355 'None of these apply' and the signs still exclude each other", async ({ page }) => {
  await startSession(page);
  await expect(page.locator(".choice-divider")).toHaveText("or"); // #184 (formerly ux.spec.ts): set apart
  const seizure = page.getByRole("checkbox", { name: "A seizure" });
  const blood = page.getByRole("checkbox", { name: "Coughing up blood" });
  await none(page).check();
  await seizure.check();
  await expect(none(page)).not.toBeChecked();
  await blood.check();
  await expect(page.locator(".choice-feedback")).toHaveText("2 signs ticked. Continue will take you to urgent help.");
  await none(page).check();
  await expect(seizure).not.toBeChecked();
  await expect(blood).not.toBeChecked();
  await expect(page.locator(".choice-feedback")).toHaveText("");
  await none(page).uncheck();
  await expect(question(page).getByRole("checkbox", { checked: true })).toHaveCount(0);
});

test("#355 the error summary link and the keyboard reach 'None of these apply' first", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await page.getByRole("button", { name: "Continue" }).click();
  const summary = page.getByRole("group", { name: "Check these before you continue" });
  await expect(summary).toBeFocused();
  await summary.getByRole("link", { name: "Answer whether any warning signs apply to you" }).click();
  await expect(none(page)).toBeFocused();
  await expect(page.locator("#red-flags-first")).toHaveAccessibleName(PACKAGE.none_label);
  await expect(none(page)).toBeInViewport();
  await page.keyboard.press("Space");
  await expect(summary).toHaveCount(0);
  // From the concern field, the next Tab stop is the exclusive choice.
  await page.getByLabel("Main concern").focus();
  await page.keyboard.press("Tab");
  await expect(none(page)).toBeFocused();
});

test.describe("#355 axe", () => {
  test.use({ bypassCSP: true });
  test("#355 A03 with the grouped checklist passes axe (WCAG 2.2 AA and best practice)", async ({ page }) => {
    await startSession(page);
    await page.getByRole("checkbox", { name: "A seizure" }).check();
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
