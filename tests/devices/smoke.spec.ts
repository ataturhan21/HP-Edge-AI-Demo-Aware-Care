import { writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { answerAll, enterConcern } from "../ui/support/journey";
import { DEV, offDevice, OUT, TAG } from "./support/device";
// Release smoke (ADR-019): about three minutes per device, once at 1440. One patient
// consultation from the home page's Patient choice to the device AI's guidance, and every presenter Quick flow on the
// device AI (#538: only the first ran before, so the Self-care flow failed on the Nano through three releases unseen).
// Each flow must land on its result screen; one that ends "not shown" fails the smoke. Synthetic text only; fails on
// any request that is not to 127.0.0.1. Writes OUT_DIR/smoke-<name>.json.

// The presenter's Quick flows (O03's FLOWS): the card title, the patient-tab path and heading of its result.
const QUICK_FLOWS: [string, RegExp, string][] = [
  ["Guidance from the local AI", /\/guidance$/, "Your guidance"],
  ["Self-care guidance", /\/guidance$/, "Your guidance"],
  ["Urgent warning sign", /\/urgent$/, "Seek urgent help now"],
];

const result = (name: string, values: Record<string, unknown>) =>
  writeFileSync(`${OUT}/smoke-${name}.json`, JSON.stringify({ device: DEV, ...values }, null, 1));

test(`smoke ${TAG}on the ZGX ${DEV}: a patient consultation from the home page reaches the device AI's guidance`, async ({ page }, info) => {
  test.skip(info.project.name.includes("360"), "once at 1440");
  test.setTimeout(180_000);
  const off = offDevice(page);
  const t0 = Date.now();
  await page.goto("/");
  await page.locator(".role-patient").getByRole("link").click();
  await expect(page).toHaveURL(/\/app\/start$/);
  await page.getByLabel("Yes, I am 18 or older").check();
  await page.getByLabel("I understand and accept these terms.").check();
  await page.getByRole("button", { name: "Accept and begin" }).click();
  await page.getByRole("button", { name: "Use for this session" }).click();
  await expect(page).toHaveURL(/\/app\/new$/);
  await enterConcern(page, "A mild headache since Monday, worse in the evening.");
  await answerAll(page);
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 120_000 });
  result("patient", { outcome: "guidance shown", ms: Date.now() - t0, off_device_requests: off.length });
  expect(off).toEqual([]);
});

test(`smoke ${TAG}on the ZGX ${DEV}: every presenter Quick flow runs the device AI and lands on its result`, async ({ context }, info) => {
  test.skip(info.project.name.includes("360"), "once at 1440");
  test.setTimeout(420_000);
  const off = offDevice(context);
  const p = await context.newPage();
  await p.goto("/");
  await p.getByRole("link", { name: "Open the presenter tools" }).click();
  await p.getByRole("button", { name: "Start presenter session" }).click();
  await expect(p.getByText(`HP ZGX ${DEV} · AI ready`)).toBeVisible({ timeout: 30_000 });
  const flows: Record<string, { outcome: string; ms: number }> = {};
  for (const [title, path, heading] of QUICK_FLOWS) {
    const t0 = Date.now();
    await p.getByRole("button", { name: `Run on HP ZGX ${DEV}: ${title}` }).click();
    // #548: the run shows in a dialog; #688: "Open the result" shows it in this window as the Demo patient (no tab).
    const box = p.getByRole("dialog");
    const open = box.getByRole("button", { name: "Open the result" });
    const failed = box.getByText(/did not|failed|could not|Nothing was substituted/i);
    await expect(open.or(failed.first())).toBeVisible({ timeout: 150_000 });
    let outcome: string;
    if (await open.isVisible()) {
      await open.click();
      const done = p.getByRole("heading", { name: heading, exact: true });
      const landed = await expect.poll(async () => path.test(new URL(p.url()).pathname) &&
        await done.isVisible().catch(() => false), { timeout: 150_000, intervals: [250] }).toBe(true).then(() => true, () => false);
      outcome = landed ? "shown" : `not shown: ${new URL(p.url()).pathname}`;
      await p.getByTestId("mode-strip").getByRole("link", { name: "Back to presenter" }).click();
      await expect(p).toHaveURL(/\/presenter\/scenarios$/);
    } else {
      outcome = `not shown: ${(await failed.first().innerText()).slice(0, 160)}`;
      await box.getByRole("button", { name: "Close" }).click();
    }
    flows[title] = { ms: Date.now() - t0, outcome };
  }
  const shown = Object.values(flows).every((f) => f.outcome === "shown");
  result("presenter", { outcome: shown ? "all Quick flows shown" : "a Quick flow failed", flows, off_device_requests: off.length });
  // #538: every flow must show its result; the release fails otherwise.
  expect(Object.fromEntries(Object.entries(flows).map(([t, f]) => [t, f.outcome]))).toEqual(
    Object.fromEntries(QUICK_FLOWS.map(([t]) => [t, "shown"])));
  expect(off).toEqual([]);
});
