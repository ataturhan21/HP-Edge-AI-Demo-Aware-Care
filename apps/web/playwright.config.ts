// Browser acceptance tests (tests/ui). Runs an isolated stack: its own API on 127.0.0.1:18000
// (mock mode, throwaway data dir, origin allowlist = the test web origin) and one production
// build served by `vite preview` on 127.0.0.1:15174, the one gateway of both roles as deployed
// (#487, ADR-005 amendment): /api is the patient API and /presenter-api the presenter API, signed
// with a throwaway key. It never touches the dev servers
// on 8000/5173 or contacts ZRT. #66: the Vite dev server intermittently stalled on module requests
// mid-suite (a file watcher on the folder Playwright writes to, and two servers sharing one
// dependency-optimizer cache); a production build per server has neither, and is what the
// deployed gateway serves.
// Run from apps/web: `npm run test:ui`.
import { defineConfig, devices } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const WEB = "http://127.0.0.1:15174";
const API = "http://127.0.0.1:18000";
// The runner creates the throwaway directory; workers inherit it through the environment. #94: the process that
// created it removes it when it exits (pass or fail). A directory passed in AWARECARE_UI_DATA_DIR is never removed,
// and AWARECARE_UI_KEEP_DATA=1 keeps a created one for debugging. Test results and traces stay in ./test-results.
const created = !process.env.AWARECARE_UI_DATA_DIR;
const dataDir = process.env.AWARECARE_UI_DATA_DIR ?? mkdtempSync(join(tmpdir(), "aware-care-ui-"));
process.env.AWARECARE_UI_DATA_DIR = dataDir;
if (created && process.env.AWARECARE_UI_KEEP_DATA !== "1")
  process.on("exit", () => rmSync(dataDir, { recursive: true, force: true }));
// Throwaway presenter key for the isolated stack only (config is evaluated by the runner and each worker).
const presenterKey = join(dataDir, "presenter-test.key");
if (!existsSync(presenterKey)) writeFileSync(presenterKey, randomBytes(32).toString("hex"), { mode: 0o600 });

// The build goes outside the Vite root, so the server never reads files Playwright is writing.
const build = (port: number) => {
  const out = join(dataDir, `web-${port}`);
  return `npx vite build --logLevel warn --emptyOutDir --outDir ${out} && npx vite preview --outDir ${out}`;
};

export default defineConfig({
  testDir: "../../tests/ui",
  outputDir: "./test-results/ui",
  // #509: tests are independent (own browser context and guest session; a demo reset only removes its own presenter's
  // demo patients), so CI shards split per test rather than per file. CI runs one worker per shard (its own runner);
  // locally two workers share the one isolated stack (AWARECARE_UI_WORKERS overrides).
  fullyParallel: true,
  workers: process.env.CI ? 1 : Number(process.env.AWARECARE_UI_WORKERS ?? 2),
  retries: 0,
  timeout: 60_000,
  reporter: [["list"], ["json", { outputFile: "./test-results/ui-report.json" }]],
  use: { baseURL: WEB, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    // #509: phone width only where it matters (layout, the menu, overflow, touch targets, one full journey): tests
    // tagged @mobile. routes.layout.spec.ts still sweeps every route at 360, 390, 768 and 1440 px on desktop-1440.
    { name: "mobile-360", grep: /@mobile/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 360, height: 780 }, hasTouch: true } },
  ],
  webServer: [
    {
      command: "uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 18000",
      cwd: "../api",
      url: `${API}/api/v1/health/ready`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        AWARECARE_MODE: "mock", AWARECARE_DATA_DIR: dataDir, AWARECARE_ALLOWED_ORIGINS: WEB,
        AWARECARE_PRESENTER_KEY_FILE: presenterKey,
      },
    },
    {
      command: build(15174),
      url: WEB,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { AWARECARE_WEB_PORT: "15174", AWARECARE_API_TARGET: API, AWARECARE_PRESENTER_KEY_FILE: presenterKey },
    },
  ],
});
