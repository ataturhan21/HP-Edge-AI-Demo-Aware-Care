// QA regression tests (2026-10-19 QA pass, issues #277-#305): one test or group per confirmed finding, titled by issue.
// They drive only the real UI against the isolated mock-mode stack; failures are injected with page.route.
import { join } from "node:path";
import { expect, test, type Page, type Request } from "@playwright/test";
import {
  animationsSettled, answerAll, answerCurrent, apiSettled, confirmAndGenerate, enterConcern, expectNoHorizontalOverflow,
  noRedFlags, serverStep, startSession, toGuidance, trackApi,
} from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const PRESENTER = "http://127.0.0.1:15174";
const PATIENT = "http://127.0.0.1:15174";
const ERROR_BODY = (code: string, message: string) => JSON.stringify({
  code, message, field_errors: [], retryable: true, request_id: "00000000-0000-4000-8000-000000000000",
});
// A case resource (read or delete); the delete carries ?expected_revision=, and page.route matches the full URL.
const CASE_READ = /\/api\/v1\/cases\/[0-9a-f-]{36}(\?.*)?$/;
const RESUME = /^(Continue questions|Review answers|View guidance|View urgent help|View limits)$/;
const isPath = (req: Request, method: string, re: RegExp) => req.method() === method && re.test(new URL(req.url()).pathname);

/** Counts requests matching method and path from now on. */
function count(page: Page, method: string, re: RegExp) {
  const seen: string[] = [];
  page.on("request", (r) => { if (isPath(r, method, re)) seen.push(r.url()); });
  return seen;
}

test("#277 A07 'Try again' after a failed load runs the load again", async ({ page }) => {
  const caseId = await toGuidance(page);
  let fail = true;
  await page.route(CASE_READ, (route) => (fail && route.request().method() === "GET" ? route.abort() : route.continue()));
  await page.goto(`/app/cases/${caseId}/guidance`);
  await expect(page.getByText("This step did not complete")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible();
  await expect(page.getByText("Loading guidance")).toHaveCount(0);
});

test("#278 leaving A07 during generation stops polling and never navigates later", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  // The job reads as running, and the first read is held until the person has left the page.
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  let first = true;
  await page.route("**/v1/jobs/*", async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    if (first) {
      first = false;
      await held;
    }
    // The page may have aborted this read meanwhile (that is the fix); fulfilling it then fails harmlessly.
    await route.fulfill({ response, json: { ...job, status: "running", result_id: null, result_type: null } }).catch(() => undefined);
  });
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Preparing your guidance" })).toBeVisible();
  // #415: the preparing view has no "Back to review" (the case cannot be reviewed then); leave through the navigation.
  const menu = page.getByRole("banner").getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("banner").getByRole("link", { name: "History" }).click();
  await expect(page).toHaveURL(/\/history$/);
  const later = count(page, "GET", /\/v1\/jobs\//);
  const guidanceReads = count(page, "GET", /\/api\/v1\/cases\/[^/]+\/guidance$/);
  release(); // the read that was in flight when the page was left now answers
  await page.waitForTimeout(3_000);
  expect(later, "no job reads after leaving A07").toEqual([]);
  expect(guidanceReads).toEqual([]);
  await expect(page).toHaveURL(/\/history$/);
});

test("#279 'Create again' makes a new export and an expired link turns to 'expired' on screen", async ({ page }) => {
  await page.clock.install();
  const caseId = await toGuidance(page);
  const keys: string[] = [];
  page.on("request", (r) => { if (isPath(r, "POST", /\/exports$/)) keys.push(r.headers()["idempotency-key"]); });
  await page.goto(`/app/cases/${caseId}/summary`);
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).click();
  const link = page.getByRole("link", { name: "Download summary (PDF)" });
  await expect(link).toBeVisible({ timeout: 15_000 });
  const first = await link.getAttribute("href");
  await page.clock.fastForward("16:00");
  await expect(page.getByText("The download link expired. Create a new summary.")).toBeVisible();
  await expect(link).toHaveCount(0);
  await page.getByRole("button", { name: "Create again" }).click();
  await expect(link).toBeVisible({ timeout: 15_000 });
  expect(await link.getAttribute("href")).not.toBe(first);
  expect(keys).toHaveLength(2);
  expect(keys[0]).not.toBe(keys[1]);
  await expect(page.getByText("The download link expired.", { exact: false })).toHaveCount(0);
});

test.describe("#280 A06", () => {
  test("Generate after a busy refusal does not confirm the review again", async ({ page }) => {
    await startSession(page);
    await enterConcern(page);
    await answerAll(page);
    const reviews = count(page, "POST", /\/review$/);
    const conflicts: number[] = [];
    page.on("response", (r) => { if (r.status() === 409) conflicts.push(r.status()); });
    let busy = true;
    await page.route(/\/api\/v1\/cases\/[^/]+\/guidance$/, (route) =>
      busy && route.request().method() === "POST"
        ? route.fulfill({ status: 429, contentType: "application/json", body: ERROR_BODY("SERVICE_BUSY", "The service is busy. Try again shortly.") })
        : route.continue());
    await page.getByLabel("I confirm this information is complete as far as I know.").check();
    await page.getByRole("button", { name: "Generate guidance" }).click();
    await expect(page.getByText("The service is busy. Try again shortly.")).toBeVisible();
    busy = false;
    await page.getByRole("button", { name: "Generate guidance" }).click();
    await expect(page).toHaveURL(/\/guidance$/);
    await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 15_000 });
    expect(reviews).toHaveLength(1);
    expect(conflicts).toEqual([]);
  });

  test("the answer editor's buttons are disabled while a save is pending", async ({ page }) => {
    await startSession(page);
    await enterConcern(page);
    await answerAll(page);
    await page.getByRole("button", { name: "Change answer to Has the pattern changed?" }).click();
    await page.getByLabel("Worsening").check();
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/answers/*", async (route) => {
      if (route.request().method() === "PUT") await held;
      await route.continue();
    });
    await page.getByRole("button", { name: "Save answer" }).click();
    const editor = page.getByRole("group", { name: "Change answer: Has the pattern changed?" });
    await expect(editor.getByRole("button", { name: "Mark not sure" })).toBeDisabled();
    await expect(editor.getByRole("button", { name: "Cancel" })).toBeDisabled();
    release();
    await expect(page.locator(".datum", { hasText: "Has the pattern changed?" })).toContainText("Worsening");
  });
});

test("#281 A05 'Try again' after the next question fails loads it without re-sending the answer", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  const saves = count(page, "PUT", /\/answers\//);
  let fail = true;
  await page.route("**/questions/next", (route) => (fail ? route.abort() : route.continue()));
  await answerCurrent(page, "answer");
  await expect(page.getByRole("heading", { name: "Your answer was saved" })).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Question 2 of up to 10")).toBeVisible();
  expect(saves).toHaveLength(1);
  await expect(page.getByText("Your answer was not saved", { exact: false })).toHaveCount(0);
});

test("#282 a recoverable generation failure opened from History goes to A07 with Retry", async ({ context }) => {
  const presenter = await context.newPage();
  await presenter.goto(`${PRESENTER}/presenter/scenarios/more`); // #358: full journeys
  await presenter.getByRole("button", { name: "Start presenter session" }).click();
  await presenter.getByRole("button", { name: "Load scenario: Guidance unavailable" }).click();
  await expect(presenter.getByText("Loaded: Guidance unavailable")).toBeVisible();
  const page = await context.newPage();
  await page.goto(`${PATIENT}/app/history`);
  await page.locator("tbody tr").getByRole("button", { name: RESUME }).click();
  await answerAll(page);
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Guidance is unavailable right now" })).toBeVisible({ timeout: 15_000 });
  await page.goto(`${PATIENT}/app/history`);
  const row = page.locator("tbody tr");
  await expect(row).toContainText("Guidance failed, can retry");
  await expect(row).not.toContainText("Outside demo limits");
  await row.getByRole("button", { name: "View guidance" }).click();
  await expect(page).toHaveURL(/\/guidance$/);
  await expect(page.getByRole("heading", { name: "Guidance is unavailable right now" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
});

test.describe("#283 dialogs", () => {
  const focused = (page: Page) => page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    return { tag: el?.tagName ?? "", text: el?.textContent?.trim() ?? "", inDialog: Boolean(el?.closest("[role=dialog]")) };
  });

  test("A13: focus stays put across the 30 s tick, errors show in the dialog, and focus never falls to the body", async ({ page }) => {
    await page.clock.install();
    await startSession(page);
    await enterConcern(page);
    await page.goto("/app/history");
    await page.locator("tbody tr").getByRole("button", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete this consultation?" });
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeFocused();
    await page.clock.fastForward("00:31");
    await page.clock.fastForward("00:31");
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeFocused();
    let fail = true;
    await page.route(CASE_READ, (route) =>
      fail && route.request().method() === "DELETE"
        ? route.fulfill({ status: 500, contentType: "application/json", body: ERROR_BODY("INTERNAL", "The deletion could not be started.") })
        : route.continue());
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(dialog.getByRole("alert")).toContainText("The deletion could not be started.");
    fail = false;
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText("The consultation was deleted.")).toBeVisible();
    await expect(dialog).toHaveCount(0);
    await expect.poll(async () => (await focused(page)).tag).toBe("H1");
  });

  test("A14: after Delete all, focus goes to the heading instead of the body", async ({ page }) => {
    await startSession(page);
    await enterConcern(page);
    await page.goto("/app/settings");
    await page.getByRole("button", { name: "Delete all consultations" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete everything" }).click();
    await expect(page.getByText("All consultations were deleted from this device.")).toBeVisible();
    const f = await focused(page);
    expect(f.tag).not.toBe("BODY");
    expect(f.inDialog).toBe(false);
  });
});

test("#284 A04's correction editor closes after a save and stays open with the error on failure", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Add sample PDF" }).click();
  await expect(page.getByText("Sample record read. Review the extracted fact below.")).toBeVisible();
  const fact = page.getByLabel("Extracted fact", { exact: true });
  await fact.getByRole("button", { name: "Correct" }).click();
  await page.getByLabel("Corrected value").fill("Takes a daily vitamin (fictional)");
  let fail = true;
  await page.route("**/facts/*", (route) =>
    fail && route.request().method() === "PATCH"
      ? route.fulfill({ status: 500, contentType: "application/json", body: ERROR_BODY("INTERNAL", "The review was not saved.") })
      : route.continue());
  await page.getByRole("button", { name: "Save correction" }).click();
  await expect(page.getByText("The review was not saved.")).toBeVisible();
  await expect(page.getByLabel("Corrected value")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Save correction" }).click();
  await expect(fact).toContainText("Your correction: Takes a daily vitamin (fictional)");
  await expect(page.getByLabel("Corrected value")).toHaveCount(0);
});

test.describe("#285 session redirects and error bodies", () => {
  test("a first-time visitor reaches A01 without 'Your session ended'", async ({ page }) => {
    await page.goto("/app/history");
    await expect(page).toHaveURL(/\/app\/start$/);
    await expect(page.getByRole("heading", { name: "Before you begin" })).toBeVisible();
    await expect(page.getByText("Your session ended")).toHaveCount(0);
  });

  test("a session known in this tab that ends says 'Your session ended'", async ({ page, context }) => {
    await startSession(page);
    await enterConcern(page);
    await context.clearCookies();
    await answerCurrent(page, "answer");
    await expect(page).toHaveURL(/\/app\/start$/);
    await expect(page.getByText("Your session ended")).toBeVisible();
  });

  test("non-JSON error bodies become errors with their status, and an HTML 401 still redirects", async ({ page }) => {
    await startSession(page);
    let status = 502;
    await page.route("**/api/v1/cases", (route) => route.request().method() === "POST"
      ? route.fulfill({ status, contentType: "text/html", body: `<html><body>Gateway error ${status}</body></html>` })
      : route.continue());
    await page.getByLabel("Main concern").fill("A fictional concern.");
    await noRedFlags(page);
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("The Aware Care service had a problem (502).", { exact: false })).toBeVisible();
    status = 401;
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page).toHaveURL(/\/app\/start$/);
    await expect(page.getByText("Your session ended")).toBeVisible();
  });
});

test.describe("#286 W06 period switcher", () => {
  test("a slow answer for an earlier period never replaces the chosen one", async ({ page }) => {
    await page.route("**/v1/telemetry*", async (route) => {
      const period = new URL(route.request().url()).searchParams.get("period");
      const response = await route.fetch();
      const t = await response.json();
      if (period === "24h") await new Promise((r) => setTimeout(r, 1_500));
      const guided = period === "24h" ? 111 : period === "release" ? 333 : t.consultations.guided;
      await route.fulfill({ response, json: { ...t, consultations: { ...t.consultations, guided } } });
    });
    await page.goto("/telemetry");
    await expect(page.locator(".kpi", { hasText: "Consultations guided" })).toBeVisible();
    await page.getByRole("radio", { name: "Last 24 hours" }).click();
    await page.getByRole("radio", { name: "Since this release" }).click();
    await page.waitForTimeout(2_500);
    await expect(page.getByRole("radio", { name: "Since this release" })).toHaveAttribute("aria-checked", "true");
    await expect(page.locator(".kpi", { hasText: "Consultations guided" }).locator(".kpi-value")).toHaveText("333");
  });

  test("the radios follow the radio pattern, with Refresh outside the group", async ({ page }) => {
    await page.goto("/telemetry");
    const group = page.getByRole("radiogroup", { name: "Period" });
    await expect(group.getByRole("button")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
    await expect(group.locator('[tabindex="0"]')).toHaveCount(1);
    const week = page.getByRole("radio", { name: "Last 7 days" });
    await week.focus();
    await page.keyboard.press("ArrowRight");
    const release = page.getByRole("radio", { name: "Since this release" });
    await expect(release).toBeFocused();
    await expect(release).toHaveAttribute("aria-checked", "true");
    await page.keyboard.press("ArrowRight");
    const day = page.getByRole("radio", { name: "Last 24 hours" });
    await expect(day).toBeFocused();
    await expect(day).toHaveAttribute("aria-checked", "true");
    await page.keyboard.press("ArrowLeft");
    await expect(release).toHaveAttribute("aria-checked", "true");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Refresh" })).toBeFocused();
  });
});

test.describe("#287 accessibility on O01, A02 and O03", () => {
  // Only the test tool (axe) is injected, so the gateway policy is bypassed here (as in tests/ui/a11y.spec.ts).
  test.use({ bypassCSP: true });
  const AXE = join(__dirname, "../../apps/web/node_modules/axe-core/axe.min.js");
  const axe = async (page: Page) => {
    await page.addScriptTag({ path: AXE });
    await animationsSettled(page);
    return page.evaluate(async () => {
      // @ts-expect-error axe is injected above
      const result = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } });
      return result.violations.map((v: { id: string }) => v.id);
    });
  };

  test("A02's allergies error is tied to the field and announced", async ({ page }) => {
    await startSession(page);
    await page.goto("/app/profile");
    await page.getByLabel("I have allergies to report").check();
    await page.getByRole("button", { name: "Use for this session" }).click();
    const field = page.getByRole("textbox", { name: "Allergies to report" });
    await expect(page.getByRole("alert")).toHaveText("Enter at least one allergy, or choose another option.");
    await expect(field).toHaveAttribute("aria-describedby", "allergies-error");
    await expect(field).toBeFocused();
    expect(await axe(page)).toEqual([]);
  });

  test("O01's tiles are a named group and O03's busy button says it is loading", async ({ page }) => {
    await page.goto(`${PRESENTER}/presenter/runtime`);
    await page.getByRole("button", { name: "Start presenter session" }).click();
    await expect(page.getByRole("group", { name: "Runtime at a glance" })).toBeVisible();
    expect(await axe(page)).toEqual([]);
    await page.goto(`${PRESENTER}/presenter/scenarios/more`); // #358: full journeys
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/presenter-api/v1/presenter/scenarios/*/load", async (route) => {
      await held;
      await route.continue();
    });
    await page.getByRole("button", { name: "Load scenario: Find the right clinician" }).click();
    const busy = page.getByRole("button", { name: /^Loading scenario: Find the right clinician/ });
    await expect(busy).toBeVisible();
    await expect(busy).toHaveAttribute("aria-busy", "true");
    release();
    await expect(page.getByText("Loaded: Find the right clinician")).toBeVisible();
  });
});

test("#288 error states offer Try again, and a missing case shows the unavailable state", async ({ page }) => {
  const caseId = await toGuidance(page);
  const missing = "00000000-0000-4000-8000-000000000000";
  for (const screen of ["sources", "summary"]) {
    await page.goto(`/app/cases/${missing}/${screen}`);
    await expect(page.getByRole("heading", { name: "This consultation is not available" })).toBeVisible();
  }
  // A08 and A12: the first read fails, Try again succeeds.
  for (const [screen, re, heading] of [
    ["sources", /\/api\/v1\/cases\/[^/]+\/sources$/, "Where the guidance comes from"],
    ["summary", /\/api\/v1\/settings$/, "Appointment summary"],
  ] as const) {
    let fail = true;
    await page.route(re, (route) => (fail ? route.abort() : route.continue()));
    await page.goto(`/app/cases/${caseId}/${screen}`);
    await expect(page.getByText("This step did not complete")).toBeVisible();
    fail = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await page.unroute(re);
  }
  // A11.
  await page.goto(`/app/cases/${caseId}/preferences`);
  await page.getByRole("button", { name: "Find matches" }).click();
  await page.getByRole("link", { name: "Inspect doctor" }).first().click();
  await expect(page.getByRole("heading", { name: "Why this doctor appears" })).toBeVisible();
  let fail = true;
  await page.route(/\/api\/v1\/cases\/[^/]+\/providers\/[^/]+$/, (route) => (fail ? route.abort() : route.continue()));
  await page.reload();
  await expect(page.getByText("This step did not complete")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "Why this doctor appears" })).toBeVisible();
  // PresenterState.
  const presenter = await page.context().newPage();
  await presenter.goto(`${PRESENTER}/presenter/runtime`);
  await presenter.getByRole("button", { name: "Start presenter session" }).click();
  await expect(presenter.getByText("Device inventory")).toBeVisible();
  let failRuntime = true;
  await presenter.route("**/presenter-api/v1/presenter/runtime", (route) => (failRuntime ? route.abort() : route.continue()));
  await presenter.reload();
  await expect(presenter.getByText("This step did not complete")).toBeVisible();
  failRuntime = false;
  await presenter.getByRole("button", { name: "Try again" }).click();
  await expect(presenter.getByText("Device inventory")).toBeVisible();
});

test.describe("#289 print and buttons", () => {
  test("print keeps the demo notice and hides journey steps, the expiry alert and dialogs", async ({ page }) => {
    await startSession(page);
    await enterConcern(page);
    await page.evaluate(() => {
      const fake = document.createElement("section");
      fake.className = "notice warn expiry";
      fake.id = "fake-expiry";
      fake.textContent = "Your session ends at 10:00 AM";
      document.body.appendChild(fake);
    });
    await page.emulateMedia({ media: "print" });
    await expect(page.locator(".demo")).toBeVisible();
    await expect(page.locator(".demo")).toContainText("do not enter real health information");
    await expect(page.locator(".journey")).toBeHidden();
    await expect(page.locator("#fake-expiry")).toBeHidden();
    await page.emulateMedia({ media: "screen" });
    await page.goto("/app/settings");
    await page.getByRole("button", { name: "End session and delete" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.emulateMedia({ media: "print" });
    await expect(page.getByRole("dialog")).toBeHidden();
    await page.emulateMedia({ media: "screen" });
  });

  test("a disabled button does not change on hover", async ({ page }) => {
    const caseId = await toGuidance(page);
    await page.goto(`/app/cases/${caseId}/summary`);
    const create = page.getByRole("button", { name: "Create PDF" });
    await expect(create).toBeDisabled();
    const look = () => create.evaluate((el) => { const s = getComputedStyle(el); return `${s.backgroundImage}|${s.backgroundColor}|${s.borderColor}`; });
    await page.mouse.move(0, 0);
    const before = await look();
    await create.hover({ force: true });
    await page.waitForTimeout(300); // past the background transition
    expect(await look()).toBe(before);
  });
});

test("#290 after End session, A01 says the data is being deleted, not that it was", async ({ page }) => {
  await startSession(page);
  await page.goto("/app/settings");
  await page.getByRole("button", { name: "End session and delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "End session" }).click();
  await expect(page).toHaveURL(/\/app\/start$/);
  const banner = page.locator(".notice", { hasText: "Session ended" });
  await expect(banner).toContainText("are being deleted from this device");
  await expect(banner).not.toContainText("were removed");
  await expect(banner).not.toContainText("data deleted");
});

test("#291 local-mode A05 and W02 do not promise finishing before 10", async ({ page }) => {
  await page.goto("/how-it-works");
  await expect(page.getByRole("heading", { name: "2. Answer up to 10 questions" })).toBeVisible();
  await expect(page.getByText("finish sooner", { exact: false })).toHaveCount(0);
  // The suite runs in mock mode; the issued question is shown as a local (reviewed pathway) one here.
  await page.route("**/questions/next", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: body.kind === "question" ? { ...body, question: { ...body.question, pathway_version: "general-adult-4" } } : body });
  });
  await startSession(page);
  await enterConcern(page);
  await expect(page.getByText("Questions come from the reviewed pathway, up to 10 in all.")).toBeVisible();
  await expect(page.getByText("finish before 10", { exact: false })).toHaveCount(0);
});

test("#292 W04 lists AI usage counts, W06 labels 0 bytes as by design, A11 copy is correct", async ({ page }) => {
  await page.goto("/privacy");
  await expect(page.locator("li", { hasText: "AI usage counts are kept for 90 days" })).toContainText("no health content");
  await page.goto("/telemetry");
  const tile = page.locator(".kpi", { hasText: "Patient data sent off the device" });
  await expect(tile).toContainText("0 bytes");
  await expect(tile.locator(".basis")).toHaveText("By design");
  await expect(tile).toContainText("not a byte count");
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/doctors/00000000-0000-4000-8000-000000000000`);
  await expect(page.getByRole("heading", { name: "This doctor is not in your current results" })).toBeVisible();
  await expect(page.getByText("Results expire when your case changes.", { exact: false })).toBeVisible();
  await expect(page.getByText("after a reload", { exact: false })).toHaveCount(0);
});

test("#302 a long unbroken concern does not overflow any screen at 360 px", { tag: "@mobile" }, async ({ page }, info) => {
  test.skip(info.project.name !== "mobile-360", "phone width only");
  const token = `Headache${"x".repeat(292)}`;
  expect(token).toHaveLength(300);
  await startSession(page);
  const caseId = await enterConcern(page, token);
  await answerAll(page);
  await expect(page.getByText(token)).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await confirmAndGenerate(page);
  await expectNoHorizontalOverflow(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.getByLabel("Summary preview")).toContainText(token);
  await expectNoHorizontalOverflow(page);
  await page.goto("/app/history");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expectNoHorizontalOverflow(page);
});

test.describe("#303 A14 delete-all failures", () => {
  test("a request that never reached the server says nothing was deleted and offers Try again", async ({ page }) => {
    await startSession(page);
    await enterConcern(page);
    await page.goto("/app/settings");
    for (const fail of ["abort", "500"] as const) {
      await page.route("**/api/v1/privacy/delete-all", (route) => fail === "abort" ? route.abort()
        : route.fulfill({ status: 500, contentType: "application/json", body: ERROR_BODY("INTERNAL", "Internal error.") }));
      await page.getByRole("button", { name: "Delete all consultations" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Delete everything" }).click();
      const banner = page.locator(".notice", { hasText: "Deletion did not start." });
      await expect(banner).toContainText("nothing was deleted");
      await expect(page.getByText("while the server retries", { exact: false })).toHaveCount(0);
      await expect(banner.getByRole("button", { name: "Try again" })).toBeVisible();
      await page.unroute("**/api/v1/privacy/delete-all");
    }
    await page.locator(".notice", { hasText: "Deletion did not start." }).getByRole("button", { name: "Try again" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete everything" }).click();
    await expect(page.getByText("All consultations were deleted from this device.")).toBeVisible();
  });

  test("a deletion the server accepted but did not finish keeps its wording", async ({ page }) => {
    await startSession(page);
    await enterConcern(page);
    await page.goto("/app/settings");
    await page.route("**/v1/jobs/*", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), status: "failed", error_code: "PURGE_FAILED" } });
    });
    await page.getByRole("button", { name: "Delete all consultations" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete everything" }).click();
    await expect(page.getByText("Deletion did not finish.")).toBeVisible();
    await expect(page.getByText("Access stays blocked while the server retries. You can try again.")).toBeVisible();
    await expect(page.getByText("Deletion did not start.")).toHaveCount(0);
  });
});

test("#304 after a reload on review, Change offers the real answer choices", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Review your case" })).toBeVisible();
  await page.getByRole("button", { name: "Change answer to Has the pattern changed?" }).click();
  const editor = page.getByRole("group", { name: "Change answer: Has the pattern changed?" });
  await expect(editor.getByText("not available on this page", { exact: false })).toHaveCount(0);
  await editor.getByLabel("Worsening").check();
  await editor.getByRole("button", { name: "Save answer" }).click();
  await expect(page.getByText("Your change was saved. Please review again before continuing.")).toBeVisible();
  await expect(page.locator(".datum", { hasText: "Has the pattern changed?" })).toContainText("Worsening");
  // A scale answer, too.
  await page.reload();
  await page.getByRole("button", { name: "Change answer to How much does it affect your day?" }).click();
  const scale = page.getByRole("group", { name: "Change answer: How much does it affect your day?" });
  await scale.locator('input[value="7"]').check();
  await scale.getByRole("button", { name: "Save answer" }).click();
  await expect(page.locator(".datum", { hasText: "How much does it affect your day?" })).toContainText("7 on a 0–10 scale");
});

test.describe("#305 en-US times in another locale and time zone", () => {
  test.use({ locale: "ar-EG", timezoneId: "Asia/Kathmandu" });

  // #347: the shared 24-hour time style ("08:21"), the same in every browser locale.
  test("history and the expiry warning use en-US with Latin digits, in local time", async ({ page }) => {
    await trackApi(page);
    await page.clock.install();
    await startSession(page);
    await enterConcern(page);
    const list = serverStep(page, "GET", "/api/v1/cases", 200);
    await page.goto("/app/history");
    const created = ((await (await list).json()).items[0].created_at) as string;
    const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Kathmandu" }).format(new Date(created));
    const day = (d: Date) => new Intl.DateTimeFormat("en-US", { dateStyle: "short", timeZone: "Asia/Kathmandu" }).format(d);
    const startedCell = page.locator("tbody tr td").nth(2);
    if (day(new Date(created)) === day(new Date())) await expect(startedCell).toHaveText(`Today, ${time}`);
    else await expect(startedCell).toContainText(time);
    await expect(page.locator("table")).not.toContainText(/[٠-٩۰-۹]/);
    await apiSettled(page); // #501: no read that reports the expiry is handled after the jump
    await page.clock.fastForward("28:30");
    const warning = page.getByRole("alert").filter({ hasText: "Your session ends at" });
    await expect(warning).toBeVisible();
    await expect(warning).toContainText(/Your session ends at \d{2}:\d{2}/);
    await expect(warning).not.toContainText(/\d\s?(AM|PM)/);
    await expect(warning).not.toContainText(/[٠-٩۰-۹]/);
  });
});

// --- QA 2026-10-22, API security (#397, #434): refusals the screens show, and the session rotated at consent ---------

test("#397 A03 shows a busy refusal and a session's case limit, and keeps the concern for a retry", async ({ page }) => {
  await startSession(page);
  const refusals = [
    { status: 429, code: "QUEUE_FULL", message: "The local runtime is busy. Try again shortly." },
    { status: 409, code: "CASE_LIMIT", message: "This session already holds 100 consultations. Delete one in History, or end the session, to start another." },
  ];
  await page.route("**/api/v1/cases", (route) => {
    const refusal = route.request().method() === "POST" ? refusals.shift() : undefined;
    return refusal
      ? route.fulfill({ status: refusal.status, contentType: "application/json", headers: { "Retry-After": "5" },
        body: ERROR_BODY(refusal.code, refusal.message) })
      : route.continue();
  });
  await page.getByLabel("Main concern").fill("A fictional concern for the refusal check.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("The local runtime is busy. Try again shortly.")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("This session already holds 100 consultations.", { exact: false })).toBeVisible();
  await expect(page.getByLabel("Main concern")).toHaveValue("A fictional concern for the refusal check.");
  await expectNoHorizontalOverflow(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/records$/);
});

test("#397 A12 says why a summary was refused (429 EXPORT_LIMIT), and a later try works", async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.getByRole("heading", { name: "Appointment summary" })).toBeVisible();
  const message = "Up to 10 summaries can be created in 15 minutes. Use the latest one, or try again later.";
  let refuse = true;
  await page.route(/\/api\/v1\/cases\/[^/]+\/exports$/, (route) => refuse
    ? route.fulfill({ status: 429, contentType: "application/json", headers: { "Retry-After": "600" },
      body: ERROR_BODY("EXPORT_LIMIT", message) })
    : route.continue());
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).click();
  const banner = page.getByRole("alert").filter({ hasText: "The PDF could not be created" });
  await expect(banner).toContainText(message);
  await expectNoHorizontalOverflow(page);
  refuse = false;
  await page.getByRole("button", { name: "Create PDF" }).click();
  await expect(page.getByRole("link", { name: "Download summary (PDF)" })).toBeVisible({ timeout: 15_000 });
  await expect(banner).toHaveCount(0);
});

test("#434 accepting consent again issues a new session cookie and keeps the consultation", async ({ page, context }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  const session = async () => (await context.cookies()).find((c) => c.name === "awarecare_session")?.value;
  const before = await session();
  expect(before).toBeTruthy();
  await page.goto("/app/start");
  await page.getByLabel("Yes, I am 18 or older").check();
  await page.getByLabel("I understand and accept these terms.").check();
  const created = serverStep(page, "POST", "/api/v1/sessions", 201);
  await page.getByRole("button", { name: "Accept and begin" }).click();
  expect((await (await created).allHeaders())["set-cookie"] ?? "").toContain("awarecare_session=");
  await expect(page).toHaveURL(/\/app\/profile$/);
  const after = await session();
  expect(after).toBeTruthy();
  expect(after).not.toBe(before);
  // The same consultation is still there under the new session, and writes keep working (new CSRF token).
  await page.goto(`/app/cases/${caseId}/questions`);
  const saved = page.waitForResponse((r) => r.request().method() === "PUT" && r.url().includes("/answers/"));
  await answerCurrent(page, "answer");
  expect((await saved).status()).toBe(200);
});
