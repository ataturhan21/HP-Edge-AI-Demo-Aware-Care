// Usability walk 2026-10-21 (v0.11.0-demo.1, both devices), W06 telemetry and dates across the site:
// #346 the W06 section menu follows the title and the period choice; every section ends with "Back to sections".
// #347 one date style ("16 Oct 2026") and one 24-hour time style ("17:04") on the patient site, telemetry and
// presenter, from one helper (components/ui.tsx); UTC labeled; no seconds outside technical status fields.
// The suite runs in mock mode; W06 tests rewrite the snapshot to a device-like one (local mode, metering that began
// after the period start), with fixed instants so the expected text is exact.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { enterConcern, expectNoHorizontalOverflow, startSession, toGuidance } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));
// #547: these tests read the advanced view (every figure); the basic view is tested in W06-modes.spec.ts.
test.beforeEach(({ page }) => page.addInitScript(() => { try { localStorage.setItem("awarecare.telemetry.view", "advanced"); } catch { /* none */ } }));

const PRESENTER = "http://127.0.0.1:15174";
const MON = "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)";
const NUMERIC_DATE = /\b\d{1,2}\/\d{1,2}\/\d{4}\b/;
const ISO_DATE = /\b\d{4}-\d{2}-\d{2}\b/;
const WITH_SECONDS = /\b\d{1,2}:\d{2}:\d{2}\b/;
const TWELVE_HOUR = /\b\d{1,2}:\d{2}\s?(AM|PM)\b/i;
// #469: Reliability and What we don't claim are in the menu too. #547: the advanced view's sections, in page order.
const MENU = ["Usage", "Latency", "Privacy", "Model and runtime", "Tokens", "Energy", "Cost", "Break-even", "Reliability",
  "What we don't claim", "Slide", "Sources"];
const HEADINGS: Record<string, string> = {
  Usage: "usage-heading", Latency: "perf-heading", Tokens: "tokens-heading", Energy: "energy-heading", Cost: "cost-heading",
  "Break-even": "calc-heading", Privacy: "privacy-heading", "Model and runtime": "identity-heading", Reliability: "rel-heading",
  "What we don't claim": "claim-heading", Slide: "slide-heading", Sources: "src-heading",
};

/** A device-like snapshot with fixed instants: generated 16 Oct 2026 17:04:03 UTC; AI calls metered since 13:00 UTC. */
async function deviceLike(page: Page): Promise<{ pricing?: Record<string, any> }> {
  const seen: { pricing?: Record<string, any> } = {};
  await page.route("**/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    const json = { ...t, generated_at: "2026-10-16T17:04:03Z",
      identity: { ...t.identity, mode: "local", qualification: { result: "PASSED", date: "2026-10-16", reference: "x" } },
      period: { ...t.period, from: "2026-10-09T17:04:03Z", to: "2026-10-16T17:04:03Z" },
      metered: { ...t.metered, since: "2026-10-16T13:00:00Z", guided: 2 },
      consultations: { ...t.consultations, guided: 5 },
      ai_calls: { ...t.ai_calls, total: 657, with_token_counts: 657, prompt_tokens: 411089, completion_tokens: 23417 },
      privacy: { ...t.privacy, last_verified: { date: "2026-10-19", method: "socket sampling", samples: 143, non_loopback: 0, reference: "x" } } };
    seen.pricing = t.pricing;
    await route.fulfill({ response, json });
  });
  return seen;
}

/** The reviewed price list's own labels, notes and version id as written (e.g. "released 2026-09-24"). */
function priceListText(pricing: Record<string, any> | undefined): string[] {
  const out: string[] = [];
  const walk = (v: unknown, key = ""): void => {
    if (typeof v === "string") { if (["label", "note"].includes(key) && /\d{4}-\d{2}-\d{2}/.test(v)) out.push(v); }
    else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) walk(x, k);
  };
  walk(pricing);
  // The price list's version is a date ("2026-10-17"); #472: shown as "Price list of 17 Oct 2026".
  if (typeof pricing?.pricing_version === "string") out.push(`Price list ${pricing.pricing_version}`);
  return out;
}

async function top(page: Page, selector: ReturnType<Page["locator"]>) {
  return Math.round(await selector.evaluate((el) => el.getBoundingClientRect().top + window.scrollY));
}

// ── #346 ─────────────────────────────────────────────────────────────────────────────────────────────────────────

test("#346 the section menu follows the title and the period choice, before the figures", { tag: "@mobile" }, async ({ page }, info) => {
  await page.goto("/telemetry");
  const nav = page.getByRole("navigation", { name: "Sections on this page", exact: true });
  await expect(nav).toBeVisible();
  await expect(nav.getByRole("link")).toHaveText(MENU);
  // Directly after the period switcher (and its Refresh button), before the mock notice and the first section.
  const order = await page.evaluate(() => {
    const group = document.querySelector('[role="radiogroup"][aria-label="Period"]')!.closest(".segmented")!;
    return group.nextElementSibling?.id;
  });
  expect(order).toBe("sections");
  const glance = page.getByRole("heading", { name: "Usage", exact: true });
  const navY = await top(page, nav);
  expect(navY).toBeLessThan(await top(page, glance));
  // Measured (before: 2,680 px at 360 and 1,448 px at 1440 on this stack; 2,763 / 1,457 on the Nano).
  const privacyY = await top(page, page.getByRole("main").getByRole("link", { name: "Privacy", exact: true }).first());
  info.annotations.push({ type: "W06_section_nav_y", description: String(privacyY) });
  expect(privacyY).toBeLessThan(page.viewportSize()!.height); // on the first screen at 360 and 1440
  // At 360 the links wrap inside the page: no link wider than the viewport, no horizontal scroll.
  const width = page.viewportSize()!.width;
  for (const link of await nav.getByRole("link").all()) {
    const box = (await link.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
  }
  await expectNoHorizontalOverflow(page);
});

test("#346 every menu link focuses its section heading, and each section ends with Back to sections", async ({ page }) => {
  await page.goto("/telemetry");
  const nav = page.getByRole("navigation", { name: "Sections on this page", exact: true });
  await expect(nav).toBeVisible();
  for (const label of MENU) {
    await nav.getByRole("link", { name: label, exact: true }).click();
    await expect(page.locator(`#${HEADINGS[label]}`)).toBeFocused();
    // The section's last line takes the reader back to the menu, with focus on it.
    const section = page.locator("main section", { has: page.locator(`#${HEADINGS[label]}`) }).last();
    const back = section.getByRole("link", { name: "Back to sections" });
    await expect(back).toHaveCount(1);
    expect(await section.evaluate((s) => s.lastElementChild?.classList.contains("back-to-sections"))).toBe(true);
    await back.click();
    await expect(nav).toBeFocused();
    await expect(nav).toBeInViewport();
  }
  // Every section of the page ends with it, including Reliability and What we don't claim.
  const sections = page.locator("main section:has(h2)");
  const n = await sections.count();
  expect(n).toBeGreaterThanOrEqual(9);
  for (let i = 0; i < n; i++)
    expect(await sections.nth(i).evaluate((s) => s.lastElementChild?.classList.contains("back-to-sections")), `section ${i}`).toBe(true);
  // Keyboard: Enter on a link moves focus to the heading; Enter on Back returns to the menu.
  await nav.getByRole("link", { name: "Privacy", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#privacy-heading")).toBeFocused();
  await page.locator("#privacy").getByRole("link", { name: "Back to sections" }).focus();
  await page.keyboard.press("Enter");
  await expect(nav).toBeFocused();
});

test("#346 the slide, the calculator, the formulas, the badges, the sources and the R39 sentence stay", async ({ page }) => {
  await page.goto("/telemetry");
  await expect(page.getByRole("heading", { name: "Share as a slide" })).toBeVisible();
  await expect(page.locator(".slide-preview")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Break-even calculator" })).toBeVisible();
  await expect(page.getByLabel("Consultations per day")).toBeVisible();
  await expect(page.getByText("Show the formulas")).toBeVisible();
  for (const name of ["Measured", "Estimated", "Not measured", "By design"]) expect(await page.locator(".basis", { hasText: name }).count()).toBeGreaterThan(0);
  await expect(page.getByRole("heading", { name: "Sources and assumptions" })).toBeVisible();
  await expect(page.getByText("Healthcare outcomes such as avoided visits or staff time are not measured", { exact: false })).toBeVisible();
  // /telemetry#privacy (#331) still lands on the privacy section (a fresh load, not a same-page hash change).
  await page.goto("/help");
  await page.goto("/telemetry#privacy");
  await expect(page.locator("#privacy")).toBeFocused();
});

// ── #347 ─────────────────────────────────────────────────────────────────────────────────────────────────────────

test.describe("#347 in another locale and time zone", () => {
  test.use({ locale: "ar-EG", timezoneId: "Asia/Kathmandu" });

  test("#347 W06 uses one date style and one 24-hour time style, labeled UTC, without seconds", async ({ page }) => {
    const seen = await deviceLike(page);
    await page.goto("/telemetry");
    await expect(page.getByRole("heading", { name: "Usage", exact: true })).toBeVisible();
    // #472: the reviewed price list's labels and notes quote dates as ISO ("released 2026-09-24"); the page shows them
    // in the one style too, so no text is exempt from the checks below.
    const text = await page.locator("main").innerText();
    const quoted = priceListText(seen.pricing);
    expect(quoted.length).toBeGreaterThan(0);
    for (const q of quoted) expect(text).not.toContain(q);
    expect(text).not.toMatch(NUMERIC_DATE); // before: "10/16/2026, 6:45:00 PM" (local, numeric, with seconds)
    expect(text).not.toMatch(WITH_SECONDS);
    expect(text).not.toMatch(TWELVE_HOUR);
    expect(text.match(new RegExp(`.{0,40}${ISO_DATE.source}.{0,10}`, "g")) ?? []).toEqual([]); // before: "(2026-10-19)", "retrieved 2026-10-16"
    // Every time on the page is UTC and says so.
    const times = text.match(/\b\d{1,2}:\d{2}\b(?! UTC)/g) ?? [];
    expect(times).toEqual([]);
    await expect(page.locator(".kpi", { hasText: "AI calls on the device" })).toContainText("counted since 16 Oct 2026, 13:00 UTC");
    await expect(page.getByText("AI calls are metered since 16 Oct 2026, 13:00 UTC", { exact: false })).toBeVisible();
    await expect(page.locator(".meta-line")).toContainText("updated 17:04 UTC");
    await expect(page.locator(".meta-line")).toContainText("re-qualification PASSED (16 Oct 2026)");
    await expect(page.locator(".kpi", { hasText: "Patient data sent off the device" })).toContainText("(19 Oct 2026)");
    const sources = page.locator("section", { has: page.getByRole("heading", { name: "Sources and assumptions" }) });
    await expect(sources).toContainText(new RegExp(`retrieved \\d{1,2} ${MON} \\d{4}`));
    // Every date on the page has the one style: "16 Oct 2026" (or a range of days in it, "14–20 Oct 2026").
    const dates = text.match(new RegExp(`\\b\\d{1,2}(?:–\\d{1,2})? ${MON}\\b(?: \\d{4})?`, "g")) ?? [];
    expect(dates.length).toBeGreaterThan(3);
  });

  test("#347 the slide prints the same date and time style", async ({ page }) => {
    await deviceLike(page);
    await page.goto("/telemetry");
    await expect(page.locator(".slide-preview")).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download SVG" }).click();
    const svg = readFileSync(await (await download).path(), "utf8");
    expect(svg).toContain("16 Oct 2026, 17:04 UTC"); // generated
    expect(svg).toContain("AI calls metered since 16 Oct 2026, 13:00 UTC");
    expect(svg).toMatch(new RegExp(`retrieved \\d{1,2} ${MON} \\d{4}`));
    for (const re of [NUMERIC_DATE, WITH_SECONDS, TWELVE_HOUR, ISO_DATE]) expect(svg).not.toMatch(re);
  });

  test("#347 History shows the 24-hour time and the shared date style", async ({ page }) => {
    await startSession(page);
    await enterConcern(page);
    await page.goto("/app/history");
    const started = page.locator('td[data-label="Started"]').first();
    await expect(started).toHaveText(/^(Today|\d{1,2} [A-Z][a-z]{2} \d{4}), \d{2}:\d{2}$/); // before: "Today, 8:21 AM"
    const expected = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Kathmandu" });
    const created = await page.evaluate(async () => (await (await fetch("/api/v1/cases", { credentials: "same-origin" })).json()).items[0].created_at as string);
    await expect(started).toContainText(expected.format(new Date(created)));
    await expect(page.locator('td[data-label="Time left"] time').first()).toHaveAttribute("title", new RegExp(`^\\d{1,2} ${MON} \\d{4}, \\d{2}:\\d{2}$`));
    const text = await page.locator("main").innerText();
    expect(text).not.toMatch(TWELVE_HOUR);
    expect(text).not.toMatch(/[٠-٩۰-۹]/);
  });
});

test("#347 the evidence page names its retrieval date in the shared style", async ({ page }) => {
  const caseId = await toGuidance(page);
  // No reviewed evidence is loaded in this build, so the response gains one synthetic, display-only source record.
  await page.route("**/api/v1/cases/*/sources", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, evidence: [{ ...(body.evidence[0] ?? {}), id: "ev-test", title: "Synthetic test source",
      publisher: "Test publisher", retrieved_at: "2026-10-01T22:30:00Z", locator: "section 1", source_url: "https://example.org/" }] } });
  });
  await page.goto(`/app/cases/${caseId}/sources`);
  const line = page.getByText(/· retrieved /).first();
  await expect(line).toBeVisible();
  await expect(line).toContainText("retrieved 1 Oct 2026 ·"); // before: "retrieved 2026-10-01"
});

test("#347 the presenter uses the same 24-hour time style; only the technical check time keeps seconds", async ({ page }) => {
  await page.goto(`${PRESENTER}/presenter/scenarios`);
  const start = page.getByRole("button", { name: "Start presenter session" });
  await start.click();
  await expect(start).toBeHidden();
  // #358: the quick flows run at the click (no prepared-until time and no check time on the page any more).
  await page.getByRole("button", { name: "Run on HP ZGX Nano: Urgent warning sign" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click({ timeout: 30_000 }); // #548
  const card = page.locator(".flow-card").last();
  await expect(card).toContainText("Ready: not shown yet", { timeout: 30_000 });
  const text = (await page.locator("main").innerText()).replace(/checked \d{2}:\d{2}:\d{2}/, "checked");
  expect(text).not.toMatch(TWELVE_HOUR);
  expect(text).not.toMatch(WITH_SECONDS);
  expect(text).not.toMatch(NUMERIC_DATE);
});
