// Visit summary (CHG-DEV-API-004, #356; maintainer decision 2026-10-21): A12 and its PDF show the suggested level of
// care from the published guidance (in A07's words, labelled) and the fictional doctors of the latest doctor search
// (at most three, with their confirmed facts), each only when it exists. Mock stack, synthetic data, both viewports.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { expectNoHorizontalOverflow, guardNetwork, toGuidance } from "./support/journey";

const preview = (page: Page) => page.getByLabel("Summary preview");

/** The PDF's drawn text lines (uncompressed `(text) Tj` operators, WinAnsi bytes), unescaped. */
function pdfLines(bytes: Buffer): string[] {
  const raw = bytes.toString("latin1");
  return [...raw.matchAll(/\(((?:\\.|[^\\)])*)\) Tj/g)].map((m) => m[1].replace(/\\(.)/g, "$1"));
}

async function levelOnGuidance(page: Page): Promise<string> {
  return ((await page.locator(".level-card .level-badge").textContent()) ?? "").trim();
}

test("#356 A12 and the PDF show the level of care and the doctors after a doctor search", async ({ page }) => {
  const offenders = guardNetwork(page);
  const caseId = await toGuidance(page);
  const level = await levelOnGuidance(page);
  expect(level).not.toBe("");
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await page.getByRole("button", { name: "Find matches" }).click();
  await expect(page.getByRole("heading", { name: "Doctor matches" })).toBeVisible();
  const cards = page.locator("article.provider");
  await expect(cards.first().getByRole("heading", { level: 2 })).not.toHaveText(/^Match /);
  const names = (await cards.getByRole("heading", { level: 2 }).allTextContents()).slice(0, 3);
  expect(names.length).toBeGreaterThan(0);
  await page.getByRole("navigation", { name: "Next steps" }).getByRole("link", { name: "Continue to visit summary", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/cases/${caseId}/summary$`));

  // The level, in the same words as A07, labelled as the scripted outcome it is in mock mode.
  const levelSection = preview(page).getByRole("region", { name: "Suggested level of care" });
  await expect(levelSection).toBeVisible();
  await expect(levelSection.locator(".level-badge")).toHaveText(level);
  await expect(levelSection).toContainText("Scripted synthetic outcome");
  // The doctors: fictional, labelled, in A10's order, with their confirmed facts.
  const doctors = preview(page).getByRole("region", { name: "Doctors you found" });
  await expect(doctors).toBeVisible();
  await expect(doctors).toContainText("Fictional doctors");
  await expect(doctors.locator("ol.summary-doctors > li > b")).toHaveText(names);
  await expect(doctors.locator(".facts-confirmed li").first()).toBeVisible();
  await expectNoHorizontalOverflow(page);
  // Read from the server: a reload keeps both (the search is not only in this tab's memory).
  await page.reload();
  await expect(preview(page).getByRole("region", { name: "Doctors you found" }).locator("ol > li > b")).toHaveText(names);

  // The PDF says the same.
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).click();
  const link = page.getByRole("link", { name: "Download summary (PDF)" });
  await expect(link).toBeVisible({ timeout: 15_000 });
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  const bytes = readFileSync((await download.path())!);
  const lines = pdfLines(bytes);
  const heading = lines.indexOf("Suggested level of care (synthetic scripted outcome)");
  expect(heading).toBeGreaterThan(-1);
  expect(lines[heading + 1]).toBe(level);
  expect(lines).toContain("Doctors you found (fictional doctors from a synthetic directory)");
  for (const name of names) expect(lines.some((l) => l.startsWith(`- ${name} \u00b7 `))).toBe(true);
  expect(bytes.toString("latin1").split("/Encoding /WinAnsiEncoding").length - 1).toBe(2);
  expect(offenders).toEqual([]);
});

test("#356 A12 without a doctor search shows the level of care but no doctors section", async ({ page }) => {
  const caseId = await toGuidance(page);
  const level = await levelOnGuidance(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.getByRole("heading", { name: "Appointment summary" })).toBeVisible();
  await expect(preview(page).getByRole("region", { name: "Suggested level of care" }).locator(".level-badge")).toHaveText(level);
  await expect(preview(page).getByText("Questions for a clinician")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Doctors you found" })).toHaveCount(0);
  await expect(page.getByText("Fictional doctors", { exact: true })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});
