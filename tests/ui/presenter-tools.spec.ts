// Owner decisions of 28 Oct 2026 for the presenter tools, inside the existing screens:
// #691 (B4) "Reset demo" is "Clear demos for the next audience", and the Scenarios page offers it after a session;
// #692 (B5) a short "How to present" panel on Scenarios with README "Present it"'s steps;
// #693 (B6) Telemetry's "Not measured" says plainly when the number will appear. Mock stack; the local-mode telemetry
// is a rewritten snapshot (as in W06-modes.spec.ts), and the rule itself is unit-tested (W06Cost.ts whenMeasured).
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { expectNoHorizontalOverflow } from "./support/journey";
import { costMessage, whenMeasured } from "../../apps/web/src/screens/W06Cost";
import { usd } from "../../apps/web/src/screens/W06Slide";

/** README "Present it"'s step titles (each step starts with its bold title). */
const README_STEPS = [...readFileSync(`${__dirname}/../../README.md`, "utf8").split("## Present it")[1].split("\n## ")[0]
  .matchAll(/^\d\. \*\*(.+?)\.\*\*/gm)].map((m) => m[1]);

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const DEVICE = "HP ZGX Nano";
const CLEAR = "Clear demos for the next audience";

async function presenterOn(page: Page, path = "/presenter/scenarios") {
  await page.goto(path);
  const start = page.getByRole("button", { name: "Start presenter session" });
  await start.click();
  await expect(start).toBeHidden();
  await expect(page.locator(".flow-card, .scenario-card").first()).toBeVisible();
}

// ── #691 Clear demos for the next audience ──────────────────────────────────────────────────────────────────────────

test("#691 Scenarios offers Clear demos for the next audience once a demo ran, and it clears them", { tag: "@mobile" }, async ({ page }) => {
  await presenterOn(page);
  const main = page.locator("main");
  await expect(main.getByRole("button", { name: CLEAR })).toHaveCount(0); // nothing to clear yet
  await expect(main.getByText("Reset demo")).toHaveCount(0);
  await page.getByRole("button", { name: `Run on ${DEVICE}: Self-care guidance` }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Open the result" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  const section = main.locator("section.clear-demos");
  await expect(section.getByRole("heading", { level: 2, name: "Finished with this audience?" })).toBeVisible();
  await expect(section).toContainText("Consultations typed by hand and other browsers' demos stay.");
  const clear = section.getByRole("button", { name: CLEAR });
  await expectNoHorizontalOverflow(page);
  await clear.click();
  await expect(main.getByText("Demos cleared: ready for the next audience")).toBeVisible({ timeout: 15_000 });
  const status = page.locator(".flow-card", { hasText: "Self-care guidance" }).locator(".flow-status");
  await expect(status).not.toContainText("Ready: not shown yet");
  await expect(main.getByRole("button", { name: CLEAR })).toHaveCount(0); // nothing left to clear
  // More scenarios offers it at any time, under the same name.
  await page.goto("/presenter/scenarios/more");
  await expect(page.locator("section.clear-demos").getByRole("heading", { level: 2, name: "Between audiences" })).toBeVisible();
  await expect(page.getByRole("button", { name: CLEAR })).toBeVisible();
  await expect(page.getByText("Reset demo")).toHaveCount(0);
});

test("#691 a demo still open from an earlier presenter session is offered for clearing too", async ({ page }) => {
  await presenterOn(page, "/presenter/scenarios/more");
  await page.getByRole("button", { name: "Load scenario: Urgent interruption" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  await page.goto("/presenter/scenarios"); // a reload: this page's runs are none, the server still lists the demo
  await expect(page.locator(".flow-card").first()).toBeVisible();
  await expect(page.getByRole("button", { name: CLEAR })).toBeVisible();
});

// ── #692 How to present ─────────────────────────────────────────────────────────────────────────────────────────────

test("#692 How to present opens and closes by keyboard and lists README's steps", { tag: "@mobile" }, async ({ page }) => {
  await page.goto("/presenter/scenarios");
  const toggle = page.getByRole("button", { name: "How to present" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false"); // closed: the flows stay first
  const steps = page.locator(".how-steps li");
  await expect(steps.first()).toBeHidden();
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(steps).toHaveCount(7);
  expect(README_STEPS).toHaveLength(7);
  await expect(steps.locator("b")).toHaveText(README_STEPS.map((title) => `${title}.`));
  await expect(steps.nth(2)).toContainText(`Choose Run on ${DEVICE}. Open the result shows it in this window as the Demo patient`);
  await expect(steps.nth(3)).toContainText(CLEAR);
  await expectNoHorizontalOverflow(page);
  await page.keyboard.press("Space");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(steps.first()).toBeHidden();
  // It is there with a presenter session too, above the flows.
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.locator(".flow-card")).toHaveCount(3);
  const [help, firstFlow] = [await toggle.boundingBox(), await page.locator(".flow-card").first().boundingBox()];
  expect(help!.y).toBeLessThan(firstFlow!.y);
});

// ── #693 Not measured says when ─────────────────────────────────────────────────────────────────────────────────────

test("#693 unit: a figure that is not measured says when it will appear", () => {
  const time = (iso: string) => iso.slice(11, 16); // a fixed clock for the test
  const now = Date.parse("2026-10-28T14:23:00Z");
  const base = { mock: false, samplerActive: true, now, time };
  expect(whenMeasured({ ...base, what: "Cost", perConsultation: true, from: "2026-10-28T15:00:00Z" }))
    .toBe("Cost appears after the first full hour, at 15:00, with the first consultation from then on");
  expect(whenMeasured({ ...base, what: "Cost", perConsultation: true, from: "2026-10-28T14:00:00Z" }))
    .toBe("Cost appears with the next consultation guided on this device");
  expect(whenMeasured({ ...base, what: "Energy", perConsultation: false, from: "2026-10-28T15:00:00Z" }))
    .toBe("Energy appears with the next AI call on this device");
  expect(whenMeasured({ ...base, samplerActive: false, what: "Cost", perConsultation: true, from: "2026-10-28T15:00:00Z" }))
    .toBe("Cost appears once the GPU power sampler runs (./demo.sh setup starts it)");
  expect(whenMeasured({ ...base, mock: true, what: "Cost", perConsultation: true }))
    .toBe("Cost is not measured in mock mode: no model runs, so the device uses no AI energy");
  const s = { device: 7699, localPer: 0, perDay: 48, months: 36 };
  const o = [{ id: "qwen", label: "the same model in the cloud", cloudPer: 0.0054, consultations: null, months: null,
    within: false, savedAtEnd: 0 }];
  expect(costMessage({ localPer: null, outcomes: o, defaultId: "qwen", s, usd,
    notYet: "Cost appears after the first full hour, at 15:00, with the first consultation from then on" }))
    .toBe("Through a cloud API, 1,000 consultations would cost $5.40; the device's electricity is not measured yet "
      + "(cost appears after the first full hour, at 15:00, with the first consultation from then on).");
});

/** A new local-mode installation: metering began this hour, so per-consultation figures start at the next hour. */
async function newInstallation(page: Page, sampler: "active" | "not_running") {
  await page.route("**/api/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    const next = new Date(Date.now() + 3_600_000);
    next.setUTCMinutes(0, 0, 0);
    const iso = next.toISOString().replace(".000", "");
    await route.fulfill({ response, json: { ...t,
      identity: { ...t.identity, mode: "local" },
      metered: { ...t.metered, guided: 0, from: iso, to: iso, ai_calls: 0, calls_with_energy: 0, wh_total: null },
      energy: { ...t.energy, status: "not_measured", calls_with_energy: 0, wh_total: null,
        sampler: { status: sampler, last_sample_age_s: sampler === "active" ? 0.5 : null } } } });
  });
  const next = new Date(Date.now() + 3_600_000);
  next.setUTCMinutes(0, 0, 0);
  return next;
}

test("#693 on a new installation Telemetry says the cost appears after the first full hour, at its local time", { tag: "@mobile" }, async ({ page }) => {
  const next = await newInstallation(page, "active");
  const hhmm = `${String(next.getHours()).padStart(2, "0")}:${String(next.getMinutes()).padStart(2, "0")}`;
  const sentence = `Cost appears after the first full hour, at ${hhmm}, with the first consultation from then on`;
  await page.goto("/telemetry");
  const tile = page.locator(".kpi", { hasText: "AI cost per 1,000 consultations" });
  await expect(tile).toContainText("Not measured");
  await expect(tile).toContainText(sentence);
  await expect(page.getByRole("main")).toContainText(`the device's electricity is not measured yet (${sentence.charAt(0).toLowerCase()}${sentence.slice(1)})`);
  await expectNoHorizontalOverflow(page);
  // Advanced: the calculator and the energy tiles say it too.
  await page.getByRole("radiogroup", { name: "View: basic or advanced" }).getByRole("radio", { name: "Advanced" }).click();
  await expect(page.locator(".kpi", { hasText: "Per consultation on this device" })).toContainText(`${sentence}; until then electricity is not included`);
  await expect(page.locator(".kpi", { hasText: "GPU energy per consultation" }))
    .toContainText(`Energy per consultation appears after the first full hour, at ${hhmm}`);
  await expect(page.locator(".kpi", { hasText: "GPU energy for AI calls" }))
    .toContainText("Power sampler active: energy appears with the next AI call on this device");
});

test("#693 without the power sampler Telemetry says the cost appears once it runs", async ({ page }) => {
  await newInstallation(page, "not_running");
  await page.goto("/telemetry");
  await expect(page.locator(".kpi", { hasText: "AI cost per 1,000 consultations" }))
    .toContainText("Cost appears once the GPU power sampler runs (./demo.sh setup starts it)");
});

test("#693 in mock mode Telemetry says no device energy is measured, and why", async ({ page }) => {
  await page.goto("/telemetry"); // the suite runs in mock mode
  await expect(page.locator(".kpi", { hasText: "AI cost per 1,000 consultations" }))
    .toContainText("Cost is not measured in mock mode: no model runs, so the device uses no AI energy");
});
