// A03 Describe concern (R07, R08, R15). Required, trimmed, 4000-character limit; refresh-safe submission; the
// reviewed red-flag checklist (ADR-003) must be answered, and any ticked sign routes to urgent help (A15).
import { expect, test, type Page } from "@playwright/test";
import { expectNoHorizontalOverflow, noRedFlags, startSession, startSessionOnly } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

/** Case creations (POST /api/v1/cases) from now on. */
function creations(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && new URL(r.url()).pathname === "/api/v1/cases") seen.push(r.url()); });
  return seen;
}

test("empty concern is refused and a valid concern creates a case", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("    ");
  await page.getByRole("button", { name: "Continue" }).click();
  // #342: field messages are shown without role="alert"; the focused error summary announces them (improve-forms.spec.ts).
  await expect(page.locator("#concern-error")).toHaveText("Describe your main concern to continue.");
  await expect(page.getByLabel("Main concern")).toHaveAttribute("maxlength", "4000");
  await page.reload(); // in-memory CSRF token is lost; the client must recover it (ADR-008 #8)
  await page.getByLabel("Main concern").fill("  A fictional concern.  ");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/records$/);
});

test("the red-flag checklist must be answered before a case is created", async ({ page }) => {
  await startSession(page);
  let created = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/v1/cases")) created++;
  });
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.locator("#red-flags-error")).toHaveText("Tick the signs that apply, or choose “None of these apply”.");
  expect(created).toBe(0);
  await expect(page.getByRole("group", { name: "Do any of these apply to you right now?" })
    .getByRole("checkbox")).toHaveCount(21); // RF01-RF20 (general-adult-4) and "None of these apply"
  // "None of these apply" and a ticked sign exclude each other.
  await noRedFlags(page);
  await page.getByRole("checkbox", { name: "A seizure" }).check();
  await expect(page.getByRole("checkbox", { name: "None of these apply" })).not.toBeChecked();
  await noRedFlags(page);
  await expect(page.getByRole("checkbox", { name: "A seizure" })).not.toBeChecked();
  await expectNoHorizontalOverflow(page);
});

test("a ticked emergency sign goes straight to urgent help with the reviewed message", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await page.getByRole("checkbox", { name: "A sudden, severe headache, the worst you have ever had" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  await expect(page.getByText("Call 911 now or go to the nearest emergency department. Do not wait for this consultation."))
    .toBeVisible();
  await expect(page.getByText("A sudden, severe headache")).toHaveCount(0); // the sign itself is never displayed
});

test("a ticked urgent-clinician sign shows the same-day message", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await page.getByRole("checkbox", { name: "A painful, swollen calf or leg" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  await expect(page.getByText("Contact a clinician or urgent care today. Do not wait for a routine appointment."))
    .toBeVisible();
});

test("the amendment's red flags RF17 and RF18 route to same-day help", async ({ page }) => {
  for (const sign of ["Coughing up blood", "Skin redness that is spreading, with fever"]) {
    await startSession(page);
    await page.getByLabel("Main concern").fill("A fictional concern.");
    await page.getByRole("checkbox", { name: sign }).check();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page).toHaveURL(/\/urgent$/);
    await expect(page.getByText("Contact a clinician or urgent care today. Do not wait for a routine appointment."))
      .toBeVisible();
    await page.context().clearCookies();
  }
});

test("the amendment's RF19 (possible cauda equina) routes to emergency help", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await page.getByRole("checkbox", { name: /^New numbness around the groin, buttocks or inner thighs/ }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  await expect(page.getByText("Call 911 now or go to the nearest emergency department. Do not wait for this consultation."))
    .toBeVisible();
});

// #154: in local mode, text that describes no health matter is refused when the case is created (422, field
// `concern`, code not_health_concern), and A03 asks for a health concern at once. Mock mode never reads text, so the
// create response is replaced with what the local API returns in that case.
test("a description with no health matter is refused inline, and a health concern then continues", async ({ page }) => {
  await startSession(page);
  let refuse = true;
  await page.route("**/api/v1/cases", async (route) => {
    if (route.request().method() !== "POST" || !refuse) return route.continue();
    await route.fulfill({ status: 422, contentType: "application/json", json: {
      code: "VALIDATION_FAILED", message: "Describe a health concern, for example a symptom and when it started.",
      field_errors: [{ field: "concern", code: "not_health_concern",
        message: "Describe a health concern, for example a symptom and when it started." }],
      retryable: false, request_id: "00000000-0000-4000-8000-000000000000" } });
  });
  await page.getByLabel("Main concern").fill("asdf qwer zxcv uiop");
  await page.getByRole("checkbox", { name: "None of these apply" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.locator("#concern-error")).toContainText("We could not find a health concern in this description.");
  await expect(page.getByLabel("Main concern")).toHaveAttribute("aria-invalid", "true");
  await expect(page).toHaveURL(/\/app\/new$/);
  refuse = false;
  await page.getByLabel("Main concern").fill("A mild headache since Monday.");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/records$/);
});

// QA 2026-10-22 (journey group).
test("#392 a ticked warning sign with no concern written goes straight to urgent help", async ({ page }) => {
  await startSession(page);
  const created = creations(page);
  await page.getByRole("checkbox", { name: /^Chest pain or pressure/ }).check();
  await expect(page.getByText("1 sign ticked. Continue will take you to urgent help.")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  await expect(page.getByText("Call 911 now or go to the nearest emergency department. Do not wait for this consultation."))
    .toBeVisible();
  expect(created).toHaveLength(1);
  // Without a ticked sign the concern is still required.
  await page.goto("/app/new");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.locator("#concern-error")).toHaveText("Describe your main concern to continue.");
  expect(created).toHaveLength(1);
});

test("#408 without a session the concern form is not shown and both start links lead to consent", async ({ page }) => {
  // The session check is held, so the page is caught before the server answers: no form is shown meanwhile.
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/v1/profile", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto("/app/new");
  await expect(page.getByText("Checking your session")).toBeVisible();
  await expect(page.locator("#concern")).toHaveCount(0);
  release();
  await expect(page).toHaveURL(/\/app\/start$/);
  await expect(page.locator("#concern")).toHaveCount(0);
  // Declined consent: A16's button and the header link of the same name lead to the same place, and to consent.
  await page.getByRole("button", { name: "Decline" }).click();
  await expect(page).toHaveURL(/\/app\/limits$/);
  const header = page.getByRole("banner").locator("a", { hasText: "Start a new consultation" });
  const button = page.getByRole("main").getByRole("link", { name: "Start a new consultation" });
  // Wait for A16's own layout (its main button) before comparing: the A01 header can still be mounted for a moment.
  await expect(button).toBeVisible();
  await expect.poll(async () => header.getAttribute("href")).toBe(await button.getAttribute("href"));
  await button.click();
  await expect(page).toHaveURL(/\/app\/start$/);
  await expect(page.getByRole("heading", { name: "Before you begin" })).toBeVisible();
});

test("#412 after a reload A03 says that no profile will be used and links back to it", async ({ page }) => {
  await startSessionOnly(page);
  await page.getByLabel("Age in years").fill("61");
  await page.getByLabel("I have allergies to report").check();
  await page.getByRole("textbox", { name: "Allergies to report" }).fill("Penicillin (synthetic)");
  await page.getByRole("button", { name: "Use for this session" }).click();
  await expect(page.getByLabel("Main concern")).toBeVisible();
  const notice = page.getByText("No profile details on this page");
  await expect(notice).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel("Main concern")).toBeVisible();
  await expect(notice).toBeVisible();
  await expect(page.getByText("none will be used for this consultation", { exact: false })).toBeVisible();
  await page.getByRole("link", { name: "Add profile details first" }).click();
  await expect(page).toHaveURL(/\/app\/profile$/);
});

test("#452 a concern of only blank-looking characters gets the field error, as an empty one", async ({ page }) => {
  await startSession(page);
  const created = creations(page);
  await noRedFlags(page);
  // #509: includes the zero-width characters of the former qa.spec.ts #305 test.
  for (const blank of ["\u00ad", "\u200e\u200f", "\u180e", "\u2800", "\u3164", "\u115f\u1160 ",
    "\u200b\u200c\u200d\u2060\ufeff  "]) {
    await page.getByLabel("Main concern").fill(blank);
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.locator("#concern-error")).toHaveText("Describe your main concern to continue.");
    await expect(page.getByText("This step did not complete")).toHaveCount(0);
  }
  expect(created).toEqual([]);
  // Should the server still find the concern empty (code "empty"), A03 shows the same field error, not a banner.
  await page.route("**/api/v1/cases", (route) => route.request().method() !== "POST" ? route.continue()
    : route.fulfill({ status: 422, contentType: "application/json", json: {
      code: "VALIDATION_FAILED", message: "Describe one main concern to continue.",
      field_errors: [{ field: "concern", code: "empty", message: "Required." }], retryable: false,
      request_id: "00000000-0000-4000-8000-000000000000" } }));
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.locator("#concern-error")).toHaveText("Describe your main concern to continue.");
  await expect(page.getByText("This step did not complete")).toHaveCount(0);
});

// #594: a consultation created after the person already left the form (here: Help in the header) stays in History, but
// its late response never takes them away from the page they chose. A normal Continue still opens the new case once.
test("#594 @mobile a late case create does not navigate away from Help, and the case is in History once", async ({ page }) => {
  await startSession(page);
  const posts = creations(page);
  // The real POST reaches the server and is committed there (201); only the delivery of its real response is held.
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  let committed: (status: number) => void = () => {};
  const serverCommitted = new Promise<number>((resolve) => (committed = resolve));
  await page.route((url) => url.pathname === "/api/v1/cases", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const response = await route.fetch();
    committed(response.status());
    await held;
    await route.fulfill({ response });
  });
  await page.getByLabel("Main concern").fill("Fictional late concern: a stiff neck after a long drive.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  expect(await serverCommitted).toBe(201);
  const menu = page.getByRole("banner").getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click(); // 360 px: the header links are behind the menu
  await page.getByRole("banner").getByRole("link", { name: "Help", exact: true }).click();
  await expect(page).toHaveURL(/\/help$/);
  const finished = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/cases");
  release();
  await finished;
  await page.waitForTimeout(500); // the create's continuation has run; it must not navigate
  await expect(page).toHaveURL(/\/help$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // #630: a routine result shows no notice.
  await expect(page.getByRole("link", { name: "Open urgent help for this consultation" })).toHaveCount(0);
  await expect(page.getByRole("alert").filter({ hasText: "Your new consultation needs urgent help" })).toHaveCount(0);
  // The committed case is in History, exactly once, and was sent once.
  await page.unrouteAll({ behavior: "ignoreErrors" });
  const list = await (await page.request.get("/api/v1/cases")).json();
  expect(list.items.length).toBe(1);
  expect(posts.length).toBe(1);
  await page.goto("/app/history");
  await expect(page.locator("tbody tr").filter({ hasText: "a stiff neck" })).toHaveCount(1);
  // The control: on the form, a normal Continue still opens the new case, once.
  await page.goto("/app/new");
  await page.getByLabel("Main concern").fill("Fictional second concern: a dry cough at night.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/app\/cases\/[^/]+\/records$/);
  expect(posts.length).toBe(2);
});

// #630 (owner decision on #594): a late create still never navigates, but when its result is urgent the person is told on
// the page they are on now (role=alert), with a link to that consultation's urgent help. Opening it ends the notice.
test("#630 @mobile a late urgent create shows an urgent notice on Help with a link to its urgent page", async ({ page }) => {
  await startSession(page);
  const posts = creations(page);
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  let committed: (status: number) => void = () => {};
  const serverCommitted = new Promise<number>((resolve) => (committed = resolve));
  await page.route((url) => url.pathname === "/api/v1/cases", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const response = await route.fetch();
    committed(response.status());
    await held;
    await route.fulfill({ response });
  });
  await page.getByLabel("Main concern").fill("Fictional late concern: a headache.");
  await page.getByRole("checkbox", { name: "A sudden, severe headache, the worst you have ever had" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  expect(await serverCommitted).toBe(201);
  const menu = page.getByRole("banner").getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click(); // 360 px: the header links are behind the menu
  await page.getByRole("banner").getByRole("link", { name: "Help", exact: true }).click();
  await expect(page).toHaveURL(/\/help$/);
  const alert = page.getByRole("main").getByRole("alert").filter({ hasText: "Your new consultation needs urgent help" });
  await expect(alert).toHaveCount(0);
  const finished = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/cases");
  release();
  const created = await (await finished).json();
  expect(created.state).toBe("urgent");
  // The page stays Help; the notice is an alert in the main content, naming what happened, with the case's link.
  await expect(alert).toBeVisible();
  await expect(page).toHaveURL(/\/help$/);
  const link = alert.getByRole("link", { name: "Open urgent help for this consultation" });
  await expect(link).toHaveAttribute("href", `/app/cases/${created.id}/urgent`);
  await expectNoHorizontalOverflow(page);
  // It stays on the next page they choose, until its urgent page is opened.
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("banner").getByRole("link", { name: "Privacy", exact: true }).click();
  await expect(page).toHaveURL(/\/privacy$/);
  await expect(alert).toBeVisible();
  await alert.getByRole("link", { name: "Open urgent help for this consultation" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${created.id}/urgent$`));
  await expect(page.getByText("Call 911 now or go to the nearest emergency department. Do not wait for this consultation."))
    .toBeVisible();
  await expect(page.getByText("Your new consultation needs urgent help")).toHaveCount(0);
  expect(posts.length).toBe(1);
});
