// A13 History (R03, R10, R35). Owned cases with server state; resume; delete with confirmation.
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
// #188: the history action is named for the next step.
const RESUME = /^(Continue questions|Review answers|View guidance|View urgent help|View limits)$/;
import { ADDRESS, answerAll, CONCERN, enterConcern, serverStep, startSession } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

test("history resumes server state and deletion cannot be undone by Back", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  await page.goto("/app/history");
  const row = page.locator("tbody tr");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Answering questions");
  await row.getByRole("button", { name: RESUME }).click();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/questions$`));
  await page.goto("/app/history");
  await page.locator("tbody tr").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: "Delete this consultation?" }).getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("The consultation was deleted.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "No consultations yet" })).toBeVisible();
  // Back returns to the case's question page; nothing is restored from browser state or cache (T-R10-S02).
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/questions$`));
  await expect(page.getByRole("heading", { name: "This consultation is not available" })).toBeVisible();
  await expect(page.getByText(/^Question \d+ of up to 10$/)).toHaveCount(0);
  await expect(page.locator("form.card")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(CONCERN);
  await page.goto(`/app/cases/${caseId}/questions`);
  await expect(page.getByRole("heading", { name: "This consultation is not available" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(CONCERN);
});

test("a reloaded browser resumes the case and its answers from the server, not from browser storage", async ({ page, context }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  await answerAll(page);
  await page.reload();
  await page.goto("/app/history");
  const read = serverStep(page, "GET", `/api/v1/cases/${caseId}`, 200);
  await page.locator("tbody tr").getByRole("button", { name: RESUME }).click();
  const answers = ((await (await read).json()).case.confirmed_context as { kind: string; original_text: string; value: unknown }[])
    .filter((f) => f.kind.startsWith("answer:"));
  expect(answers).toHaveLength(10);
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/review$`));
  for (const fact of answers) {
    const shown = Array.isArray(fact.value) ? fact.value[0] : fact.value;
    await expect(page.locator(".datum", { hasText: fact.original_text })).toContainText(String(shown));
  }
  // The browser keeps no health content of its own: no web storage, Cache Storage or IndexedDB.
  const stored = await page.evaluate(async () => ({
    local: localStorage.length, session: sessionStorage.length,
    caches: (await caches.keys()).length, idb: (await indexedDB.databases()).length,
  }));
  expect(stored).toEqual({ local: 0, session: 0, caches: 0, idb: 0 });
  // A new page has no in-memory state at all, yet shows the same answers: they can only come from the server.
  const fresh = await context.newPage();
  await fresh.goto(`/app/cases/${caseId}/review`);
  for (const fact of answers) {
    const shown = Array.isArray(fact.value) ? fact.value[0] : fact.value;
    await expect(fresh.locator(".datum", { hasText: fact.original_text })).toContainText(String(shown));
  }
});

test("another browser session sees none of these cases", async ({ page, browser }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  const other = await browser.newContext();
  const p2 = await other.newPage();
  await startSession(p2);
  await p2.goto("/app/history");
  await expect(p2.getByRole("heading", { name: "No consultations yet" })).toBeVisible();
  await p2.goto(`/app/cases/${caseId}/questions`);
  await expect(p2.getByRole("heading", { name: "This consultation is not available" })).toBeVisible();
  await other.close();
});

test("a deletion whose purge fails is not reported as deleted", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await page.goto("/app/history");
  // Server-side purge failure is exercised in test_R35; here the job result the browser reads says failed.
  await page.route("**/v1/jobs/*", async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    await route.fulfill({ response, json: { ...job, status: "failed", error_code: "PURGE_FAILED" } });
  });
  await page.locator("tbody tr").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: "Delete this consultation?" }).getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("Deletion did not finish.")).toBeVisible();
  await expect(page.getByText("The consultation stays unavailable while the server retries the removal.")).toBeVisible();
  await expect(page.getByText("The consultation was deleted.")).toHaveCount(0);
});

// #266: the history is paged (20 newest first); older consultations load with "Show older consultations".
test("older consultations load page by page from the server's cursor", async ({ page }) => {
  await startSession(page);
  const first = await enterConcern(page, "First fictional concern for paging.");
  await page.goto("/app/new");
  const second = await enterConcern(page, "Second fictional concern for paging.");
  // One case per page, so two real server pages exist; the cursor comes from the server unchanged.
  const asked: string[] = [];
  await page.route(/\/api\/v1\/cases(\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() !== "GET") return route.continue();
    url.searchParams.set("limit", "1");
    asked.push(url.search);
    await route.continue({ url: url.toString() });
  });
  await page.goto("/app/history");
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("Second fictional concern");
  const older = page.getByRole("button", { name: "Show older consultations" });
  await older.click();
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(1)).toContainText("First fictional concern");
  await expect(older).toHaveCount(0); // the last page has no cursor
  expect(asked.length).toBe(2);
  expect(asked[1]).toContain("cursor=");
  expect([first, second].every((id) => id.length === 36)).toBe(true);
});

// #611, #629 (owner decision): a deletion in flight keeps its own confirmation locked until it finishes or fails:
// Escape and Cancel do nothing, the dialog says "Deleting…" (aria-busy) and keeps focus. A finished deletion closes it;
// a failed one shows its error there with a way out. Another consultation is never touched.
test.describe("#629 a pending deletion locks its confirmation", () => {
  // Only for the axe scan of the locked dialog: the gateway policy (#157) rightly forbids injected scripts.
  test.use({ bypassCSP: true });
  const AXE = join(__dirname, "../../apps/web/node_modules/axe-core/axe.min.js");

  /** Holds the real response of the page's DELETE for this case (the server handles it; only its delivery waits). */
  async function holdDelete(page: Page, caseId: string) {
    let release = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    let answered: (status: number) => void = () => {};
    const status = new Promise<number>((resolve) => (answered = resolve));
    await page.route((url) => url.pathname === `/api/v1/cases/${caseId}`, async (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      const response = await route.fetch();
      answered(response.status());
      await held;
      await route.fulfill({ response });
    });
    return { release, status };
  }

  const inDialog = (page: Page) =>
    page.evaluate(() => Boolean(document.activeElement?.closest("[role=dialog]")));

  test("@mobile Escape and Cancel do nothing until the deletion finishes, then the dialog closes", async ({ page }) => {
    await startSession(page);
    const a = await enterConcern(page, "First fictional concern: a sore knee after running.");
    await page.goto("/app/new");
    const b = await enterConcern(page, "Second fictional concern: itchy eyes in spring.");
    const before = (await (await page.request.get(`/api/v1/cases/${b}`)).json()).case;
    const deletes: string[] = [];
    page.on("request", (r) => { if (r.method() === "DELETE") deletes.push(new URL(r.url()).pathname); });
    const { release, status } = await holdDelete(page, a);
    await page.goto("/app/history");
    const rows = page.locator("tbody tr");
    await expect(rows).toHaveCount(2);
    const dialog = page.getByRole("dialog", { name: "Delete this consultation?" });
    await rows.filter({ hasText: "a sore knee" }).getByRole("button", { name: "Delete", exact: true }).click();
    await expect(dialog).toContainText("a sore knee");
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    expect(await status).toBe(202);
    // Locked: "Deleting…" (busy, disabled), Cancel disabled, the dialog busy and announced, focus inside it.
    const busy = dialog.getByRole("button", { name: "Deleting…" });
    await expect(busy).toBeDisabled();
    await expect(busy).toHaveAttribute("aria-busy", "true");
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await expect(dialog).toHaveAttribute("aria-busy", "true");
    await expect(dialog.getByRole("status")).toHaveText("Deleting…");
    expect(await inDialog(page)).toBe(true);
    await page.keyboard.press("Escape");
    await dialog.getByRole("button", { name: "Cancel" }).click({ force: true });
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("a sore knee");
    expect(await inDialog(page)).toBe(true);
    // The locked dialog passes axe (WCAG 2.2 AA and best practice).
    await page.addScriptTag({ path: AXE });
    const found = await page.evaluate(async () => {
      // @ts-expect-error axe is injected above
      const result = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] } });
      return result.violations.map((v: { id: string; impact: string; nodes: { target: string[] }[] }) =>
        `${v.id} (${v.impact}) ${v.nodes.length}× e.g. ${v.nodes[0]?.target.join(" ")}`);
    });
    expect(found).toEqual([]);
    // The deletion finishes: the dialog closes, the page says so and focus is on the page heading.
    release();
    await expect(page.getByText("The consultation was deleted.")).toBeVisible();
    await expect(dialog).toHaveCount(0);
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText("itchy eyes");
    await expect(page.getByRole("heading", { level: 1, name: "Consultation history" })).toBeFocused();
    // On the server: A is gone; B is still stored, unchanged; no DELETE for B was ever sent.
    expect(deletes).toEqual([`/api/v1/cases/${a}`]);
    expect((await page.request.get(`/api/v1/cases/${a}`)).status()).toBe(404);
    const after = (await (await page.request.get(`/api/v1/cases/${b}`)).json()).case;
    expect([after.id, after.concern, after.state, after.revision]).toEqual([b, before.concern, before.state, before.revision]);
  });

  test("@mobile a failed deletion unlocks the dialog with its error, and Cancel or Escape close it", async ({ page }) => {
    await startSession(page);
    const a = await enterConcern(page, "Fictional concern: a sore knee after running.");
    const { release, status } = await holdDelete(page, a);
    await page.goto("/app/history");
    const rows = page.locator("tbody tr");
    await expect(rows).toHaveCount(1);
    // The case really goes away on the server first (outside the page), so the page's DELETE really fails.
    const token = (await page.request.get("/api/v1/settings")).headers()["x-csrf-token"];
    const revision = (await (await page.request.get(`/api/v1/cases/${a}`)).json()).case.revision;
    const gone = await page.request.delete(`/api/v1/cases/${a}?expected_revision=${revision}`,
      { headers: { Origin: ADDRESS, "X-CSRF-Token": token } });
    expect(gone.status()).toBe(202);
    const dialog = page.getByRole("dialog", { name: "Delete this consultation?" });
    await rows.getByRole("button", { name: "Delete", exact: true }).click();
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    expect(await status).toBeGreaterThanOrEqual(400);
    await expect(dialog.getByRole("button", { name: "Deleting…" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    release();
    // Unlocked: the error is in the dialog, the confirm button is back and focused, and Cancel works.
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(dialog).not.toHaveAttribute("aria-busy", "true");
    await expect(dialog.getByRole("button", { name: "Delete", exact: true })).toBeEnabled();
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(await inDialog(page)).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    expect(await page.evaluate(() => document.activeElement !== document.body)).toBe(true);
  });
});
