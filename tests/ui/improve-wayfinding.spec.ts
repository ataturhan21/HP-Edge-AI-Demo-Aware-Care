// Wayfinding (#339, #340, #345; CHG-DEV-UI-006), on the isolated mock stack at 1440 and 360 px:
// - #339 an unknown address or a screen that fails to render keeps the layout (header, "Emergency help", footer)
//   and offers ways on; no developer text, no stack trace, no substitute result.
// - #340 one resume target (the most recently changed consultation's current screen), used by Help, the home and A01
//   banners and the public header and hero, which say "Continue consultation" while a guest session is open.
// - #345 one name, "Start a new consultation", for every action that starts one.
// Registered as a shared UI test in spec/traceability.yaml.
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { animationsSettled, answerAll, answerCurrent, enterConcern, guardNetwork, startSession, startSessionOnly, toGuidance } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const PRESENTER = "http://127.0.0.1:15174";
const START = "Start a new consultation";
const CONTINUE = "Continue consultation";
const DEVELOPER_TEXT = /Unexpected Application Error|Hey developer|errorElement|TypeError|Cannot read|at [A-Za-z]+ \(|\.js:\d+/;

/** Opens the phone Menu when the navigation is collapsed, so header links can be checked as visible. */
async function openMenu(page: Page) {
  const menu = page.getByRole("banner").getByRole("button", { name: "Menu" });
  if ((await menu.isVisible()) && (await menu.getAttribute("aria-expanded")) === "false") await menu.click();
}

/** The layout around a page: header with its navigation, the emergency strip link, the footer. */
async function expectLayout(page: Page, nav: "Main" | "Presenter") {
  await expect(page.getByRole("banner").getByRole("navigation", { name: nav })).toBeAttached();
  await expect(page.getByRole("banner").getByRole("link", { name: "Emergency help" })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toBeVisible();
}

test("#339 an unknown public address shows a not-found page in the site layout with ways on", async ({ page }) => {
  const offenders = guardNetwork(page);
  for (const path of ["/telemetri", "/no/such/page"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await expectLayout(page, "Main");
    const main = page.getByRole("main");
    await expect(main).not.toContainText(DEVELOPER_TEXT);
    await expect(main.getByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "/");
    await expect(main.getByRole("link", { name: START })).toHaveAttribute("href", "/app/start");
    await expect(main.getByRole("link", { name: "Help and urgent care" })).toHaveAttribute("href", "/help");
    // Not the presenter gateway: no presenter link.
    await expect(main.getByRole("link", { name: "Presenter scenarios" })).toHaveCount(0);
  }
  await page.getByRole("main").getByRole("link", { name: "Go to the home page" }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(offenders).toEqual([]);
});

test("#339 an unknown patient address keeps the app layout and offers the open consultation", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  const question = page.url();
  for (const path of ["/app/case", "/app/cases/not-a-case/somewhere"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await expectLayout(page, "Main");
    await expect(page.getByRole("banner").getByRole("link", { name: "History", includeHidden: true })).toBeAttached(); // the app navigation
    await expect(page.getByRole("navigation", { name: "Consultation steps" })).toHaveCount(0);
  }
  await page.getByRole("main").getByRole("link", { name: CONTINUE }).click();
  await expect(page).toHaveURL(question);
  await expect(page.getByText(/^Question \d+ of up to 10$/)).toBeVisible();
});

// #487: one address; the presenter layout's not-found page always offers the scenarios page, the other layouts never.
test("#339 an unknown presenter address offers the scenarios page on the presenter gateway only", async ({ page }) => {
  await page.goto(`${PRESENTER}/presenter/nothing-here`);
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await expectLayout(page, "Presenter");
  const main = page.getByRole("main");
  await expect(main.getByRole("link", { name: "Presenter scenarios" })).toHaveAttribute("href", "/presenter/scenarios");
  await expect(main.getByRole("link", { name: "Go to the home page" })).toBeVisible();
  await main.getByRole("link", { name: "Presenter scenarios" }).click();
  await expect(page).toHaveURL(`${PRESENTER}/presenter/scenarios`);
  await page.goto("/presenter");
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await expectLayout(page, "Presenter");
  await expect(page.getByRole("main").getByRole("link", { name: "Go to the home page" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "Presenter scenarios" })).toHaveCount(1);
  await page.goto("/telemetri");
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "Presenter scenarios" })).toHaveCount(0);
});

test("#339 a screen that fails to render shows a calm error page in the layout with Reload and ways on", async ({ page }) => {
  // A malformed case list makes History throw while rendering (a defect stand-in; the real server never sends it).
  await page.route("**/api/v1/cases", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: null, next_cursor: null }) }));
  await page.goto("/app/history");
  await expect(page.getByRole("heading", { level: 1, name: "This page could not be shown" })).toBeVisible();
  await expectLayout(page, "Main");
  const main = page.getByRole("main");
  await expect(main).not.toContainText(DEVELOPER_TEXT);
  await expect(main).not.toContainText(/guidance is|AI-generated|scripted|Consultation history/i);
  await expect(main.getByRole("button", { name: "Reload" })).toBeVisible();
  await expect(main.getByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "/");
  await expect(main.getByRole("link", { name: START })).toBeVisible();
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await main.getByRole("button", { name: "Reload" }).click();
  // Without a session the reloaded History sends the visitor to the start page.
  await expect(page.getByRole("heading", { level: 1, name: "Before you begin" })).toBeVisible();
});

test("#339 a page whose code fails to load shows the same error page in the public layout", async ({ page }) => {
  await page.route(/\/assets\/W06-[\w-]+\.js$/, (route) => route.abort());
  await page.goto("/telemetry");
  await expect(page.getByRole("heading", { level: 1, name: "This page could not be shown" })).toBeVisible();
  await expectLayout(page, "Main");
  await expect(page.getByRole("main")).not.toContainText(DEVELOPER_TEXT);
  await expect(page.getByRole("main").getByRole("button", { name: "Reload" })).toBeVisible();
});

test("#339 the not-found and error pages pass axe (WCAG 2.1 AA and best practice)", async ({ browser }) => {
  const context = await browser.newContext({ bypassCSP: true, viewport: test.info().project.use.viewport ?? undefined });
  const page = await context.newPage();
  const AXE = join(__dirname, "../../apps/web/node_modules/axe-core/axe.min.js");
  const scan = async (url: string, heading: string) => {
    await page.goto(url);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await page.waitForTimeout(250);
    await page.addScriptTag({ path: AXE });
    await animationsSettled(page);
    return page.evaluate(async () => {
      // @ts-expect-error axe is injected above
      const result = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] } });
      return result.violations.map((v: { id: string; impact: string; nodes: { target: string[] }[] }) =>
        `${v.id} (${v.impact}) ${v.nodes.length}× e.g. ${v.nodes[0]?.target.join(" ")}`);
    });
  };
  const base = "http://127.0.0.1:15174";
  expect(await scan(`${base}/telemetri`, "Page not found"), "public not found").toEqual([]);
  expect(await scan(`${base}/app/case`, "Page not found"), "app not found").toEqual([]);
  expect(await scan(`${PRESENTER}/presenter/nothing-here`, "Page not found"), "presenter not found").toEqual([]);
  await page.route("**/api/v1/cases", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: null, next_cursor: null }) }));
  expect(await scan(`${base}/app/history`, "This page could not be shown"), "error page").toEqual([]);
  await context.close();
});

test("#340 Help's way back opens the open question, in one tap", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  const question = page.url();
  await page.goto("/help");
  const back = page.getByRole("main").getByRole("link", { name: CONTINUE });
  await expect(back).toBeVisible();
  await back.click();
  await expect(page).toHaveURL(question);
  await expect(page.getByText(/^Question \d+ of up to 10$/)).toBeVisible();
});

test("#340 the public header says Continue consultation only while a session is open; #688 the home hero always starts fresh", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await openMenu(page);
  const banner = page.getByRole("banner");
  const hero = page.getByRole("main").locator(".role-patient"); // #487: the home page's Patient choice
  await expect(banner.getByRole("link", { name: START })).toBeVisible();
  await expect(banner.getByRole("link", { name: START })).toHaveAttribute("href", "/app/start");
  await expect(hero.getByRole("link", { name: START })).toHaveAttribute("href", "/app/start");
  await expect(page.getByRole("link", { name: CONTINUE })).toHaveCount(0);
  await expect(page.getByText("Your guest session is still open")).toHaveCount(0);

  await startSession(page);
  await enterConcern(page);
  const question = new URL(page.url()).pathname;
  for (const path of ["/", "/how-it-works", "/help"]) {
    await page.goto(path); // a reload: the app has forgotten the session in memory
    await openMenu(page);
    await expect(banner.getByRole("link", { name: CONTINUE })).toBeVisible();
    await expect(banner.getByRole("link", { name: CONTINUE })).toHaveAttribute("href", question);
    await expect(banner.getByRole("link", { name: START })).toHaveCount(0);
  }
  await page.goto("/");
  await expect(hero.getByRole("link", { name: START })).toHaveAttribute("href", "/app/start"); // #688: always fresh
  await expect(hero.getByRole("link", { name: CONTINUE })).toHaveCount(0);
  await expect(page.locator(".resume-session")).toHaveCount(0);
  await expect(hero.getByRole("link", { name: "My consultations" })).toHaveAttribute("href", "/app/history");
  await openMenu(page);
  await banner.getByRole("link", { name: CONTINUE }).click();
  await expect(page).toHaveURL(new RegExp(`${question}$`));
});

test("#340 the A01 banner follows the consultation to its current screen; without one it opens a new consultation", async ({ page }) => {
  await startSessionOnly(page);
  await page.getByRole("button", { name: "Use for this session" }).click();
  await expect(page).toHaveURL(/\/app\/new$/);
  await page.goto("/app/start");
  const resume = page.locator(".resume-session").getByRole("link", { name: CONTINUE });
  await expect(resume).toHaveAttribute("href", "/app/new");
  await page.goto("/app/new");
  const caseId = await enterConcern(page);
  await page.goto("/app/start");
  await expect(resume).toHaveAttribute("href", `/app/cases/${caseId}/questions`);
  await page.goto(`/app/cases/${caseId}/questions`);
  await answerAll(page);
  await page.goto("/app/start");
  await expect(resume).toHaveAttribute("href", `/app/cases/${caseId}/review`);
  await resume.click();
  await expect(page.getByRole("heading", { name: "Review your case" })).toBeVisible();
});

test("#345 every action that starts a consultation is called Start a new consultation", async ({ page }) => {
  test.setTimeout(120_000);
  const OLD = /^(Start consultation|New concern|Start another case|Start a different case|Start again|Describe a concern|Start a new concern|Return to consultation|Continue your consultation)$/;
  const STARTS = /\b(start consultation|start a new consultation|start another case|start a different case|start again|new concern|describe a concern|new consultation)\b/i;
  const seen = new Set<string>();
  const old: string[] = [];
  async function collect(where: string) {
    await openMenu(page);
    for (const text of await page.locator("a:visible, button:visible").allInnerTexts()) {
      const t = text.replace(/\s+/g, " ").trim();
      if (OLD.test(t)) old.push(`${where}: ${t}`);
      if (STARTS.test(t)) seen.add(t);
    }
  }
  // No session: home (header and hero), How it works, Help, limits.
  for (const path of ["/", "/how-it-works", "/help", "/app/limits"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("main").getByRole("link", { name: START }).first()).toBeVisible();
    await collect(path);
  }
  // In the app: the navigation and History's empty state.
  await startSession(page);
  await page.goto("/app/history");
  await expect(page.getByRole("heading", { name: "No consultations yet" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: START })).toHaveAttribute("href", "/app/new");
  await collect("A13 empty");
  // Urgent (A15).
  await page.goto("/app/new");
  await enterConcern(page, "A fictional concern that becomes urgent.");
  await answerCurrent(page, "answer");
  await page.getByRole("button", { name: "Simulate urgent answer" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  await expect(page.getByRole("main").getByRole("link", { name: START })).toHaveAttribute("href", "/app/new");
  await collect("A15");
  // Guidance (A07) and the summary (A12).
  const caseId = await toGuidance(page);
  await expect(page.getByRole("main").getByRole("link", { name: START })).toHaveAttribute("href", "/app/new");
  await collect("A07");
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.getByRole("main").getByRole("link", { name: START })).toBeVisible();
  await collect("A12");
  expect(old, "old start or resume labels").toEqual([]);
  expect([...seen]).toEqual([START]);
});
