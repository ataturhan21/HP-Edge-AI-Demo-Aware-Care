import { writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
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
test(`deployed ${TAG}on the ZGX ${DEV}: three one-click flows run the device AI and show the Demo patient`, async ({ context }, info) => {
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
  const ms: Record<string, number> = {}; const outcome: Record<string, string> = {};
  for (const [title, url, heading] of FLOWS) {
    const t0 = Date.now();
    await p.getByRole("button", { name: `Run on HP ZGX ${DEV}: ${title}` }).click(); if (title === FLOWS[0][0]) clicks++;
    // #548: the run shows in a dialog; #688: "Open the result" shows it in this window as the Demo patient (one more
    // click for the first result), and "Back to presenter" returns.
    const box = p.getByRole("dialog");
    const open = box.getByRole("button", { name: "Open the result" });
    const failed = box.getByText(/did not|failed|could not|Nothing was substituted/i);
    await expect(open.or(failed.first())).toBeVisible({ timeout: 240_000 });
    if (await open.isVisible()) {
      await open.click(); if (title === FLOWS[0][0]) clicks++;
      const done = p.getByRole("heading", { name: heading, exact: true });
      const shown = await expect.poll(async () => url.test(new URL(p.url()).pathname) && await done.isVisible().catch(() => false),
        { timeout: 240_000, intervals: [100] }).toBe(true).then(() => true, () => false);
      ms[title] = Date.now() - t0;
      outcome[title] = shown ? `shown: ${new URL(p.url()).pathname.replace(/[0-9a-f-]{36}/, ":id")}` : `not shown: ${new URL(p.url()).pathname}`;
      await p.screenshot({ path: `${OUT}/flow-${title.toLowerCase().replace(/[^a-z]+/g, "-")}.png` });
      await p.getByTestId("mode-strip").getByRole("link", { name: "Back to presenter" }).click();
      await expect(p).toHaveURL(/\/presenter\/scenarios$/);
    } else {
      ms[title] = Date.now() - t0;
      outcome[title] = `not shown: ${(await failed.first().innerText()).slice(0, 120)}`;
      await box.getByRole("button", { name: "Close" }).click();
    }
  }
  await p.screenshot({ path: `${OUT}/flows-1440.png`, fullPage: true });
  const result = { device: DEV, clicks_to_first_result: clicks, run_to_result_ms: ms, outcome, off_device_requests: off.length };
  writeFileSync(`${OUT}/quick-flows.json`, JSON.stringify(result, null, 1));
  console.log(JSON.stringify(result));
  expect(off).toEqual([]);
});
