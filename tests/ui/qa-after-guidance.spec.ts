// Fixes from the comprehensive QA of 2026-10-22 (after-guidance group): deletion and case guards on the doctor
// pages (#394, #419), truthful A10 copy after a reload (#421), the A12 download in the app (#418), focus and announced
// outcomes (#402, #403, #420), distinct doctor link names (#444), telehealth distance (#454), A15 for a non-urgent
// case (#457), the delete confirmation (#458), forced colours (#400, #401), the phone menu (#474) and Help without a
// session (#475). Both viewports unless a test says otherwise.
import { expect, test, type Page } from "@playwright/test";
import { answerCurrent, answerAll, enterConcern, noRedFlags, startSession, startSessionOnly, toGuidance } from "./support/journey";

const PRESENTER = "http://127.0.0.1:15174";
const UNKNOWN = "11111111-1111-4111-8111-111111111111";
const UNAVAILABLE = "This consultation is not available";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

/** Follows a header link inside the app (the phone header keeps its links behind Menu), so tab memory is kept. */
async function headerLink(page: Page, name: string) {
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true }).click();
}

async function findMatches(page: Page, plan?: string, required = false) {
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await expect(page.getByRole("button", { name: "Find matches" })).toBeVisible();
  if (plan) await page.getByLabel("Insurance plan").selectOption(plan);
  if (required) await page.getByLabel("Require a verified match for this plan").check();
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Doctor matches" })).toBeVisible();
}

test("#394 a consultation deleted in History does not bring its doctor matches or criteria back through Back", async ({ page }) => {
  await toGuidance(page);
  await findMatches(page, "Demo Health PPO");
  await expect(page.locator("article")).toHaveCount(3);
  await headerLink(page, "History");
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("dialog", { name: "Delete this consultation?" }).getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("The consultation was deleted.")).toBeVisible();
  await page.goBack(); // A10 of the deleted case
  await expect(page).toHaveURL(/\/doctors$/);
  await expect(page.getByRole("heading", { level: 1, name: UNAVAILABLE })).toBeVisible();
  await expect(page.locator("article")).toHaveCount(0);
  await expect(page.getByText("Plan Demo Health PPO confirmed", { exact: false })).toHaveCount(0);
  await page.goBack(); // A09 of the deleted case: no form, no remembered plan
  await expect(page).toHaveURL(/\/preferences$/);
  await expect(page.getByRole("heading", { level: 1, name: UNAVAILABLE })).toBeVisible();
  await expect(page.getByRole("button", { name: "Find matches" })).toHaveCount(0);
});

test("#394 after Delete all consultations, Back to the doctor matches shows the case as not available", async ({ page }) => {
  await toGuidance(page);
  await findMatches(page);
  await expect(page.locator("article")).toHaveCount(3);
  await headerLink(page, "Data settings");
  await page.getByRole("button", { name: "Delete all consultations" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete everything" }).click();
  await expect(page.getByText("All consultations were deleted from this device.")).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/doctors$/);
  await expect(page.getByRole("heading", { level: 1, name: UNAVAILABLE })).toBeVisible();
  await expect(page.locator("article")).toHaveCount(0);
  // No step links survive for the deleted case either.
  await expect(page.getByRole("navigation", { name: "Consultation steps" })).toHaveCount(0);
});

test("#419 the doctor pages check the case: unknown is not available, no guidance says so with the way on", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page); // still in the questions
  for (const path of ["preferences", "doctors", `doctors/${UNKNOWN}?search=${UNKNOWN}`]) {
    await page.goto(`/app/cases/${UNKNOWN}/${path}`);
    await expect(page.getByRole("heading", { level: 1, name: UNAVAILABLE })).toBeVisible();
    await expect(page.getByRole("button", { name: "Find matches" })).toHaveCount(0);
    await page.goto(`/app/cases/${caseId}/${path}`);
    await expect(page.getByRole("heading", { level: 1, name: "No current guidance" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Continue questions" })).toHaveAttribute("href", `/app/cases/${caseId}/questions`);
    await expect(page.getByRole("button", { name: "Find matches" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "No current search" })).toHaveCount(0);
  }
});

test("#421 after a reload A10 says where the search is kept and offers the visit summary and the guidance", async ({ page }) => {
  const caseId = await toGuidance(page);
  await findMatches(page);
  await expect(page.locator("article")).toHaveCount(3);
  await page.reload();
  await expect(page.getByRole("heading", { name: "No search results to show" })).toBeVisible();
  await expect(page.getByText("not kept after a reload", { exact: false })).toHaveCount(0);
  await expect(page.getByText("Your latest search for this consultation is kept on this device", { exact: false })).toBeVisible();
  const ways = page.getByRole("navigation", { name: "Next steps" });
  await expect(ways.getByRole("link", { name: "Back to guidance" })).toHaveAttribute("href", `/app/cases/${caseId}/guidance`);
  await ways.getByRole("link", { name: "Continue to visit summary" }).click();
  await expect(page.getByRole("heading", { name: "Doctors you found" })).toBeVisible();
});

test("#420 #402 focus moves to the outcome of Keep my requirements and of a filter change, which is announced", async ({ page }) => {
  await toGuidance(page);
  await findMatches(page, "Demo Exclusive Plan", true);
  await expect(page.getByRole("heading", { name: "No doctors meet every requirement" })).toBeVisible();
  await page.getByRole("button", { name: "Keep my requirements" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("You kept your requirements, so no doctors are shown.")).toBeFocused();
  await page.getByRole("button", { name: "Make the plan a preference instead of a requirement." }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("article")).toHaveCount(3);
  await expect(page.locator(".results-head p")).toBeFocused();
  await expect(page.getByRole("status").filter({ hasText: "3 fictional doctors match your requirements." })).toHaveCount(1);
});

test("#420 #402 after Create PDF focus lands on the download link", async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("link", { name: "Download summary (PDF)" })).toBeFocused({ timeout: 15_000 });
});

test("#418 a download link whose consultation was deleted elsewhere stays in the app and says so", async ({ page, context }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).click();
  const link = page.getByRole("link", { name: "Download summary (PDF)" });
  await expect(link).toBeVisible({ timeout: 15_000 });
  const other = await context.newPage(); // the same browser: another tab of this session
  await other.goto("/app/settings");
  await other.getByRole("button", { name: "Delete all consultations" }).click();
  await other.getByRole("dialog").getByRole("button", { name: "Delete everything" }).click();
  await expect(other.getByText("All consultations were deleted from this device.")).toBeVisible();
  await other.close();
  await link.click();
  await expect(page.getByRole("heading", { level: 1, name: UNAVAILABLE })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/summary$`));
  await expect(page.getByRole("link", { name: "Emergency help" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("NOT_FOUND");
});

test("#418 a download link the server reports as out of date shows that state in the app", async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).click();
  const link = page.getByRole("link", { name: "Download summary (PDF)" });
  await expect(link).toBeVisible({ timeout: 15_000 });
  await page.route("**/api/v1/exports/*/download", (route) => route.fulfill({ status: 409, contentType: "application/json",
    body: JSON.stringify({ code: "STATE_CONFLICT", message: "This summary is out of date. Create a new one.", field_errors: [],
      retryable: false, request_id: "00000000-0000-4000-8000-000000000000" }) }));
  await link.click();
  await expect(page.getByText("Your case changed. Review it again before creating a summary.")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/summary$`));
  await expect(link).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Create PDF" })).toBeFocused();
});

test("#457 A15 for a guided consultation keeps the general urgent help and leads back to it", async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/urgent`);
  await expect(page.getByRole("heading", { level: 1, name: "Seek urgent help now" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to your consultation" })).toHaveAttribute("href", `/app/cases/${caseId}/guidance`);
  await expect(page.getByRole("link", { name: "Seek urgent help (call 911)" })).toHaveAttribute("href", "tel:911");
  await expect(page.getByText("This urgent case cannot continue", { exact: false })).toHaveCount(0);
  await expect(page.getByText("Routine guidance and doctor matching are not available for this consultation.")).toHaveCount(0);
});

test("#458 the delete confirmation names the consultation it deletes", async ({ page }) => {
  await startSession(page);
  await enterConcern(page, "First fictional concern: a sore knee.");
  await page.goto("/app/new");
  await enterConcern(page, "Second fictional concern: itchy eyes.");
  await page.goto("/app/history");
  const row = page.locator("tbody tr", { hasText: "Second fictional concern: itchy eyes." });
  await expect(row).toHaveCount(1);
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Delete this consultation?" });
  await expect(dialog).toContainText("“Second fictional concern: itchy eyes.”");
  await expect(dialog).toContainText(/Started Today, \d\d:\d\d · Answering questions/);
  await expect(dialog).not.toContainText("sore knee");
});

const outline = (el: Element) => {
  const c = getComputedStyle(el);
  return { style: c.outlineStyle, width: parseFloat(c.outlineWidth) };
};

test("#400 forced colours: a focused text area, select and number field show an outline", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  await startSession(page);
  const concern = page.getByLabel("Main concern");
  await concern.focus();
  const ta = await concern.evaluate(outline);
  expect(ta.style).not.toBe("none");
  expect(ta.width).toBeGreaterThanOrEqual(2);
  await page.addInitScript(() => localStorage.setItem("awarecare.telemetry.view", "advanced")); // #547: the advanced view
  await page.goto("/telemetry");
  const perDay = page.getByLabel("Consultations per day");
  await perDay.focus();
  const num = await perDay.evaluate(outline);
  expect(num.style).not.toBe("none");
  expect(num.width).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Shift+Tab"); // the "Cloud API to compare with" select, by keyboard
  const select = page.getByLabel("Cloud API to compare with");
  await expect(select).toBeFocused();
  const sel = await select.evaluate(outline);
  expect(sel.style).not.toBe("none");
  expect(sel.width).toBeGreaterThanOrEqual(2);
});

test("#401 forced colours: the chosen scale value and the selected period stand out from the others", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  const background = (el: Element) => getComputedStyle(el).backgroundColor;
  await page.goto("/telemetry");
  const on = page.locator(".segmented .seg.on");
  await expect(on).toHaveCount(1);
  expect(await on.evaluate(background)).not.toBe(await page.locator(".segmented .seg:not(.on)").first().evaluate(background));
  await startSession(page);
  await enterConcern(page);
  for (let i = 0; i < 4 && !(await page.locator("fieldset.scale").count()); i++) {
    const head = page.getByText(/^Question \d+ of up to 10$/);
    const shown = await head.textContent();
    await answerCurrent(page, "answer");
    await expect(head).not.toHaveText(shown!);
  }
  await page.locator('fieldset.scale input[value="7"]').check();
  const label = (n: number) => page.locator(`fieldset.scale input[value="${n}"]`).locator("xpath=..");
  expect(await label(7).evaluate(background)).not.toBe(await label(6).evaluate(background));
});

async function toRecords(page: Page) {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Add records" })).toBeVisible();
}

test("#402 A04 keeps keyboard focus through Add sample PDF, Correct, Cancel and Confirm", async ({ page }) => {
  await toRecords(page);
  const add = page.getByRole("button", { name: "Add sample PDF" });
  await add.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Sample record read. Review the extracted fact below.")).toBeVisible();
  await expect(add).toBeFocused();
  const fact = page.getByLabel("Extracted fact", { exact: true });
  const correct = fact.getByRole("button", { name: "Correct", exact: true });
  await correct.focus();
  await page.keyboard.press("Enter");
  await expect(fact.getByLabel("Corrected value")).toBeFocused();
  await fact.getByRole("button", { name: "Cancel", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(correct).toBeFocused();
  await fact.getByRole("button", { name: "Confirm", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(fact).toContainText("Confirmed");
  await expect(correct).toBeFocused();
});

test("#402 A06 Edit concern moves focus into the editor and Cancel back to Edit concern", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  const edit = page.getByRole("button", { name: "Edit concern" });
  await edit.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#concern-edit")).toBeFocused();
  await page.locator("section", { has: page.locator("#concern-edit") }).getByRole("button", { name: "Cancel" }).focus();
  await page.keyboard.press("Enter");
  await expect(edit).toBeFocused();
});

test("#402 A01 a refused Accept and begin leaves focus on the button", async ({ page }) => {
  await page.route("**/api/v1/sessions", (route) => route.request().method() === "POST"
    ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ code: "SERVICE_LIMITED",
      message: "The demo is busy. Try again shortly.", field_errors: [], retryable: true,
      request_id: "00000000-0000-4000-8000-000000000000" }) })
    : route.continue());
  await page.goto("/app/start");
  await page.getByLabel("Yes, I am 18 or older").check();
  await page.getByLabel("I understand and accept these terms.").check();
  const accept = page.getByRole("button", { name: "Accept and begin" });
  await accept.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("The demo is busy. Try again shortly.")).toBeVisible();
  await expect(accept).toBeFocused();
});

test("#402 presenter: Start presenter session hands focus to the page heading, Reset demo keeps it", async ({ page }) => {
  await page.goto(`${PRESENTER}/presenter/scenarios/more`);
  const start = page.getByRole("button", { name: "Start presenter session" });
  await start.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: "More scenarios" })).toBeFocused();
  const reset = page.getByRole("button", { name: "Reset demo" });
  await reset.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Reset completed")).toBeVisible({ timeout: 15_000 });
  await expect(reset).toBeFocused();
});

test("#403 a page-level unavailable or complete state takes focus with its heading", async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goBack(); // in the app: from the guidance back to the review, which has moved on
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/review$`));
  await expect(page.getByRole("heading", { level: 1, name: "This step is complete" })).toBeFocused();
  await page.goto(`/app/cases/${UNKNOWN}/summary`);
  await expect(page.getByRole("heading", { level: 1, name: UNAVAILABLE })).toBeFocused();
});

test("#444 each Inspect doctor link names its doctor", async ({ page }) => {
  await toGuidance(page);
  await findMatches(page);
  const headings = page.locator("article h2");
  await expect(headings).toHaveCount(3);
  for (let i = 0; i < 3; i++) await expect(headings.nth(i)).not.toHaveText(/^Match \d/);
  for (const name of await headings.allTextContents())
    await expect(page.getByRole("link", { name: `Inspect doctor: ${name}`, exact: true })).toHaveCount(1);
});

test("#454 A09 marks the distance as not used for telehealth, and telehealth matches show no distance", async ({ page }) => {
  await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  const tag = page.locator("#radius-kind");
  await expect(tag).toContainText("Filter");
  await page.getByLabel("Location").selectOption("Irving, TX");
  await page.getByRole("radio", { name: "Telehealth (Texas)" }).check();
  await expect(tag).toContainText("Not used");
  await expect(page.getByLabel("Distance for in-person visits")).toHaveAccessibleDescription(/not used for telehealth visits/);
  await page.getByLabel("Distance for in-person visits").selectOption("10");
  await page.getByRole("button", { name: "Find matches" }).click();
  const headings = page.locator("article h2");
  await expect(headings.first()).toBeVisible();
  for (let i = 0; i < await headings.count(); i++) await expect(headings.nth(i)).not.toHaveText(/^Match \d/); // names load per card
  await expect(page.locator("article", { hasText: "Telehealth in TX" }).first()).toBeVisible();
  await expect(page.locator("article", { hasText: " mi (fictional)" })).toHaveCount(0);
});

test("#474 the phone menu closes on Back, on the emergency link and on Escape (focus back on Menu)", { tag: "@mobile" }, async ({ page }, info) => {
  test.skip(info.project.name !== "mobile-360", "the Menu button exists at phone width only");
  await page.goto("/how-it-works");
  const menu = page.getByRole("button", { name: "Menu" });
  await menu.click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Telemetry" }).click();
  await expect(page).toHaveURL(/\/telemetry$/);
  await menu.click();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await page.goBack();
  await expect(page).toHaveURL(/\/how-it-works$/);
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await menu.click();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await expect(menu).toBeFocused();
  await menu.click();
  await page.getByRole("link", { name: "Emergency help" }).click();
  await expect(page).toHaveURL(/\/help$/);
  await expect(menu).toHaveAttribute("aria-expanded", "false");
});

test("#475 Help offers My consultations only while a guest session is open", async ({ page }) => {
  await page.goto("/help");
  await expect(page.getByRole("main").getByRole("link", { name: "Start a new consultation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "My consultations" })).toHaveCount(0);
  await startSessionOnly(page);
  await page.goto("/help");
  await expect(page.getByRole("main").getByRole("link", { name: "Continue consultation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "My consultations" })).toHaveAttribute("href", "/app/history");
});
