// QA 2026-10-22 (v0.14.0-demo.1) on the appointment summary (A12) and its PDF. Mock stack, synthetic data, both
// viewports. #417 (P-04): the reviewed preview shows every section the PDF prints, with the same items. #395 (P-02): a
// corrected record fact reads under its kind label, never under the record's old text. #456 (P-12): mock mode calls
// its explanation scripted; a local result keeps the general-medical-knowledge wording.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  answerAll, confirmAndGenerate, expectNoHorizontalOverflow, guardNetwork, noRedFlags, startSession, toGuidance,
} from "./support/journey";

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const preview = (page: Page) => page.getByLabel("Summary preview");

type Drawn = { font: string; size: string; text: string };

/** Every text line the PDF draws, with its font (F1 Helvetica, F2 Helvetica-Bold) and size, unescaped. */
function pdfDrawn(bytes: Buffer): Drawn[] {
  const raw = bytes.toString("latin1");
  return [...raw.matchAll(/\/(F\d) ([\d.]+) Tf 1 0 0 1 [\d.]+ [\d.]+ Tm \(((?:\\.|[^\\)])*)\) Tj/g)].map((m) => ({
    font: m[1], size: m[2], text: m[3].replace(/\\(.)/g, "$1"),
  }));
}

/** The PDF's section headings (Helvetica-Bold 12 pt; a wrapped heading continues on the next such line). */
function pdfHeadings(drawn: Drawn[]): string[] {
  const out: string[] = [];
  drawn.forEach((d, i) => {
    if (d.font !== "F2" || d.size !== "12") return;
    const prev = drawn[i - 1];
    if (prev && prev.font === "F2" && prev.size === "12") out[out.length - 1] += ` ${d.text}`;
    else out.push(d.text);
  });
  return out;
}

/** Text as the PDF prints it: typographic punctuation in its plain form, single spaces. */
const plain = (s: string) =>
  s.replace(/[‐-—−]/g, "-").replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
    .replace(/…/g, "...").replace(/\s+/g, " ").trim();

async function createAndDownload(page: Page): Promise<Buffer> {
  await page.getByLabel("I reviewed this summary.").check();
  await page.getByRole("button", { name: "Create PDF" }).click();
  const link = page.getByRole("link", { name: "Download summary (PDF)" });
  await expect(link).toBeVisible({ timeout: 15_000 });
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  return readFileSync((await download.path())!);
}

test("#417 the preview shows every section and item the PDF prints, under the same titles", async ({ page }) => {
  const offenders = guardNetwork(page);
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(page.getByRole("heading", { name: "Appointment summary" })).toBeVisible();
  // The published guidance the preview and the PDF are made from (this session's own read).
  const response = await page.request.get(`/api/v1/cases/${caseId}/guidance`);
  expect(response.status()).toBe(200);
  const guidance = await response.json();
  const titles = (await preview(page).locator("h2.card-title").allTextContents()).map((t) => t.trim());
  await expectNoHorizontalOverflow(page);

  const drawn = pdfDrawn(await createAndDownload(page));
  // Every PDF section is a preview section, in the same order (the PDF adds its labels in parentheses).
  expect(pdfHeadings(drawn).map((h) => h.split(" (")[0])).toEqual(titles);
  expect(titles).toEqual(expect.arrayContaining(["Suggested next step", "Possible explanations", "When to seek help sooner", "Sources"]));
  const pdfText = plain(drawn.map((d) => d.text).join(" "));
  // The items of each section, in the preview's section of that title and in the PDF.
  const items: [string, string[]][] = [
    ["Unresolved or unknown details", guidance.uncertainties],
    ["Suggested next step", guidance.actions.map((a: { text: string }) => a.text)],
    ["Possible explanations", guidance.possible_explanations.map((c: { text: string }) => c.text)],
    ["Questions for a clinician", guidance.clinician_questions],
    ["When to seek help sooner", guidance.escalation_advice],
  ];
  for (const [title, texts] of items) {
    expect(texts.length, title).toBeGreaterThan(0);
    // The section's list: the first bullet list after its title, within the same section.
    const list = preview(page).locator(
      `xpath=.//h2[normalize-space()="${title}"]/following-sibling::ul[contains(concat(" ", @class, " "), " bullets ")][1]`);
    const shown = (await list.locator("li").allTextContents()).map(plain);
    expect(shown, title).toEqual(texts.map(plain));
    for (const t of texts) expect(pdfText, title).toContain(`- ${plain(t)}`);
  }
  // The Sources statement is the PDF's, word for word; mock mode never calls the scripted text general knowledge.
  const sources = plain((await preview(page).getByRole("region", { name: "Sources" }).locator("p").textContent()) ?? "");
  expect(pdfText).toContain(`Sources ${sources}`);
  expect(sources).toContain("scripted illustrative text");
  await expect(preview(page).getByRole("region", { name: "Possible explanations" })).toContainText(
    "Scripted illustrative text, not from an AI model or reviewed sources; not a diagnosis.");
  await expect(preview(page)).not.toContainText(/general medical knowledge/i);
  expect(pdfText).not.toMatch(/general medical knowledge/i);
  expect(offenders).toEqual([]);
});

test("#395 a corrected record fact reads under its kind label in the preview and the PDF, never under the record's old text", async ({ page }) => {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern about recurring headaches.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Add records" })).toBeVisible();
  const caseId = page.url().match(/\/cases\/([^/]+)\//)![1];
  await page.getByRole("button", { name: "Add sample PDF" }).click();
  const fact = page.getByLabel("Extracted fact", { exact: true });
  await expect(fact).toContainText("“No medications listed in sample record”");
  await fact.getByRole("button", { name: "Correct" }).click();
  await page.getByLabel("Corrected value").fill("Ibuprofen 200 mg as needed");
  await page.getByRole("button", { name: "Save correction" }).click();
  await expect(fact).toContainText("Your correction: Ibuprofen 200 mg as needed");
  await page.getByRole("button", { name: "Continue to questions" }).click();
  await answerAll(page);
  await confirmAndGenerate(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  const row = preview(page).locator(".datum", { hasText: "Ibuprofen 200 mg as needed" });
  await expect(row.locator("span").first()).toHaveText("Medications (from a record you confirmed)");
  await expect(preview(page)).not.toContainText("No medications listed in sample record");
  await expectNoHorizontalOverflow(page);
  const text = plain(pdfDrawn(await createAndDownload(page)).map((d) => d.text).join(" "));
  expect(text).toContain("- Medications (from a record you confirmed): Ibuprofen 200 mg as needed");
  expect(text).not.toContain("No medications listed in sample record");
});

test("#456 a local result's preview keeps the general-medical-knowledge wording", async ({ page }) => {
  // The suite runs in mock mode, so the published guidance is shown as a local result here (as A07.spec does).
  await page.route(/\/api\/v1\/cases\/[^/]+\/guidance$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), model_manifest_id: "qwen3.6-35b-a3b-fp8@95a723d0-2026-10-15" } });
  });
  const caseId = await toGuidance(page);
  await page.goto(`/app/cases/${caseId}/summary`);
  await expect(preview(page).getByRole("region", { name: "Possible explanations" })).toContainText(
    "General medical knowledge, not from reviewed sources; not a diagnosis.");
  await expect(preview(page).getByRole("region", { name: "Sources" })).toContainText(
    "No approved evidence sources are loaded; possible explanations come from general medical knowledge.");
  await expect(preview(page).getByRole("heading", { name: "Suggested next steps" })).toBeVisible();
  await expect(preview(page).getByRole("region", { name: "Suggested next steps" })).toContainText("AI-generated on this device");
});
