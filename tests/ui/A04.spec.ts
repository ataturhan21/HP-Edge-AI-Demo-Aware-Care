// A04 Records (R18-R20). Bundled synthetic sample only; unreadable file rejected; facts need review.
import { expect, test } from "@playwright/test";
import { answerAll, confirmAndGenerate, expectNoHorizontalOverflow, noRedFlags, startSession } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

async function toRecords(page) {
  await startSession(page);
  await page.getByLabel("Main concern").fill("A fictional concern.");
  await noRedFlags(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Add records" })).toBeVisible();
}

test("unreadable file is rejected and nothing is stored", async ({ page }) => {
  await toRecords(page);
  await page.getByRole("button", { name: "Try unreadable file" }).click();
  await expect(page.getByText("This file could not be read. Try a different PDF, PNG or JPEG.")).toBeVisible();
  await expect(page.getByText("No records added.")).toBeVisible();
});

test("sample fact is unused until confirmed, then reaches review and the summary", async ({ page }) => {
  await toRecords(page);
  await page.getByRole("button", { name: "Add sample PDF" }).click();
  await expect(page.getByText("Sample record read. Review the extracted fact below.")).toBeVisible();
  const fact = page.getByLabel("Extracted fact", { exact: true });
  await expect(fact).toContainText("“No medications listed in sample record”");
  await expect(fact).toContainText("page 1");
  await expect(fact).toContainText("Needs confirmation");
  await expect(page.getByText("1 fact not reviewed")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await fact.getByRole("button", { name: "Correct" }).click();
  await page.getByLabel("Corrected value").fill("Takes a daily vitamin (fictional)");
  await page.getByRole("button", { name: "Save correction" }).click();
  await expect(fact).toContainText("Confirmed");
  await expect(fact).toContainText("Your correction: Takes a daily vitamin (fictional)");
  await expect(fact).toContainText("“No medications listed in sample record”"); // source text kept
  await page.getByRole("button", { name: "Continue to questions" }).click();
  await answerAll(page);
  await expect(page.locator(".datum", { hasText: "Medications (from a record you confirmed)" }))
    .toContainText("Takes a daily vitamin (fictional)");
  await confirmAndGenerate(page);
});

test("a rejected fact never reaches review", async ({ page }) => {
  await toRecords(page);
  await page.getByRole("button", { name: "Add sample PDF" }).click();
  const fact = page.getByLabel("Extracted fact", { exact: true });
  await fact.getByRole("button", { name: "Reject" }).click();
  await expect(fact).toContainText("Rejected");
  await page.getByRole("button", { name: "Continue to questions" }).click();
  await answerAll(page);
  await expect(page.getByText("Medications (from a record you confirmed)")).toHaveCount(0);
});

// #38 (R19, R20): printed units and reference ranges. The bundled sample has none, so this test adds synthetic lab
// facts to the real records list by intercepting it (the fixture pack is unchanged) and captures the correction.
test("lab facts show the printed unit and range, say when they are not readable, and a correction keeps its unit", async ({ page }) => {
  await toRecords(page);
  await page.getByRole("button", { name: "Add sample PDF" }).click();
  await expect(page.getByText("Sample record read. Review the extracted fact below.")).toBeVisible();
  const caseId = page.url().split("/cases/")[1].split("/")[0];
  const lab = (id: string, text: string, value: number, units: string | null, range: string | null, doc: string) => ({
    id, case_id: caseId, kind: "record:lab_result", value, units, provenance: "document", source_id: doc, page: 2,
    status: "unconfirmed", original_text: text, confirmed_at: null, ...(range === null ? {} : { reference_range: range }) });
  const glucoseId = "00000000-0000-4000-8000-00000000f001";
  const hbId = "00000000-0000-4000-8000-00000000f002";
  await page.route(`**/api/v1/cases/${caseId}/records`, async (route) => {
    const real = await (await route.fetch()).json();
    const doc = real.documents[0].id;
    real.facts.push(lab(glucoseId, "Glucose 5.4 mmol/L (3.9-5.5)", 5.4, "mmol/L", "3.9-5.5 mmol/L", doc),
                    lab(hbId, "Haemoglobin 13.1 [unit smudged]", 13.1, null, null, doc));
    await route.fulfill({ json: real });
  });
  const reviews: unknown[] = [];
  await page.route(`**/api/v1/cases/${caseId}/facts/${hbId}`, async (route) => {
    const body = route.request().postDataJSON();
    reviews.push(body);
    await route.fulfill({ json: { fact: { ...lab(hbId, "Haemoglobin 13.1 [unit smudged]", 13.1, null, null, caseId),
      status: "confirmed", value: body.corrected_value.value, units: body.corrected_value.units,
      confirmed_at: new Date().toISOString(), source_id: null }, case_revision: body.expected_revision + 1,
      next_action: "records" } });
  });
  await page.reload();
  const cards = page.getByLabel("Extracted fact", { exact: true });
  const glucose = cards.filter({ hasText: "Glucose 5.4" });
  await expect(glucose).toContainText("Value5.4");
  await expect(glucose).toContainText("Unitmmol/L");
  await expect(glucose).toContainText("Reference range3.9-5.5 mmol/L");
  await expect(glucose).toContainText("“Glucose 5.4 mmol/L (3.9-5.5)”"); // source text unchanged
  const hb = cards.filter({ hasText: "Haemoglobin 13.1" });
  await expect(hb).toContainText("Unit not readable");
  await expect(hb).toContainText("Range not readable");
  // A fact that is not a measurement shows no unit or range rows.
  const meds = cards.filter({ hasText: "No medications listed" });
  await expect(meds).not.toContainText("Unit");
  await expect(meds).not.toContainText("Reference range");
  await expectNoHorizontalOverflow(page);
  await hb.getByRole("button", { name: "Correct" }).click();
  await hb.getByLabel("Corrected value").fill("13.1");
  await hb.getByLabel("Unit (optional)").fill("g/dL");
  await hb.getByRole("button", { name: "Save correction" }).click();
  await expect.poll(() => reviews.length).toBe(1);
  expect(reviews[0]).toMatchObject({ action: "correct", corrected_value: { value: "13.1", units: "g/dL" } });
});

// QA 2026-10-22 (journey group).
test("#413 in local mode the page says up front that records are not read, and offers no upload", async ({ page }) => {
  // The suite runs in mock mode; the public telemetry identity is answered as a local-mode device's.
  await page.route(/\/api\/v1\/telemetry\?/, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, identity: { ...body.identity, mode: "local" } } });
  });
  const uploads: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/records")) uploads.push(r.url()); });
  await toRecords(page);
  await expect(page.getByText("Record reading is not available in this build")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add sample PDF" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Try unreadable file" })).toHaveCount(0);
  await expect(page.getByText("is uploaded and checked like a real one", { exact: false })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await page.getByRole("button", { name: "Skip and continue" }).click();
  await expect(page).toHaveURL(/\/questions$/);
  expect(uploads).toEqual([]);
});

test("#450 after the questions, records can no longer be added and the page says why", async ({ page }) => {
  await toRecords(page);
  await page.getByRole("button", { name: "Add sample PDF" }).click();
  await expect(page.getByText("Sample record read. Review the extracted fact below.")).toBeVisible();
  await page.getByRole("button", { name: "Continue to questions" }).click();
  await answerAll(page);
  await page.getByRole("link", { name: "Review records" }).click();
  await expect(page.getByRole("heading", { name: "Add records" })).toBeVisible();
  await expect(page.getByText("Records can no longer be added to this consultation")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add sample PDF" })).toHaveCount(0);
  await expect(page.getByText("This step did not complete")).toHaveCount(0);
  // The extracted fact can still be reviewed here, and Continue returns to the review.
  await expect(page.getByLabel("Extracted fact", { exact: true })).toContainText("Needs confirmation");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page).toHaveURL(/\/review$/);
});
