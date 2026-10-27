// #570 (QA bug hunt #556): an hour-only log row is labelled with the hour it covers in the viewer's time zone. In a zone
// whose offset is not a whole hour (UTC+05:30), the stored hour 20:00-20:59 UTC is 01:30-02:29 local, not "01:xx".
import { expect, test, type Page } from "@playwright/test";

const snapshot = () => ({
  observed_at: new Date().toISOString(), mode: "local", readiness: "ready", queue_depth: 0, active_jobs: 0, truncated: false,
  next_before: null, level_counts: { ok: 1, warn: 0, fail: 0, info: 0 }, total: 1,
  entries: [{ id: "model:1", at: "2026-10-26T20:00:00Z", precision: "hour", level: "ok", kind: "model", source: "model_call",
    name: "guidance", status: "ok", code: null, duration_ms: 9_800, reasons: null, reason: null, detail: [] }],
});

async function logsIn(page: Page) {
  await page.route("**/presenter-api/v1/presenter/logs*", (route) => route.fulfill({ json: snapshot() }));
  await page.goto("/presenter/runtime?view=logs");
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.locator(".log-row")).toHaveCount(1);
  return page.locator(".log-row .log-time");
}

test.describe("in a half-hour time zone", () => {
  test.use({ timezoneId: "Asia/Kolkata" });
  test("#570 an hour-only row shows the local range it covers", async ({ page }) => {
    await expect(await logsIn(page)).toHaveText("01:30–02:29");
  });
});

test.describe("in a whole-hour time zone", () => {
  test.use({ timezoneId: "America/Denver" });
  test("#570 an hour-only row keeps hh:xx", async ({ page }) => {
    await expect(await logsIn(page)).toHaveText("14:xx");
  });
});
