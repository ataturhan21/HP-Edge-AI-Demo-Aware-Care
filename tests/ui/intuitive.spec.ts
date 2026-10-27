// Easier-to-use pass of 2026-10-19 (#212-#221), from a screen-by-screen audit at 1440 and 360.
import { expect, test } from "@playwright/test";
import { answerAll, enterConcern, noRedFlags, startSession, startSessionOnly, toGuidance } from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

test("#212 the start screen states the guest mode and heads consent in plain words", async ({ page }) => {
  await page.goto("/app/start");
  await expect(page.getByRole("radio", { name: /As a guest/ })).toHaveCount(0); // no one-option choice
  await expect(page.getByRole("heading", { name: "You'll continue as a guest" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Please read and agree" })).toBeVisible();
  await expect(page.locator(".consent-version")).toHaveText("Consent version aware-care-demo-consent-1.0");
  const sent: unknown[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/api/v1/sessions")) sent.push(r.postDataJSON()); });
  await startSessionOnly(page);
  expect(sent.at(-1)).toMatchObject({ mode: "guest", consent_version: "aware-care-demo-consent-1.0" });
});

test("#213 the disabled Save to profile says why", async ({ page }) => {
  await startSessionOnly(page);
  const save = page.getByRole("button", { name: "Save to profile" });
  await expect(save).toBeDisabled();
  await expect(save).toHaveAttribute("aria-describedby", "save-hint");
  await expect(page.locator("#save-hint")).toContainText("needs a saved account");
});

test("#215 a scale answer shows its range on review and summary", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  await answerAll(page); // the journey answers a scale question with 4
  await expect(page.getByRole("heading", { name: "Review your case" })).toBeVisible();
  await expect(page.getByText("4 on a 0–10 scale").first()).toBeVisible();
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 15_000 });
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.getByText("4 on a 0–10 scale").first()).toBeVisible();
});

test("#216 each doctor criterion says whether it filters or only orders; the fields keep their plain names", async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/preferences`);
  for (const id of ["loc-kind", "radius-kind", "visit-kind-tag"]) await expect(page.locator(`#${id}`)).toContainText("Filter");
  await expect(page.getByRole("combobox", { name: "Location", exact: true })).toHaveAccessibleDescription(/Filter/);
  await expect(page.getByRole("group", { name: /Visit type/ })).toHaveAccessibleDescription(/Filter/);
  const plan = page.locator("#plan-kind");
  await expect(plan).toContainText("Optional");
  await page.getByLabel("Insurance plan", { exact: true }).selectOption({ index: 1 });
  await expect(plan).toContainText("Ordering");
  await page.getByLabel("Require a verified match for this plan").check();
  await expect(plan).toContainText("Filter");
  await page.getByLabel("Language", { exact: true }).selectOption("Spanish");
  await expect(page.locator("#lang-kind")).toContainText("Ordering");
  await expect(page.getByRole("combobox", { name: "Language", exact: true })).toHaveAccessibleDescription(/only changes the order/);
});

test("#217 a doctor card and the doctor page list each fact once", async ({ page }) => {
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/preferences`);
  await page.getByRole("button", { name: "Find matches" }).click();
  const card = page.locator("article.provider").first();
  await expect(card).toBeVisible();
  const specialty = (await card.locator("li", { hasText: "Specialty:" }).first().textContent())!;
  await expect(card.getByText(specialty, { exact: false })).toHaveCount(1);
  await expect(card).toContainText("ordering uses only the listed facts");
  await card.getByRole("link", { name: "Inspect doctor" }).click();
  const why = page.locator("section", { has: page.getByRole("heading", { name: "Why this doctor appears" }) });
  await expect(why.getByText(specialty, { exact: false })).toHaveCount(1);
  await expect(page.getByText(/directory version synthetic-directory-v1/)).toBeVisible();
});

test("#218 each delete action says what it removes and what happens next", async ({ page }) => {
  await startSession(page);
  await page.goto("/app/settings");
  await expect(page.getByRole("button", { name: "End session and delete" })).toHaveAttribute("aria-describedby", "end-desc");
  await expect(page.locator("#end-desc")).toContainText("signs you out");
  await expect(page.getByRole("button", { name: "Delete all consultations" })).toHaveAttribute("aria-describedby", "delete-desc");
  await expect(page.locator("#delete-desc")).toContainText("You stay in this session");
});

test("#219 the limits page says where its alternative guidance leads", async ({ page }) => {
  await page.goto("/app/limits");
  const link = page.getByRole("link", { name: "Use reviewed alternative guidance" });
  await expect(link).toHaveAttribute("aria-describedby", "alternative-desc");
  await expect(page.locator("#alternative-desc")).toContainText("Opens Help");
  await link.click();
  await expect(page).toHaveURL(/\/help$/);
});

test("#220 a returning visitor with an open session is offered the way back; a new visitor sees nothing", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText("Your guest session is still open")).toHaveCount(0);
  await startSession(page);
  await enterConcern(page);
  await page.goto("/"); // a reload: the app has forgotten the session in memory
  await expect(page.getByText("Your guest session is still open")).toBeVisible();
  await page.goto("/app/start");
  // #340: the banner opens the consultation where it was left (its open question), not History.
  await page.locator(".resume-session").getByRole("link", { name: "Continue consultation" }).click();
  await expect(page).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/questions$/);
});

test("#221 patient screens use plain words for records, the directory and data settings", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A mild headache since Monday.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/records$/);
  await expect(page.locator("main")).not.toContainText("OCR");
  await expect(page.locator("main")).not.toContainText("Record facts");
  await page.goto("/app/settings");
  await expect(page.locator("main")).not.toContainText("Content-free");
  await expect(page.locator(".datum", { hasText: "Service logs (no health details)" })).toBeVisible();
});
