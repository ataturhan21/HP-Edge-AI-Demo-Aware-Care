// Accessibility (R34 screens; #158): axe-core 4.10.3 scans all 25 routes, the 22 public/patient routes and the 3
// presenter routes (with a presenter session) on the one address (#487), at 1440 and 360 px, for WCAG 2.0/2.1 A and AA and
// axe best practices. Any violation fails, with its rule, impact and first target.
// Registered as a shared UI test in spec/traceability.yaml.
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { animationsSettled, answerCurrent, enterConcern, startSession, toGuidance } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));
// The gateway policy (#157) rightly forbids injected inline scripts; only this test tool is injected, so the policy is
// bypassed for this spec alone (tests/ui/routes.layout.spec.ts checks the product under the policy).
test.use({ bypassCSP: true });

// The pinned devDependency of apps/web (axe-core 4.10.3); the specs run from apps/web with its node_modules.
const AXE = join(__dirname, "../../apps/web/node_modules/axe-core/axe.min.js");

async function violations(page: Page, route: string) {
  await page.goto(route);
  await expect(page.locator("h1").first(), route).toBeVisible();
  await page.waitForTimeout(250);
  await page.addScriptTag({ path: AXE });
  await animationsSettled(page);
  return page.evaluate(async () => {
    // @ts-expect-error axe is injected above
    const result = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } });
    return result.violations.map((v: { id: string; impact: string; nodes: { target: string[] }[] }) =>
      `${v.id} (${v.impact}) ${v.nodes.length}× e.g. ${v.nodes[0]?.target.join(" ")}`);
  });
}

test("every route passes axe at its width (WCAG 2.1 AA and best practice)", { tag: "@mobile" }, async ({ page }, info) => {
  test.setTimeout(240_000);
  const caseId = await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await page.getByRole("button", { name: "Find matches" }).click();
  await page.getByRole("link", { name: "Inspect doctor" }).first().click();
  const providerId = page.url().split("/doctors/")[1];
  await page.goto("/app/new");
  const urgentCase = await enterConcern(page, "Another fictional concern.");
  await answerCurrent(page, "answer");
  await page.getByRole("button", { name: "Simulate urgent answer" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  const routes = [
    "/", "/how-it-works", "/healthcare", "/privacy", "/help", "/telemetry", "/app/start", "/app/profile", "/app/new",
    `/app/cases/${caseId}/records`, `/app/cases/${caseId}/questions`, `/app/cases/${caseId}/review`,
    `/app/cases/${caseId}/guidance`, `/app/cases/${caseId}/sources`, `/app/cases/${caseId}/preferences`,
    `/app/cases/${caseId}/doctors`, `/app/cases/${caseId}/doctors/${providerId}`, `/app/cases/${caseId}/summary`,
    "/app/history", "/app/settings", `/app/cases/${urgentCase}/urgent`, "/app/limits",
  ];
  expect(routes).toHaveLength(22);
  const found: string[] = [];
  for (const route of routes) for (const v of await violations(page, route)) found.push(`${route.replace(/[0-9a-f-]{36}/g, ":id")} @${info.project.name}: ${v}`);
  const presenter = await page.context().newPage();
  await presenter.goto("http://127.0.0.1:15174/presenter/runtime");
  await presenter.getByRole("button", { name: "Start presenter session" }).click();
  for (const route of ["runtime", "controls", "scenarios"])
    for (const v of await violations(presenter, `http://127.0.0.1:15174/presenter/${route}`)) found.push(`/presenter/${route} @${info.project.name}: ${v}`);
  expect(found, found.join("\n")).toEqual([]);
});

// #595 (WCAG 2.5.3 Label in Name): the shared brand link's accessible name contains its visible text, "Aware Care on
// <device>", on the public, app and presenter shells. axe's label-content-name-mismatch rule is experimental, so the
// default scan above does not run it; it runs here by name.
test("#595 the brand home link's accessible name contains its visible label on every shell", { tag: "@mobile" }, async ({ page }) => {
  const labelInName = async (route: string) => {
    const brand = page.locator("a.brand").first();
    await expect(brand, route).toBeVisible();
    const visible = (await brand.innerText()).replace(/\s+/g, " ").trim();
    expect(visible, route).toBe("Aware Care on HP ZGX Nano");
    // The link found by its visible label is the brand link.
    await expect(page.getByRole("link", { name: visible }), route).toHaveAttribute("class", /\bbrand\b/);
    await page.addScriptTag({ path: AXE });
    const found = await page.evaluate(async () => {
      // @ts-expect-error axe is injected above
      const result = await window.axe.run(document, { runOnly: { type: "rule", values: ["label-content-name-mismatch"] } });
      return result.violations.map((v: { id: string; nodes: { target: string[] }[] }) => `${v.id} ${v.nodes[0]?.target.join(" ")}`);
    });
    expect(found, route).toEqual([]);
  };
  await page.goto("/");
  await labelInName("/");
  await page.goto("/app/start");
  await labelInName("/app/start");
  await page.goto("http://127.0.0.1:15174/presenter/runtime");
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByRole("button", { name: "Start presenter session" })).toBeHidden();
  await labelInName("/presenter/runtime");
  // Home navigation still works from the brand.
  await page.locator("a.brand").first().click();
  await expect(page).toHaveURL(/\/presenter\/scenarios$/);
});
