// Product review 2026-10-20 (v0.10.0-demo.1), W06 telemetry and W03 healthcare page:
// #324 no tile mixes windows; outcome windows are absolute dates; the outcome counting start is stated.
// #325 the page leads with the live value story; outcome figures without samples have an honest empty state.
// #331 W03 agrees with W06 (local processing is By design) and gives a public reader a working next step.
// The suite runs in mock mode; the telemetry snapshot is rewritten to the ZGX Fury's demo-day figures (evidence
// v0.10.0-demo.1 fury-telemetry-24h.json), with dates relative to today.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { expectNoHorizontalOverflow } from "./support/journey";
import { USD_FLOOR, usd } from "../../apps/web/src/screens/W06Slide";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));
// #547: these tests read the advanced view (every figure); the basic view is tested in W06-modes.spec.ts.
test.beforeEach(({ page }) => page.addInitScript(() => { try { localStorage.setItem("awarecare.telemetry.view", "advanced"); } catch { /* none */ } }));

const DAY = 86_400_000;
const HOUR = 3_600_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const midnight = () => { const d = new Date(); d.setUTCHours(0, 0, 0, 0); return d.getTime(); };
const iso = (ms: number) => new Date(ms).toISOString().replace(".000", "");
const day = (ms: number) => { const d = new Date(ms); return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
const pad = (n: number) => String(n).padStart(2, "0");
/** #638: the page's "26 Oct 2026, 14:00 UTC" and the slide's "26 Oct, 14:00 UTC" for a whole hour. */
const at = (ms: number) => { const d = new Date(ms); return `${day(ms)}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`; };
const short = (ms: number) => { const d = new Date(ms); return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}, ${pad(d.getUTCHours())}:00 UTC`; };
const hourOf = (ms: number) => Math.floor(ms / HOUR) * HOUR;
const LIVE = ["Patient data sent off the device", "AI calls on the device", "Estimated cloud cost of this work", "Output speed"];

/** The Fury's demo day: 657 live AI calls in the last 24 hours, 1,324 calls by task and no counted consultation,
 * because the device began recording the mode 2 hours ago (#271). #638: the window runs up to now. */
async function furyDemoDay(page: Page, over: (t: Record<string, any>) => Record<string, unknown> = () => ({})) {
  await page.route("**/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    const hour = hourOf(Date.now());
    const json = { ...t,
      identity: { ...t.identity, mode: "local", runtime: "ZRT 0.43.0 (vllm 0.30.0)", model_manifest_id: "qwen3.8-flash-next-fp8@236dfdf2-2026-10-17" },
      period: { ...t.period, key: "24h", days: 1 },
      metered: { ...t.metered, since: t.period.from, guided: 0 },
      consultations: { ...t.consultations, guided: 0, fail_closed: 0, repaired: 0, urgent_routes: 0, busy_refusals: 0,
        counted_from: iso(hour - DAY), counted_to: iso(hour + HOUR), counting_since: iso(hour - 2 * HOUR) },
      ai_calls: { ...t.ai_calls, total: 657, by_task: { certainty_review: 1, concern_check: 514, guidance: 39, red_flag_screen: 770 }, errors: 0,
        with_token_counts: 657, prompt_tokens: 411089, completion_tokens: 23417, duration_ms_p50: 180.7, duration_ms_p95: 273.1,
        duration_ms_total: 170128.0, output_tokens_per_second: 137.6 },
      latency: { samples: 0, total_ms_p50: null, total_ms_p95: null, queue_ms_p50: null },
      energy: { ...t.energy, status: "measured", calls_with_energy: 657, wh_total: 17.7706, sampler: { status: "active", last_sample_age_s: 0.3 } },
      privacy: { ...t.privacy, last_verified: { date: "2026-10-19", method: "socket sampling", samples: 143, non_loopback: 0, reference: "x" } },
    };
    await route.fulfill({ response, json: { ...json, ...over(json) } });
  });
}

const num = (s: string) => Number(s.replace(/[^\d]/g, ""));

test("#324 no tile mixes windows: the AI-calls tile is live only; the by-task breakdown sits under its window", async ({ page }) => {
  await furyDemoDay(page);
  await page.goto("/telemetry");
  const tiles = page.locator(".kpi");
  await expect(tiles.first()).toBeVisible();
  // Measured: tiles whose parts exceed or do not match the whole (before: 1, 657 vs 1,324).
  let mixed = 0;
  for (const tile of await tiles.all()) {
    const value = (await tile.locator(".kpi-value").textContent()) ?? "";
    const parts = [...((await tile.textContent()) ?? "").matchAll(/([\d,]+) (guidance|red-flag screen|safety review|concern check)/g)];
    if (parts.length && parts.reduce((a, m) => a + num(m[1]), 0) !== num(value)) mixed++;
  }
  expect(mixed).toBe(0);
  const calls = page.locator(".kpi", { hasText: "AI calls on the device" });
  await expect(calls.locator(".kpi-value")).toHaveText("657");
  await expect(calls).not.toContainText("770");
  await expect(calls).toContainText("up to now"); // #638 (before, #432: "counted by the hour up to 14:00 UTC")
  // The breakdown and the errors: under a heading with the window's absolute start.
  const rel = page.locator(".card", { has: page.getByRole("heading", { name: "Reliability and safety" }) });
  const window = `${at(hourOf(Date.now()) - DAY)} to now`;
  await expect(rel.getByRole("heading", { level: 3 })).toHaveText(window);
  await expect(rel.getByRole("row", { name: /AI calls by task: Red-flag screen/ })).toContainText("770");
  await expect(rel.getByRole("row", { name: /AI calls by task: Concern check/ })).toContainText("514");
  await expect(rel.getByRole("row", { name: /AI calls that errored/ })).toContainText("0");
  await expect(page.getByRole("heading", { level: 3, name: /Consultation outcomes/ })).toContainText(window);
});

test("#324 outcome windows are absolute dates and the outcome counting start is stated", async ({ page }) => {
  await furyDemoDay(page);
  await page.goto("/telemetry");
  await expect(page.locator(".kpi").first()).toBeVisible();
  const text = (await page.locator("main").textContent()) ?? "";
  expect(text.match(/\b(yesterday|tomorrow)\b/gi) ?? []).toEqual([]); // before: 4 relative-date phrases
  const since = hourOf(Date.now()) - 2 * HOUR;
  await expect(page.locator(".counting-since").first())
    .toContainText(`Outcomes counted since ${at(since)} (when this device began recording the mode)`);
  await expect(page.locator(".counting-since").first()).not.toContainText("complete UTC day");
  // #638: before, "Today's consultations appear after 00:00 UTC on <tomorrow>".
  await expect(page.locator(".kpi", { hasText: "Consultations guided" }))
    .toContainText(`None yet (${at(since)} to now). A consultation counts as soon as its guidance is published.`);
});

test("#324 #638 a window names its absolute start, a release that started this hour, and no counting note without a later start", async ({ page }) => {
  await furyDemoDay(page, (t) => ({ consultations: { ...t.consultations, counted_from: "2026-09-28T00:00:00Z", counted_to: "2026-10-05T00:00:00Z",
    counting_since: "2026-09-28T00:00:00Z" } }));
  await page.goto("/telemetry");
  await expect(page.locator(".card", { has: page.getByRole("heading", { name: "Reliability and safety" }) }).getByRole("heading", { level: 3 }))
    .toHaveText("28 Sep 2026, 00:00 UTC to now");
  await expect(page.locator(".counting-since")).toHaveCount(0);
  await page.unrouteAll({ behavior: "ignoreErrors" });
  const hour = hourOf(Date.now());
  await furyDemoDay(page, (t) => ({ period: { ...t.period, key: "release" },
    consultations: { ...t.consultations, counted_from: iso(hour), counted_to: iso(hour + HOUR), counting_since: iso(hour) },
    metered: { ...t.metered, since: iso(hour), guided: 0 } }));
  await page.goto("/telemetry");
  // Before (#276): "No complete UTC day in this period yet" all day.
  await expect(page.getByRole("heading", { level: 3, name: /Consultation outcomes/ })).toContainText(`${at(hour)} to now`);
  await expect(page.locator(".kpi", { hasText: "Consultations guided" })).toContainText(`None yet (${at(hour)} to now)`);
});

// #547: the value story leads in the basic view (the default); the advanced view keeps the live and outcome groups apart.
test("#325 At a glance leads with the value facts, each with its badge; outcome figures follow in their own group", async ({ page }, info) => {
  await page.addInitScript(() => localStorage.setItem("awarecare.telemetry.view", "basic"));
  await furyDemoDay(page);
  await page.goto("/telemetry");
  const basic = page.locator(".basic-grid .kpi");
  await expect(basic.locator(".kpi-label")).toHaveText(["Where the AI runs", "Consultations guided", "Typical time to guidance",
    "AI cost per 1,000 consultations", "Patient data sent off the device"]);
  await expect(basic.locator(".basis")).toHaveText(["By design", "Measured", "Not measured", "Not measured", "By design"]);
  // At 1440×900 every basic figure is above the fold.
  if (info.project.name.includes("1440"))
    for (const value of await basic.locator(".kpi-value").all()) expect((await value.boundingBox())!.y + (await value.boundingBox())!.height).toBeLessThanOrEqual(900);
  await page.getByRole("radio", { name: "Advanced" }).click();
  const live = page.locator(".kpi-grid").first().locator(".kpi-label");
  await expect(live).toHaveText([LIVE[1]]);
  const badge = (label: string) => page.locator(".kpi", { hasText: label }).locator(".basis");
  await expect(badge(LIVE[0])).toHaveText("By design");
  await expect(badge(LIVE[1])).toHaveText("Measured");
  await expect(badge(LIVE[2])).toHaveText("Estimated");
  await expect(badge(LIVE[3])).toHaveText("Measured");
  // 411,089 in / 23,417 out at the like-for-like price ($0.248 / $1.485) vs 17.7706 Wh × $0.1453/kWh.
  await expect(page.locator(".kpi", { hasText: LIVE[2] }).locator(".kpi-value")).toHaveText("$0.14 vs $0.0026");
  await expect(page.locator(".kpi", { hasText: LIVE[3] }).locator(".kpi-value")).toHaveText("137.6 tokens/s");
  const outcomes = page.locator(".kpi-grid").nth(1);
  await expect(outcomes.locator(".kpi-label")).toHaveText(["Consultations guided"]);
});

test("#325 outcome figures without samples say when they count; '0 of 0' is hidden; the AI-call row says what it measures", async ({ page }) => {
  await furyDemoDay(page, (t) => ({ metered: { ...t.metered, since: new Date(Date.now() - 3_600_000).toISOString(), guided: 0 } }));
  await page.goto("/telemetry");
  const next = "A consultation counts as soon as its guidance is published."; // #638
  const guided = page.locator(".kpi", { hasText: "Consultations guided" });
  await expect(guided.locator(".kpi-value")).toHaveText("None yet");
  await expect(guided).toContainText(next);
  await expect(guided.locator(".basis")).toHaveText("Measured");
  const time = page.locator(".kpi", { hasText: "Typical guidance time" });
  await expect(time.locator(".kpi-value")).toHaveText("No samples yet");
  await expect(time.locator(".basis")).toHaveText("Not measured");
  await expect(page.getByText("of the period's 0 consultations", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("row", { name: /Any AI call \(mostly short safety screens\), median \/ 95th percentile/ })).toContainText("0.2 s / 0.3 s");
  await expect(page.getByText("Single AI call")).toHaveCount(0);
  // The slide: no zero leads it (#547: the architecture's figure does; figures without samples are left out), the
  // "0 of 0" note is gone, and the outcome and demonstration notice are kept.
  const [d] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download SVG" }).click()]);
  const svg = readFileSync((await d.path())!, "utf8");
  expect(svg).not.toContain("Consultations guided");
  expect(svg).not.toContain("Typical time to guidance");
  expect(svg).toContain("Where the AI runs");
  expect(svg).toContain("By design");
  expect(svg).not.toContain("(0 of 0 consultations)");
  expect(svg).toContain("Healthcare outcomes are not measured (R39).");
});

test("#325 the slide never cuts the R39 sentence, even with long price sources", async ({ page }) => {
  await furyDemoDay(page, (t) => ({ pricing: { ...t.pricing, cloud_references: t.pricing.cloud_references.map((r: Record<string, unknown>) => ({
    ...r, provider: `${r.provider} (a deliberately long provider name for the footnote test)`, model: `${r.model} with an extra-long model label` })) } }));
  await page.goto("/telemetry");
  const [d] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download SVG" }).click()]);
  const svg = readFileSync((await d.path())!, "utf8");
  expect(svg).toContain("Healthcare outcomes are not measured (R39). Synthetic demonstration; not a medical device.");
});

test("#331 W03's local-processing row is By design and links to the telemetry privacy section", async ({ page }) => {
  await page.goto("/healthcare");
  const local = page.getByRole("row", { name: /Local processing at the healthcare edge/ });
  const chip = local.getByRole("link", { name: /By design: no cloud AI/ });
  await expect(chip).toHaveAttribute("href", "/telemetry#privacy");
  for (const name of [/Clearer preparation/, /Better-organized visit summaries/, /avoidable visits/])
    await expect(page.getByRole("row", { name }).locator(".chip")).toContainText("Not measured");
  // Measured: contradictions between W03 and W06 (before: 1).
  await expect(local).not.toContainText("Not measured");
  await chip.click();
  await expect(page).toHaveURL(/\/telemetry#privacy$/);
  await expect(page.locator("#privacy")).toBeInViewport();
  await expect(page.locator("#privacy")).toBeFocused();
});

test("#331 a public reader gets working next steps; the presenter link shows only on the presenter gateway", async ({ page }) => {
  // #487: one address for both roles. W03 has no presenter action at all; the home page's Presenter choice is the way in.
  await page.goto("/healthcare");
  const actions = page.locator("main .actions");
  // Measured: dead-end actions for a public reader (before: 1, "Explore the demonstration" to presenter-only O03).
  await expect(actions.locator("a[href^='/presenter']")).toHaveCount(0);
  await actions.getByRole("link", { name: "See what is measured on this device" }).click();
  await expect(page).toHaveURL(/\/telemetry$/);
  await page.goBack();
  await page.locator("main .actions").getByRole("link", { name: "How it works" }).click();
  await expect(page).toHaveURL(/\/how-it-works$/);
  await page.goto("/");
  await page.getByRole("link", { name: "Open the presenter tools" }).click();
  await expect(page).toHaveURL(/\/presenter\/scenarios$/);
});

// ── QA of 2026-10-22 (v0.14.0-demo.1) ───────────────────────────────────────────────────────────────────────────
// #398 (T-01) per-consultation figures from one window; #432 (S-03) usage counted by the hour; #436/#467 (T-02/T-03)
// the slide names the span counted; #437 (T-04) mock mode; #438/#439 (T-05/T-06) calculator entries; #468 (T-08);
// #472/#476 (T-14/T-18) Sources; #473 (T-15) W03; #477 (T-19) the slide's bases; #405/#442/#446/#447 (A-08/A-09/A-14/
// A-15) accessibility of the calculator, the update and the chart legend.


/** The real (mock-mode) snapshot rewritten to a local-mode one: `over` returns the fields to replace. */
async function rewrite(page: Page, over: (t: Record<string, any>) => Record<string, unknown>) {
  await page.route("**/api/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    const base = { ...t, identity: { ...t.identity, mode: "local", runtime: "ZRT 0.43.0 (vllm 0.30.0)", model_manifest_id: "m@r" } };
    await route.fulfill({ response, json: { ...base, ...over(base) } });
  });
}

/** The slide's text, its wrapped lines joined with single spaces. */
const flat = (svg: string) => svg.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const slideSvg = async (page: Page) => {
  const [d] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download SVG" }).click()]);
  return readFileSync((await d.path())!, "utf8");
};

/** QA's controlled case: 2 consultations, each with one AI call of 10,000 in / 1,000 out / 0.5 Wh / 10 s, in the
 * per-consultation window; the live totals also hold 2 calls from before it (the first, partly metered hour). */
function mixedWindows(t: Record<string, any>) {
  const hour = hourOf(Date.now());
  return {
    period: { ...t.period, key: "24h", days: 1 },
    consultations: { ...t.consultations, guided: 2, counted_from: iso(hour - DAY), counted_to: iso(hour + HOUR), counting_since: iso(hour - DAY) },
    metered: { since: iso(Date.now() - DAY), guided: 2, from: iso(hour - DAY), to: iso(hour + HOUR), ai_calls: 2, with_token_counts: 2,
      prompt_tokens: 20000, completion_tokens: 2000, duration_ms_total: 20000, calls_with_energy: 2, wh_total: 1 },
    ai_calls: { ...t.ai_calls, total: 4, with_token_counts: 4, prompt_tokens: 40000, completion_tokens: 4000, duration_ms_total: 40000,
      duration_ms_p50: 10000, duration_ms_p95: 10000, output_tokens_per_second: 100 },
    energy: { ...t.energy, status: "measured", calls_with_energy: 4, wh_total: 2 },
  };
}

test("#398 per-consultation defaults divide usage and consultations from the same window", async ({ page }) => {
  await rewrite(page, mixedWindows);
  await page.goto("/telemetry");
  // Before: 20,000 / 2,000 / 1 Wh / 20.0 s (the live totals divided by the window's consultations).
  await expect(page.getByLabel("Input tokens per consultation")).toHaveValue("10000");
  await expect(page.getByLabel("Output tokens per consultation")).toHaveValue("1000");
  await expect(page.getByRole("spinbutton", { name: /GPU energy per consultation/ })).toHaveValue("0.5");
  await expect(page.getByText("the measured 10.0 s of AI time per consultation", { exact: false })).toBeVisible();
  await expect(page.locator("#privacy")).toContainText("each consultation would send about 10,000 tokens");
  // The window is named, and it is the one the consultations were counted in.
  const from = at(hourOf(Date.now()) - DAY);
  await expect(page.locator(".calc-basis")).toContainText(`${from} to now: the 2 AI calls of those hours ÷ the 2 consultations guided in the same hours`);
  await expect(page.locator(".calc-basis")).toContainText(`2 consultations guided, ${from} to now (1.0 days)`);
  await expect(page.getByRole("button", { name: "Measured (2/day)" })).toBeVisible();
  await expect(page.getByText(/covers \d+ of the period's/)).toHaveCount(0);
});

test("#398 the measured volume divides the counted consultations by the days actually counted", async ({ page }) => {
  // 7 days; outcome counting began 35 hours before the end of the current hour (#324): 35 consultations in 1.5 days, not 7.
  const end = hourOf(Date.now()) + HOUR;
  const since = end - 36 * HOUR;
  await rewrite(page, (t) => ({ period: { ...t.period, key: "7d", days: 7 },
    consultations: { ...t.consultations, guided: 35, counted_from: iso(end - 7 * DAY - HOUR), counted_to: iso(end), counting_since: iso(since) },
    metered: { ...t.metered, since: iso(end - 7 * DAY), guided: 0, from: iso(end), to: iso(end) } }));
  await page.goto("/telemetry");
  await expect(page.getByLabel("Consultations per day")).toHaveValue("23"); // before: 5 (35 / 7)
  await expect(page.getByRole("button", { name: "Measured (23/day)" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".calc-basis")).toContainText(`35 consultations guided, ${at(since)} to now (1.5 days)`);
});

test("#638 the live figures count up to now, including the current hour", async ({ page }) => {
  await rewrite(page, (t) => mixedWindows(t));
  await page.goto("/telemetry");
  // Before (#432): "up to 14:00 UTC (complete hours)" and "the AI calls of the current hour appear at 15:00 UTC".
  await expect(page.locator("#kpi-live")).toContainText("up to now");
  await expect(page.locator(".live-note")).toContainText("Every figure counts up to now, including the current hour");
  await expect(page.locator(".live-note")).toContainText("count as soon as they happen");
  await expect(page.locator(".kpi", { hasText: "AI calls on the device" })).toContainText("Every AI call in this period, up to now");
  await expect(page.locator("main")).not.toContainText(/complete (hours|UTC day)|appear (at|after)/);
});

test("#436 #467 the outcome figures name the span actually counted, on the page and on the slide", async ({ page }) => {
  const hour = hourOf(Date.now());
  const since = hour - 2 * DAY;
  await rewrite(page, (t) => ({ consultations: { ...t.consultations, guided: 115, counted_from: iso(hour - 7 * DAY), counted_to: iso(hour + HOUR), counting_since: iso(since) } }));
  await page.goto("/telemetry");
  await expect(page.locator(".kpi", { hasText: "Consultations guided" })).toContainText(`Published AI guidance, ${at(since)} to now`);
  let svg = flat(await slideSvg(page));
  // Before: "Published guidance in complete UTC days, <7 days>" with no counting start on the slide.
  expect(svg).not.toContain("complete UTC days");
  expect(svg).toContain(`Published guidance, ${short(since)} to now`);
  // A release that started at 15:30 two days ago: its window starts at the whole hour, 15:00.
  await page.unrouteAll({ behavior: "ignoreErrors" });
  const start = midnight() - 2 * DAY + 15 * HOUR;
  await rewrite(page, (t) => ({ period: { ...t.period, key: "release" },
    consultations: { ...t.consultations, guided: 6, counted_from: iso(start), counted_to: iso(hour + HOUR), counting_since: iso(start) } }));
  await page.goto("/telemetry");
  const rel = page.locator(".card", { has: page.getByRole("heading", { name: "Reliability and safety" }) });
  await expect(rel.getByRole("heading", { level: 3 })).toHaveText(`${day(start)}, 15:00 UTC to now`);
  await expect(page.locator("main")).not.toContainText("complete UTC days");
  svg = flat(await slideSvg(page));
  expect(svg).not.toContain("complete UTC days");
  expect(svg).toContain(`Published guidance, ${short(start)} to now`);
});

test("#437 mock mode presents scripted calls and guidance as scripted, never as a running AI model", async ({ page }) => {
  await page.route("**/api/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    await route.fulfill({ response, json: { ...t, consultations: { ...t.consultations, guided: 3 },
      ai_calls: { ...t.ai_calls, total: 5, by_task: { guidance: 3, red_flag_screen: 2 }, duration_ms_p50: 0, duration_ms_p95: 0 } } });
  });
  await page.goto("/telemetry");
  await expect(page.locator(".kpi", { hasText: "Scripted calls (mock mode)" })).toContainText("No AI model ran");
  await expect(page.locator(".kpi .kpi-label", { hasText: "AI calls on the device" })).toHaveCount(0);
  await expect(page.locator(".kpi", { hasText: "Consultations guided" })).toContainText("Published scripted guidance (mock mode)");
  await expect(page.getByText("Published AI guidance")).toHaveCount(0);
  await expect(page.locator("#privacy")).toContainText("Mock mode: no AI model runs; the results are scripted.");
  await expect(page.locator("#privacy")).not.toContainText("The model runs only on this device.");
  await expect(page.locator("#privacy")).not.toContainText("off-device connections");
  await expect(page.getByRole("row", { name: /Any AI call/ })).toHaveCount(0);
  await expect(page.getByRole("row", { name: /AI call time/ })).toContainText("no AI model in mock mode");
  await expect(page.getByRole("row", { name: /Scripted calls by task: Guidance/ })).toContainText("3");
  const svg = flat(await slideSvg(page));
  expect(svg).toContain("Aware Care in mock mode: scripted results, no AI model");
  expect(svg).not.toContain("local AI on the");
  expect(svg).not.toContain("the model runs only on the");
  // The API names no network check of a model in mock mode.
  expect((await (await page.request.get("/api/v1/telemetry")).json()).privacy.last_verified).toBeNull();
});

test("#438 a calculator field can be emptied; an invalid entry is rejected visibly and never becomes another number", async ({ page }) => {
  await localLike(page);
  await page.goto("/telemetry");
  const perDay = page.getByLabel("Consultations per day");
  const cloud = page.locator(".kpi", { hasText: "Cloud API per month" }).locator(".kpi-value");
  await perDay.fill("10");
  const atTen = await cloud.textContent();
  await perDay.fill("");
  await expect(perDay).toHaveValue(""); // before: "0"
  await expect(perDay).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#perDay-error")).toHaveText("Enter a number. The results use the last valid value, 10.");
  await expect(cloud).toHaveText(atTen!);
  await perDay.pressSequentially("-5");
  await expect(perDay).toHaveValue("-5"); // before: "05", and 5 consultations per day were used
  await expect(page.locator("#perDay-error")).toContainText("Enter 0 or more.");
  await expect(cloud).toHaveText(atTen!);
  await perDay.fill("20");
  await expect(perDay).not.toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#perDay-error")).toHaveCount(0);
  await expect(cloud).not.toHaveText(atTen!);
  const kwh = page.getByRole("spinbutton", { name: /Electricity price/ });
  await kwh.fill("");
  await kwh.pressSequentially("0.12");
  await expect(kwh).toHaveValue("0.12"); // before: "00.12"
  // A preset replaces an invalid entry.
  await perDay.fill("");
  await page.getByRole("button", { name: "Small clinic (50/day)" }).click();
  await expect(perDay).toHaveValue("50");
  await expect(page.locator("#perDay-error")).toHaveCount(0);
});

test("#439 a lifetime below 1 month is rejected, the device price always counts, and the axis labels are distinct", async ({ page }) => {
  await localLike(page);
  await page.goto("/telemetry");
  const months = page.getByRole("spinbutton", { name: /Device lifetime/ });
  const device = page.locator(".kpi", { hasText: "This device per month" });
  const before = await device.textContent();
  await months.fill("0");
  await expect(page.locator("#months-error")).toContainText("Enter a lifetime of at least 1 month.");
  await expect(device).toHaveText(before!); // before: "$0.00 device amortization"
  await expect(page.locator(".kpi", { hasText: "Device pays for itself" })).not.toContainText("The cloud API is not more expensive");
  await months.fill("1");
  const ticks = page.locator("svg.line-chart text.axis").filter({ hasText: / mo$/ });
  await expect(ticks).toHaveText(["0 mo", "0.5 mo", "1 mo"]); // before: "0 mo, 1 mo, 1 mo"
  await months.fill("3");
  await expect(ticks).toHaveText(["0 mo", "1.5 mo", "3 mo"]); // before: "2 mo"
  await expect(device).toContainText("device amortization");
  expect(await device.textContent()).not.toContain("$0.00 device amortization");
});

/** A local-mode snapshot with metered consultations (12 in 7 days) and a frontier API dearer than the electricity. */
async function localLike(page: Page) {
  await rewrite(page, (t) => ({ consultations: { ...t.consultations, guided: 12 },
    metered: { ...t.metered, guided: 12, from: t.consultations.counted_from, to: t.consultations.counted_to, ai_calls: 30, with_token_counts: 30,
      prompt_tokens: 60000, completion_tokens: 9000, duration_ms_total: 300000, calls_with_energy: 30, wh_total: 3.2 },
    ai_calls: { ...t.ai_calls, total: 30, with_token_counts: 30, prompt_tokens: 60000, completion_tokens: 9000, duration_ms_total: 300000 },
    energy: { ...t.energy, status: "measured", calls_with_energy: 30, wh_total: 3.2 } }));
}

test("#468 the volume preset is Measured when consultations were counted, even without token counts", async ({ page }) => {
  await rewrite(page, (t) => ({ consultations: { ...t.consultations, guided: 14 },
    metered: { ...t.metered, guided: 14, with_token_counts: 0, prompt_tokens: 0, completion_tokens: 0, ai_calls: 14 } }));
  await page.goto("/telemetry");
  await expect(page.getByRole("button", { name: "Measured (2/day)" })).toBeVisible(); // before: "Fallback (2/day)"
  await expect(page.getByRole("button", { name: /^Fallback/ })).toHaveCount(0);
  await expect(page.getByText("Fallback tokens per consultation:", { exact: false })).toBeVisible();
  await expect(page.locator(".calc-basis")).toContainText("Consultations per day: 14 consultations guided");
});

test("#472 Sources uses the page's one date style and one money style", async ({ page }) => {
  await page.goto("/telemetry");
  const sources = page.locator("section", { has: page.getByRole("heading", { name: "Sources and assumptions" }) });
  await expect(sources).toContainText("Price list of 17 Oct 2026 (USD)");
  await expect(sources).toContainText("released 24 Sep 2026");
  await expect(sources).toContainText("out of stock on 16 Oct 2026");
  await expect(sources.getByRole("row", { name: /HP Store US list price/ })).toContainText("$7,699");
  await expect(sources.getByRole("row", { name: /electricity price/ })).toContainText("$0.1453/kWh");
  await expect(sources.getByRole("row", { name: /amortization period/ })).toContainText("36 months");
  const text = await sources.innerText();
  expect(text.match(/\b\d{4}-\d{2}-\d{2}\b/g) ?? []).toEqual([]); // before: 2026-10-17, 2026-10-16, 2026-09-24
  expect(text).not.toMatch(/\b7699 USD\b|\bUSD\/kWh\b/);
});

test("#473 W03 never presents local processing as a hypothesis, at any width", { tag: "@mobile" }, async ({ page }, info) => {
  await page.goto("/healthcare");
  const region = page.getByRole("region", { name: "Benefits by stakeholder" });
  await expect(region.getByRole("columnheader", { name: "Hypothesis" })).toHaveCount(0);
  await expect(page.locator("caption")).not.toContainText("Hypothesized");
  const local = page.getByRole("row", { name: /Local processing at the healthcare edge/ });
  await expect(local.locator('td[data-label="Hypothesis"]')).toHaveCount(0); // before: 1
  await expect(local.locator('td[data-label="By design"]')).toHaveText("Local processing at the healthcare edge");
  if (info.project.name.includes("360")) {
    const label = await local.locator('td[data-label="By design"]').evaluate((td) => getComputedStyle(td, "::before").content);
    expect(label).toContain("By design");
  }
  for (const name of [/Clearer preparation/, /Better-organized visit summaries/, /avoidable visits/])
    await expect(page.getByRole("row", { name }).locator('td[data-label="Hypothesis"]')).toHaveCount(1);
  await expect(page.getByRole("main")).toContainText("Local processing is not a hypothesis");
});

test("#476 every column and Source link of the Sources table stays visible at 360 px", { tag: "@mobile" }, async ({ page }) => {
  await page.goto("/telemetry");
  const region = page.getByRole("region", { name: "Prices and assumptions table" });
  await region.scrollIntoViewIfNeeded();
  const width = page.viewportSize()!.width;
  const box = (await region.boundingBox())!;
  const links = region.getByRole("link", { name: "Source" });
  expect(await links.count()).toBeGreaterThanOrEqual(4);
  for (const link of await links.all()) {
    const l = (await link.boundingBox())!;
    expect(l.x + l.width, "Source link inside the table's box").toBeLessThanOrEqual(Math.min(box.x + box.width, width) + 0.5);
  }
  // Nothing scrolls sideways inside the table (before at 360: the table was 451 px in a 328 px card).
  expect(await region.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0);
  await expectNoHorizontalOverflow(page);
});

test("#477 the slide keeps the scenario's fallback basis, and an empty cost panel is not badged Estimated", async ({ page }) => {
  // Measured tokens in the period, but no consultation counted yet: the scenario runs on the fallback values.
  await rewrite(page, (t) => ({ consultations: { ...t.consultations, guided: 0 }, metered: { ...t.metered, guided: 0 },
    ai_calls: { ...t.ai_calls, total: 120, with_token_counts: 120, prompt_tokens: 704058, completion_tokens: 30000 } }));
  await page.goto("/telemetry");
  await expect(page.getByRole("button", { name: "Fallback (20/day)" })).toBeVisible();
  let svg = flat(await slideSvg(page));
  expect(svg).toContain("At 20 consultations per day (fallback), compared with"); // before: no basis
  expect(svg).toContain("Fallback tokens per consultation: the guidance call only.");
  await page.getByLabel("Consultations per day").fill("1");
  svg = flat(await slideSvg(page));
  expect(svg).toContain("At 1 consultation per day (assumed)"); // before: "At 1 consultations per day"
  // Mock mode without token counts. #547: the panel is the cost per consultation: the cloud bars are list prices on the
  // fallback tokens (Estimated, and said so), and the device's bar, without measured energy, is Not measured.
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await page.goto("/telemetry");
  svg = await slideSvg(page);
  const badge = svg.match(/Cost per consultation<\/text><rect[^>]*\/><text[^>]*>([^<]+)<\/text>/);
  expect(badge?.[1]).toBe("Estimated");
  expect(flat(svg)).toContain("This device (electricity) Not measured");
  expect(flat(svg)).toContain("Fallback tokens per consultation: the guidance call only.");
});

test("#405 #442 the volume presets expose which is active, and every unit is part of its field's name", async ({ page }) => {
  await localLike(page);
  await page.goto("/telemetry");
  const presets = page.getByRole("group", { name: "Volume presets (assumptions)" }).getByRole("button");
  await expect(presets).toHaveCount(4);
  await page.getByRole("button", { name: "Small clinic (50/day)" }).click();
  // Before: no aria-pressed on any preset (the state was shown by colour only).
  expect(await presets.evaluateAll((b) => b.map((x) => x.getAttribute("aria-pressed")))).toEqual(["false", "true", "false", "false"]);
  for (const name of ["GPU energy per consultation Wh", "Device price USD", "Device lifetime months", "Electricity price USD/kWh",
    "Other system power during AI calls W"])
    await expect(page.getByRole("spinbutton", { name, exact: true })).toHaveCount(1); // before: the name had no unit
});

test("#446 the minute-by-minute update can be stopped and started again", async ({ page }) => {
  await page.clock.install();
  let reads = 0;
  page.on("request", (r) => { if (r.url().includes("/api/v1/telemetry?period=7d")) reads++; });
  await page.goto("/telemetry");
  await expect(page.getByRole("heading", { name: "Usage", exact: true })).toBeVisible();
  const toggle = page.getByRole("checkbox", { name: "Update every minute" });
  await expect(toggle).toBeChecked(); // before: no such control
  await page.clock.runFor(61_000);
  await expect.poll(() => reads).toBeGreaterThanOrEqual(3); // the page, the app's facts, one update
  await toggle.uncheck();
  const stopped = reads;
  await page.clock.runFor(185_000);
  expect(reads).toBe(stopped);
  await toggle.check();
  await page.clock.runFor(61_000);
  await expect.poll(() => reads).toBe(stopped + 1);
  // Refresh still loads on demand.
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect.poll(() => reads).toBe(stopped + 2);
});

test("#447 each chart legend swatch stays next to its own label, and the series differ by more than colour", async ({ page }) => {
  await localLike(page);
  await page.goto("/telemetry");
  const legend = page.locator(".chart-legend");
  await legend.scrollIntoViewIfNeeded();
  const gaps = await legend.locator(".swatch").evaluateAll((swatches) => swatches.map((s) => {
    // The first visible character of the label that follows the swatch must sit on the swatch's line.
    let node = s.nextSibling;
    while (node && !(node.textContent ?? "").trim()) node = node.nextSibling;
    const textNode = node && node.nodeType === Node.TEXT_NODE ? node : node?.firstChild;
    if (!textNode) return Infinity;
    const at = (textNode.textContent ?? "").search(/\S/);
    const range = document.createRange();
    range.setStart(textNode, at);
    range.setEnd(textNode, at + 1);
    const a = s.getBoundingClientRect(), b = range.getBoundingClientRect();
    return Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2);
  }));
  expect(gaps).toHaveLength(5); // #547: the device, each cloud API and the savings
  for (const gap of gaps) expect(gap).toBeLessThan(8); // before at 360: the device swatch ended the cloud line
  await expect(legend.locator("li")).toHaveText(["This device: price paid once, then electricity (dashed line)",
    "Same model, cloud API, cumulative (solid line)", "Frontier API: Claude Sonnet 5.5, cumulative (dotted line)",
    "Frontier API: GPT-6 Astra, cumulative (dash-dot line)", "Savings after break-even (shaded)"]);
  const dashes = await page.locator("svg.line-chart line.series-other").evaluateAll((ls) => ls.map((l) => getComputedStyle(l).strokeDasharray));
  expect(dashes).toHaveLength(2);
  expect(new Set(dashes).size).toBe(2);
  expect(await page.locator("svg.line-chart .series-local").evaluate((l) => getComputedStyle(l).strokeDasharray)).not.toBe("none");
});

// ── #492 (device verification of v0.15.0-demo.1) ─────────────────────────────────────────────────────────────────
// Tiny and huge amounts read in the page's money style, never in exponent notation (before: "$1.8e-8").

test("#492 unit: the money style covers zero, tiny, sub-dollar, cents, dollars and huge amounts without exponents", () => {
  const cases: [number, string][] = [
    [0, "$0.00"],
    [1.8e-8, "less than $0.0001"], // before: "$1.8e-8"
    [1e-7, "less than $0.0001"], // before: "$1.0e-7"
    [9.99e-5, "less than $0.0001"], // before: "$0.00010" (not below the floor once rounded, but smaller)
    [1e-4, "$0.00010"],
    [4.6e-4, "$0.00046"], // the page's established style (W06.spec.ts)
    [0.0026, "$0.0026"],
    [0.028, "$0.028"],
    [0.14, "$0.14"],
    [0.5, "$0.50"],
    [0.999, "$1.00"], // before: "$1.0"
    [1.05, "$1.05"],
    [99.999, "$100"], // before: "$100.00"
    [7699, "$7,699"],
    [123_456_789, "$123,456,789"],
    [1.234e9, "$1.23 billion"], // before: "$1,234,000,000"
    [4.5e13, "$45 trillion"],
    [1e25, "more than $999 trillion"], // before: "$10,000,000,000,000,000,905,969,664"
    [Infinity, "more than $999 trillion"], // before: "$∞"
    [NaN, "—"], // before: "$NaN"
  ];
  for (const [n, text] of cases) expect(usd(n), String(n)).toBe(text);
  for (const n of [1e-300, 1e-12, 1.8e-8, 3e-6, 1e-4, 0.5, 42, 1e6, 1e9, 1e14, 1e300, Number.MAX_VALUE])
    expect(usd(n), String(n)).not.toMatch(/e[+-]?\d|∞|NaN/i);
  expect(USD_FLOOR).toBe(0.0001);
});

test("#492 a tiny volume reads 'less than $0.0001' in the calculator and the slide, never in exponent notation", async ({ page }) => {
  await localLike(page);
  await page.goto("/telemetry");
  const perDay = page.getByLabel("Consultations per day");
  const cloud = page.locator(".kpi", { hasText: "Cloud API per month" });
  const device = page.locator(".kpi", { hasText: "This device per month" });
  await perDay.fill("");
  await perDay.pressSequentially("1e-7");
  await expect(perDay).not.toHaveAttribute("aria-invalid", "true");
  await expect(cloud.locator(".kpi-value")).toHaveText("less than $0.0001"); // before: "$1.8e-8"
  await expect(device).toContainText("electricity");
  const calculator = page.locator("section", { has: cloud });
  for (const text of [await calculator.innerText(), (await page.locator("svg.line-chart").getAttribute("aria-label")) ?? ""])
    expect(text).not.toMatch(/\$-?[\d.]+e[+-]?\d/i);
  expect(flat(await slideSvg(page))).not.toMatch(/\$-?[\d.]+e[+-]?\d/i);
  // A huge volume reads in words, not as a 20-digit number.
  await perDay.fill("1e15");
  await expect(cloud.locator(".kpi-value")).toHaveText(/^\$[\d.]+ (billion|trillion)$|^more than \$999 trillion$/);
  await expectNoHorizontalOverflow(page);
});
