import { writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { BASE, DEV, offDevice, OUT, TAG } from "./support/device";
// One-click presenter flows on a deployed device (#358, #367): from the home page's Presenter choice (#487, the one
// address), start the session and run
// each flow on the device AI; time from the Run click to the finished patient screen. Writes OUT_DIR/quick-flows.json
// (clicks to the first result, milliseconds per flow, outcome, off-device requests) and a screenshot per flow.
const FLOWS: [string, RegExp, string][] = [
  ["Guidance from the local AI", /\/guidance$/, "Your guidance"],
  ["Self-care guidance", /\/guidance$/, "Your guidance"],
  ["Urgent warning sign", /\/urgent$/, "Seek urgent help now"],
];
test(`deployed ${TAG}on the ZGX ${DEV}: three one-click flows run the device AI and land in the patient tab`, async ({ context }, info) => {
  test.skip(info.project.name.includes("360"), "timed once at 1440");
  test.setTimeout(420_000);
  const off = offDevice(context);
  const p = await context.newPage();
  let clicks = 0;
  await p.goto(`${BASE}/`);
  await p.getByRole("link", { name: "Open the presenter tools" }).click(); clicks++;
  await expect(p).toHaveURL(/\/presenter\/scenarios$/);
  const start = p.getByRole("button", { name: "Start presenter session" });
  await start.click(); clicks++;
  await expect(start).toBeHidden();
  await expect(p.getByText(`HP ZGX ${DEV} · AI ready`)).toBeVisible({ timeout: 30_000 });
  let tab: Page | null = null;
  const ms: Record<string, number> = {}; const outcome: Record<string, string> = {};
  for (const [title, url, heading] of FLOWS) {
    const before = tab ? tab.url() : "";
    const t0 = Date.now();
    await p.getByRole("button", { name: `Run on HP ZGX ${DEV}: ${title}` }).click(); if (title === FLOWS[0][0]) clicks++;
    // #548: the run shows in a dialog; "Open the result" opens the patient tab (one more click for the first result).
    const box = p.getByRole("dialog");
    const open = box.getByRole("button", { name: "Open the result" });
    const failed = box.getByText(/did not|failed|could not|Nothing was substituted/i);
    await expect(open.or(failed.first())).toBeVisible({ timeout: 240_000 });
    if (await open.isVisible()) {
      const popup: Promise<Page> | null = tab ? null : p.waitForEvent("popup");
      await open.click(); if (title === FLOWS[0][0]) clicks++;
      if (popup) tab = await popup;
    }
    const done = tab ? tab.getByRole("heading", { name: heading, exact: true }) : null;
    await expect.poll(async () => (tab !== null && tab.url() !== before && url.test(new URL(tab.url()).pathname) && await done!.isVisible().catch(() => false)) || (await failed.first().isVisible().catch(() => false)), { timeout: 240_000, intervals: [100] }).toBe(true);
    ms[title] = Date.now() - t0;
    const shown = done !== null && await done.isVisible();
    outcome[title] = shown ? `shown: ${new URL(tab!.url()).pathname.replace(/[0-9a-f-]{36}/, ":id")}` : `not shown: ${(await failed.first().innerText()).slice(0, 120)}`;
    if (shown) await expect(tab!).toHaveURL(url);
    if (tab) await tab.screenshot({ path: `${OUT}/flow-${title.toLowerCase().replace(/[^a-z]+/g, "-")}.png` });
    if (await box.isVisible()) await box.getByRole("button", { name: "Close" }).click();
  }
  await p.screenshot({ path: `${OUT}/flows-1440.png`, fullPage: true });
  const result = { device: DEV, clicks_to_first_result: clicks, run_to_result_ms: ms, outcome, off_device_requests: off.length };
  writeFileSync(`${OUT}/quick-flows.json`, JSON.stringify(result, null, 1));
  console.log(JSON.stringify(result));
  expect(off).toEqual([]);
});
