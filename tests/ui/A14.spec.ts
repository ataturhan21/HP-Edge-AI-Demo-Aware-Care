// A14 Data settings (R34-R36). Retention facts; delete-all; end session reports failures truthfully.
import { expect, test } from "@playwright/test";
import { enterConcern, noRedFlags, startSession, startSessionOnly } from "./support/journey";

test("delete all consultations empties history", async ({ page }) => {
  await startSession(page);
  await enterConcern(page);
  await page.goto("/app/settings");
  await expect(page.getByRole("heading", { name: "Retention" })).toBeVisible();
  await expect(page.locator(".datum", { hasText: "Backups of your health information" })).toContainText("Disabled");
  await page.getByRole("button", { name: "Delete all consultations" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete everything" }).click();
  await expect(page.getByText("All consultations were deleted from this device.")).toBeVisible();
  await page.goto("/app/history");
  await expect(page.getByRole("heading", { name: "No consultations yet" })).toBeVisible();
});

test("a failed end-session request is shown and nothing is cleared", async ({ page }) => {
  await startSession(page);
  await page.goto("/app/settings");
  await page.route("**/api/v1/sessions/current", (r) => r.fulfill({ status: 503, contentType: "application/json",
    body: JSON.stringify({ code: "SERVICE_LIMITED", message: "Try again.", field_errors: [], retryable: true,
      request_id: "00000000-0000-4000-8000-000000000000" }) }));
  await page.getByRole("button", { name: "End session and delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "End session" }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
  await expect(page).toHaveURL(/\/app\/settings$/);
  await page.unroute("**/api/v1/sessions/current");
  await page.getByRole("dialog").getByRole("button", { name: "End session" }).click();
  await expect(page).toHaveURL(/\/app\/start$/);
  // #290: the deletion is reported as under way, not as finished.
  await expect(page.locator(".notice", { hasText: "Session ended" })).toContainText("are being deleted from this device");
});

// #610: tab B held guest 1's profile in memory; tab A ended guest 1 and started guest 2. Tab B's case was refused
// (CSRF_REJECTED), the client fetched guest 2's token and replayed the write: guest 2's case carried guest 1's history
// and allergy as confirmed facts. Ending or replacing the session now ends it in every tab, and a write is never
// replayed under another session.
for (const channel of ["with", "without"] as const) {
  test(`an older tab never carries an ended guest's profile into the next guest's case, ${channel} the cross-tab message (#610) @mobile`,
    async ({ page, context }) => {
      const HISTORY = "FICTIONAL FIRST GUEST HISTORY";
      const ALLERGY = "FICTIONAL FIRST GUEST ALLERGY";
      // without: a browser that does not deliver the message (no BroadcastChannel); the server write must still hold
      if (channel === "without") await page.addInitScript(() => Reflect.deleteProperty(window, "BroadcastChannel"));
      await startSessionOnly(page); // tab B, guest 1
      await page.getByLabel("Relevant history").fill(HISTORY);
      await page.getByLabel("I have allergies to report").check();
      await page.getByLabel("Allergies to report", { exact: true }).fill(ALLERGY);
      await page.getByRole("button", { name: "Use for this session" }).click();
      await expect(page).toHaveURL(/\/app\/new$/);

      const a = await context.newPage(); // tab A: end guest 1, start guest 2 without a profile
      await a.goto("/app/settings");
      await a.getByRole("button", { name: "End session and delete" }).click();
      await a.getByRole("dialog").getByRole("button", { name: "End session" }).click();
      await expect(a).toHaveURL(/\/app\/start$/);
      await startSessionOnly(a);
      await a.getByRole("button", { name: "Skip — continue without a profile" }).click();
      await expect(a).toHaveURL(/\/app\/new$/);

      if (channel === "with") {
        // tab B leaves guest 1's profile as soon as guest 1 ends, before anything is typed into it
        await expect(page).toHaveURL(/\/app\/start$/);
        await expect(page.getByText("Your session ended")).toBeVisible();
      } else {
        await page.getByLabel("Main concern").fill("Fictional SECOND guest concern, no profile supplied.");
        await noRedFlags(page);
        await page.getByRole("button", { name: "Continue" }).click();
        await expect(page).toHaveURL(/\/app\/start$/);
        await expect(page.getByText("Your session ended")).toBeVisible();
      }
      // guest 2's stored cases: none from tab B, so none with guest 1's facts
      const list = await (await a.request.get("/api/v1/cases")).json();
      expect(list.items).toEqual([]);
      // tab A, guest 2, works on as before
      await a.getByLabel("Main concern").fill("Fictional SECOND guest concern.");
      await noRedFlags(a);
      await a.getByRole("button", { name: "Continue" }).click();
      await expect(a).toHaveURL(/\/app\/cases\/[0-9a-f-]+\/records$/);
      const caseId = a.url().split("/cases/")[1].split("/")[0];
      const stored = JSON.stringify((await (await a.request.get(`/api/v1/cases/${caseId}`)).json()).case.confirmed_context);
      expect(stored).not.toContain(HISTORY);
      expect(stored).not.toContain(ALLERGY);
    });
}
