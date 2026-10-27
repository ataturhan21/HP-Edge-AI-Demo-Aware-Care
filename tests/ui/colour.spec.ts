// Colour design passes (#239-#248, #250-#259): a wider, contrast-checked palette (scripts/check_contrast.py) used by purpose.
// Colour is never the only signal: every hue sits beside a text label, number or icon that stays.
import { expect, test, type Locator } from "@playwright/test";
import { answerCurrent, enterConcern, startSession, startSessionOnly, toGuidance } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const css = (l: Locator, prop: string, pseudo?: string) =>
  l.evaluate((el, [p, ps]) => getComputedStyle(el, ps || null).getPropertyValue(p).trim(), [prop, pseudo ?? ""] as const);
const distinct = (values: string[]) => new Set(values).size;

test("#240 a brand gradient line closes the header and opens the footer, with a soft wash behind the hero", async ({ page }) => {
  await page.goto("/");
  expect(await css(page.locator(".site-header"), "background-image", "::after")).toContain("linear-gradient");
  expect(await css(page.locator(".footer"), "background-image", "::before")).toContain("linear-gradient");
  expect(await css(page.locator(".hero"), "background-image", "::before")).toContain("radial-gradient");
});

test("#241 the three home steps each have their own hue, an icon and their number", async ({ page }) => {
  await page.goto("/");
  const steps = page.locator(".steps li");
  await expect(steps).toHaveCount(3);
  const tops = [];
  for (let i = 0; i < 3; i++) {
    tops.push(await css(steps.nth(i), "border-top-color"));
    await expect(steps.nth(i).locator(".step-icon svg")).toHaveCount(1);
    expect(await css(steps.nth(i), "content", "::before")).toMatch(/counter|"\d"/);
  }
  expect(distinct(tops)).toBe(3);
});

test("#242 done steps turn teal with a check and the current step is filled blue", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  const steps = page.getByRole("navigation", { name: "Consultation steps" });
  const done = steps.locator("li.done .journey-num").first();
  const current = steps.locator("li.current .journey-num");
  if (await done.isVisible()) {
    await expect(done).toHaveText("✓");
    expect(await css(done, "border-top-color")).toBe("rgb(0, 137, 123)");
    expect(await css(current, "background-color")).not.toBe(await css(done, "background-color"));
  } else {
    expect(await css(steps.locator(".journey-bar i"), "background-image")).toContain("linear-gradient");
  }
});

test("#243 #244 the level of care has its own band and wash, and each guidance card its own accent and icon", async ({ page }) => {
  await toGuidance(page);
  const level = page.locator(".level-card");
  expect(await css(level, "border-top-width")).toBe("6px");
  expect(await css(level, "background-image")).toContain("linear-gradient");
  await expect(level.locator(".level-badge")).toBeVisible(); // the level is still named in text
  const cards = page.locator(".accent-card");
  await expect(cards).toHaveCount(4);
  const tops = [];
  for (let i = 0; i < 4; i++) {
    tops.push(await css(cards.nth(i), "border-top-color"));
    await expect(cards.nth(i).locator(".card-title .card-icon svg")).toHaveCount(1);
    await expect(cards.nth(i).locator(".card-title")).not.toHaveText("");
  }
  expect(distinct([...tops, await css(level, "border-top-color")])).toBe(5);
});

test("#245 scale numbers run cool to warm, keep their numerals, and the chosen one fills with its colour", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  // The scripted demo asks the 0-10 impact scale as question 3.
  for (const next of [2, 3]) {
    await answerCurrent(page, "answer");
    await expect(page.getByText(`Question ${next} of up to 10`, { exact: true })).toBeVisible();
  }
  const options = page.locator(".scale-option");
  const n = await options.count();
  expect(n).toBeGreaterThan(2);
  const colours = [];
  for (let i = 0; i < n; i++) colours.push(await css(options.nth(i), "border-top-color"));
  expect(distinct(colours)).toBe(n);
  await expect(options.first()).toHaveText(/^\d+$/);
  await options.nth(n - 1).locator("input").check({ force: true });
  await expect(options.nth(n - 1)).toHaveClass(/selected/);
  expect(await css(options.nth(n - 1), "background-color")).toBe(colours[n - 1]);
  expect(await css(options.nth(n - 1), "color")).toBe("rgb(255, 255, 255)");
});

test("#246 history statuses are coloured chips with an icon and their words", async ({ page }) => {
  await toGuidance(page);
  await page.goto("/app/history");
  const chip = page.locator(".chip").first();
  await expect(chip).toHaveText("Guidance ready");
  await expect(chip.locator("svg")).toHaveCount(1);
  expect(await css(chip, "background-color")).not.toBe("rgba(0, 0, 0, 0)");
});

test("#247 doctor cards take a hue per rank, and confirmed and unknown facts carry marks", async ({ page }) => {
  await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await page.getByLabel("Insurance plan").selectOption("Demo Health PPO");
  await page.getByRole("button", { name: "Find matches" }).click();
  const cards = page.locator("article.provider");
  await expect(cards).toHaveCount(3);
  const edges = [];
  for (let i = 0; i < 3; i++) edges.push(await css(cards.nth(i), "border-left-color"));
  expect(distinct(edges)).toBe(3);
  const confirmed = cards.first().locator(".facts-confirmed li").first();
  const unknown = cards.first().locator(".facts-unknown li").first();
  expect(await css(confirmed, "content", "::before")).toContain("✓");
  expect(await css(unknown, "content", "::before")).toContain("?");
  await expect(cards.first().getByRole("heading", { name: "Confirmed" })).toBeVisible(); // headings still say which is which
});

test("#248 telemetry tiles and presenter scenarios get distinct accents", async ({ page }) => {
  await page.goto("/telemetry");
  const kpis = page.locator(".kpi-grid .kpi");
  await expect(kpis.first()).toBeVisible();
  const tops = [];
  for (let i = 0; i < Math.min(5, await kpis.count()); i++) tops.push(await css(kpis.nth(i), "border-top-color"));
  expect(distinct(tops)).toBe(tops.length);
  await page.goto("http://127.0.0.1:15174/presenter/scenarios/more"); // #358: the full journeys' view
  await page.getByRole("button", { name: "Start presenter session" }).click();
  const cards = page.locator(".scenario-card");
  await expect(cards).toHaveCount(6);
  const accents = [];
  for (let i = 0; i < 6; i++) accents.push(await css(cards.nth(i), "border-top-color"));
  expect(distinct(accents)).toBe(6);
});

// ── Second pass (#250-#259) ──────────────────────────────────────────────────────────────────────────────────────

const PRESENTER = "http://127.0.0.1:15174";
const ROSE = "rgb(200, 51, 111)";
const GREEN = "rgb(30, 142, 90)";

async function distinctTops(cards: Locator, n: number) {
  await expect(cards).toHaveCount(n);
  const tops = [];
  for (let i = 0; i < n; i++) tops.push(await css(cards.nth(i), "border-top-color"));
  expect(distinct(tops)).toBe(n);
}

test("#250 #251 eyebrows start with a gradient bar and primary buttons are a gradient; secondary buttons stay plain", async ({ page }) => {
  await page.goto("/help");
  expect(await css(page.locator(".eyebrow").first(), "background-image", "::before")).toContain("linear-gradient");
  expect(await css(page.getByRole("main").getByRole("link", { name: "Start a new consultation" }), "background-image")).toContain("linear-gradient");
  // #475: /help offers "My consultations" only with an open session; A01's Decline is the plain secondary button here.
  await page.goto("/app/start");
  expect(await css(page.getByRole("button", { name: "Decline" }), "background-image")).toBe("none");
});

test("#252 How it works: coloured steps with icons, and the example's choices as chips", async ({ page }) => {
  await page.goto("/how-it-works");
  const steps = page.locator(".steps-grid .accent-card");
  await distinctTops(steps, 3);
  for (let i = 0; i < 3; i++) await expect(steps.nth(i).locator(".step-icon svg")).toHaveCount(1);
  await expect(steps.nth(0).getByRole("heading")).toHaveText("1. Describe one concern");
  await expect(page.locator(".example-choices li")).toHaveText(["Within the last week", "One to four weeks ago", "More than a month ago", "Not sure"]);
});

test("#253 each stakeholder has its own hue and icon, and Not measured is a chip", async ({ page }) => {
  await page.goto("/healthcare");
  const who = page.locator(".stakeholder");
  await expect(who).toHaveText(["Patients", "Clinicians", "Health systems", "Payers"]);
  const tiles = [];
  for (let i = 0; i < 4; i++) {
    await expect(who.nth(i).locator("svg")).toHaveCount(1);
    tiles.push(await css(who.nth(i).locator(".card-icon"), "background-color"));
  }
  expect(distinct(tiles)).toBe(4);
  await expect(page.locator("td .chip")).toHaveCount(4);
  await expect(page.locator("td .chip").last()).toHaveText("Not measured — savings are a hypothesis");
});

test("#254 privacy cards have accents and icons; an open FAQ item is tinted and its chevron turns", async ({ page }) => {
  await page.goto("/privacy");
  const cards = page.locator(".accent-card");
  await distinctTops(cards, 4);
  for (let i = 0; i < 4; i++) await expect(cards.nth(i).locator(".card-title svg")).toHaveCount(1);
  await page.goto("/help");
  const item = page.locator(".faq details").first();
  expect(await css(item, "background-color")).toBe("rgba(0, 0, 0, 0)");
  await item.locator("summary").click();
  await expect(item.getByText("No. Aware Care is a demonstration using fictional data.", { exact: false })).toBeVisible();
  expect(await css(item, "background-color")).not.toBe("rgba(0, 0, 0, 0)");
  expect(await css(item.locator(".faq-chevron"), "transform")).not.toBe("none");
});

test("#255 the consent panel is violet until the terms are accepted, then green with a check", async ({ page }) => {
  await page.goto("/app/start");
  const panel = page.locator(".consent-box");
  await expect(panel).toHaveClass(/acc-violet/);
  const before = await css(panel, "background-color");
  await page.getByRole("checkbox", { name: /I understand and accept these terms/ }).check();
  await expect(panel).toHaveClass(/acc-green/);
  expect(await css(panel, "background-color")).not.toBe(before);
  await expect(panel.getByRole("heading", { name: "Please read and agree" })).toBeVisible();
});

test("#256 a ticked warning sign turns rose; a ticked None of these apply turns green", async ({ page }) => {
  await startSession(page);
  const sign = page.locator(".choice", { hasText: "A seizure" });
  await page.getByRole("checkbox", { name: "A seizure" }).check();
  // The choice's border animates (unless reduced motion is set), so wait for the final colour.
  await expect.poll(() => css(sign, "border-top-color")).toBe(ROSE);
  await page.getByRole("checkbox", { name: "None of these apply" }).check();
  await expect.poll(() => css(page.locator(".choice-exclusive"), "border-top-color")).toBe(GREEN);
  await expect.poll(() => css(sign, "border-top-color")).not.toBe(ROSE); // unticked by the exclusive choice
});

test("#257 the summary's sections have icon tiles and unanswered items stand out as slate tags", async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  const titles = page.locator(".paper .card-title");
  // #356: the suggested level of care sits before the questions (no doctor search here, so no doctors section).
  // #417: the preview shows every section the PDF prints, in the PDF's order.
  await expect(titles).toHaveText(["Main concern", "What you reported", "Unresolved or unknown details",
    "Suggested level of care", "Suggested next step", "Possible explanations", "Questions for a clinician",
    "When to seek help sooner", "Sources"]);
  const tiles = [];
  for (let i = 0; i < 8; i++) tiles.push(await css(titles.nth(i).locator(".card-icon"), "background-color"));
  expect(distinct(tiles)).toBe(8); // the content sections each have their own tile; Sources shares the explanations' slate
  const gap = page.locator(".datum.gap b").first();
  await expect(gap).toHaveText(/^Unknown/);
  expect(await css(gap, "background-color")).toBe("rgb(238, 243, 247)");
  expect(await css(gap, "text-decoration-line")).toBe("none");
  expect(await css(page.locator(".datum:not(.gap) b").first(), "background-color")).toBe("rgba(0, 0, 0, 0)");
});

test("#258 data settings and urgent help cards have accents and icons", async ({ page }) => {
  await startSessionOnly(page);
  await page.goto("/app/settings");
  await expect(page.locator(".accent-card.acc-sky .card-title")).toHaveText("Retention");
  await expect(page.locator(".accent-card.acc-rose .card-title")).toHaveText("Delete data");
  await startSession(page);
  await enterConcern(page, "Another fictional concern.");
  await answerCurrent(page, "answer");
  await page.getByRole("button", { name: "Simulate urgent answer" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  const todo = page.locator(".accent-card.acc-red");
  await expect(todo.locator(".card-title")).toHaveText("What to do");
  await expect(todo.locator(".card-title svg")).toHaveCount(1);
  await expect(page.locator(".accent-card.acc-slate .card-title")).toHaveText("Start a new consultation");
});

test("#259 runtime tiles take a hue, status by state in words, and each timing has a proportional bar", async ({ page }) => {
  await page.goto(`${PRESENTER}/presenter/runtime`);
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByText("Device inventory", { exact: true })).toBeVisible();
  await distinctTops(page.locator(".tiles .tile"), 3);
  const status = page.locator(".tiles .tile").nth(2);
  await expect(status).toContainText("Ready");
  expect(await css(status, "border-top-color")).toBe(GREEN);
  const rows = page.locator(".datum.timing");
  await expect(rows).toHaveCount(3); // #428: mock mode has no inference row (no model runs)
  await expect(rows.last()).toContainText(/Total\s*\d+ ms/);
  const track = await rows.last().locator(".timing-bar").boundingBox();
  const bar = await rows.last().locator(".timing-bar i").boundingBox();
  expect(bar && track && Math.abs(bar.width - track.width)).toBeLessThan(1); // the total fills its track
});
