// A06 Review your case (R09, R24). Editing an answer adds no slot and requires a new confirmation.
import { expect, test } from "@playwright/test";
import { answerAll, answerCurrent, confirmAndGenerate, enterConcern, noRedFlags, startSession } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

test("editing an answer on review keeps ten slots and requires re-confirmation", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Change answer to Has the pattern changed?" }).click();
  await page.getByLabel("Worsening").check();
  await page.getByRole("button", { name: "Save answer" }).click();
  await expect(page.getByText("Your change was saved. Please review again before continuing.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your answers (10 questions asked)" })).toBeVisible();
  await expect(page.getByLabel("I confirm this information is complete as far as I know.")).not.toBeChecked();
  await expect(page.getByRole("button", { name: "Generate guidance" })).toBeDisabled();
  await expect(page.locator(".datum", { hasText: "Has the pattern changed?" })).toContainText("Worsening");
});

test("the case cannot be confirmed while an answer edit is open or saving (#148)", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  const confirm = page.getByLabel("I confirm this information is complete as far as I know.");
  const generate = page.getByRole("button", { name: "Generate guidance" });
  await expect(confirm).toBeEnabled();
  await page.getByRole("button", { name: "Change answer to Has the pattern changed?" }).click();
  await expect(confirm).toBeDisabled(); // an open edit: confirming now would confirm data about to change
  await expect(generate).toBeDisabled();
  await page.getByLabel("Worsening").check();
  // Hold the save back, as on a slow device: the box stays disabled until the saved case is shown.
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/answers/*", async (route) => {
    if (route.request().method() === "PUT") await held;
    await route.continue();
  });
  await page.getByRole("button", { name: "Save answer" }).click();
  await expect(confirm).toBeDisabled();
  release();
  await expect(page.locator(".datum", { hasText: "Has the pattern changed?" })).toContainText("Worsening");
  await expect(confirm).toBeEnabled();
  await expect(confirm).not.toBeChecked();
  await confirm.check();
  await expect(generate).toBeEnabled(); // a confirmation given after the save stays given
});

test("an unreviewed record fact is surfaced on review and in guidance, and is never used", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Add sample PDF" }).click();
  await expect(page.getByText("Sample record read. Review the extracted fact below.")).toBeVisible();
  await page.getByRole("button", { name: "Continue to questions" }).click();
  await answerAll(page);
  const pending = page.getByText("1 fact from your records not reviewed");
  await expect(pending).toBeVisible();
  await expect(page.getByText("Unreviewed facts are not used in your guidance or summary.")).toBeVisible();
  await expect(page.getByText("Medications (from a record you confirmed)")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Review records" })).toHaveAttribute("href", /\/app\/cases\/[0-9a-f-]+\/records$/);
  await confirmAndGenerate(page);
  await expect(page.getByText("1 fact from your records was not reviewed, so it was not used.")).toBeVisible();
  await expect(page.getByText("No medications listed in sample record")).toHaveCount(0);
});

test("the red-flag answer is shown on review in plain words", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  const details = page.locator(".datum", { hasText: "Urgent warning signs" });
  await expect(details).toContainText("None of these apply");
});

// #38 (R19): a confirmed test result keeps its printed unit and reference range on review, or says they were not
// readable. Synthetic lab facts are added to the real case read by interception (fixture pack unchanged).
test("confirmed lab results show unit and reference range on review", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  await answerAll(page);
  const fact = (id: string, value: number, units: string | null, range: string | null) => ({
    id, case_id: caseId, kind: "record:lab_result", value, units, provenance: "document",
    source_id: "00000000-0000-4000-8000-00000000d0c1", page: 2, status: "confirmed", original_text: null,
    confirmed_at: new Date().toISOString(), ...(range === null ? {} : { reference_range: range }) });
  await page.route(`**/api/v1/cases/${caseId}`, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const real = await (await route.fetch()).json();
    real.case.confirmed_context.push(fact("00000000-0000-4000-8000-00000000f101", 5.4, "mmol/L", "3.9-5.5 mmol/L"),
                                     fact("00000000-0000-4000-8000-00000000f102", 13.1, null, null));
    await route.fulfill({ json: real });
  });
  await page.reload();
  const results = page.locator(".datum", { hasText: "Test result (from a record you confirmed)" });
  await expect(results).toHaveCount(2);
  await expect(results.nth(0)).toContainText("5.4 mmol/L; reference range 3.9-5.5 mmol/L");
  await expect(results.nth(1)).toContainText("13.1 (unit not readable); reference range not readable");
});

// QA 2026-10-22 (journey group).
test("#388 Change opens the editor with the saved answer filled in", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page); // first choice, first options, scale 4, text "No changes yet."
  const saves: string[] = [];
  page.on("request", (r) => { if (r.method() === "PUT" && r.url().includes("/answers/")) saves.push(r.url()); });
  const editor = (name: string) => page.getByRole("group", { name: `Change answer: ${name}` });
  await page.getByRole("button", { name: "Change answer to Which details apply to your concern?" }).click();
  await expect(editor("Which details apply to your concern?").getByLabel("After long screen sessions")).toBeChecked();
  await expect(editor("Which details apply to your concern?").getByRole("button", { name: "Save answer" })).toBeEnabled();
  // Adding one more choice is one tap; the saved one stays.
  await editor("Which details apply to your concern?").getByLabel("After missed meals").check();
  await editor("Which details apply to your concern?").getByRole("button", { name: "Save answer" }).click();
  await expect(page.locator(".datum", { hasText: "Which details apply to your concern?" }))
    .toContainText("After long screen sessions, After missed meals");
  await page.getByRole("button", { name: "Change answer to What have you already tried?" }).click();
  await expect(editor("What have you already tried?").getByRole("textbox")).toHaveValue("No changes yet.");
  await editor("What have you already tried?").getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Change answer to How much does it affect your day?" }).click();
  await expect(editor("How much does it affect your day?").locator('input[value="4"]')).toBeChecked();
  await page.getByRole("button", { name: "Change answer to When did this concern begin?" }).click();
  await expect(editor("When did this concern begin?").getByLabel("Within the last week")).toBeChecked();
  // Saved unchanged: nothing is sent and nothing changes.
  await editor("When did this concern begin?").getByRole("button", { name: "Save answer" }).click();
  await expect(editor("When did this concern begin?")).toHaveCount(0);
  expect(saves).toHaveLength(1);
});

test("#411 after editing the concern the review shows the confirmation and Generate again", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  const edits: string[] = [];
  page.on("request", (r) => { if (r.method() === "PATCH" && /\/api\/v1\/cases\/[^/]+$/.test(r.url())) edits.push(r.url()); });
  const confirm = page.getByLabel("I confirm this information is complete as far as I know.");
  // Saved unchanged: no request, the review stays as it is.
  await page.getByRole("button", { name: "Edit concern" }).click();
  await page.getByRole("button", { name: "Save change" }).click();
  await expect(page.getByRole("button", { name: "Edit concern" })).toBeVisible();
  expect(edits).toEqual([]);
  await expect(page.getByText("Your change was saved.", { exact: false })).toHaveCount(0);
  // Changed: saved, and the case is back in review with every question asked.
  await page.getByRole("button", { name: "Edit concern" }).click();
  await page.getByLabel("Main concern").fill("Headaches after long workdays, now also in the mornings.");
  await page.getByRole("button", { name: "Save change" }).click();
  await expect(page.getByText("Your change was saved. Please review again before continuing.")).toBeVisible();
  await expect(page.locator(".user-text").first()).toHaveText("Headaches after long workdays, now also in the mornings.");
  expect(edits).toHaveLength(1);
  await expect(page.getByText("More questions may be needed.")).toHaveCount(0);
  await expect(confirm).toBeVisible();
  await confirm.check();
  await confirmAndGenerate(page);
});

test("#449 an earlier answer changed with Previous question keeps its place on review", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  for (let slot = 1; slot <= 3; slot++) {
    const next = page.waitForResponse((r) => r.url().endsWith("/questions/next") && r.request().method() === "POST");
    await answerCurrent(page, "answer");
    await next;
  }
  await expect(page.getByText("Question 4 of up to 10")).toBeVisible();
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "Previous question" }).click();
  await expect(page.getByText("Question 1 of up to 10")).toBeVisible();
  await page.getByRole("radio", { name: "More than a month ago" }).check();
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page.getByText("Question 4 of up to 10")).toBeVisible();
  await answerAll(page);
  const order = await page.locator(".datum .user-text").allTextContents();
  expect(order.slice(0, 4)).toEqual(["When did this concern begin?", "Has the pattern changed?",
    "How much does it affect your day?", "Which details apply to your concern?"]);
  await expect(page.locator(".datum", { hasText: "When did this concern begin?" })).toContainText("More than a month ago");
});

// #580: Back from B's review to A's, with A's read failing, showed B at A's URL, and Save wrote B's concern into A.
test("review shows and edits only the consultation its own read loaded (#580)", async ({ page }) => {
  const A = "Fictional case A: headaches after long workdays.";
  const B = "Fictional case B: ankle soreness after walking.";
  await startSession(page);
  const a = await enterConcern(page, A);
  await answerAll(page);
  await page.goto("/app/new");
  const b = await enterConcern(page, B);
  await answerAll(page);
  const concernOf = async (id: string) => (await (await page.request.get(`/api/v1/cases/${id}`)).json()).case.concern;
  /** A's review, then History, then B's review (three entries of this tab's history); `hold` runs before B's read. */
  const aThenB = async (hold?: () => Promise<void>) => {
    await page.goto(`/app/cases/${a}/review`);
    await expect(page.getByText(A)).toBeVisible();
    await page.getByRole("link", { name: "History" }).click();
    const row = page.getByRole("row").filter({ hasText: B });
    await expect(row).toBeVisible();
    await hold?.();
    await row.getByRole("button", { name: "Review answers" }).click();
    await expect(page).toHaveURL(new RegExp(`/cases/${b}/review$`));
  };

  // A late read: B's answer arrives after Back has already returned to A's review.
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  let delivered!: Promise<void>;
  await aThenB(async () => {
    delivered = new Promise<void>((done) => void page.route(`**/api/v1/cases/${b}`, async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      await held;
      await route.continue();
      await route.request().response();
      done();
    }));
  });
  await expect(page.getByText("Loading your review")).toBeVisible();
  await page.evaluate(() => history.go(-2));
  await expect(page).toHaveURL(new RegExp(`/cases/${a}/review$`));
  await expect(page.getByText(A)).toBeVisible();
  release();
  await delivered;
  // two frames: time for the app to handle the late answer before the page is read
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await expect(page.getByText(A)).toBeVisible();
  await expect(page.getByText(B)).toHaveCount(0);
  await page.unroute(`**/api/v1/cases/${b}`);

  // A failed read: Back to A's review while A's read fails shows the error, never B, and offers no edit.
  await aThenB();
  await expect(page.getByText(B)).toBeVisible();
  await page.route(`**/api/v1/cases/${a}`, (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ status: 503, contentType: "application/json",
          body: JSON.stringify({ code: "SERVICE_LIMITED", message: "Try again.", field_errors: [], retryable: true,
            request_id: "00000000-0000-4000-8000-000000000000" }) })
      : route.continue());
  await page.evaluate(() => history.go(-2));
  await expect(page).toHaveURL(new RegExp(`/cases/${a}/review$`));
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.getByText(B)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit concern" })).toHaveCount(0);
  await page.unroute(`**/api/v1/cases/${a}`);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText(A)).toBeVisible();
  expect(await concernOf(a)).toBe(A);
  expect(await concernOf(b)).toBe(B);
});
