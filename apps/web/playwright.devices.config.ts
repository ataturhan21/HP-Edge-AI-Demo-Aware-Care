// Device specs (tests/devices, #367): a deployed release on the HP ZGX Fury or Nano, reached through an SSH tunnel or
// forwarder on loopback: the one address http://127.0.0.1:18180 of patients and presenters (#487; Wiki
// Release and Deployment, Presenter access). No web server is started and no mock stack is involved; the specs drive
// the device's real app and model with synthetic text only, and fail on any request that is not to 127.0.0.1.
// Run from apps/web:  DEVICE=Fury|Nano [MODEL=<manifest id>] [OUT_DIR=<folder>] [RELEASE=<tag>] npm run test:device
// Results, screenshots and report.json go to OUT_DIR (default test-results/devices/<device>). The mock suite
// (playwright.config.ts, testDir tests/ui) never picks these up.
import { defineConfig, devices } from "@playwright/test";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const device = process.env.DEVICE ?? "";
if (device !== "Fury" && device !== "Nano") throw new Error("Set DEVICE=Fury or DEVICE=Nano for the device specs (tests/devices).");
const out = resolve(process.env.OUT_DIR ?? process.env.SHOT_DIR ?? join(dirname(fileURLToPath(import.meta.url)), "test-results/devices", device.toLowerCase()));
process.env.OUT_DIR = out; // the specs' helper reads the same folder

export default defineConfig({
  testDir: "../../tests/devices",
  outputDir: "./test-results/devices/artifacts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  reporter: [["list"], ["json", { outputFile: join(out, "report.json") }]],
  use: { baseURL: "http://127.0.0.1:18180", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile-360", use: { ...devices["Desktop Chrome"], viewport: { width: 360, height: 780 }, hasTouch: true } },
  ],
});
