// #677 (owner decision, 28 Oct 2026: warn first): a quick flow, its Try again and Load scenario give this browser's
// patient tab a demo patient, which ends a consultation typed by hand in the same browser. The presenter screen warns
// first, with what happens, the safe alternative and 2 choices; never when there is nothing to lose. Mock stack.
import { expect, test, type Page } from "@playwright/test";
import { enterConcern, startSession, startSessionOnly } from "./support/journey";

const DEVICE = "HP ZGX Nano";
const TITLE = "A consultation typed by hand is open in this browser";
const FLOW_EFFECT = "Running this quick flow ends it: this browser's patient pages get a synthetic demo patient " +
  "instead, and the consultation typed by hand can no longer be opened here (its tab says “Your session ended”). " +
  "Its answers stay on the device, out of reach, until its session expires.";
const SCENARIO_EFFECT = FLOW_EFFECT.replace("Running this quick flow", "Loading this scenario");
const ALTERNATIVE = "To keep it, choose Cancel. Type consultations by hand in a separate browser or a private window: " +
  "presenter demos never touch them there.";

async function startPresenter(page: Page, path = "/presenter/scenarios") {
  await page.goto(path);
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByRole("heading", { level: 1, name: path.endsWith("/more") ? "More scenarios" : "Demo scenarios" }))
    .toBeVisible();
  await expect(page.getByText("mock mode: scripted outcomes, no AI model")).toBeVisible();
}

const runButton = (page: Page, title: string) => page.getByRole("button", { name: `Run on ${DEVICE}: ${title}` });
const warning = (page: Page) => page.getByRole("alertdialog", { name: TITLE });

/** The presenter's loads (quick flows and Load scenario), so a test can prove that Cancel loaded nothing. */
function loads(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/presenter\/scenarios\/[a-z]+\/load$/.test(new URL(r.url()).pathname)) seen.push(r.url());
  });
  return seen;
}

/** A consultation typed by hand in this browser: consent, profile, concern, then the first question. */
async function handTyped(page: Page): Promise<string> {
  await startSession(page);
  const caseId = await enterConcern(page);
  return caseId;
}

test("#677 a quick flow warns before it ends a consultation typed by hand; Cancel and Escape keep it", async ({ context }) => {
  const patient = await context.newPage();
  const caseId = await handTyped(patient);
  const page = await context.newPage();
  await startPresenter(page);
  const sent = loads(page);

  await runButton(page, "Guidance from the local AI").click();
  const box = warning(page);
  await expect(box).toBeVisible();
  await expect(box).toHaveAttribute("aria-modal", "true");
  await expect(box).toContainText(FLOW_EFFECT);
  await expect(box).toContainText(ALTERNATIVE);
  await expect(box.locator("#hand-typed-effect")).toHaveText(FLOW_EFFECT);
  await expect(page.getByRole("dialog")).toHaveCount(0); // no progress dialog: nothing runs yet
  // Keyboard: focus starts on Cancel (the safe choice) and stays inside the 2 choices.
  await expect(box.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(box.getByRole("button", { name: "Continue anyway" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(box.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(box.getByRole("button", { name: "Continue anyway" })).toBeFocused();
  // Escape cancels; focus goes back to the Run button.
  await page.keyboard.press("Escape");
  await expect(box).toHaveCount(0);
  await expect(runButton(page, "Guidance from the local AI")).toBeFocused();
  // Cancel does the same.
  await runButton(page, "Self-care guidance").click();
  await warning(page).getByRole("button", { name: "Cancel" }).click();
  await expect(warning(page)).toHaveCount(0);
  await expect(runButton(page, "Self-care guidance")).toBeFocused();
  expect(sent).toEqual([]);

  // The consultation typed by hand is still this browser's: History lists it and it continues at its questions.
  await patient.bringToFront();
  await patient.goto("/app/history");
  await expect(patient.getByRole("button", { name: "Continue questions" })).toHaveCount(1);
  await patient.getByRole("button", { name: "Continue questions" }).click();
  await expect(patient).toHaveURL(new RegExp(`/app/cases/${caseId}/questions$`));
  await expect(patient.getByText("Your session ended")).toHaveCount(0);
});

test("#677 Continue anyway runs the flow and ends the consultation as the warning says; demos alone are never warned about", async ({ context }) => {
  const patient = await context.newPage();
  await handTyped(patient);
  const page = await context.newPage();
  await startPresenter(page);

  await runButton(page, "Guidance from the local AI").click();
  await warning(page).getByRole("button", { name: "Continue anyway" }).click();
  await expect(warning(page)).toHaveCount(0);
  const progress = page.getByTestId("flow-dialog");
  await expect(progress).toBeVisible();
  await expect(progress.getByRole("heading", { name: "Guidance from the local AI" })).toBeFocused();
  await expect(progress.getByRole("button", { name: "Open the result" })).toBeVisible({ timeout: 30_000 });
  await progress.getByRole("button", { name: "Close" }).click();

  // The patient tab's consultation typed by hand has ended, as the warning said.
  await patient.bringToFront();
  await patient.getByRole("link", { name: "History" }).click();
  await expect(patient.getByText("Your session ended")).toBeVisible();

  // Now the browser holds only the demo patient's session: the next flow runs without a warning.
  await page.bringToFront();
  await runButton(page, "Self-care guidance").click();
  await expect(page.getByTestId("flow-dialog")).toBeVisible();
  await expect(warning(page)).toHaveCount(0);
});

test("#677 no warning without a consultation typed by hand, also with a guest session that has none", async ({ context }) => {
  const patient = await context.newPage();
  await startSessionOnly(patient); // consent only: no consultation yet
  const page = await context.newPage();
  await startPresenter(page);
  await runButton(page, "Urgent warning sign").click();
  await expect(page.getByTestId("flow-dialog")).toBeVisible();
  await expect(warning(page)).toHaveCount(0);
});

test("#677 Load scenario warns too, by keyboard only; Continue anyway loads it in this window (#688)", async ({ context }) => {
  const patient = await context.newPage();
  await handTyped(patient);
  const page = await context.newPage();
  await startPresenter(page, "/presenter/scenarios/more");
  const sent = loads(page);

  const load = page.getByRole("button", { name: "Load scenario: Find the right clinician" });
  await load.focus();
  await page.keyboard.press("Enter");
  const box = warning(page);
  await expect(box).toBeVisible();
  await expect(box.locator("#hand-typed-effect")).toHaveText(SCENARIO_EFFECT);
  await expect(box.locator("#hand-typed-alternative")).toHaveText(ALTERNATIVE);
  await page.keyboard.press("Escape");
  await expect(box).toHaveCount(0);
  await expect(load).toBeFocused();
  expect(sent).toEqual([]);

  await page.keyboard.press("Enter");
  await expect(warning(page)).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(warning(page).getByRole("button", { name: "Continue anyway" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/questions$/); // #688: the Demo patient, in this window
  await expect(page.getByTestId("mode-strip")).toContainText("Presenter mode · Demo patient");
  expect(sent).toHaveLength(1);
});
