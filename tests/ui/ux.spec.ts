// UI/UX improvements of 2026-10-19 (#182-#191), from a screen-by-screen audit at 1440 and 360.
import { expect, test } from "@playwright/test";
import { answerAll, apiSettled, enterConcern, expectNoHorizontalOverflow, noRedFlags, startSession, toGuidance, confirmAndGenerate, trackApi } from "./support/journey";

const phone = (name: string) => name.includes("360");

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

test("#182 app and presenter links sit behind a Menu button on phones and in a row on wider screens", { tag: "@mobile" }, async ({ page }, info) => {
  await startSession(page);
  const nav = page.getByRole("navigation", { name: "Main" });
  const menu = nav.getByRole("button", { name: "Menu" });
  const history = nav.getByRole("link", { name: "History" });
  if (phone(info.project.name)) {
    await expect(history).toBeHidden();
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await menu.click();
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    for (const name of ["Start a new consultation", "History", "Data settings", "Help", "Telemetry"])
      await expect(nav.getByRole("link", { name })).toBeVisible();
    await history.click();
    await expect(page).toHaveURL(/\/app\/history$/);
    await expect(nav.getByRole("link", { name: "Data settings" })).toBeHidden(); // closed after navigating
    await page.goto("http://127.0.0.1:15174/presenter/runtime");
    await expect(page.getByRole("navigation", { name: "Presenter" }).getByRole("button", { name: "Menu" })).toBeVisible();
  } else {
    await expect(menu).toBeHidden();
    await expect(history).toBeVisible();
  }
  await expectNoHorizontalOverflow(page);
});

test("#183 the journey steps show where the person is, and only on consultation steps", async ({ page }) => {
  const steps = page.getByRole("navigation", { name: "Consultation steps" });
  await startSession(page);
  await expect(steps.locator('[aria-current="step"]')).toContainText("Concern");
  const caseId = await enterConcern(page);
  await expect(steps.locator('[aria-current="step"]')).toContainText("Questions");
  await expect(steps.getByText(/Concern/)).toContainText("(done)");
  await answerAll(page);
  await expect(steps.locator('[aria-current="step"]')).toContainText("Review");
  // #419: the doctor pages need current guidance (an unguided case shows a page-level state without the steps), so the
  // Find care step is checked on a guided case.
  await confirmAndGenerate(page);
  await page.goto(`/app/cases/${caseId}/preferences`);
  await expect(steps.locator('[aria-current="step"]')).toContainText("Find care");
  for (const path of ["/app/history", "/app/settings", `/app/cases/${caseId}/urgent`, "/app/limits"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(steps).toHaveCount(0);
  }
});

test("#185 a question that offers Not sure as a choice shows no second Not sure button", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  // Question 1 offers "Not sure" as a choice.
  await expect(page.getByRole("radio", { name: "Not sure" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Not sure" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Skip", exact: true })).toBeVisible();
  // Choosing the "Not sure" choice records uncertainty (status unknown), as the button does elsewhere (R13, R14).
  const sent: unknown[] = [];
  page.on("request", (r) => { if (r.method() === "PUT" && r.url().includes("/answers/")) sent.push(r.postDataJSON()); });
  await page.getByRole("radio", { name: "Not sure" }).check();
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page.getByText("Question 2 of up to 10", { exact: true })).toBeVisible();
  expect(sent).toEqual([expect.objectContaining({ status: "unknown", value: null })]);
  // Answer until a question without that choice: the button is there.
  for (let slot = 2; slot < 10; slot++) {
    if (!(await page.getByRole("radio", { name: "Not sure" }).count())) break;
    await page.locator("form.card input[type=radio]").first().check();
    await page.getByRole("button", { name: "Submit answer" }).click();
    await expect(page.getByText(`Question ${slot + 1} of up to 10`, { exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Not sure" })).toBeVisible();
});

test("#186 the guidance wait shows elapsed time and what is happening, and announces it at most every 10 s", async ({ page }) => {
  await trackApi(page);
  // #638: telemetry counts up to now, so guidance jobs of earlier tests on this server would be measured; this test
  // checks the mock-mode default, so it reads a snapshot with no guidance samples yet.
  await page.route("**/api/v1/telemetry*", async (route) => {
    const response = await route.fetch();
    const t = await response.json();
    await route.fulfill({ response, json: { ...t, latency: { samples: 0, total_ms_p50: null, total_ms_p95: null, queue_ms_p50: null } } });
  });
  await page.clock.install();
  await startSession(page);
  await enterConcern(page);
  await answerAll(page);
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  let hold = true;
  await page.route("**/v1/jobs/*", async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    // Hold the job as running, as a slower device would, until the test releases it.
    await route.fulfill({ response, json: hold ? { ...job, status: "running", result_id: null } : job });
  });
  await page.getByRole("button", { name: "Generate guidance" }).click();
  // #322: this stack runs in mock mode, so the wait names the scripted scenario, not the AI (#323: and says the usual time).
  await expect(page.getByText("The demo scenario prepares a scripted result; no AI model reads your answers.")).toBeVisible();
  await expect(page.getByTestId("generating-typical")).toHaveText(/^Usually a few seconds in this scripted demo\./);
  const elapsed = page.locator(".generating-elapsed");
  const spoken = page.locator(".generating-progress [role=status]");
  await expect(elapsed).toHaveText(/^\d+ s$/);
  // #501: the count is anchored to the job's start on the server's clock when the first job read is handled; a read
  // handled after the jump below would start the count again from the server's time.
  await apiSettled(page, "/v1/jobs/");
  await page.clock.runFor(5_000);
  await expect(elapsed).toHaveText(/^[4-6] s$/);
  await expect(spoken).toHaveText(""); // nothing announced yet
  await page.clock.runFor(6_000);
  await expect(spoken).toHaveText("Still working, 10 seconds so far.");
  await expect(page.getByText("Please keep this page open.", { exact: false })).toHaveCount(0);
  await page.clock.runFor(5_000);
  await expect(spoken).toHaveText("Still working, 10 seconds so far."); // unchanged between 10 s steps
  await page.clock.runFor(16_000);
  await expect(spoken).toHaveText("Still working, 30 seconds so far.");
  await expect(page.getByText("Please keep this page open.", { exact: false })).toBeVisible();
  hold = false;
  await page.clock.runFor(5_000);
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 30_000 });
});

test("#187 the next steps come right after the result", { tag: "@mobile" }, async ({ page }) => {
  await toGuidance(page);
  const next = page.getByRole("navigation", { name: "Next steps" });
  await expect(next.getByRole("link", { name: "Find appropriate care" })).toBeVisible();
  await expect(next.getByRole("link", { name: "Appointment summary" })).toBeVisible();
  await expect(next.getByRole("link", { name: "Sources" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Find appropriate care" })).toHaveCount(1); // once on the page
  const nextTop = (await next.boundingBox())!.y;
  const explanationsTop = (await page.getByRole("heading", { name: "Possible explanations" }).boundingBox())!.y;
  expect(nextTop).toBeLessThan(explanationsTop);
});

test("#188 history rows say which consultation, its status, the time left and the next step", async ({ page }) => {
  await startSession(page);
  await enterConcern(page, "A fictional itchy rash on my forearm.");
  await page.goto("/app/history");
  const row = page.locator("tbody tr").first();
  await expect(row).toContainText("A fictional itchy rash on my forearm.");
  await expect(row).toContainText("Answering questions");
  await expect(row).toContainText(/Ends in \d+ (minutes|h \d+ min)/);
  await expect(row).toContainText(/Today, /);
  await expect(page.locator(".tablewrap")).toHaveAttribute("tabindex", "0"); // still a focusable scroll region
  await expect(page.locator(".tablewrap")).toHaveAttribute("role", "region");
  const action = row.getByRole("button", { name: "Continue questions" });
  await expect(action).toHaveAttribute("aria-describedby", /^concern-/);
  await action.click();
  await expect(page).toHaveURL(/\/questions$/);
});

test("#189 the demo notice is one line on phones and complete on wider screens", { tag: "@mobile" }, async ({ page }, info) => {
  await page.goto("/");
  const notice = page.locator(".demo").first();
  if (phone(info.project.name)) {
    await expect(notice.locator(".demo-short")).toBeVisible();
    await expect(notice.locator(".demo-short")).toContainText("fictional people only");
    expect((await notice.boundingBox())!.height).toBeLessThan(36);
  } else {
    await expect(notice.locator(".demo-full")).toBeVisible();
    await expect(notice.locator(".demo-short")).toBeHidden();
  }
  // Screen readers hear the full notice at every width, and never the short one too.
  const spoken = await notice.ariaSnapshot();
  expect(spoken).toContain("do not enter real health information");
  expect(spoken).not.toContain("Demo ·");
});

test("#190 a disabled Generate guidance or Create PDF says why", async ({ page }) => {
  await startSession(page);
  const caseId = await enterConcern(page);
  await answerAll(page);
  const generate = page.getByRole("button", { name: "Generate guidance" });
  await expect(generate).toBeDisabled();
  await expect(page.locator("#generate-hint")).toHaveText("Tick the confirmation above to continue.");
  await expect(generate).toHaveAttribute("aria-describedby", "generate-hint");
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await expect(page.locator("#generate-hint")).toHaveCount(0);
  await expect(generate).toBeEnabled();
  await generate.click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 30_000 });
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.locator("#create-hint")).toContainText("I reviewed this summary");
  await page.getByLabel("I reviewed this summary.").check();
  await expect(page.locator("#create-hint")).toHaveCount(0);
});

test("#191 the telemetry page opens with links to its sections", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("awarecare.telemetry.view", "advanced")); // #547: the advanced view
  await page.goto("/telemetry");
  const nav = page.getByRole("navigation", { name: "On this page" });
  await expect(nav.getByRole("link")).toHaveCount(12); // #469: Reliability and What we don't claim too; #547: the advanced sections
  await nav.getByRole("link", { name: "Sources" }).click();
  await expect(page.getByRole("heading", { name: "Sources and assumptions" })).toBeFocused();
  await expectNoHorizontalOverflow(page);
});
