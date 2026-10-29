import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { answerAll, enterConcern, startSession } from "../ui/support/journey";
import { BASE, COST_BARS, cspErrors, DEV, escapeRegExp, MODEL, offDevice, OTHER, OUT, pdfHeadings, PRICE, SUMMARY_SECTIONS, TAG, width,
  ZRT_VERSION } from "./support/device";
// Deployed walk-through (#367; the release walk-through of #362 and earlier, moved into the repo). One device per run:
// DEVICE=Fury|Nano; MODEL, OUT_DIR, RELEASE optional (tests/devices/support/device.ts). Real model, no rewriting.

test(`deployed ${TAG}on the ZGX ${DEV}: device name, title, headers, landmarks, telemetry and slide; nothing off the device`, async ({ page }, info) => {
  test.setTimeout(120_000);
  const off = offDevice(page);
  const csp = cspErrors(page);
  const w = width(info.project.name);
  const res = await page.goto("/");
  const h = res!.headers();
  expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(h["content-security-policy"]).toContain("script-src 'self'");
  expect(h["x-frame-options"]).toBe("DENY");
  await expect(page).toHaveTitle(`Aware Care - Local AI Healthcare Demo on ZGX ${DEV} via ZRT`);
  await expect(page.getByRole("link", { name: /^HP Aware Care on .+, home$/ })).toContainText(`on HP ZGX ${DEV}`);
  await expect(page.getByTestId("local-ai-signature-strip")).toContainText(`HP ZGX ${DEV}`);
  await expect(page.getByText(new RegExp(`ZGX ${OTHER}`))).toHaveCount(0);
  await expect(page.getByRole("banner").getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.screenshot({ path: `${OUT}/home-${w}.png`, fullPage: false });
  await page.goto("/app/start");
  await expect(page).toHaveTitle(/Aware Care/);
  await page.addInitScript(() => localStorage.setItem("awarecare.telemetry.view", "advanced")); // #547: every figure
  await page.goto("/telemetry");
  await expect(page.getByRole("heading", { level: 1, name: `Local AI on the HP ZGX ${DEV}: usage, cost and privacy` })).toBeVisible();
  await page.getByRole("radio", { name: "Last 24 hours" }).click();
  await expect(page.getByText(new RegExp(`model ${escapeRegExp(MODEL)}`))).toBeVisible();
  await expect(page.getByText(new RegExp(`ZRT ${escapeRegExp(ZRT_VERSION)}`)).first()).toBeVisible();
  for (const label of COST_BARS)
    await expect(page.locator(".bars .bar-row", { hasText: label })).not.toContainText("Not measured");
  await expect(page.getByRole("region", { name: "Prices and assumptions table" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Slide preview/ })).toBeVisible();
  await page.screenshot({ path: `${OUT}/telemetry-${w}.png`, fullPage: true });
  if (w === 1440) {
    const [s] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download SVG" }).click()]);
    const svg = readFileSync((await s.path())!, "utf8");
    expect(svg).toContain(`Aware Care: local AI on the HP ZGX ${DEV}`);
    expect(svg).toContain(PRICE);
    expect(svg).not.toMatch(/(href|src)="https?:/);
    const [p] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download PNG" }).click()]);
    await p.saveAs(`${OUT}/slide-deployed.png`);
    const png = readFileSync(`${OUT}/slide-deployed.png`);
    expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([3200, 1800]);
  }
  expect(csp).toEqual([]);
  expect(off).toEqual([]);
});

test(`deployed ${TAG}on the ZGX ${DEV}: the presenter gateway sends the headers and sees live scenarios`, async ({ page }, info) => {
  // #487: the presenter tools are the /presenter/... pages of the one address, signed under /presenter-api/.
  test.skip(info.project.name.includes("360"), "once");
  const off = offDevice(page);
  const csp = cspErrors(page);
  const res = await page.goto(`${BASE}/presenter/scenarios`);
  expect(res!.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(res!.headers()["x-frame-options"]).toBe("DENY");
  // #487: the home page's Presenter choice opens the scenarios page (before, the presenter port's root did, #326).
  await page.goto(`${BASE}/`);
  await page.getByRole("link", { name: "Open the presenter tools" }).click();
  await expect(page).toHaveURL(/\/presenter\/scenarios$/);
  const ready = await page.request.get(`${BASE}/presenter-api/v1/health/ready`);
  expect(ready.headers()["x-awarecare-gateway"]).toBe("presenter");
  const forged = await page.request.get(`${BASE}/api/v1/presenter/runtime`, {
    headers: { "X-AwareCare-Presenter": ["v1", "0", "0".repeat(32), "0".repeat(64)].join(".") } });
  expect([401, 403]).toContain(forged.status()); // the patient API strips the header: never presenter data
  const start = page.getByRole("button", { name: "Start presenter session" });
  const main = page.getByRole("button", { name: /^Run on HP ZGX/ }).first();
  await expect(start.or(main)).toBeVisible({ timeout: 15_000 });
  if (await start.isVisible()) await start.click();
  // #358: Scenarios first; three one-click flows and one status line.
  await expect(page.getByText(`HP ZGX ${DEV} · AI ready`)).toBeVisible();
  await expect(page.locator(".flow-card")).toHaveCount(3);
  await page.screenshot({ path: `${OUT}/presenter-scenarios-1440.png`, fullPage: false });
  expect(csp).toEqual([]);
  expect(off).toEqual([]);
});

// #153: in local mode a warning sign written in the concern routes to urgent help when the case is created, before
// any question, with the reviewed level's message. Real model, no rewriting.
test(`deployed ${TAG}on the ZGX ${DEV}: a written emergency goes to urgent help before any question`, async ({ page }, info) => {
  test.skip(info.project.name.includes("360"), "once");
  test.setTimeout(90_000);
  const off = offDevice(page);
  await startSession(page);
  await page.getByLabel("Main concern").fill("Crushing chest pain spreading to my left arm, and I am sweating.");
  await page.getByRole("checkbox", { name: "None of these apply" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/urgent$/, { timeout: 30_000 });
  await expect(page.getByText("Emergency", { exact: true })).toBeVisible();
  await expect(page.getByText("Call 911 now or go to the nearest emergency department.", { exact: false })).toBeVisible();
  await page.screenshot({ path: `${OUT}/urgent-at-creation-1440.png`, fullPage: false });
  expect(off).toEqual([]);
});

// #154: text that describes no health matter is refused when the case is created; A03 asks for a health concern.
// Real model, no rewriting.
test(`deployed ${TAG}on the ZGX ${DEV}: a description with no health matter is refused on A03`, async ({ page }, info) => {
  test.skip(info.project.name.includes("360"), "once");
  test.setTimeout(90_000);
  const off = offDevice(page);
  await startSession(page);
  await page.getByLabel("Main concern").fill("asdf qwer zxcv uiop");
  await page.getByRole("checkbox", { name: "None of these apply" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("We could not find a health concern in this description.")).toBeVisible({ timeout: 30_000 });
  await expect(page).toHaveURL(/\/app\/new$/);
  await page.screenshot({ path: `${OUT}/not-health-refused-1440.png`, fullPage: false });
  expect(off).toEqual([]);
});

// #182-#191 on the device: the new aids through a whole consultation with the real model, at both widths.
test(`deployed ${TAG}on the ZGX ${DEV}: the consultation aids (#182-#191) through a real consultation`, async ({ page }, info) => {
  test.setTimeout(240_000);
  const off = offDevice(page);
  const csp = cspErrors(page);
  const w = width(info.project.name);
  const steps = page.getByRole("navigation", { name: "Consultation steps" });
  const notice = page.locator(".demo").first();
  // #189: one line on phones; the full notice in the accessibility tree at every width.
  await page.goto("/");
  expect(await notice.ariaSnapshot()).toContain("do not enter real health information");
  if (w === 360) expect((await notice.boundingBox())!.height).toBeLessThan(36);
  await startSession(page);
  // #182: Menu on phones, links in a row on wider screens.
  const nav = page.getByRole("navigation", { name: "Main" });
  if (w === 360) {
    await nav.getByRole("button", { name: "Menu" }).click();
    await expect(nav.getByRole("link", { name: "History" })).toBeVisible();
    await nav.getByRole("button", { name: "Menu" }).click();
  } else await expect(nav.getByRole("link", { name: "History" })).toBeVisible();
  // #183 and #184
  await expect(steps.locator('[aria-current="step"]')).toContainText("Concern");
  await page.getByRole("checkbox", { name: "A seizure" }).check();
  await expect(page.locator(".choice-feedback")).toHaveText("1 sign ticked. Continue will take you to urgent help.");
  await page.getByRole("checkbox", { name: "A seizure" }).uncheck();
  const caseId = await enterConcern(page, "A mild headache since Monday, worse in the evening.");
  await expect(steps.locator('[aria-current="step"]')).toContainText("Questions");
  await page.screenshot({ path: `${OUT}/ux-questions-${w}.png`, fullPage: false });
  await answerAll(page);
  await expect(steps.locator('[aria-current="step"]')).toContainText("Review");
  // #190 and #186
  await expect(page.locator("#generate-hint")).toHaveText("Tick the confirmation above to continue.");
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  const result = page.getByRole("heading", { name: "Your guidance", exact: true });
  await expect(page.locator(".generating-elapsed").or(result).first()).toBeVisible({ timeout: 30_000 });
  await expect(result.or(page.getByRole("heading", { level: 1, name: /urgent|limit/i })).first()).toBeVisible({ timeout: 120_000 });
  let outcome = "guided";
  if (await result.isVisible()) {
    // #187: the next steps directly under the level card, once.
    const next = page.getByRole("navigation", { name: "Next steps" });
    await expect(next.getByRole("link", { name: "Find appropriate care" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Find appropriate care" })).toHaveCount(1);
    expect((await next.boundingBox())!.y).toBeLessThan((await page.getByRole("heading", { name: "Possible explanations" }).boundingBox())!.y);
    await page.screenshot({ path: `${OUT}/ux-guidance-${w}.png`, fullPage: false });
  } else outcome = page.url();
  // #188: the history row names the consultation and the next step.
  await page.goto("/app/history");
  const row = page.locator("tbody tr").first();
  await expect(row).toContainText("A mild headache since Monday");
  await expect(row).toContainText(/Ends in /);
  if (outcome === "guided") await expect(row.getByRole("button", { name: "View guidance" })).toBeVisible();
  await page.screenshot({ path: `${OUT}/ux-history-${w}.png`, fullPage: false });
  // #191
  await page.addInitScript(() => localStorage.setItem("awarecare.telemetry.view", "advanced")); // #547: every figure
  await page.goto("/telemetry");
  await page.getByRole("navigation", { name: "On this page" }).getByRole("link", { name: "Sources" }).click();
  await expect(page.getByRole("heading", { name: "Sources and assumptions" })).toBeFocused();
  console.log(`ux ${DEV} ${w}: case ${caseId.slice(0, 8)} outcome ${outcome}`);
  expect(outcome).toBe("guided");
  expect(csp).toEqual([]);
  expect(off).toEqual([]);
});

// #194: an overdose written on A03 now goes to urgent help when the case is created (RF20, general-adult-4).
test(`deployed ${TAG}on the ZGX ${DEV}: an overdose written in the concern goes to urgent help at creation`, async ({ page }, info) => {
  test.skip(info.project.name.includes("360"), "once");
  test.setTimeout(90_000);
  const off = offDevice(page);
  await startSession(page);
  await expect(page.getByRole("checkbox", { name: "Took too much of a medicine, or swallowed something poisonous" })).toBeVisible();
  await page.getByLabel("Main concern").fill("I took twenty paracetamol tablets about an hour ago.");
  await page.getByRole("checkbox", { name: "None of these apply" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/urgent$/, { timeout: 30_000 });
  await expect(page.getByText("Call 911 now or go to the nearest emergency department.", { exact: false })).toBeVisible();
  await page.screenshot({ path: `${OUT}/overdose-at-creation-1440.png`, fullPage: false });
  expect(off).toEqual([]);
});

// #212, #215, #220: the start screen states guest mode; a scale answer shows its range; an open session is offered.
test(`deployed ${TAG}on the ZGX ${DEV}: start, scale range and the way back to an open session`, async ({ page }, info) => {
  test.setTimeout(180_000);
  const off = offDevice(page);
  const w = width(info.project.name);
  await page.goto("/app/start");
  await expect(page.getByRole("heading", { name: "You'll continue as a guest" })).toBeVisible();
  await startSession(page);
  await enterConcern(page, "A mild headache since Monday, worse in the evening.");
  await answerAll(page);
  await expect(page.getByRole("heading", { name: "Review your case" })).toBeVisible();
  await expect(page.getByText(/on a 0–10 scale/).first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/review-scale-${w}.png`, fullPage: false });
  // #688: the home page always starts fresh; the open session is under My consultations, and A01 offers it.
  await page.goto("/");
  await expect(page.getByRole("link", { name: "My consultations" })).toBeVisible();
  await page.goto("/app/start");
  await expect(page.getByText("Your guest session is still open")).toBeVisible();
  expect(off).toEqual([]);
});

// #239-#259 and #261-#305 on the device: colours, truthful copy, the telemetry outcome window, a real PDF.
test(`deployed ${TAG}on the ZGX ${DEV}: colours, truthful copy, telemetry outcome window and the PDF`, async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const off = offDevice(page);
  const csp = cspErrors(page);
  const w = width(info.project.name);
  const css = (sel: string, prop: string, pseudo?: string) =>
    page.locator(sel).first().evaluate((el, [p, ps]) => getComputedStyle(el, ps || null).getPropertyValue(p), [prop, pseudo ?? ""] as const);
  // #240, #250, #251: brand line, eyebrow bar, primary button gradient.
  await page.goto("/how-it-works");
  expect(await css(".site-header", "background-image", "::after")).toContain("linear-gradient");
  expect(await css(".eyebrow", "background-image", "::before")).toContain("linear-gradient");
  expect(await css(".btn:not(.secondary)", "background-image")).toContain("linear-gradient");
  // #291: no early-finish promise in local mode.
  await expect(page.getByText("It may finish sooner")).toHaveCount(0);
  // #292: the privacy page lists the 90-day AI usage counts.
  await page.goto("/privacy");
  await expect(page.getByText(/90 days/)).toBeVisible();
  // #638, #324: every figure counts up to now, from an absolute start, never "yesterday".
  await page.goto("/telemetry");
  await expect(page.getByText(/UTC to now/).first()).toBeVisible();
  await expect(page.getByText(/yesterday/i)).toHaveCount(0);
  const t = await (await request.get("/api/v1/telemetry?period=24h")).json();
  expect(Date.parse(t.consultations.counted_to)).toBeGreaterThan(Date.parse(t.generated_at)); // the current hour counts
  // A real consultation with the local model.
  await startSession(page);
  const caseId = await enterConcern(page, "A mild headache since Monday, worse in the evening.");
  await expect(page.getByText(/up to 10 in all/)).toBeVisible(); // #291
  await answerAll(page);
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 150_000 });
  // #243, #244: the level card band and four accented section cards.
  expect(await css(".level-card", "border-top-width")).toBe("6px");
  await expect(page.locator(".accent-card")).toHaveCount(4);
  await page.screenshot({ path: `${OUT}/colours-guidance-${w}.png`, fullPage: false });
  // #257, #279, #265: summary tiles, a fresh export, a PDF with WinAnsi fonts.
  await page.goto(`/app/cases/${caseId}/summary`);
  // #417 (#493): the preview shows every section the PDF prints, 9 without a doctor search (before #417: 5 cards).
  const titles = page.locator(".paper .card-title");
  await expect(titles).toHaveText(SUMMARY_SECTIONS);
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).click();
  const link = page.getByRole("link", { name: /Download summary/ });
  await expect(link).toBeVisible({ timeout: 60_000 });
  const dl = await page.request.get((await link.getAttribute("href"))!); // the page's session cookie
  expect(dl.status()).toBe(200);
  const pdf = await dl.body();
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  expect(pdf.toString("latin1").split("/Encoding /WinAnsiEncoding").length - 1).toBe(2);
  // The app's own section list: the PDF's headings are the preview's titles, in the same order (#417).
  expect(pdfHeadings(pdf)).toEqual((await titles.allTextContents()).map((t) => t.trim()));
  await page.screenshot({ path: `${OUT}/summary-pdf-${w}.png`, fullPage: false });
  // #290: ending the session says the data is being deleted, not that it was.
  await page.goto("/app/settings");
  await page.getByRole("button", { name: "End session and delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "End session" }).click();
  await expect(page.getByText(/being deleted/)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${OUT}/session-ended-${w}.png`, fullPage: false });
  expect(csp).toEqual([]);
  expect(off).toEqual([]);
});
