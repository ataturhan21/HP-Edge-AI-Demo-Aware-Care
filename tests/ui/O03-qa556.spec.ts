// #556 QA bug hunt, O03 quick flows: a failed run's Try again says why it cannot run now instead of doing nothing
// (#568), and the flow card gives the same plain-words reason as the dialog (#569). Mock stack, shown as local.
import { expect, test, type Page } from "@playwright/test";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const DEVICE = "HP ZGX Nano";
const WHY = "The first draft was rejected: a statement was judged to rule out a risk (a stated fact). Nothing was published.";

async function failingSelfCare(page: Page, readiness: { value: string }) {
  await page.route("**/presenter-api/v1/presenter/runtime", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), mode: "local", readiness: readiness.value } });
  });
  await page.route("**/v1/jobs/*", async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    await route.fulfill({ response, json: job.kind === "scenario_prepare" && job.status !== "running"
      ? { ...job, status: "failed", error_code: "OUTPUT_VALIDATION_FAILED", error_reason: WHY, result_id: null, result_type: null }
      : job });
  });
  await page.goto("/presenter/scenarios");
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await page.getByRole("button", { name: `Run on ${DEVICE}: Self-care guidance` }).click();
  await expect(page.getByRole("dialog")).toContainText("Not shown", { timeout: 30_000 });
}

test("#568 Try again in a failed run's dialog is disabled with the reason when the device is not ready", async ({ page }) => {
  const readiness = { value: "ready" };
  await failingSelfCare(page, readiness);
  const box = page.getByRole("dialog");
  await expect(box.getByRole("button", { name: "Try again" })).toBeEnabled();
  readiness.value = "degraded";
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  const again = box.getByRole("button", { name: "Try again" });
  await expect(again).toBeDisabled();
  await expect(again).toHaveAccessibleDescription(/^Try again waits until the device is ready \(the device is .+\)\.$/);
  // Ready again: Try again is offered again.
  readiness.value = "ready";
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(again).toBeEnabled();
});

test("#569 the flow card gives the same plain-words reason as the dialog", async ({ page }) => {
  await failingSelfCare(page, { value: "ready" });
  await expect(page.getByRole("dialog")).toContainText(WHY);
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  const status = page.locator(".flow-card", { has: page.getByRole("heading", { name: "Self-care guidance", exact: true }) })
    .locator(".flow-status");
  await expect(status).toContainText(WHY);
});
