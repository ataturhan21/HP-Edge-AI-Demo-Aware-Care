// Easier-to-use pass of 2026-10-19 (#228-#237), from a screen-by-screen audit of question types, records, review,
// urgent help, empty states and the presenter screens at 1440 and 360.
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { answerAll, answerCurrent, enterConcern, expectNoHorizontalOverflow, openQuestion, startSession, toGuidance } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

/** Answers questions until one of the given type is shown; returns false if the intake ends first. */
async function answerUntil(page: Page, selector: string): Promise<boolean> {
  for (let i = 0; i < 10; i++) {
    const slot = await openQuestion(page); // #506
    if (slot === null) return false;
    if (await page.locator(`form.card ${selector}`).count()) return true;
    await answerCurrent(page, "answer");
    await expect(page.getByText(`Question ${slot} of up to 10`, { exact: true })).toHaveCount(0);
  }
  return false;
}

test("#228 a scale is a row of value buttons with its end meanings, operable by keyboard", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  expect(await answerUntil(page, "fieldset.scale")).toBe(true);
  const scale = page.locator("fieldset.scale");
  await expect(scale.getByRole("radio")).toHaveCount(11);
  await expect(page.locator("form.card select")).toHaveCount(0);
  await expect(scale.locator(".scale-anchors")).toContainText("0 = No impact");
  await expect(scale.locator(".scale-anchors")).toContainText("10 = Highest impact");
  await expect(scale).toHaveAccessibleDescription(/No impact.*Highest impact/);
  await scale.getByRole("radio", { name: "6", exact: true }).check();
  await page.keyboard.press("ArrowRight");
  await expect(scale.getByRole("radio", { name: "7", exact: true })).toBeChecked();
  await expect(scale.locator(".scale-option.selected")).toHaveText("7");
  await expectNoHorizontalOverflow(page);
  await page.getByRole("button", { name: "Submit answer" }).click();
  await answerAll(page);
  await expect(page.getByText("7 on a 0–10 scale")).toBeVisible();
});

test("#229 choice questions say whether to choose one or all that apply", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await expect(page.locator("form.card fieldset").first()).toHaveAccessibleDescription("Choose one");
  expect(await answerUntil(page, "input[type=checkbox]")).toBe(true);
  await expect(page.locator("form.card fieldset").first()).toHaveAccessibleDescription("Choose all that apply");
  await expect(page.getByText("Choose all that apply", { exact: true })).toBeVisible();
});

test("#230 the answer editor opens under the answer it changes and takes focus; Cancel returns focus", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  const change = page.getByRole("button", { name: /^Change answer to / }).nth(4);
  const name = (await change.textContent())!.replace(/^Change answer to /, "");
  await change.click();
  const editor = page.getByRole("group", { name: `Change answer: ${name}` });
  await expect(editor).toBeFocused();
  await expect(change).toHaveAttribute("aria-expanded", "true");
  // Directly after the answer's row, not after the whole list.
  const follows = await editor.evaluate((el) => el.previousElementSibling?.querySelector("button[data-change-for]") !== null);
  expect(follows).toBe(true);
  await editor.getByRole("button", { name: "Cancel" }).click();
  await expect(editor).toHaveCount(0);
  await expect(change).toBeFocused();
});

test("#231 an extracted record fact says what it is about, what the record says, and what each action does", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A mild headache since Monday.");
  await page.getByRole("checkbox", { name: "None of these apply" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/records$/);
  await page.getByRole("button", { name: "Add sample PDF" }).click();
  const fact = page.getByLabel("Extracted fact", { exact: true });
  await expect(fact.getByRole("heading", { name: "Medications" })).toBeVisible({ timeout: 15_000 });
  await expect(fact).toContainText("What the record says: “No medications listed in sample record”");
  await expect(fact.getByText("Confirm uses it as the record says. Correct lets you change it first. Reject leaves it out.")).toBeVisible();
  await expect(page.locator("section.card", { has: page.getByRole("heading", { name: "Review extracted facts" }) })).toBeVisible();
});

test("#232 an unavailable consultation explains why, offers a way on, and shows no step indicator", async ({ page }) => {
  await startSession(page);
  await page.goto("/app/cases/00000000-0000-4000-8000-000000000000/questions");
  await expect(page.getByRole("heading", { level: 1, name: "This consultation is not available" })).toBeVisible();
  await expect(page.getByText(/ended with your guest session, been deleted, or belong to a different session/)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Consultation steps" })).toHaveCount(0);
  await expect(page.getByRole("main").getByRole("link", { name: "Start a new consultation" })).toBeVisible();
  await page.getByRole("link", { name: "Go to history" }).click();
  await expect(page).toHaveURL(/history$/);
  await page.goto("/app/new"); // the indicator comes back on a real step
  await expect(page.getByRole("navigation", { name: "Consultation steps" })).toBeVisible();
});

test("#233 urgent help shows one emergency instruction; the generic one only when the level is unknown", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("Crushing chest pain.");
  await page.getByRole("checkbox", { name: /Chest pain or pressure/ }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/urgent$/);
  await expect(page.getByRole("alert")).toHaveCount(1);
  await expect(page.getByRole("alert")).toContainText("Call 911 now or go to the nearest emergency department.");
  await expect(page.getByText("Routine guidance and doctor matching are not available for this consultation.")).toBeVisible();
  // Without a readable case (no reviewed level), the generic alert is the fallback.
  const url = page.url();
  await page.route("**/api/v1/cases/*", (r) => r.request().method() === "GET" ? r.fulfill({ status: 404, contentType: "application/json",
    body: JSON.stringify({ code: "NOT_FOUND", message: "Not found.", field_errors: [], retryable: false, request_id: "00000000-0000-4000-8000-000000000000" }) }) : r.continue());
  await page.goto(url);
  await expect(page.getByRole("alert")).toContainText("If this could be an emergency, call 911");
});

test("#234 presenter scenario cards say what each scenario shows, verbatim from the fixtures", async ({ page }) => {
  const fixtures = JSON.parse(readFileSync(`${__dirname}/../../fixtures/scenarios.json`, "utf8"));
  const list = (Array.isArray(fixtures) ? fixtures : fixtures.scenarios) as { id: string; desc: string }[];
  await page.goto("http://127.0.0.1:15174/presenter/scenarios/more"); // #358: full journeys
  await page.getByRole("button", { name: "Start presenter session" }).click();
  // #315: the History instruction is gone; #688: a full journey opens at its first question in this window.
  await expect(page.getByText(/A full journey opens at its first question in this window, as the Demo patient/)).toBeVisible();
  for (const s of list) await expect(page.getByText(s.desc, { exact: true })).toBeVisible();
});

test("#235 the doctor list says how many match, with Change preferences above it", async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/preferences`);
  await page.getByRole("button", { name: "Find matches" }).click();
  const head = page.locator(".results-head");
  await expect(head).toContainText(/^\d+ fictional doctors? match(es)? your requirements\./);
  const count = Number((await head.locator("b").textContent())!);
  await expect(page.locator("article.provider")).toHaveCount(count);
  await head.getByRole("link", { name: "Change preferences" }).click();
  await expect(page).toHaveURL(/preferences$/);
});

test("#236 the concern screen explains the demo in plain words, and names the mode only once it is known", async ({ page }) => {
  // #322: the telemetry identity would name the mode at page load; without it the mode is unknown until a question.
  await page.route("**/v1/telemetry*", (route) => route.abort());
  await startSession(page);
  const notice = page.locator(".notice", { hasText: "Synthetic demonstration" });
  await expect(notice).toContainText("Depending on how this demo is running");
  await expect(notice).not.toContainText(/mock mode|local mode/i);
  await enterConcern(page); // the first question proves the mode (mock on this stack)
  const nav = page.getByRole("navigation", { name: "Main" });
  const menu = nav.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click(); // phones: links sit behind the Menu (#182); in-app, so the mode is kept
  await nav.getByRole("link", { name: "Start a new consultation" }).click();
  await expect(notice).toContainText("This demo is running a scripted scenario");
});

test("#237 review explains what skipped or Not sure answers do to the guidance and marks them", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page, (slot) => (slot === 2 || slot === 5 ? "skip" : "answer"));
  const banner = page.locator(".notice", { hasText: "skipped or answered “Not sure”" });
  await expect(banner).toContainText("2 questions were skipped or answered “Not sure”");
  await expect(banner).toContainText("the guidance will not suggest self-care: it points you to a clinician instead");
  await expect(page.locator(".datum-gap")).toHaveCount(2);
});
