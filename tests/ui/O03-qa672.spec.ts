// #672 QA bug hunt (presenter usage), O03: an earlier result stays open when the next quick flow runs (#673),
// a quick flow outlives a brief network failure (#675), and a reset that never reached the device says so (#676).
// Mock stack.
import { expect, test, type Page } from "@playwright/test";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const DEVICE = "HP ZGX Nano";

async function startPresenter(page: Page) {
  await page.goto("/presenter/scenarios");
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByRole("heading", { name: "Guidance from the local AI" })).toBeVisible();
}

async function runFlow(page: Page, title: string) {
  await page.getByRole("button", { name: `Run on ${DEVICE}: ${title}` }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Open the result" })).toBeVisible({ timeout: 30_000 });
}

/** #688: Open the result shows the result in this window as the Demo patient; returns its address. */
async function openResult(page: Page): Promise<string> {
  await page.getByRole("dialog").getByRole("button", { name: "Open the result" }).click();
  await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/guidance$/);
  await expect(page.getByRole("heading", { name: "Your guidance", level: 1 })).toBeVisible();
  return page.url();
}
const backToPresenter = (page: Page) =>
  page.getByTestId("mode-strip").getByRole("link", { name: "Back to presenter" }).click();

test("#673 the first result stays open when the next quick flow runs", async ({ page }) => {
  await startPresenter(page);
  await runFlow(page, "Guidance from the local AI");
  const guidance = await openResult(page);

  await backToPresenter(page);
  await runFlow(page, "Self-care guidance");
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  // Show again: the first result, under the same demo patient session.
  const patient = page;
  await page.locator(".flow-card", { hasText: "Guidance from the local AI" }).getByRole("link", { name: "Show again" }).click();
  await expect(patient).toHaveURL(guidance);
  const sources = patient.waitForResponse((r) => r.url().endsWith("/sources") && r.request().method() === "GET");
  await patient.getByRole("link", { name: "Sources" }).click();
  expect((await sources).status()).toBe(200);
  await expect(patient.getByRole("heading", { name: "Where the guidance comes from", level: 1 })).toBeVisible();
  await expect(patient).toHaveURL(guidance.replace(/\/guidance$/, "/sources"));
  await expect(patient.getByText("Your session ended")).toHaveCount(0);
});

test("#675 a quick flow outlives a few seconds without the network and shows its result", async ({ page }) => {
  await startPresenter(page);
  let offline = true;
  await page.route("**/presenter-api/v1/jobs/*", (route) => (offline ? route.abort("internetdisconnected") : route.fallback()));
  await page.getByRole("button", { name: `Run on ${DEVICE}: Guidance from the local AI` }).click();
  const box = page.getByRole("dialog");
  await expect(box).toBeVisible();
  await page.waitForTimeout(2_500);
  await expect(box.getByText("Not shown", { exact: true })).toHaveCount(0);
  offline = false;
  await expect(box.getByRole("button", { name: "Open the result" })).toBeVisible({ timeout: 30_000 });
  await expect(box).toContainText("Guidance is ready");
});

test("#676 a reset that never reached the device says so and moves nothing", async ({ page }) => {
  await startPresenter(page);
  await runFlow(page, "Guidance from the local AI");
  await openResult(page);
  await backToPresenter(page);
  const shown = page.locator(".flow-card", { hasText: "Guidance from the local AI" }).getByRole("link", { name: "Show again" });
  await expect(shown).toBeVisible();

  await page.goto("/presenter/scenarios/more");
  await page.route("**/presenter-api/v1/presenter/reset", (route) => route.abort("internetdisconnected"));
  await page.getByRole("button", { name: "Clear demos for the next audience" }).click();
  const reset = page.locator("section.card", { has: page.getByRole("heading", { name: "Between audiences", exact: true }) });
  await expect(reset.getByText("This step did not complete")).toBeVisible();
  await expect(reset).toContainText("could not be reached");
  await expect(page.getByText("Demos cleared: ready for the next audience")).toHaveCount(0);
  // Nothing moved: the run is still kept for the Scenarios page (IDs and states only, per tab).
  expect(await page.evaluate(() => sessionStorage.getItem("aware-care:o03-runs"))).toContain('"kind":"done"');

  // The device answers again: Try again runs the reset.
  await page.unroute("**/presenter-api/v1/presenter/reset");
  await reset.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Demos cleared: ready for the next audience")).toBeVisible();
  await expect(reset.getByText("This step did not complete")).toHaveCount(0);
  await page.goto("/presenter/scenarios");
  await expect(page.locator(".flow-card").first()).toBeVisible();
  await expect(shown).toHaveCount(0); // cleared
});
