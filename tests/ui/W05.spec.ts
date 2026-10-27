// W05 Help (R15-R17). Emergency guidance is visible without a session.
import { expect, test } from "@playwright/test";
import { expectNoHorizontalOverflow, startSession } from "./support/journey";

test("help shows emergency guidance and FAQ without a session", async ({ page }) => {
  await page.goto("/help");
  await expect(page.getByRole("heading", { level: 1, name: "Help and urgent care" })).toBeVisible();
  await expect(page.getByText("If you think you may have a medical emergency, call 911 now.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Frequently asked questions" })).toBeVisible();
});

// #445: the strip link opens Help, so its text says where it goes instead of promising a call it does not make. It is
// deliberately not a tel: link: a tap during a demo on a phone must never dial real emergency services.
test("#445 the strip link says Emergency help, opens Help and never dials", async ({ page }) => {
  for (const path of ["/", "/app"]) {
    if (path === "/app") await startSession(page);
    else await page.goto(path);
    const strip = page.locator(".strip");
    const link = strip.getByRole("link", { name: "Emergency help", exact: true });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/help");
    await expect(strip).not.toContainText("Call 911");
    await expect(page.locator(".strip a[href^='tel:']")).toHaveCount(0);
    // One line at every width: the label never wraps, and the page never scrolls sideways.
    const lines = await link.evaluate((el) => {
      const text = [...el.childNodes].find((n) => n.nodeType === Node.TEXT_NODE && n.textContent!.trim())!;
      const range = document.createRange();
      range.selectNodeContents(text);
      return new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top))).size;
    });
    expect(lines, "the label stays on one line").toBe(1);
    await expectNoHorizontalOverflow(page);
  }
  await page.locator(".strip").getByRole("link", { name: "Emergency help" }).click();
  await expect(page).toHaveURL(/\/help$/);
  await expect(page.getByText("If you think you may have a medical emergency, call 911 now.")).toBeVisible();
});
