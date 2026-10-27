import { expect, test } from "@playwright/test";
import { answerCurrent, enterConcern, startSession } from "../ui/support/journey";
import { DEV, mergeResult } from "./support/device";
// #355-#357 on a deployed device (#367): warning-sign "None" position and group headings on A03, "Previous question"
// on question 2, and whether the visit summary shows the level of care and the doctor found. Same script before and
// after a change. Writes OUT_DIR/measures.json, keyed "<width>:<measure>".
test(`#355-#357 measures on the ZGX ${DEV}`, async ({ page }, info) => {
  test.setTimeout(300_000);
  const w = info.project.name.includes("360") ? "360" : "1440"; const m: Record<string, unknown> = {};
  await startSession(page);
  const none = page.getByRole("checkbox", { name: "None of these apply" });
  m[`${w}:A03_none_y`] = Math.round(await none.evaluate((el) => el.getBoundingClientRect().top + window.scrollY));
  m[`${w}:A03_group_headings`] = await page.locator("form fieldset fieldset legend, form .sign-group-title, form [data-group] legend").count();
  await enterConcern(page);
  await answerCurrent(page, "answer");
  await expect(page.getByText(/^Question 2 of up to 10$/)).toBeVisible({ timeout: 60_000 });
  const prev = page.getByRole("button", { name: /previous question/i }).or(page.getByRole("link", { name: /previous question/i }));
  m[`${w}:A05_previous_on_q2`] = (await prev.count()) > 0 && await prev.first().isVisible();
  // Finish, generate, search doctors, open the summary.
  for (let g = 0; g < 11; g++) {
    const head = page.getByText(/^Question \d+ of up to 10$/);
    await expect(head.or(page.getByRole("heading", { name: "Review your case" }))).toBeVisible({ timeout: 60_000 });
    if (page.url().endsWith("/review")) break;
    const t = await head.textContent(); await answerCurrent(page, "answer"); await expect(page.getByText(t!)).toHaveCount(0, { timeout: 60_000 });
  }
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 180_000 });
  const level = (await page.locator(".level-card").first().innerText()).split("\n").map((s) => s.trim()).filter(Boolean)[1] ?? "";
  await page.getByRole("button", { name: "Find appropriate care" }).or(page.getByRole("link", { name: "Find appropriate care" })).first().click();
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.getByRole("heading", { name: "Doctor matches" })).toBeVisible({ timeout: 30_000 });
  const doctor = (await page.locator("main h3, main h2").filter({ hasText: /^Dr\. / }).first().innerText()).trim();
  const id = page.url().split("/cases/")[1].split("/")[0];
  await page.goto(`/app/cases/${id}/summary`);
  await expect(page.getByRole("heading", { name: "Appointment summary" })).toBeVisible();
  const text = await page.locator("main").innerText();
  m[`${w}:A12_level_label`] = level; m[`${w}:A12_shows_level`] = level.length > 3 && text.includes(level.replace(/\s*\(illustrative\)\s*/i, "").trim());
  m[`${w}:A12_doctor`] = doctor; m[`${w}:A12_shows_doctor`] = doctor.length > 3 && text.includes(doctor);
  mergeResult("measures.json", m);
});
