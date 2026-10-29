// #688 (owner decision B1, 28 Oct 2026): presenter and patient are fully separate modes. Every page shows a colored
// mode strip ("Presenter mode" or "Patient mode") with a Switch link; a quick flow's result and a full journey open in
// the presenter's own window as the "Demo patient", with "Back to presenter" and no pop-up; the home page's Patient
// choice always starts a fresh consultation and never sees a demo session (History in Patient mode lists only the
// person's own consultations). Nothing here grants a role: the server decides (tests/ui/O03.spec.ts).
import { expect, test, type Page } from "@playwright/test";
import { ADDRESS, apiCalls, enterConcern, expectNoHorizontalOverflow, startSession } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const DEVICE = "HP ZGX Nano";
const strip = (page: Page) => page.getByTestId("mode-strip");

async function presenterSession(page: Page, path = "/presenter/scenarios") {
  await page.goto(`${ADDRESS}${path}`);
  const start = page.getByRole("button", { name: "Start presenter session" });
  await start.click();
  await expect(start).toBeHidden();
  await expect(page.locator(".flow-card, .scenario-card").first()).toBeVisible();
}

/** Runs a quick flow and opens its result from the dialog; returns the result's path. */
async function runAndOpen(page: Page, title: string, ends: RegExp): Promise<string> {
  await page.getByRole("button", { name: `Run on ${DEVICE}: ${title}` }).click();
  const open = page.getByRole("dialog").getByRole("button", { name: "Open the result" });
  await expect(open).toBeVisible({ timeout: 30_000 });
  await open.click();
  await expect(page).toHaveURL(ends, { timeout: 30_000 });
  return new URL(page.url()).pathname;
}

test("#688 every page shows its mode strip, and Switch leads to the other mode", { tag: "@mobile" }, async ({ page }) => {
  for (const path of ["/", "/help", "/telemetry", "/app/start", "/how-it-works"]) {
    await page.goto(path);
    await expect(strip(page), path).toHaveAttribute("data-mode", "patient");
    await expect(strip(page)).toContainText("Patient mode");
    await expect(strip(page).getByRole("link", { name: "Switch to presenter mode" })).toHaveAttribute("href", "/presenter/scenarios");
    await expectNoHorizontalOverflow(page);
  }
  await strip(page).getByRole("link", { name: "Switch to presenter mode" }).click();
  await expect(page).toHaveURL(`${ADDRESS}/presenter/scenarios`);
  await expect(strip(page)).toHaveAttribute("data-mode", "presenter");
  await expect(strip(page)).toContainText("Presenter mode");
  await expectNoHorizontalOverflow(page);
  // The two modes differ in color, not only in words.
  const presenterColor = await strip(page).evaluate((el) => getComputedStyle(el).backgroundColor);
  // Telemetry from the presenter navigation stays in Presenter mode; a public page opened from here says so too.
  for (const path of ["/presenter/runtime", "/presenter/telemetry", "/presenter/scenarios/more", "/help"]) {
    await page.goto(path);
    await expect(strip(page), path).toHaveAttribute("data-mode", "presenter");
  }
  await expect(strip(page).getByRole("link", { name: "Back to presenter" })).toHaveAttribute("href", "/presenter/scenarios/more");
  await strip(page).getByRole("link", { name: "Switch to patient mode" }).click();
  await expect(page).toHaveURL(`${ADDRESS}/`);
  await expect(strip(page)).toHaveAttribute("data-mode", "patient");
  const patientColor = await strip(page).evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(patientColor).not.toBe(presenterColor);
  await page.goto("/help");
  await expect(strip(page)).toHaveAttribute("data-mode", "patient"); // the tab keeps the mode it switched to
});

test("#688 the mode strip works by keyboard with visible focus", async ({ page }) => {
  await page.goto("/");
  const switchLink = strip(page).getByRole("link", { name: "Switch to presenter mode" });
  await expect(switchLink).toBeVisible();
  // #704: it reads as words on a wide screen (the flex item dropped the space: "Switchto presenter mode")
  expect(await switchLink.evaluate((el) => (el as HTMLElement).innerText)).toBe("Switch to presenter mode");
  await page.locator("a.skip").focus(); // the page's first stop
  await page.keyboard.press("Tab");
  await expect(switchLink).toBeFocused(); // the strip comes right after it, before the navigation
  expect(await switchLink.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/presenter\/scenarios$/);
});

test("#688 a quick flow's result opens in this window as the Demo patient, with Back to presenter and no pop-up", { tag: "@mobile" }, async ({ context }) => {
  const page = await context.newPage();
  const popups: Page[] = [];
  page.on("popup", (p) => popups.push(p));
  await presenterSession(page);
  const path = await runAndOpen(page, "Guidance from the local AI", /\/app\/cases\/[0-9a-f-]+\/guidance$/);
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
  await expect(strip(page)).toHaveAttribute("data-mode", "presenter");
  await expect(strip(page)).toContainText("Presenter mode · Demo patient");
  await expectNoHorizontalOverflow(page);
  expect(popups, "no pop-up").toHaveLength(0);
  expect(context.pages()).toHaveLength(1);
  await strip(page).getByRole("link", { name: "Back to presenter" }).click();
  await expect(page).toHaveURL(`${ADDRESS}/presenter/scenarios`);
  const status = page.locator(".flow-card", { hasText: "Guidance from the local AI" }).locator(".flow-status");
  await expect(status).toContainText("Shown as the Demo patient");
  await expect(status.getByRole("link", { name: "Show again" })).toHaveAttribute("href", path);
  await status.getByRole("link", { name: "Show again" }).click();
  await expect(page).toHaveURL(`${ADDRESS}${path}`);
  await expect(strip(page)).toContainText("Demo patient");
  expect(popups).toHaveLength(0);
});

test("#688 a full journey from More scenarios opens in this window as the Demo patient", async ({ page }) => {
  const popups: Page[] = [];
  page.on("popup", (p) => popups.push(p));
  await presenterSession(page, "/presenter/scenarios/more");
  await page.getByRole("button", { name: "Load scenario: Find the right clinician" }).click();
  await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/questions$/);
  await expect(page.getByText("Question 1 of up to 10")).toBeVisible();
  await expect(strip(page)).toContainText("Presenter mode · Demo patient");
  await strip(page).getByRole("link", { name: "Back to presenter" }).click();
  await expect(page).toHaveURL(`${ADDRESS}/presenter/scenarios/more`);
  expect(popups).toHaveLength(0);
});

test("#688 after a quick flow the home page's Patient choice starts fresh and never sees the demo", async ({ page }) => {
  const calls = apiCalls(page);
  await presenterSession(page);
  const demo = await runAndOpen(page, "Self-care guidance", /\/guidance$/);
  const demoCase = demo.split("/")[3];
  await strip(page).getByRole("link", { name: "Switch to patient mode" }).click();
  await expect(page).toHaveURL(`${ADDRESS}/`);
  await expect(strip(page)).toContainText("Patient mode");
  const patient = page.getByRole("article", { name: "Patient: try it yourself" });
  await expect(patient.getByRole("link", { name: "Start a new consultation" })).toHaveAttribute("href", "/app/start");
  await expect(page.getByText("Your guest session is still open")).toHaveCount(0);
  // The header never offers to continue the demo patient's consultation either.
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Continue consultation" })).toHaveCount(0);
  // My consultations is offered only for the person's own consultations: the demo patient's are none of them.
  await expect(patient.getByRole("link", { name: "Start a new consultation" })).toBeVisible();
  await expect(patient.getByRole("link", { name: "My consultations" })).toHaveCount(0);
  // History in Patient mode leaves the demo patient's consultations out, and starts a new one with a fresh session.
  await page.goto("/app/history");
  await expect(strip(page)).toContainText("Patient mode");
  await expect(page.locator(`a[href*="${demoCase}"], tbody tr`)).toHaveCount(0);
  await expect(page.getByText("No consultations yet")).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "Start a new consultation" })).toHaveAttribute("href", "/app/start");
  // Start a new consultation: a fresh guest session, not the demo patient's.
  calls.length = 0;
  await page.goto("/");
  await page.getByRole("article", { name: "Patient: try it yourself" }).getByRole("link", { name: "Start a new consultation" }).click();
  await expect(page).toHaveURL(/\/app\/start$/);
  await expect(page.getByText("Your guest session is still open")).toHaveCount(0);
  await page.getByLabel("Yes, I am 18 or older").check();
  await page.getByLabel("I understand and accept these terms.").check();
  await page.getByRole("button", { name: "Accept and begin" }).click();
  await expect(page).toHaveURL(/\/app\/profile$/);
  await expect(strip(page)).toContainText("Patient mode");
  expect(calls.filter((c) => c.startsWith("/presenter-api/")), calls.join(", ")).toEqual([]);
});

test("#688 a consultation typed by hand stays in Patient mode, and its History lists it", async ({ page }) => {
  await startSession(page);
  const own = await enterConcern(page);
  await expect(strip(page)).toContainText("Patient mode");
  await page.goto("/");
  await page.getByRole("article", { name: "Patient: try it yourself" }).getByRole("link", { name: "My consultations" }).click();
  await expect(page.locator("tbody tr, .history-card").first()).toBeVisible();
  await expect(page.getByRole("main")).not.toContainText("No consultations");
  expect(page.url()).toContain("/app/history");
  expect(own).toMatch(/^[0-9a-f-]{36}$/);
});
