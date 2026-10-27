// W06 Telemetry (R34, R38, R39; ADR-017). Public, content-free aggregates; every figure badged Measured, Estimated or
// Not measured; estimates show their formula and reviewed sources; outcomes stay Not measured; nothing leaves the device.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { guardNetwork, startSession } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));
// #547: these tests read the advanced view (every figure); the basic view is tested in W06-modes.spec.ts.
test.beforeEach(({ page }) => page.addInitScript(() => { try { localStorage.setItem("awarecare.telemetry.view", "advanced"); } catch { /* none */ } }));

const badges = (page: Page, name: string) => page.locator(`.basis`, { hasText: new RegExp(`^${name}$`) });

/** The suite runs in mock mode; this rewrites the snapshot to a populated local-mode one (fixed measured values). */
async function localSnapshot(page: Page, over: Record<string, unknown> = {}) {
  await page.route("**/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    await route.fulfill({ response, json: {
      ...t,
      identity: { ...t.identity, mode: "local", runtime: "ZRT 0.43.0 (vllm 0.30.0)", model_manifest_id: "qwen3.6-35b-a3b-fp8@95a723d0-2026-10-15",
        prompt_version: "guidance-local-3", qualification: { result: "PASSED", date: "2026-10-16", reference: "evidence/model-qualification/2026-10-16-guidance-local-3/README.md" } },
      period: { ...t.period, days: 7 },
      // #398: the per-consultation window (the outcome window, up to now, #638) with its own usage.
      metered: { since: t.period.from, guided: 12, from: t.consultations.counted_from, to: t.consultations.counted_to, ai_calls: 30,
        with_token_counts: 30, prompt_tokens: 60000, completion_tokens: 9000, duration_ms_total: 300000, calls_with_energy: 30, wh_total: 3.2 },
      consultations: { ...t.consultations, guided: 12, repaired: null, fail_closed: null, urgent_routes: 6, busy_refusals: 0 },
      ai_calls: { ...t.ai_calls, total: 30, by_task: { guidance: 14, red_flag_screen: 12, certainty_review: 4, concern_check: 3 }, errors: 0, with_token_counts: 30,
        prompt_tokens: 60000, completion_tokens: 9000, duration_ms_p50: 9000, duration_ms_p95: 15000, duration_ms_total: 300000, output_tokens_per_second: 52.1 },
      latency: { samples: 12, total_ms_p50: 13000, total_ms_p95: 21000, queue_ms_p50: 1.2 },
      energy: { ...t.energy, status: "measured", calls_with_energy: 30, wh_total: 3.2, sampler: { status: "active", last_sample_age_s: 0.8 } },
      ...over,
    } });
  });
}

test("the telemetry page is public, labels every figure and is truthful in mock mode", async ({ page }) => {
  const offenders = guardNetwork(page);
  await page.goto("/telemetry");
  await expect(page.getByRole("heading", { level: 1, name: "Local AI on the HP ZGX Nano: usage, cost and privacy" })).toBeVisible();
  await expect(page.getByText("Mock mode: scripted results, no AI model")).toBeVisible();
  for (const name of ["Measured", "Estimated", "Not measured"]) expect(await badges(page, name).count()).toBeGreaterThan(0);
  await expect(page.locator(".kpi", { hasText: "Patient data sent off the device" })).toContainText("0 bytes");
  await expect(page.locator(".kpi", { hasText: "Tokens processed" }).locator(".basis")).toHaveText("Not measured");
  await expect(page.getByRole("heading", { name: "What we don't claim" })).toBeVisible();
  await expect(page.getByText("Healthcare outcomes such as avoided visits or staff time are not measured", { exact: false })).toBeVisible();
  const sources = page.locator("section", { has: page.getByRole("heading", { name: "Sources and assumptions" }) });
  await expect(sources.getByRole("link", { name: "Source" }).first()).toHaveAttribute("href", /^https:\/\//);
  await expect(sources).toContainText("retrieved 16 Oct 2026");
  expect(offenders).toEqual([]);
});

test("measured tokens and energy become clearly labeled cost estimates with their formula", async ({ page }) => {
  await localSnapshot(page);
  await page.goto("/telemetry");
  await expect(page.getByText("Mock mode: scripted results")).toHaveCount(0);
  await expect(page.locator(".kpi", { hasText: "Tokens processed" })).toContainText("69,000");
  await expect(page.locator(".kpi", { hasText: "GPU energy for AI calls" })).toContainText("3.20 Wh");
  const bars = page.locator(".bars");
  // 60,000 in / 9,000 out: Qwen hosted $0.248/$1.485, Claude Sonnet 5.5 $2/$10; energy 3.2 Wh × $0.1453/kWh.
  await expect(bars.locator(".bar-row", { hasText: "Same model, cloud API" })).toContainText("$0.028");
  await expect(bars.locator(".bar-row", { hasText: "Frontier API: Claude Sonnet 5.5" })).toContainText("$0.21");
  await expect(bars.locator(".bar-row", { hasText: "Frontier API: GPT-6 Astra" })).toContainText("$1.05"); // $10 / $50 (#127)
  await expect(bars.locator(".bar-row", { hasText: "This device (electricity)" })).toContainText("$0.00046");
  await page.getByText("Show the formulas").click();
  await expect(page.getByText("Cloud cost = input tokens × input price", { exact: false })).toBeVisible();
  await expect(page.locator(".card", { has: page.getByRole("heading", { name: "Reliability and safety" }) })).toContainText("fewer than 5");
  await expect(page.getByRole("row", { name: /Cloud API latency/ })).toContainText("Not measured");
});

test("the fail-closed results say which validator rule stopped them, by rule only (#538)", async ({ page }) => {
  await localSnapshot(page, { consultations: { guided: 12, repaired: null, fail_closed: 7, urgent_routes: 6, busy_refusals: 0,
    suppressed_below: 5, counted_from: "2026-10-19T00:00:00Z", counted_to: "2026-10-26T00:00:00Z", counting_since: "2026-10-19T00:00:00Z",
    fail_closed_reasons: [{ rule: "prohibited_certainty/rules_out_risk", count: 9 }, { rule: "third_person", count: null }] } });
  await page.goto("/telemetry");
  const card = page.locator(".card", { has: page.getByRole("heading", { name: "Reliability and safety" }) });
  await expect(card.getByRole("row", { name: "Stopped safely instead of shown (fail closed) 7" })).toBeVisible();
  await expect(card.getByRole("row", { name: /rejected by rule: prohibited_certainty\/rules_out_risk/ })).toContainText("9");
  await expect(card.getByRole("row", { name: /rejected by rule: third_person/ })).toContainText("fewer than 5");
});

test("the break-even calculator starts from measurements and recomputes from the viewer's assumptions", async ({ page }) => {
  await localSnapshot(page);
  await page.goto("/telemetry");
  // Defaults: 12 consultations in 7 days → 2 per day; 5,000 in / 750 out tokens and 0.2667 Wh per consultation.
  await expect(page.getByLabel("Consultations per day")).toHaveValue("2");
  await expect(page.getByLabel("Input tokens per consultation")).toHaveValue("5000");
  await expect(page.getByLabel("Output tokens per consultation")).toHaveValue("750");
  await page.getByLabel("Cloud API to compare with").selectOption("frontier");
  await page.getByLabel("Consultations per day").fill("500");
  const n = 500 * 30.44, cloud = ((5000 * 2 + 750 * 10) / 1e6) * n, energy = (0.2667 / 1000) * 0.1453 * n;
  const months = (7699 / (cloud - energy)).toFixed(1);
  await expect(page.locator(".kpi", { hasText: "Device pays for itself" })).toContainText(`${months} months`);
  await expect(page.locator(".kpi", { hasText: "Cloud API per month" })).toContainText(`$${Math.round(cloud).toLocaleString("en-US")}`);
  await expect(page.locator("svg.line-chart")).toBeVisible();
  // Presets are labeled assumptions; the measured default stays one click away.
  await page.getByRole("button", { name: "Health system (2,000/day)" }).click();
  await expect(page.getByLabel("Consultations per day")).toHaveValue("2000");
  await page.getByRole("button", { name: "Measured (2/day)" }).click();
  await expect(page.getByLabel("Consultations per day")).toHaveValue("2");
  await page.getByLabel("Consultations per day").fill("500");
  // A refresh within the period keeps the viewer's inputs.
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByLabel("Consultations per day")).toHaveValue("500");
});

test("switching the period asks the API for that period and nothing else", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/api/v1/telemetry")) asked.push(new URL(r.url()).searchParams.get("period") ?? ""); });
  await page.goto("/telemetry");
  await expect(page.getByRole("radio", { name: "Last 7 days" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("radio", { name: "Since this release" }).click();
  await expect(page.getByRole("radio", { name: "Since this release" })).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => asked).toContain("release");
  expect(new Set(asked)).toEqual(new Set(["7d", "release"]));
});

test("the Telemetry button opens the page from the home page, the patient app and the footer", { tag: "@mobile" }, async ({ page }, info) => {
  await page.goto("/");
  await page.locator(".hero").getByRole("link", { name: "See live telemetry" }).click();
  await expect(page).toHaveURL(/\/telemetry$/);
  await startSession(page);
  if (info.project.name.includes("360")) await page.locator("footer").getByRole("link", { name: /Telemetry/ }).click();
  else await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Telemetry" }).click();
  await expect(page).toHaveURL(/\/telemetry$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("usage, cost and privacy");
});

test("per-consultation figures use only the metered consultations and say since when (#124)", async ({ page }) => {
  // 12 consultations in the period, but AI calls were metered only for the last 3 (metering began mid-period). #398:
  // the snapshot's per-consultation window holds those 3 consultations with their own 9 AI calls.
  await localSnapshot(page, { metered: { since: new Date(Date.now() - 3600_000).toISOString(), guided: 3, from: "2026-10-15T00:00:00Z",
    to: "2026-10-16T00:00:00Z", ai_calls: 9, with_token_counts: 9, prompt_tokens: 18000, completion_tokens: 2700, duration_ms_total: 90000,
    calls_with_energy: 9, wh_total: 0.9 } });
  await page.goto("/telemetry");
  await expect(page.getByLabel("Input tokens per consultation")).toHaveValue("6000"); // 18,000 / 3, not 60,000 / 3 or / 12
  await expect(page.getByLabel("Output tokens per consultation")).toHaveValue("900");
  await expect(page.locator(".kpi", { hasText: "Tokens processed" })).toContainText("counted since");
  await expect(page.getByText("so this covers the AI work from then on", { exact: false })).toBeVisible();
  await expect(page.locator(".calc-basis")).toContainText("15 Oct 2026, 00:00 UTC to now: the 9 AI calls of those hours ÷ the 3 consultations guided in the same hours");
});

test("whole-system power is stated as not measured, and an assumed wattage applies over measured AI time (#127)", async ({ page }) => {
  await localSnapshot(page);
  await page.goto("/telemetry");
  await expect(page.getByText("Whole-system power is", { exact: false })).toContainText("Not measured");
  await expect(page.getByText("the measured 25.0 s of AI time per consultation", { exact: false })).toBeVisible(); // 300 s / 12
  await expect(page.getByLabel("Other system power during AI calls")).toHaveValue("0");
  await page.getByLabel("Consultations per day").fill("500");
  await page.getByLabel("Other system power during AI calls").fill("30");
  // 0.2667 Wh GPU + 30 W × 25 s / 3600 = 0.475 Wh per consultation; × $0.1453/kWh × 500 × 30.44 ≈ $1.05 per month.
  await expect(page.getByText("(0.475 Wh per consultation in total)", { exact: false })).toBeVisible();
  await expect(page.locator(".kpi", { hasText: "This device per month" })).toContainText("+ $1.05 electricity");
  await expect(page.locator("section", { has: page.getByRole("heading", { name: "Sources and assumptions" }) }))
    .toContainText("Other (non-GPU) system power during AI calls");
});

test("the figures export as a self-contained slide (SVG and PNG), built on the device (#129)", async ({ page }) => {
  const offenders = guardNetwork(page);
  await localSnapshot(page);
  await page.goto("/telemetry");
  await page.getByLabel("Cloud API to compare with").selectOption("frontier");
  await page.getByLabel("Consultations per day").fill("500");
  await expect(page.getByRole("img", { name: /Slide preview: Aware Care telemetry, Last 7 days/ })).toBeVisible();
  const [svgDownload] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download SVG" }).click()]);
  expect(svgDownload.suggestedFilename()).toMatch(/^aware-care-telemetry-\d{4}-\d{2}-\d{2}\.svg$/);
  const svg = readFileSync((await svgDownload.path())!, "utf8");
  for (const s of ["Aware Care: local AI on the HP ZGX Nano", "Measured", "Estimated",
    "At 500 consultations per day (assumed),", "Claude Sonnet 5.5", "Healthcare outcomes are not measured",
    "0 bytes of patient data sent off the device", "GPT-6 Astra"])
    expect(svg, s).toContain(s);
  expect(svg).toContain("data:image/svg+xml;base64,"); // the HP logo is embedded, not linked
  expect(svg).not.toMatch(/(href|src)="https?:/);
  expect(svg).not.toMatch(/url\(\s*['"]?https?:/);
  const [pngDownload] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download PNG" }).click()]);
  expect(pngDownload.suggestedFilename()).toMatch(/\.png$/);
  const png = readFileSync((await pngDownload.path())!);
  expect(png.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([3200, 1800]); // 1600×900 at 2×
  expect(offenders).toEqual([]);
});

test("the slide names an estimated device price as an estimate, a list price as a list price (#145)", async ({ page }) => {
  const svgText = async () => {
    const [d] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download SVG" }).click()]);
    return readFileSync((await d.path())!, "utf8");
  };
  await localSnapshot(page);
  await page.goto("/telemetry");
  expect(await svgText()).toContain("list price; electricity"); // the Nano's reviewed HP Store price
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await page.route("**/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    t.pricing.assumptions.device_price_usd = { value: 100000, label: "HP ZGX Fury G1n AI Station: estimate. HP has published no list price" };
    await route.fulfill({ response, json: t });
  });
  await page.goto("/telemetry");
  const svg = await svgText();
  expect(svg).toContain("Device $100,000 estimated price; electricity");
  expect(svg).not.toContain("$100,000 list price");
});

test("the slide never cuts a figure's detail; the metering date sits in the cost note (#132)", async ({ page }) => {
  await localSnapshot(page, { metered: { since: new Date(Date.now() - 3600_000).toISOString(), guided: 3, from: "2026-10-15T00:00:00Z",
    to: "2026-10-16T00:00:00Z", ai_calls: 9, with_token_counts: 9, prompt_tokens: 18000, completion_tokens: 2700, duration_ms_total: 90000,
    calls_with_energy: 9, wh_total: 0.9 } });
  await page.goto("/telemetry");
  await expect(page.getByRole("img", { name: /Slide preview/ })).toBeVisible();
  const [d] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download SVG" }).click()]);
  const svg = readFileSync((await d.path())!, "utf8");
  expect(svg).not.toMatch(/counted since<\/text>/); // no detail line ends half-way
  expect(svg).toContain("AI calls metered since");
  expect(svg).not.toContain("(3 of 12 consultations)"); // #398: no count of consultations from another window
});

// #271: the concern check is shown in the task breakdown. #638: every figure counts up to now; #324: the breakdown
// sits with its window (an absolute start) in the Reliability section, not in the live AI-calls tile.
test("the task breakdown includes the concern check and the outcome window is stated", async ({ page }) => {
  await localSnapshot(page, { consultations: { guided: 12, repaired: null, fail_closed: null, urgent_routes: 6, busy_refusals: 0,
    suppressed_below: 5, counted_from: "2026-10-19T00:00:00Z", counted_to: "2026-10-26T01:00:00Z", counting_since: "2026-10-19T00:00:00Z",
    fail_closed_reasons: [] } });
  await page.goto("/telemetry");
  const rel = page.locator(".card", { has: page.getByRole("heading", { name: "Reliability and safety" }) });
  for (const [task, n] of [["Guidance", "14"], ["Red-flag screen", "12"], ["Safety review", "4"], ["Concern check", "3"]])
    await expect(rel.getByRole("row", { name: new RegExp(`AI calls by task: ${task}`) })).toContainText(n);
  await expect(rel.getByRole("heading", { level: 3 })).toHaveText("19 Oct 2026, 00:00 UTC to now");
  await expect(page.locator(".kpi", { hasText: "Consultations guided" })).toContainText("19 Oct 2026, 00:00 UTC to now");
  await expect(rel.getByText("These figures count up to now, including the current hour", { exact: false })).toBeVisible();
  await expect(page.locator("main")).not.toContainText("complete UTC day"); // before: "(complete UTC days)"
});

test("#638 the live mock-mode snapshot counts the last 7 days up to now, including the current hour", async ({ page }) => {
  const read = page.waitForResponse((r) => r.url().includes("/api/v1/telemetry") && r.status() === 200);
  await page.goto("/telemetry");
  const t = await (await read).json();
  const hour = Math.floor(Date.parse(t.generated_at) / 3_600_000) * 3_600_000;
  // Before: counted_to was 00:00 UTC today and counted_from 7 days before it.
  expect(Date.parse(t.consultations.counted_to)).toBe(hour + 3_600_000);
  expect(Date.parse(t.consultations.counted_from)).toBe(hour - 7 * 86_400_000);
  expect(t.ai_calls.counted_to).toBe(t.consultations.counted_to);
});

// #513: the slide embeds the bundled HP logo without a runtime fetch, so the page's security policy (connect-src 'self',
// which refuses a data: URL) never blocks it and no Content Security Policy error is logged.
test("#513 the slide carries the HP logo and the telemetry page logs no security-policy error", async ({ page }) => {
  const csp: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && /Content Security Policy|Refused to/i.test(m.text())) csp.push(m.text()); });
  await page.goto("/telemetry");
  await expect(page.locator("img.slide-preview")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download SVG" }).click();
  const svg = readFileSync(await (await download).path(), "utf8");
  expect(svg).toContain('<image x="60" y="44" width="64" height="64" href="data:image/svg+xml;base64,');
  expect(csp).toEqual([]);
});
