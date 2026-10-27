// #358 (ADR-016 amendment 2, CHG-DEV-API-006): the presenter's Scenarios page is three one-click flows. Scenarios is
// the first presenter tab; each flow has every input ready, and one click runs the flow on the device then and there.
// #548: the click opens no tab: a dialog on the presenter screen shows the progress (the steps from the job's real
// stage, the device, the elapsed seconds, the usual time), then "Open the result", whose click lands the one patient tab
// on the finished screen. A failure says so and never shows a substitute. Full journeys and the reset moved to
// "More scenarios" (/presenter/scenarios/more). The suite runs the mock stack; local-mode wording is checked with the
// runtime snapshot shown as local, and the server side of local mode by tests/acceptance/test_R37.py.
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { animationsSettled, expectNoHorizontalOverflow } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const PRESENTER = "http://127.0.0.1:15174";
const PATIENT = "http://127.0.0.1:15174";
const DEVICE = "HP ZGX Nano";
const FLOWS = ["Guidance from the local AI", "Self-care guidance", "Urgent warning sign"];
const runButton = (page: Page, title: string) => page.getByRole("button", { name: `Run on ${DEVICE}: ${title}` });
const card = (page: Page, title: string) =>
  page.locator(".flow-card", { has: page.getByRole("heading", { name: title, exact: true }) });
const dialog = (page: Page) => page.getByRole("dialog");
/** #548: no tab may open while a flow runs; collects any that do. */
function popupsOf(page: Page): Page[] {
  const popups: Page[] = [];
  page.on("popup", (p) => popups.push(p));
  return popups;
}
/** #548: the dialog's "Open the result" (the click that opens the patient tab); returns the tab. */
async function openResult(page: Page, tab: Page | null = null): Promise<Page> {
  const open = dialog(page).getByRole("button", { name: "Open the result" });
  await expect(open).toBeVisible({ timeout: 30_000 });
  if (tab) {
    await open.click();
    return tab;
  }
  const popup = page.waitForEvent("popup");
  await open.click();
  return popup;
}

async function presenterOn(page: Page, path = "/presenter/scenarios") {
  await page.goto(`${PRESENTER}${path}`);
  const start = page.getByRole("button", { name: "Start presenter session" });
  await start.click();
  await expect(start).toBeHidden();
}

async function asLocal(page: Page) {
  await page.route("**/presenter-api/v1/presenter/runtime", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), mode: "local" } });
  });
}

test("#358 Scenarios is the first presenter tab, and its secondary view is a tab too", async ({ page }) => {
  await presenterOn(page);
  const nav = page.getByRole("navigation", { name: "Presenter" });
  const menu = nav.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  const links = nav.locator(".navlinks a");
  await expect(links.first()).toHaveText("Scenarios");
  await expect(links).toHaveText(["Scenarios", "Runtime", "Controls", "Telemetry", "More scenarios"]);
  await expect(links.first()).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "More scenarios" })).not.toHaveAttribute("aria-current", "page");
});

test("#358 the Scenarios page shows only the three quick flows, one button each, and one line of device status", async ({ page }) => {
  await presenterOn(page);
  const main = page.locator("main");
  await expect(main.getByRole("heading", { level: 1, name: "Demo scenarios" })).toBeVisible();
  await expect(main.locator(".flow-card")).toHaveCount(3);
  await expect(main.getByRole("heading", { level: 2 })).toHaveText(FLOWS);
  await expect(main.getByRole("button")).toHaveCount(3);
  for (const title of FLOWS) {
    await expect(runButton(page, title)).toHaveText(`Run on ${DEVICE}`);
    await expect(card(page, title).locator(".flow-line")).toBeVisible();
  }
  await expect(main.locator(".o03-line")).toHaveText(`${DEVICE} · mock mode: scripted outcomes, no AI model`);
  for (const gone of ["Prepare quick demos", "How these demos work", "Full journeys", "Load scenario", "Reset demo", "Reset for next audience"])
    await expect(main.getByText(gone)).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test("#548 one click runs a flow in a dialog; no tab opens until Open the result, which lands one tab on each result", async ({ context }, info) => {
  const page = await context.newPage();
  await presenterOn(page);
  const screens: [string, string, RegExp, (tab: Page) => ReturnType<Page["getByRole"]>][] = [
    ["Guidance from the local AI", "Guidance is ready", /\/app\/cases\/[0-9a-f-]+\/guidance$/, (t) => t.getByRole("heading", { name: "Your guidance", exact: true })],
    ["Self-care guidance", "Self-care guidance is ready", /\/app\/cases\/[0-9a-f-]+\/guidance$/, (t) => t.getByRole("heading", { name: "Your guidance", exact: true })],
    ["Urgent warning sign", "The case was routed to urgent help", /\/app\/cases\/[0-9a-f-]+\/urgent$/, (t) => t.getByRole("heading", { name: "Seek urgent help now" })],
  ];
  let tab: Page | null = null;
  const seen = new Set<string>();
  for (const [title, outcome, url, content] of screens) {
    const popups = popupsOf(page);
    const started = Date.now();
    await runButton(page, title).click();
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page).getByRole("heading", { name: title })).toBeVisible();
    await expect(dialog(page)).toContainText(outcome, { timeout: 30_000 });
    expect(popups, "no tab opens before the click on Open the result").toHaveLength(0);
    tab = await openResult(page, tab);
    await expect(tab).toHaveURL(url, { timeout: 30_000 });
    await expect(content(tab)).toBeVisible();
    await expect(dialog(page)).toHaveCount(0); // opening the result closes the dialog
    const seconds = (Date.now() - started) / 1000;
    info.annotations.push({ type: "measure", description: `${title}: click to result ${seconds.toFixed(1)} s (mock stack)` });
    const status = card(page, title).locator(".flow-status");
    await expect(status).toContainText("Shown in the patient tab");
    // #462: one pair of parentheses; a sub-second run is never shown as "0 s".
    await expect(status).toContainText(/scripted outcome in mock mode, no AI model, (under 0\.1 s|\d+(\.\d)? s)\)/);
    await expect(status.getByRole("link", { name: "Show again" })).toHaveAttribute("href", new URL(tab.url()).pathname);
    await expect(status.getByRole("link", { name: "Show again" })).toHaveAttribute("target", "aware-care-patient");
    seen.add(tab.url());
  }
  expect(seen.size).toBe(3); // a fresh case per click
  expect(context.pages()).toHaveLength(2); // the presenter page and the one patient tab
  // Show again returns the patient tab to that flow's result.
  await card(page, "Guidance from the local AI").getByRole("link", { name: "Show again" }).click();
  await expect(tab!).toHaveURL(/\/guidance$/);
  await expect(tab!.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
});

test("#548 QA app-02: a second run never shows the earlier guidance as its result; the open tab moves only on the click", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page);
  await runButton(page, "Guidance from the local AI").click();
  const tab = await openResult(page);
  await expect(tab).toHaveURL(/\/guidance$/, { timeout: 30_000 });
  const first = tab.url();
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/presenter-api/v1/presenter/scenarios/selfcare/load", async (route) => {
    await held;
    await route.continue();
  });
  await page.bringToFront();
  await runButton(page, "Self-care guidance").click();
  await expect(dialog(page)).toContainText("Loading the scenario");
  await page.waitForTimeout(500);
  expect(tab.url(), "the patient tab is not touched while the second run works").toBe(first);
  release();
  await expect(dialog(page)).toContainText("Self-care guidance is ready", { timeout: 30_000 });
  expect(tab.url()).toBe(first); // still the first result until the presenter opens the new one
  await openResult(page, tab);
  await expect(tab).not.toHaveURL(first);
  await expect(tab).toHaveURL(/\/guidance$/);
  await expect(tab.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
  expect(context.pages()).toHaveLength(2);
});

test("#548 the dialog names the device and counts the seconds; Close keeps the run going and returns focus", async ({ context }) => {
  const page = await context.newPage();
  await asLocal(page);
  await presenterOn(page);
  await expect(page.locator(".o03-line")).toHaveText(`${DEVICE} · AI ready`);
  const popups = popupsOf(page);
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/presenter-api/v1/presenter/scenarios/routine/load", async (route) => {
    await held;
    await route.continue();
  });
  const button = card(page, "Guidance from the local AI").locator("button.flow-run");
  await button.focus();
  await page.keyboard.press("Enter");
  const box = dialog(page);
  await expect(box).toBeVisible();
  await expect(box).toHaveAttribute("aria-modal", "true");
  await expect(box.getByRole("heading", { name: "Guidance from the local AI" })).toBeFocused();
  await expect(box).toContainText(`Running on the ${DEVICE}`);
  await expect(box.locator(".flow-step")).toHaveText([/^Loading the scenario/, /checking for warning signs/,
    /writing the guidance/, /Checking the guidance/]);
  await expect(box.locator('[aria-current="step"]')).toContainText("Loading the scenario");
  const elapsed = box.getByTestId("flow-dialog-elapsed");
  await expect(elapsed).toHaveAttribute("aria-hidden", "true"); // shown every second, not announced
  await expect(elapsed).toHaveText(/^[1-9]\d* s elapsed$/, { timeout: 3_000 }); // it counts
  await expect(box).toContainText(/Usually .+ on this device\./);
  await expect(box).not.toContainText("%");
  await expect(box.getByTestId("flow-dialog-live")).toHaveText("Step 1 of 4: Loading the scenario.");
  // Tab stays inside the dialog (its one button), Escape closes it and focus returns to the Run button.
  await page.keyboard.press("Tab");
  await expect(box.getByRole("button", { name: "Close" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(box.getByRole("button", { name: "Close" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog(page)).toHaveCount(0);
  await expect(button).toBeFocused();
  await expect(button).toHaveAttribute("aria-busy", "true");
  for (const other of ["Self-care guidance", "Urgent warning sign"]) // one flow at a time
    await expect(runButton(page, other)).toHaveAttribute("aria-disabled", "true");
  const status = card(page, "Guidance from the local AI").locator(".flow-status");
  await expect(status).toContainText(`Loading the scenario on the ${DEVICE}…`);
  // The card offers the dialog again; the run went on while it was closed.
  await status.getByRole("button", { name: "Show progress" }).click();
  await expect(dialog(page)).toBeVisible();
  await dialog(page).getByRole("button", { name: "Close" }).click();
  await expect(button).toBeFocused();
  release();
  await expect(status).toContainText(`Ready: not shown yet (written by the AI on the ${DEVICE}`, { timeout: 30_000 });
  expect(popups).toHaveLength(0);
  await expect(page.locator("main")).not.toContainText(/scripted/i); // local mode is never labelled scripted
  const popup = page.waitForEvent("popup");
  await status.getByRole("link", { name: "Open in the patient tab" }).click();
  await expect(await popup).toHaveURL(/\/guidance$/);
  await expect(status).toContainText("Shown in the patient tab");
});

/**
 * #529/#548: the device's AI takes its time (12-30 s for guidance on the Nano): every read of the quick flow's prepare
 * job reports it still running at the step set with `stage(...)` until `release`, and the runtime snapshot reads as
 * local mode. Done in the page (a wrapped fetch), so the job reads keep their real timing.
 */
async function guidanceHeld(page: Page, title = "Guidance from the local AI"):
  Promise<{ stage: (s: string) => Promise<void>; release: () => Promise<void> }> {
  await page.addInitScript(() => {
    const real = window.fetch.bind(window);
    const w = window as unknown as { heldStage: string | null; releaseJobs: () => void };
    w.heldStage = "preparing";
    w.releaseJobs = () => (w.heldStage = null);
    window.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const response = await real(input, init);
      if (/\/v1\/jobs\//.test(url) && response.ok && w.heldStage !== null) {
        const job = await response.clone().json();
        if (job.kind !== "scenario_prepare") return response;
        const body = { ...job, status: "running", stage: w.heldStage, result_id: null, result_type: null, error_code: null,
          finished_at: null };
        return new Response(JSON.stringify(body), { status: response.status, headers: response.headers });
      }
      if (!/\/presenter-api\/v1\/presenter\/runtime$/.test(url) || !response.ok) return response;
      const body = { ...(await response.clone().json()), mode: "local" };
      return new Response(JSON.stringify(body), { status: response.status, headers: response.headers });
    };
  });
  await presenterOn(page);
  await expect(page.locator(".o03-line")).toHaveText(`${DEVICE} · AI ready`);
  await runButton(page, title).click();
  return {
    stage: (value: string) => page.evaluate((v) => {
      (window as unknown as { heldStage: string }).heldStage = v;
    }, value),
    release: () => page.evaluate(() => (window as unknown as { releaseJobs: () => void }).releaseJobs()),
  };
}

test("#548 the dialog follows the job's real steps, then says the guidance is ready and opens it on the click", { tag: "@mobile" }, async ({ context }) => {
  const page = await context.newPage();
  const popups = popupsOf(page);
  const { stage, release } = await guidanceHeld(page);
  const box = dialog(page);
  const current = box.locator('[aria-current="step"]');
  const live = box.getByTestId("flow-dialog-live");
  await expect(live).toHaveAttribute("aria-live", "polite");
  const spinner = box.getByTestId("flow-dialog-spinner");
  await expect(spinner).toBeVisible();
  await expect(spinner).toHaveCSS("animation-name", "spin");
  for (const [value, step, label] of [
    ["queued", 1, "Loading the scenario"],
    ["screening", 2, "The on-device AI is checking for warning signs"],
    ["writing", 3, "The on-device AI is writing the guidance"],
    ["checking", 4, "Checking the guidance"],
    ["rewriting", 3, "The on-device AI is writing the guidance"],
  ] as const) {
    await stage(value);
    await expect(current).toContainText(label, { timeout: 5_000 });
    await expect(live).toContainText(`Step ${step} of 4: ${label}`);
    await expect(box.locator(".flow-step.done")).toHaveCount(step - 1);
  }
  await expect(current).toContainText("a second draft, after the first did not pass a check");
  await expect(card(page, "Guidance from the local AI").locator(".flow-status"))
    .toContainText(`The on-device AI is writing the guidance on the ${DEVICE}…`);
  await expectNoHorizontalOverflow(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(spinner).toHaveCSS("animation-name", "none"); // reduced motion: a still ring
  await expect(spinner).toBeVisible();
  await release();
  await expect(box).toContainText("Guidance is ready", { timeout: 30_000 });
  await expect(box).toContainText(`Written by the AI on the ${DEVICE}`);
  await expect(live).toHaveText("Guidance is ready.");
  const open = box.getByRole("button", { name: "Open the result" });
  await expect(open).toBeFocused();
  expect(popups, "no tab before the click").toHaveLength(0);
  const tab = await openResult(page);
  await expect(tab).toHaveURL(/\/guidance$/, { timeout: 30_000 });
  await expect(tab.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
  await expect(runButton(page, "Guidance from the local AI")).toBeFocused();
});

test("#358 #548 a failed run says so plainly in the dialog, offers Try again, and never shows a substitute", async ({ context }) => {
  const page = await context.newPage();
  await asLocal(page);
  await presenterOn(page);
  const popups = popupsOf(page);
  // The device's guidance fails validation (as a failed local generation would).
  let failing = true;
  await page.route("**/v1/jobs/*", async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    await route.fulfill({ response, json: failing && job.kind === "scenario_prepare" && job.status !== "running"
      ? { ...job, status: "failed", error_code: "OUTPUT_VALIDATION_FAILED", result_id: null, result_type: null } : job });
  });
  await runButton(page, "Self-care guidance").click();
  const box = dialog(page);
  await expect(box).toContainText("Not shown", { timeout: 30_000 });
  await expect(box).toContainText("The guidance failed: the AI's answer did not pass the checks. Nothing was substituted.");
  await expect(box.getByTestId("flow-dialog-live"))
    .toHaveText("Not shown: The guidance failed: the AI's answer did not pass the checks. Nothing was substituted.");
  const again = box.getByRole("button", { name: "Try again" });
  await expect(again).toBeFocused();
  await expect(box.getByRole("button", { name: "Open the result" })).toHaveCount(0);
  const status = card(page, "Self-care guidance").locator(".flow-status");
  await expect(status).toContainText("the guidance failed: the AI's answer did not pass the checks. Nothing was substituted.");
  await expect(status.getByRole("link")).toHaveCount(0); // no Show again
  // Try again runs the flow again from the dialog; this time the device publishes.
  failing = false;
  await again.click();
  await expect(box).toContainText("Self-care guidance is ready", { timeout: 30_000 });
  await box.getByRole("button", { name: "Close" }).click();
  await expect(runButton(page, "Self-care guidance")).toBeFocused();
  await expect(status).toContainText("Ready: not shown yet");
  expect(popups).toHaveLength(0);

  // #550: when the server explains the failure in plain words (Job.error_reason), the dialog says that instead.
  const why = "The first draft was rejected: a statement was judged to rule out a risk (a stated fact). The repair " +
    "was rejected: a statement was judged to rule out a risk (a stated fact). Nothing was published.";
  await page.unroute("**/v1/jobs/*");
  await page.route("**/v1/jobs/*", async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    await route.fulfill({ response, json: job.kind === "scenario_prepare" && job.status !== "running"
      ? { ...job, status: "failed", error_code: "OUTPUT_VALIDATION_FAILED", error_reason: why, result_id: null,
        result_type: null } : job });
  });
  await runButton(page, "Self-care guidance").click();
  await expect(box).toContainText(why, { timeout: 30_000 });
  await expect(box).not.toContainText("did not pass the checks");
  await expect(box.getByTestId("flow-dialog-live")).toHaveText(`Not shown: ${why}`);
  await box.getByRole("button", { name: "Close" }).click();
  await page.unroute("**/v1/jobs/*");

  // The warning-sign screen of the device cannot run: the load refuses, nothing is created or shown.
  await page.route("**/presenter-api/v1/presenter/scenarios/urgent/load", (route) => route.fulfill({ status: 503,
    contentType: "application/json", body: JSON.stringify({ code: "RED_FLAG_SCREEN_UNAVAILABLE",
      message: "The local AI's warning-sign screen did not answer; nothing was created.", field_errors: [], retryable: true,
      request_id: "00000000-0000-4000-8000-000000000000" }) }));
  await runButton(page, "Urgent warning sign").click();
  await expect(box).toContainText("The AI's warning-sign screen did not answer, so no case was created. Nothing was substituted.");
  await box.getByRole("button", { name: "Close" }).click();
  await expect(card(page, "Urgent warning sign").locator(".flow-status"))
    .toContainText("the AI's warning-sign screen did not answer, so no case was created. Nothing was substituted.");
  // The AI does not flag the written emergency: said so; the case is offered at its questions, not as urgent help.
  await page.unroute("**/presenter-api/v1/presenter/scenarios/urgent/load");
  await page.route("**/presenter-api/v1/presenter/scenarios/urgent/load", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, state: "intake", next_path: `/app/cases/${body.case_id}/questions` } });
  });
  await runButton(page, "Urgent warning sign").click();
  await expect(box).toContainText("The AI did not flag a warning sign in the written concern this time");
  await expect(box.getByRole("link", { name: "Open the case at its questions" })).toHaveAttribute("href", /\/questions$/);
  await page.keyboard.press("Escape");
  const urgent = card(page, "Urgent warning sign").locator(".flow-status");
  await expect(urgent).toContainText("the AI did not flag a warning sign in the written concern this time");
  await expect(urgent.getByRole("link", { name: "Open the case at its questions" })).toHaveAttribute("href", /\/questions$/);
  expect(popups).toHaveLength(0);
});

test("#358 when the device is not ready the flows wait and say why", async ({ page }) => {
  await page.route("**/presenter-api/v1/presenter/runtime", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), mode: "local", readiness: "degraded" } });
  });
  await presenterOn(page);
  await expect(page.locator(".o03-line")).toContainText(`${DEVICE} · AI degraded · the flows wait until it is ready`);
  for (const title of FLOWS) {
    await expect(runButton(page, title)).toHaveAttribute("aria-disabled", "true");
    await expect(card(page, title)).toContainText("Waits until the device is ready (the device is Degraded)");
  }
  const popups: Page[] = [];
  page.on("popup", (p) => popups.push(p));
  await runButton(page, "Urgent warning sign").click({ force: true });
  await page.waitForTimeout(300);
  expect(popups).toHaveLength(0); // nothing opened, nothing run
});

test("#358 full journeys and the reset work on More scenarios", async ({ context }) => {
  const page = await context.newPage();
  await presenterOn(page);
  const nav = page.getByRole("navigation", { name: "Presenter" });
  const menu = nav.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await nav.getByRole("link", { name: "More scenarios" }).click();
  await expect(page).toHaveURL(`${PRESENTER}/presenter/scenarios/more`);
  await expect(page.getByRole("heading", { level: 1, name: "More scenarios" })).toBeVisible();
  await expect(page.locator(".scenario-card")).toHaveCount(6);
  await expect(page.locator(".flow-card")).toHaveCount(0);
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Load scenario: Find the right clinician" }).click();
  const tab = await popup;
  await expect(tab).toHaveURL(/\/questions$/);
  await expect(page.getByText("Loaded: Find the right clinician")).toBeVisible();
  await page.getByRole("button", { name: "Reset demo" }).click();
  await expect(page.getByText("Reset completed")).toBeVisible({ timeout: 15_000 });
  await expect(tab).toHaveURL(`${PATIENT}/app/start`);
});

test.describe("#358 accessibility and layout", () => {
  // Only the test tool (axe) is injected, so the gateway policy is bypassed here (as in tests/ui/a11y.spec.ts).
  test.use({ bypassCSP: true });
  const AXE = join(__dirname, "../../apps/web/node_modules/axe-core/axe.min.js");
  const axe = async (page: Page) => {
    await page.addScriptTag({ path: AXE });
    await animationsSettled(page);
    return page.evaluate(async () => {
      // @ts-expect-error axe is injected above
      const result = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] } });
      return result.violations.map((v: { id: string }) => v.id);
    });
  };

  test("#548 the progress dialog is axe clean while it runs and when the result is ready, at 1440 and 360", { tag: "@mobile" }, async ({ context }) => {
    const page = await context.newPage();
    const { stage, release } = await guidanceHeld(page);
    await stage("writing");
    await expect(dialog(page).locator('[aria-current="step"]')).toContainText("writing the guidance");
    expect(await axe(page)).toEqual([]);
    await expectNoHorizontalOverflow(page);
    const box = (await dialog(page).boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
    await release();
    await expect(dialog(page)).toContainText("Guidance is ready", { timeout: 30_000 });
    expect(await axe(page)).toEqual([]);
  });

  test("#358 the flows and More scenarios are axe clean, three cards in a row at 1440 and stacked at 360", { tag: "@mobile" }, async ({ context }, info) => {
    const page = await context.newPage();
    await presenterOn(page);
    expect(await axe(page)).toEqual([]);
    const boxes = await Promise.all(FLOWS.map(async (t) => (await card(page, t).boundingBox())!));
    if (info.project.name === "desktop-1440") {
      expect(new Set(boxes.map((b) => Math.round(b.y))).size, "one row").toBe(1);
      for (const t of FLOWS) {
        const box = (await runButton(page, t).boundingBox())!;
        expect(box.y + box.height, `${t}: button above the fold`).toBeLessThanOrEqual(page.viewportSize()!.height);
        expect(box.height).toBeGreaterThanOrEqual(48);
      }
    } else {
      expect(boxes[1].y).toBeGreaterThan(boxes[0].y + boxes[0].height - 1); // stacked
      expect(boxes[2].y).toBeGreaterThan(boxes[1].y + boxes[1].height - 1);
    }
    await expectNoHorizontalOverflow(page);
    // After a run (the result state with its link) and on the secondary view.
    await runButton(page, "Urgent warning sign").click();
    await (await openResult(page)).waitForURL(/\/urgent$/);
    await expect(card(page, "Urgent warning sign")).toContainText("Shown in the patient tab");
    await page.bringToFront();
    expect(await axe(page)).toEqual([]);
    await page.goto(`${PRESENTER}/presenter/scenarios/more`);
    await expect(page.locator(".scenario-card")).toHaveCount(6);
    expect(await axe(page)).toEqual([]);
    await expectNoHorizontalOverflow(page);
  });
});
