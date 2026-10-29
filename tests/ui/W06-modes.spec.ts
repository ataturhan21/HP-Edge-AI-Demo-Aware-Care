// #547 W06 telemetry: a basic view a presenter explains in under 30 seconds (the default) and an advanced view with
// every figure, remembered per browser; a break-even chart that tells the cost story truthfully (same prices, formulas
// and measurements): the device price is paid once, the per-consultation cost is the headline, and the point where the
// device becomes cheaper than each cloud API is marked, with the savings after it shaded.
// The suite runs in mock mode; the snapshot is rewritten to a local-mode week shaped like the Nano's of 20-25 Oct 2026
// (338 consultations; 4,900,159 in / 410,904 out tokens and 102.6 Wh over them).
import { join } from "node:path";
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { animationsSettled, expectNoHorizontalOverflow } from "./support/journey";
import { breakEvenConsultations, cloudPerConsultation, costMessage, DAYS_PER_MONTH, localPerConsultation, monthsFor, outcomes }
  from "../../apps/web/src/screens/W06Cost";
import { usd } from "../../apps/web/src/screens/W06Slide";

test.use({ bypassCSP: true }); // axe is injected (as in a11y.spec.ts)
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const VIEW_KEY = "awarecare.telemetry.view";
const DAY = 86_400_000;
const midnight = () => { const d = new Date(); d.setUTCHours(0, 0, 0, 0); return d.getTime(); };
const iso = (ms: number) => new Date(ms).toISOString().replace(".000", "");
const AXE = join(__dirname, "../../apps/web/node_modules/axe-core/axe.min.js");
const QWEN = { input_usd_per_mtok: 0.248, output_usd_per_mtok: 1.485 };
const SONNET = { input_usd_per_mtok: 2, output_usd_per_mtok: 10 };
const ASTRA = { input_usd_per_mtok: 10, output_usd_per_mtok: 50 };

/** A local-mode week: 338 consultations in 7 days (48 a day), 14,498 in / 1,216 out tokens and 0.3036 Wh each. */
async function nanoWeek(page: Page, over: (t: Record<string, any>) => Record<string, unknown> = () => ({})) {
  await page.route("**/api/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    const today = midnight();
    const json = { ...t,
      identity: { ...t.identity, mode: "local", runtime: "ZRT 0.43.0 (vllm 0.30.0)", model_manifest_id: "qwen3.6-35b-a3b-fp8@95a723d0-2026-10-15",
        prompt_version: "guidance-local-4", qualification: { result: "PASSED", date: "2026-10-19", reference: "x" }, app_commit: "edea3dbbbaef" },
      consultations: { ...t.consultations, guided: 338, fail_closed: 34, repaired: 160, urgent_routes: 934, busy_refusals: 8,
        fail_closed_reasons: [{ rule: "prohibited_certainty/rules_out_risk", count: 21 }, { rule: "third_person", count: null }],
        counted_from: iso(today - 7 * DAY), counted_to: iso(today), counting_since: iso(today - 7 * DAY) },
      metered: { since: t.period.from, guided: 338, from: iso(today - 7 * DAY), to: iso(today), ai_calls: 6826, with_token_counts: 6826,
        prompt_tokens: 4900159, completion_tokens: 410904, duration_ms_total: 9323713.3, calls_with_energy: 6826, wh_total: 102.6273 },
      ai_calls: { ...t.ai_calls, total: 7196, by_task: { certainty_review: 238, concern_check: 2734, guidance: 605, red_flag_screen: 4121 }, errors: 0,
        with_token_counts: 7196, prompt_tokens: 5149424, completion_tokens: 433350, duration_ms_p50: 424.8, duration_ms_p95: 10264.3,
        duration_ms_total: 9930672.1, output_tokens_per_second: 43.6 },
      latency: { samples: 338, total_ms_p50: 13841.8, total_ms_p95: 26786.8, queue_ms_p50: 0.1 },
      energy: { ...t.energy, status: "measured", calls_with_energy: 7196, wh_total: 109.2706, sampler: { status: "active", last_sample_age_s: 0.9 } },
      privacy: { ...t.privacy, last_verified: { date: "2026-10-19", method: "socket sampling", samples: 755, non_loopback: 0, reference: "x" } },
    };
    await route.fulfill({ response, json: { ...json, ...over(json) } });
  });
}

const advanced = (page: Page) => page.addInitScript((k) => { try { localStorage.setItem(k, "advanced"); } catch { /* none */ } }, VIEW_KEY);

async function axe(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE });
  await animationsSettled(page);
  return page.evaluate(async () => {
    // @ts-expect-error axe is injected above
    const result = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } });
    return result.violations.map((v: { id: string; impact: string; nodes: { target: string[] }[] }) =>
      `${v.id} (${v.impact}) ${v.nodes.length}× e.g. ${v.nodes[0]?.target.join(" ")}`);
  });
}

// ── The break-even arithmetic (unit) ───────────────────────────────────────────────────────────────────────────────

test("#547 unit: the break-even point is the device price over the per-consultation difference", () => {
  // The Nano's week: 14,498 in / 1,216 out tokens and 0.3036 Wh per consultation; electricity $0.1453/kWh.
  const local = localPerConsultation(0.3036, 0.1453);
  expect(local).toBeCloseTo(0.0000441, 7);
  const astra = cloudPerConsultation(ASTRA, 14498, 1216);
  expect(astra).toBeCloseTo(0.20578, 5);
  const n = breakEvenConsultations(7699, astra, local)!;
  expect(Math.ceil(n)).toBe(37_422);
  // At that consultation the two cumulative costs meet.
  expect(7699 + local * n).toBeCloseTo(astra * n, 6);
  expect(monthsFor(n, 48)).toBeCloseTo(n / (48 * DAYS_PER_MONTH), 9);
  expect(monthsFor(n, 48)!.toFixed(1)).toBe("25.6");
  // The same model hosted in the cloud: 1.44 million consultations, so not within 36 months at 48 a day.
  expect(Math.ceil(breakEvenConsultations(7699, cloudPerConsultation(QWEN, 14498, 1216), local)!)).toBe(1_437_145);
  // No crossing when the cloud API is not dearer per consultation; at once when the device is free.
  expect(breakEvenConsultations(7699, 0.001, 0.001)).toBeNull();
  expect(breakEvenConsultations(7699, 0.0005, 0.001)).toBeNull();
  expect(breakEvenConsultations(0, 0.01, 0.001)).toBe(0);
  expect(monthsFor(100, 0)).toBeNull();
});

test("#547 unit: the outcome per cloud API and the one-line cost message stay truthful", () => {
  const s = { device: 7699, localPer: localPerConsultation(0.3036, 0.1453), perDay: 48, months: 36 };
  const refs = [["qwen", "the same model in the cloud", QWEN], ["sonnet", "Claude Sonnet 5.5 (frontier API)", SONNET], ["astra", "GPT-6 Astra (frontier API)", ASTRA]] as const;
  const o = outcomes(s, refs.map(([id, label, p]) => ({ id, label, cloudPer: cloudPerConsultation(p, 14498, 1216) })));
  expect(o.map((x) => x.within)).toEqual([false, false, true]);
  const horizon = 48 * DAYS_PER_MONTH * 36;
  expect(o[2].savedAtEnd).toBeCloseTo(o[2].cloudPer * horizon - (7699 + s.localPer * horizon), 6);
  expect(o[0].savedAtEnd).toBeLessThan(0); // over 36 months the hosted same model costs less: said, not hidden
  const message = costMessage({ localPer: s.localPer, outcomes: o, defaultId: "qwen", s, usd });
  expect(message).toBe("1,000 consultations cost $0.044 in electricity on this device, against $5.40 to $206 through a cloud API. "
    + "The $7,699 device is paid once: at 48 consultations a day it pays for itself in 25.6 months against GPT-6 Astra (frontier API); "
    + "against the same model in the cloud it does not within 36 months on AI cost alone.");
  // At a health system's volume the frontier APIs are overtaken sooner; the default reference is named when it is.
  const busy = { ...s, perDay: 2000 };
  const ob = outcomes(busy, refs.map(([id, label, p]) => ({ id, label, cloudPer: cloudPerConsultation(p, 14498, 1216) })));
  expect(costMessage({ localPer: s.localPer, outcomes: ob, defaultId: "sonnet", s: busy, usd })).toContain("it pays for itself in 3.1 months against Claude Sonnet 5.5 (frontier API).");
  // No crossing within the lifetime against any reference: said so, with the nearest crossing.
  const small = { ...s, perDay: 5 };
  const os = outcomes(small, refs.map(([id, label, p]) => ({ id, label, cloudPer: cloudPerConsultation(p, 14498, 1216) })));
  expect(costMessage({ localPer: s.localPer, outcomes: os, defaultId: "qwen", s: small, usd }))
    .toContain("it does not pay for itself within 36 months on AI cost alone; against GPT-6 Astra (frontier API) it would after 37,422 consultations.");
  // Energy not measured: no claim about the device's running cost.
  expect(costMessage({ localPer: null, outcomes: o, defaultId: "qwen", s, usd })).toBe(
    "Through a cloud API, 1,000 consultations would cost $5.40 to $206; the device's electricity is not measured yet.");
});

// ── The basic and advanced views ───────────────────────────────────────────────────────────────────────────────

test("#547 basic is the default: five plain figures with their basis and the cost sentence; the choice is remembered", { tag: "@mobile" }, async ({ page }) => {
  await nanoWeek(page);
  await page.goto("/telemetry");
  const view = page.getByRole("radiogroup", { name: "View: basic or advanced" });
  await expect(view.getByRole("radio", { name: "Basic" })).toHaveAttribute("aria-checked", "true");
  const tiles = page.locator(".basic-grid .kpi");
  await expect(tiles.locator(".kpi-label")).toHaveText(["Where the AI runs", "Consultations guided", "Typical time to guidance",
    "AI cost per 1,000 consultations", "Patient data sent off the device"]);
  await expect(tiles.locator(".basis")).toHaveText(["By design", "Measured", "Measured", "Estimated", "By design"]);
  await expect(tiles.nth(0).locator(".kpi-value")).toHaveText("ZGX Nano");
  await expect(tiles.nth(1).locator(".kpi-value")).toHaveText("338");
  await expect(tiles.nth(2).locator(".kpi-value")).toHaveText("13.8 s");
  // 0.3036 Wh × $0.1453/kWh × 1,000 = $0.044; the same model in the cloud: 14,498 × $0.248 + 1,216 × $1.485 per 1M = $5.40.
  await expect(tiles.nth(3).locator(".kpi-value")).toHaveText("$0.044 vs $5.40 for the same model in the cloud");
  await expect(tiles.nth(4).locator(".kpi-value")).toHaveText("0 bytes");
  for (const tile of await tiles.all()) expect(((await tile.locator("p.small").textContent()) ?? "").length).toBeLessThan(90); // one line of meaning
  await expect(page.locator(".cost-line")).toContainText("at 48 consultations a day it pays for itself in 25.6 months against GPT-6 Astra (frontier API)");
  await expect(page.locator(".cost-line")).toContainText("against the same model in the cloud it does not within 36 months on AI cost alone");
  // No jargon and no detail sections in basic.
  await expect(page.getByRole("navigation", { name: "Sections on this page" })).toHaveCount(0);
  await expect(page.getByLabel("Consultations per day")).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText(/tokens|p95|percentile|nvidia-smi/i);
  await expectNoHorizontalOverflow(page);
  expect(await axe(page)).toEqual([]);

  // Arrow keys move and select (the radio pattern); the choice survives a reload.
  await view.getByRole("radio", { name: "Basic" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(view.getByRole("radio", { name: "Advanced" })).toBeFocused();
  await expect(view.getByRole("radio", { name: "Advanced" })).toHaveAttribute("aria-checked", "true");
  await expect(view.locator('[tabindex="0"]')).toHaveCount(1);
  await expect(page.getByRole("navigation", { name: "Sections on this page" })).toBeVisible();
  expect(await page.evaluate((k) => localStorage.getItem(k), VIEW_KEY)).toBe("advanced");
  await page.reload();
  await expect(view.getByRole("radio", { name: "Advanced" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByLabel("Consultations per day")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(await axe(page)).toEqual([]);
  await view.getByRole("radio", { name: "Basic" }).click();
  await page.reload();
  await expect(view.getByRole("radio", { name: "Basic" })).toHaveAttribute("aria-checked", "true");
});

test("#547 without browser storage the page still opens in basic and switches", async ({ page }) => {
  await page.addInitScript(() => {
    const deny = () => { throw new DOMException("denied", "SecurityError"); };
    Object.defineProperty(window, "localStorage", { get: deny, configurable: true });
  });
  await nanoWeek(page);
  await page.goto("/telemetry");
  await expect(page.getByRole("radio", { name: "Basic" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("radio", { name: "Advanced" }).click();
  await expect(page.getByRole("heading", { name: "Break-even calculator" })).toBeVisible();
});

test("#547 a link to an advanced section opens the advanced view on it", async ({ page }) => {
  await nanoWeek(page);
  await page.goto("/telemetry#privacy");
  await expect(page.locator("#privacy")).toBeFocused();
  await expect(page.getByRole("radio", { name: "Advanced" })).toHaveAttribute("aria-checked", "true");
});

test("#547 advanced keeps every figure, in sections on one card grid", { tag: "@mobile" }, async ({ page }) => {
  await advanced(page);
  await nanoWeek(page);
  await page.goto("/telemetry");
  const nav = page.getByRole("navigation", { name: "Sections on this page" });
  await expect(nav.getByRole("link")).toHaveText(["Usage", "Latency", "Privacy", "Model and runtime", "Tokens", "Energy", "Cost",
    "Break-even", "Reliability", "What we don't claim", "Slide", "Sources"]);
  const card = (name: string | RegExp) => page.locator("section.card", { has: page.getByRole("heading", { level: 2, name }) });
  const tile = (section: string | RegExp, label: string) => card(section).locator(".kpi", { hasText: label });
  // Every figure the page showed before #547, each in its section.
  await expect(tile("Usage", "AI calls on the device").locator(".kpi-value")).toHaveText("7,196");
  await expect(tile("Usage", "Consultations guided").locator(".kpi-value")).toHaveText("338");
  await expect(tile("Latency", "Typical guidance time")).toContainText("13.8 s");
  await expect(tile("Latency", "Typical guidance time")).toContainText("95th percentile 26.8 s");
  await expect(tile("Latency", "Output speed").locator(".kpi-value")).toHaveText("43.6 tokens/s");
  await expect(card("Latency").getByRole("row", { name: /Any AI call/ })).toContainText("0.4 s / 10.3 s");
  await expect(card("Latency").getByRole("row", { name: /Time waiting in the queue/ })).toContainText("0.1 ms");
  await expect(card("Latency").getByRole("row", { name: /Cloud API latency/ })).toContainText("Not measured");
  await expect(tile("Tokens", "Tokens processed").locator(".kpi-value")).toHaveText("5,582,774");
  await expect(tile("Tokens", "Tokens processed")).toContainText("5,149,424 in · 433,350 out");
  await expect(tile("Tokens", "Tokens per consultation")).toContainText("14,498 in · 1,216 out");
  await expect(tile("Energy", "GPU energy for AI calls").locator(".kpi-value")).toHaveText("109.27 Wh");
  await expect(tile("Energy", "GPU energy per consultation").locator(".kpi-value")).toHaveText("0.3036 Wh");
  await expect(tile(/^Cost:/, "Estimated cloud cost of this work").locator(".kpi-value")).toHaveText("$1.92 vs $0.016");
  for (const bar of ["Same model, cloud API", "Frontier API: Claude Sonnet 5.5", "Frontier API: GPT-6 Astra", "This device (electricity)"])
    await expect(card(/^Cost:/).locator(".bar-row", { hasText: bar })).toBeVisible();
  await expect(tile("Break-even calculator", "Device pays for itself")).toBeVisible();
  await expect(tile(/Privacy/, "Patient data sent off the device")).toContainText("0 bytes");
  await expect(card(/Privacy/)).toContainText("0 off-device connections");
  const identity = card("Model and runtime");
  for (const [row, value] of [["Mode", "Local mode"], ["Runtime", "ZRT 0.43.0 (vllm 0.30.0)"], ["Model", "qwen3.6-35b-a3b-fp8@95a723d0-2026-10-15"],
    ["Prompt", "guidance-local-4"], ["ADR-002 re-qualification", "PASSED (19 Oct 2026)"], ["Build", "edea3db"]] as const)
    await expect(identity.getByRole("row", { name: new RegExp(`^${row} `) })).toContainText(value);
  const rel = card("Reliability and safety");
  for (const [row, value] of [["Guidance published", "338"], ["Published after the single repair", "160"], ["Stopped safely instead of shown", "34"],
    ["rejected by rule: prohibited_certainty/rules_out_risk", "21"], ["rejected by rule: third_person", "fewer than 5"], ["Routed to urgent help", "934"],
    ["Requests refused while busy", "8"], ["AI calls by task: Red-flag screen", "4,121"], ["AI calls that errored", "0"]] as const)
    await expect(rel.getByRole("row", { name: new RegExp(row.replace(/[/()]/g, "\\$&")) })).toContainText(value);
  await expect(card("What we don't claim")).toContainText("not measured");
  await expect(card("Share as a slide").locator(".slide-preview")).toBeVisible();
  await expect(card("Sources and assumptions").getByRole("link", { name: "Source" }).first()).toBeVisible();
  // One card grid: the paired sections line up (same top, same height) at desktop width, one column on a phone.
  const box = async (name: string) => (await card(name).boundingBox())!;
  const [usage, latency] = [await box("Usage"), await box("Latency")];
  if (page.viewportSize()!.width >= 1000) {
    expect(Math.abs(usage.y - latency.y)).toBeLessThan(1);
    expect(Math.abs(usage.height - latency.height)).toBeLessThan(1);
  } else expect(Math.abs(usage.x - latency.x)).toBeLessThan(1);
  await expectNoHorizontalOverflow(page);
});

// ── The break-even chart ───────────────────────────────────────────────────────────────────────────────────────

test("#547 the chart marks the break-even point, shades the savings after it and states its assumption", { tag: "@mobile" }, async ({ page }) => {
  await advanced(page);
  await nanoWeek(page);
  await page.goto("/telemetry");
  const chart = page.locator("svg.breakeven-chart");
  await chart.scrollIntoViewIfNeeded();
  // The like-for-like reference (the default) is not overtaken within 36 months at 48 a day: said, not hidden; the
  // earliest crossing (GPT-6 Astra, 25.6 months) is marked and its savings shaded.
  await expect(chart.locator(".chart-note").first()).toHaveText(/^Break-even( vs GPT-6 Astra)?: 25\.6 mo$/);
  await expect(chart.locator("circle.series-point")).toHaveCount(1);
  await expect(chart.locator("polygon.savings-area")).toHaveCount(1);
  await expect(chart.locator(".savings-note")).toHaveText(/^Saved \$[\d,]+$/);
  await expect(chart).toHaveAttribute("aria-label", /This device becomes cheaper than Frontier API: GPT-6 Astra after 37,422 consultations \(25\.6 months\)/);
  // Every series is labeled at its end, so colour is never the only key.
  await expect(chart.locator(".end-label")).toHaveText(["GPT-6 Astra", "This device", "Claude Sonnet 5.5", "Same model, cloud API"]);
  // The headline is the per-consultation cost; the assumption is stated.
  await expect(page.locator(".kpi", { hasText: "Per consultation on this device" }).locator(".kpi-value")).toHaveText("less than $0.0001");
  await expect(page.locator(".kpi", { hasText: "Per consultation, same model, cloud API" }).locator(".kpi-value")).toHaveText("$0.0054");
  await expect(page.locator(".kpi", { hasText: "Local becomes cheaper after" }).locator(".kpi-value")).toHaveText("Not within the lifetime");
  await expect(page.locator(".assumption")).toContainText("48 consultations a day (measured on this device,");
  await expect(page.locator(".assumption")).toContainText("over the 36-month device lifetime: 52,600 consultations in all");
  const list = page.getByRole("list", { name: "Break-even by cloud API" });
  await expect(list.locator("li").nth(0)).toContainText("Same model, cloud API: not within the 36-month lifetime: after 1,437,145 consultations");
  await expect(list.locator("li").nth(2)).toContainText("Frontier API: GPT-6 Astra: this device becomes cheaper after 37,422 consultations (25.6 months at this volume)");
  // Choosing GPT-6 Astra moves the shading to it; a busy practice overtakes the frontier API sooner.
  await page.getByLabel("Cloud API to compare with").selectOption("frontier-gpt");
  await expect(page.locator(".kpi", { hasText: "Local becomes cheaper after" }).locator(".kpi-value")).toHaveText("37,422 consultations");
  await page.getByRole("button", { name: "Busy practice (200/day)" }).click();
  await expect(chart.locator(".chart-note").first()).toHaveText(/: 6\.1 mo$/);
  await expect(chart.locator("circle.series-point")).toHaveCount(2); // Claude Sonnet 5.5 is overtaken too (30.8 months)
  // At a tiny volume nothing is overtaken: no point, no shading, and the chart says so.
  await page.getByLabel("Consultations per day").fill("1");
  await expect(chart.locator("circle.series-point")).toHaveCount(0);
  await expect(chart.locator("polygon.savings-area")).toHaveCount(0);
  await expect(chart.locator(".chart-note")).toHaveText("No break-even within 36 months at this volume");
  await expectNoHorizontalOverflow(page);
});

test("#679 the break-even list writes months like the page's other figures", async ({ page }) => {
  await advanced(page);
  await nanoWeek(page);
  await page.goto("/telemetry");
  const list = page.getByRole("list", { name: "Break-even by cloud API" });
  // At 1 a day the like-for-like reference takes tens of thousands of months: grouped, as the consultations are.
  await page.getByLabel("Consultations per day").fill("1");
  await expect(list.locator("li").nth(0)).toContainText(/after 1,437,145 consultations \(\d{1,3}(,\d{3})+ months at this volume\)/);
  // At a huge volume the frontier API is overtaken within days: never "0.0 months".
  await page.getByLabel("Consultations per day").fill("1000000000");
  await expect(list.locator("li").nth(2)).toContainText("after 37,422 consultations (less than a month at this volume)");
  await expect(list).not.toContainText("0.0 months");
});

test("#547 the slide carries the basic figures, the cost per consultation and the HP logo", async ({ page }) => {
  await nanoWeek(page);
  await page.goto("/telemetry");
  const [d] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download SVG" }).click()]);
  const svg = readFileSync((await d.path())!, "utf8");
  const text = svg.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
  for (const s of ["Where the AI runs", "ZGX Nano", "Consultations guided", "338", "Typical time to guidance", "13.8 s",
    "AI cost per 1,000 consultations", "$0.044", "Patient data sent off the device", "0 bytes", "Cost per consultation",
    "pays for itself in 25.6 months against GPT-6 Astra (frontier API)"])
    expect(text, s).toContain(s);
  expect(svg).toContain('href="data:image/svg+xml;base64,'); // #513
  expect(text).not.toContain("Tokens processed");
});
