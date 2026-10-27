// #556 QA bug hunt, W06 telemetry: keyboard focus after "Show every figure", truthful payback and cost sentences,
// bounded calculator fields and chart labels that stay inside the plot. Runs on the mock stack's own telemetry.
import { expect, test, type Page } from "@playwright/test";
import { costMessage, outcomes } from "../../apps/web/src/screens/W06Cost";
import { usd } from "../../apps/web/src/screens/W06Slide";

const VIEW_KEY = "awarecare.telemetry.view";

async function openAdvanced(page: Page) {
  await page.addInitScript((k) => { try { localStorage.setItem(k, "advanced"); } catch { /* none */ } }, VIEW_KEY);
  await page.goto("/telemetry");
  await expect(page.getByLabel("Consultations per day")).toBeVisible();
}

test("#561 Show every figure (Advanced) moves keyboard focus to the advanced view", async ({ page }) => {
  await page.addInitScript((k) => { try { localStorage.setItem(k, "basic"); } catch { /* none */ } }, VIEW_KEY);
  await page.goto("/telemetry");
  const button = page.getByRole("button", { name: "Show every figure (Advanced)" });
  await button.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 2, name: "Usage" })).toBeFocused();
});

test("#572 the device never pays for itself when the cloud API is not dearer per consultation", async ({ page }) => {
  await openAdvanced(page);
  await page.getByLabel("GPU energy per consultation").fill("0.5");
  await page.getByLabel("Electricity price").fill("1000");
  const payback = page.locator(".kpi", { hasText: "Device pays for itself" });
  await expect(payback.locator(".kpi-value")).toHaveText("Never");
  await page.getByLabel("Consultations per day").fill("2000");
  await expect(payback.locator(".kpi-value")).toHaveText("Never");
  // A positive margin that is too small at this volume still says so.
  await page.getByLabel("Electricity price").fill("0.15");
  await page.getByLabel("Consultations per day").fill("0");
  await expect(payback.locator(".kpi-value")).toHaveText("Not at this volume");
});

test("#573 a calculator entry too large to compute is refused, never shown as ∞ or NaN", async ({ page }) => {
  await openAdvanced(page);
  const field = page.getByLabel("Consultations per day");
  await field.fill("1e308");
  await expect(page.getByText("Enter 1,000,000,000,000,000 or less.", { exact: false })).toBeVisible();
  await expect(field).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("main")).not.toContainText("∞");
  await expect(page.locator("main")).not.toContainText("NaN");
});

for (const width of [1440, 360]) {
  test(`#571 at low volume the chart's labels stay inside the plot (${width} px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openAdvanced(page);
    await page.getByLabel("Consultations per day").fill("1");
    const chart = page.locator("svg.breakeven-chart");
    await expect(chart.locator(".end-label")).toHaveCount(4);
    const boxes = await chart.evaluate((svg) => {
      const box = (el: Element) => { const b = (el as SVGGraphicsElement).getBBox(); return { top: b.y, bottom: b.y + b.height, left: b.x, right: b.x + b.width }; };
      const months = [...svg.querySelectorAll("text.axis")].filter((t) => / mo$/.test(t.textContent ?? "")).map(box);
      const ticks = [...svg.querySelectorAll("text.axis")].filter((t) => t.textContent?.startsWith("$")).map(box);
      const note = [...svg.querySelectorAll("text.chart-note")].map(box);
      return { labels: [...svg.querySelectorAll(".end-label")].map(box), months, ticks, note };
    });
    const axisTop = Math.min(...boxes.months.map((b) => b.top));
    for (const l of boxes.labels) expect(l.bottom, "an end label sits above the month labels").toBeLessThanOrEqual(axisTop);
    for (let i = 1; i < boxes.labels.length; i++) expect(boxes.labels[i].top).toBeGreaterThanOrEqual(boxes.labels[i - 1].bottom - 1);
    const overlap = (a: { top: number; bottom: number; left: number; right: number }, b: typeof a) =>
      a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    for (const n of boxes.note) for (const t of boxes.ticks) expect(overlap(n, t), "the chart note clears the tick labels").toBe(false);
  });
}

test("#574 unit: the cost sentence keeps a fractional volume and its plural", () => {
  const ref = [{ id: "astra", label: "GPT-6 Astra (frontier API)", cloudPer: 0.2 }];
  for (const [perDay, words] of [[0.5, "at 0.5 consultations a day"], [1, "at 1 consultation a day"], [2.5, "at 2.5 consultations a day"]] as const) {
    const s = { device: 7699, localPer: 0.00005, perDay, months: 36 };
    expect(costMessage({ localPer: s.localPer, outcomes: outcomes(s, ref), defaultId: "astra", s, usd })).toContain(words);
  }
});
