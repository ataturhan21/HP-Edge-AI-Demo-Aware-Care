// W01 Home (R01, R37). Public, labeled synthetic; starts consultation; readiness is public and minimal.
import { expect, test } from "@playwright/test";
import { apiCalls, expectNoHorizontalOverflow, guardNetwork, startSessionOnly } from "./support/journey";

test("home explains the demo and starts a consultation", async ({ page }) => {
  const offenders = guardNetwork(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Understand your concern and find the right care." })).toBeVisible();
  await expect(page.getByRole("note").first()).toContainText("fictional people and doctors only");
  await expect(page.getByText("The consultation service is unavailable right now.")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await page.getByRole("main").getByRole("link", { name: "Start a new consultation" }).click();
  await expect(page).toHaveURL(/\/app\/start$/);
  expect(offenders).toEqual([]);
});

test("unavailable readiness is shown truthfully with help still reachable", async ({ page }) => {
  await page.route("**/api/v1/health/ready", (r) => r.fulfill({ status: 503, contentType: "application/json",
    body: JSON.stringify({ readiness: "unavailable" }) }));
  await page.goto("/");
  await expect(page.getByText("The consultation service is unavailable right now.")).toBeVisible();
  await page.getByRole("link", { name: "Open help and urgent-care information" }).click();
  await expect(page).toHaveURL(/\/help$/);
});

// #437 (QA 2026-10-22, T-04): W01 validation rule: do not assert local inference is active in mock mode.
test("#437 in mock mode the home page says no language model runs; in local mode it names the device's model", async ({ page }) => {
  await page.goto("/");
  const panel = page.locator(".hero-panel");
  await expect(panel).toContainText("Mock mode: no language model runs"); // this suite runs in mock mode
  await expect(panel).not.toContainText("The language model runs on the");
  await page.route("**/api/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    await route.fulfill({ response, json: { ...t, identity: { ...t.identity, mode: "local" } } });
  });
  await page.goto("/");
  await expect(panel).toContainText("The language model runs on the HP ZGX Nano");
  await expect(panel).not.toContainText("Mock mode");
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

// #487 (ADR-005 amendment): one address for both roles. The home page offers two large choices, Patient and Presenter,
// at 1440 and 360 px (both projects), by pointer, keyboard and screen reader.
test("#487 the home page offers Patient and Presenter as two large choices", { tag: "@mobile" }, async ({ page }, info) => {
  const offenders = guardNetwork(page);
  const calls = apiCalls(page);
  await page.goto("/");
  const choice = page.getByRole("region", { name: "How would you like to use Aware Care?" });
  await expect(choice).toBeVisible();
  const patient = choice.getByRole("article", { name: "Patient" });
  const presenter = choice.getByRole("article", { name: "Presenter" });
  await expect(patient.getByRole("heading", { level: 3, name: "Patient" })).toBeVisible();
  await expect(presenter.getByRole("heading", { level: 3, name: "Presenter" })).toBeVisible();
  await expect(patient.getByRole("link")).toHaveCount(1); // one named link per card
  await expect(presenter.getByRole("link")).toHaveCount(1);
  await expect(patient.getByRole("link", { name: "Start a new consultation" })).toHaveAttribute("href", "/app/start");
  await expect(presenter.getByRole("link", { name: "Open the presenter tools" })).toHaveAttribute("href", "/presenter/scenarios");
  // Large: each card is a big target; side by side on a wide screen, stacked on a phone.
  const [a, b] = [(await patient.boundingBox())!, (await presenter.boundingBox())!];
  const width = page.viewportSize()!.width;
  if (info.project.name.includes("360")) {
    expect(a.width).toBeGreaterThan(width - 2 * 16 - 2);
    expect(b.y).toBeGreaterThan(a.y + a.height - 1);
  } else {
    expect(Math.abs(a.y - b.y)).toBeLessThanOrEqual(1);
    expect(a.width).toBeGreaterThan(400);
    expect(a.height).toBeGreaterThan(280);
  }
  // The demo notice, urgent help and the local-AI signature stay on the page.
  await expect(page.getByRole("note").first()).toContainText("fictional people and doctors only");
  await expect(page.getByRole("link", { name: "Emergency help" })).toBeVisible();
  await expect(page.getByTestId("local-ai-signature-strip")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  // The whole Presenter card follows its link for a pointer; the presenter tools open at Scenarios (quick flows).
  await presenter.click({ position: { x: 24, y: 24 } }); // the card's corner, away from its link
  await expect(page).toHaveURL(/\/presenter\/scenarios$/);
  await expect(page.getByRole("heading", { level: 1, name: "Demo scenarios" })).toBeVisible();
  expect(calls.some((c) => c.startsWith("/presenter-api/")), "the presenter page uses the presenter API").toBe(true);
  await page.goBack();
  await expect(page.getByRole("region", { name: "How would you like to use Aware Care?" })).toBeVisible();
  calls.length = 0; // from here on: the home page again and the patient start
  await page.getByRole("region", { name: "How would you like to use Aware Care?" }).getByRole("article", { name: "Patient" })
    .click({ position: { x: 24, y: 24 } });
  await expect(page).toHaveURL(/\/app\/start$/);
  expect(offenders).toEqual([]);
  // Back on the home page and on the patient start: never the presenter API.
  expect(calls.filter((c) => c.startsWith("/presenter-api/")), calls.join(", ")).toEqual([]);
});

test("#487 the two choices work by keyboard with visible focus", async ({ page }) => {
  await page.goto("/");
  const choice = page.getByRole("region", { name: "How would you like to use Aware Care?" });
  const start = choice.getByRole("link", { name: "Start a new consultation" });
  const tools = choice.getByRole("link", { name: "Open the presenter tools" });
  await expect(start).toBeVisible();
  await start.focus();
  await expect(start).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(tools).toBeFocused(); // the next stop after the patient choice is the presenter choice
  expect(await tools.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe("none"); // visible focus
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/presenter\/scenarios$/);
  await page.goBack();
  await page.getByRole("region", { name: "How would you like to use Aware Care?" })
    .getByRole("link", { name: "Start a new consultation" }).press("Enter");
  await expect(page).toHaveURL(/\/app\/start$/);
});

test("#487 with an open consultation the patient choice continues it", async ({ page }) => {
  await startSessionOnly(page);
  await page.goto("/");
  const patient = page.getByRole("region", { name: "How would you like to use Aware Care?" }).getByRole("article", { name: "Patient" });
  await expect(patient.getByRole("link", { name: "Continue consultation" })).toBeVisible();
});

// #487: the role of every request follows its page, including reloads and deep links.
test("#487 a patient page never calls the presenter API, and a presenter page only the presenter API", async ({ page }) => {
  const calls = apiCalls(page);
  await startSessionOnly(page);
  for (const path of ["/app/history", "/app/settings", "/help", "/telemetry", "/"]) {
    await page.goto(path); // deep link
    await expect(page.locator("h1").first()).toBeVisible();
  }
  await page.reload();
  await expect(page.locator("h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(calls.length).toBeGreaterThan(3);
  expect(calls.filter((c) => !c.startsWith("/api/v1/")), calls.join(", ")).toEqual([]);
  calls.length = 0;
  await page.goto("/presenter/runtime");
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByText("Device inventory", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Device inventory", { exact: true })).toBeVisible(); // the presenter session survives a reload
  await page.goto("/presenter/scenarios/more"); // deep link
  await expect(page.locator(".scenario-card").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(calls.length).toBeGreaterThan(3);
  expect(calls.filter((c) => !c.startsWith("/presenter-api/v1/")), calls.join(", ")).toEqual([]);
});
