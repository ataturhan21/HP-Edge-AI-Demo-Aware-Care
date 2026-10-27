// Patient clarity improvements of 2026-10-20 (#322, #323, #330), from the product review of v0.10.0-demo.1 on the
// ZGX Nano and the ZGX Fury. The isolated stack runs in mock mode; local mode is simulated by answering the public
// telemetry snapshot (and, where a journey runs, the issued question) as a local-mode server would.
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { animationsSettled, answerAll, apiSettled, CONCERN, enterConcern, expectNoHorizontalOverflow, startSession, trackApi } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const phone = (name: string) => name.includes("360");
const PRESENTER = "http://127.0.0.1:15174";
const STRONG = "AI runs locally on HP ZGX Nano via ZRT";
const HEDGED = "Built to run AI locally on HP ZGX Nano via ZRT";
const strip = (page: Page) => page.getByTestId("local-ai-signature-strip");
const FURY_DEVICE = 'window.AWARE_CARE_DEVICE = { name: "HP ZGX Fury", shortName: "ZGX Fury" };';
const Z8_DEVICE = 'window.AWARE_CARE_DEVICE = { name: "HP Z8 Fury G5 Workstation Desktop PC", shortName: "Z8 Fury G5" };';

type Latency = { samples: number; total_ms_p50: number | null };

/** The telemetry snapshot as a local-mode server answers it, with the given guidance latency figures. */
async function telemetryAsLocal(page: Page, latency: Latency = { samples: 0, total_ms_p50: null }, delayMs = 0) {
  await page.route("**/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    await route.fulfill({ response, json: { ...t, identity: { ...t.identity, mode: "local" }, latency: { ...t.latency, ...latency } } });
  });
}

/** Issued questions as a local-mode server issues them (the reviewed pathway's version). */
async function questionsAsLocal(page: Page) {
  await page.route("**/questions/next", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (body.question) body.question.pathway_version = "general-adult-4";
    await route.fulfill({ response, json: body });
  });
}

test.describe("#322 one local-AI claim from the first screen", () => {
  test("#322 local mode shows the strong claim on every screen before any question, after a reload and on presenter pages", async ({ page }) => {
    test.setTimeout(120_000);
    await telemetryAsLocal(page);
    for (const route of ["/", "/how-it-works", "/healthcare", "/privacy", "/help", "/telemetry", "/app/start"]) {
      await page.goto(route);
      await expect(strip(page), route).toContainText(STRONG);
      await expect(page.getByTestId("local-ai-signature-footer"), route).toContainText(STRONG);
    }
    await page.reload();
    await expect(strip(page), "after a reload").toContainText(STRONG);
    await startSession(page); // A02 then A03, no question issued yet
    await expect(strip(page)).toContainText(STRONG);
    // The A03 notice and the patient footer follow the mode.
    const notice = page.locator(".notice", { hasText: "Synthetic demonstration" });
    await expect(notice).toContainText("The AI model on this device reads what you write and your answers.");
    await expect(notice).not.toContainText("Depending on how this demo is running");
    await expect(page.locator("footer")).not.toContainText("scripted mock");
    await expect(page.locator("footer")).toContainText("labeled AI-generated");
    for (const route of ["/app/history", "/app/settings", "/app/limits"]) {
      await page.goto(route);
      await expect(strip(page), route).toContainText(STRONG);
      await expect(page.locator("footer"), route).not.toContainText("scripted mock");
    }
    // Presenter pages (#487: same address, presenter API): the claim is there before the runtime snapshot is read.
    for (const route of ["/presenter/controls", "/presenter/scenarios"]) {
      await page.goto(PRESENTER + route);
      await expect(strip(page), route).toContainText(STRONG);
    }
  });

  test("#322 mock mode is named from the first screen and keeps its truthful wording", async ({ page }) => {
    await page.goto("/");
    await expect(strip(page)).toContainText("Mock mode on HP ZGX Nano");
    await expect(strip(page)).not.toContainText("AI runs locally");
    await startSession(page);
    await expect(page.locator(".notice", { hasText: "Synthetic demonstration" }))
      .toContainText("This demo is running a scripted scenario: the result follows the scenario, and what you write is not analysed.");
    await expect(page.locator("footer")).toContainText("synthetic demonstration · scripted mock outcomes are labeled on each result");
    await page.goto(PRESENTER + "/presenter/scenarios");
    await expect(strip(page)).toContainText("Mock mode on HP ZGX Nano");
  });

  test("#322 without a server answer the wording stays neutral, and the strong claim never comes first", async ({ page }) => {
    await page.route("**/v1/telemetry*", (route) => route.abort());
    await page.goto("/");
    await expect(strip(page)).toContainText(HEDGED);
    await startSession(page);
    await expect(page.locator(".notice", { hasText: "Synthetic demonstration" })).toContainText("Depending on how this demo is running");
    await page.unrouteAll({ behavior: "ignoreErrors" });
    // A slow local answer: neutral until it arrives, then the strong claim.
    await telemetryAsLocal(page, undefined, 1_500);
    await page.goto("/help");
    await expect(strip(page)).toContainText(HEDGED);
    await expect(strip(page)).not.toContainText("AI runs locally");
    await expect(strip(page)).toContainText(STRONG, { timeout: 10_000 });
  });
});

/** A local-mode journey to Generate guidance with the job held as running until `release()`. */
async function holdGuidance(page: Page) {
  let hold = true;
  await questionsAsLocal(page);
  await trackApi(page);
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.route("**/v1/jobs/*", async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    await route.fulfill({ response, json: hold ? { ...job, status: "running", result_id: null } : job });
  });
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Preparing your guidance" })).toBeVisible();
  // #501: the wait's count is anchored to the job's start once the first job read is handled (server clock); the
  // tests move the page clock only after that.
  await apiSettled(page, "/v1/jobs/");
  return () => {
    hold = false;
  };
}

// The bar's target width (a short CSS transition eases it there in real time, which the test clock does not drive).
const barWidth = (page: Page) => page.getByTestId("generating-bar").locator("i").evaluate((el) =>
  parseFloat((el as HTMLElement).style.width) / 100);
const KEEP_OPEN = "Please keep this page open.";

test.describe("#323 the guidance wait says how long it takes", () => {
  test("#323 from 0 s the Nano's default is shown, the bar fills then turns indeterminate, and focus moves to the result", async ({ page }) => {
    test.setTimeout(120_000);
    await page.clock.install();
    await telemetryAsLocal(page); // no measured figures yet (a new deployment): the device default
    const release = await holdGuidance(page);
    const typical = page.getByTestId("generating-typical");
    await expect(typical).toHaveText(/^Usually 15–25 seconds on this device\./); // at 0 s
    await expect(page.getByText(/first checks your words for urgent warning signs/)).toBeVisible();
    const parts = page.locator(".generating-progress ul li");
    await expect(parts).toHaveText(["Suggested level of care", "Possible explanations", "Questions to ask a clinician",
      "When to seek help sooner", "Limits of this result"]);
    await page.clock.runFor(10_000);
    expect(await barWidth(page)).toBeGreaterThan(0.35);
    expect(await barWidth(page)).toBeLessThan(0.65);
    await expect(page.getByTestId("generating-bar")).not.toHaveClass(/indeterminate/);
    await page.clock.runFor(11_000);
    await expect(page.getByTestId("generating-bar")).toHaveClass(/indeterminate/);
    await expect(page.getByText("Taking a little longer than usual. It is still working.")).toBeVisible();
    await expect(page.getByText(KEEP_OPEN, { exact: false })).toHaveCount(0);
    await page.clock.runFor(10_000); // 31 s: max(30 s, 1.5 × 20 s)
    await expect(page.getByText(KEEP_OPEN, { exact: false })).toBeVisible();
    release();
    await page.clock.runFor(5_000);
    const heading = page.getByRole("heading", { name: "Your guidance", exact: true });
    await expect(heading).toBeVisible({ timeout: 30_000 });
    await expect(heading).toBeFocused();
  });

  test("#323 the device's own measured median sets the usual time, the bar and the keep-open threshold", async ({ page }) => {
    test.setTimeout(120_000);
    await page.clock.install();
    await telemetryAsLocal(page, { samples: 12, total_ms_p50: 40_000 });
    await holdGuidance(page);
    await expect(page.getByTestId("generating-typical")).toHaveText(
      "Usually about 40 seconds on this device. Measured on this device over recent days.");
    await page.clock.runFor(20_000);
    expect(await barWidth(page)).toBeGreaterThan(0.4);
    expect(await barWidth(page)).toBeLessThan(0.6);
    await page.clock.runFor(35_000); // 55 s: past the usual time, below 1.5 × 40 s
    await expect(page.getByTestId("generating-bar")).toHaveClass(/indeterminate/);
    await expect(page.getByText(KEEP_OPEN, { exact: false })).toHaveCount(0);
    await page.clock.runFor(6_000); // 61 s
    await expect(page.getByText(KEEP_OPEN, { exact: false })).toBeVisible();
  });

  test("#323 on the ZGX Fury the default is a few seconds", async ({ page }) => {
    await page.route("**/aware-care-device.js", (route) =>
      route.fulfill({ contentType: "application/javascript", body: FURY_DEVICE }));
    await telemetryAsLocal(page);
    await holdGuidance(page);
    await expect(page.getByTestId("generating-typical")).toHaveText(/^Usually a few seconds on this device\./);
  });

  test("#537 on any other machine the default makes no device-specific claim", async ({ page }) => {
    await page.route("**/aware-care-device.js", (route) =>
      route.fulfill({ contentType: "application/javascript", body: Z8_DEVICE }));
    await telemetryAsLocal(page);
    await holdGuidance(page);
    await expect(page.getByTestId("generating-typical")).toHaveText(/^Usually under a minute on this device\./);
  });
});

// The pinned axe-core of apps/web, as in a11y.spec.ts; only this test tool is injected.
const AXE = join(__dirname, "../../apps/web/node_modules/axe-core/axe.min.js");
async function axe(page: Page) {
  await page.addScriptTag({ path: AXE });
  await animationsSettled(page);
  return page.evaluate(async () => {
    // @ts-expect-error axe is injected above
    const r = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } });
    return r.violations.map((v: { id: string; nodes: { target: string[] }[] }) => `${v.id} e.g. ${v.nodes[0]?.target.join(" ")}`);
  });
}

/** Horizontal overflow of the page and of a scroll region, in px (0 = none). */
async function overflow(page: Page, region: string) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel)!;
    return { page: document.documentElement.scrollWidth - document.documentElement.clientWidth, region: el.scrollWidth - el.clientWidth };
  }, region);
}

test.describe("#330 History and tables at 360 px", () => {
  test.use({ bypassCSP: true }); // axe is injected (as in a11y.spec.ts); routes.layout.spec.ts checks the policy

  test("#330 History shows each consultation as a card with full-width actions, wraps words, and keeps the table on desktop", { tag: "@mobile" }, async ({ page }, info) => {
    await startSession(page);
    await enterConcern(page, CONCERN);
    await page.goto("/app/history");
    const row = page.locator("tbody tr");
    await expect(row).toHaveCount(1);
    await expect(row.locator(".history-concern")).toContainText("recurring headaches");
    const action = row.getByRole("button", { name: "Continue questions" });
    const remove = row.getByRole("button", { name: "Delete" });
    const region = page.getByRole("region", { name: "Consultation history" });
    await expect(region).toHaveAttribute("tabindex", "0");
    if (phone(info.project.name)) {
      expect(await overflow(page, ".tablewrap")).toEqual({ page: 0, region: 0 });
      const card = (await row.boundingBox())!;
      expect(card.x).toBeGreaterThanOrEqual(0);
      expect(card.x + card.width).toBeLessThanOrEqual(360);
      for (const button of [action, remove]) {
        await expect(button).toBeInViewport({ ratio: 1 });
        const b = (await button.boundingBox())!;
        expect(b.width, "full-width action").toBeGreaterThan(card.width - 2 * 24 - 4);
        expect(b.height).toBeGreaterThanOrEqual(44);
      }
      // Status and times are in the card, each time with its label.
      await expect(row).toContainText("Answering questions");
      const labels = await row.locator("td[data-label]").evaluateAll((tds) =>
        tds.map((td) => getComputedStyle(td, "::before").content));
      expect(labels.join(" | ")).toMatch(/Started.*Time left/);
    } else {
      // Desktop: still a table with its column headers, in the named scroll region (#188).
      await expect(region.getByRole("table")).toBeVisible();
      await expect(region.getByRole("columnheader")).toHaveCount(5);
      await expect(page.locator("thead")).toBeVisible();
    }
    // Normal words wrap at word boundaries: no word of the concern is split across lines.
    const split = await row.locator(".history-concern").evaluate((td) => {
      const text = td.firstChild as Text;
      const words = [...text.data.matchAll(/\S+/g)];
      return words.filter((m) => {
        const range = document.createRange();
        range.setStart(text, m.index!);
        range.setEnd(text, m.index! + m[0].replace(/…$/, "").length);
        return new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size > 1;
      }).map((m) => m[0]);
    });
    expect(split, "words broken mid-word").toEqual([]);
    expect(await row.locator(".history-concern").evaluate((td) => getComputedStyle(td).overflowWrap)).toBe("break-word");
    expect(await axe(page)).toEqual([]);
  });

  test("#330 a long unbroken concern still wraps on the History card", { tag: "@mobile" }, async ({ page }, info) => {
    test.skip(!phone(info.project.name), "phone width only");
    await startSession(page);
    await enterConcern(page, `Headache${"x".repeat(80)}`);
    await page.goto("/app/history");
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await expect(page.locator(".history-concern")).toHaveClass(/unbroken/);
    await expectNoHorizontalOverflow(page);
  });

  test("#330 the W03 table reads fully at 360 px and stays a table at desktop width", { tag: "@mobile" }, async ({ page }, info) => {
    await page.goto("/healthcare");
    const region = page.getByRole("region", { name: "Benefits by stakeholder" }); // #473: not all are hypotheses
    await expect(region).toBeVisible();
    expect(await overflow(page, ".tablewrap")).toEqual({ page: 0, region: 0 });
    const wrap = (await region.boundingBox())!;
    const viewport = page.viewportSize()!.width;
    for (const chip of await region.locator(".chip").all()) {
      const c = (await chip.boundingBox())!;
      expect(c.x).toBeGreaterThanOrEqual(wrap.x);
      expect(c.x + c.width, "chip fully inside the table").toBeLessThanOrEqual(Math.min(wrap.x + wrap.width, viewport));
    }
    await expect(region.getByRole("table")).toBeAttached();
    if (!phone(info.project.name)) {
      await expect(region.getByRole("columnheader")).toHaveCount(3);
      await expect(page.locator("thead")).toBeVisible();
    } else {
      const labels = await region.locator("td[data-label]").evaluateAll((tds) => tds.map((td) => getComputedStyle(td, "::before").content));
      expect(labels.filter((l) => l.includes("Status"))).toHaveLength(4);
    }
    expect(await axe(page)).toEqual([]);
  });
});
