import { expect, test, type Locator, type Page } from "@playwright/test";
import { DEV, mergeResult } from "./support/device";
// Usability task walk (#367; synthetic data only): drives the visible UI only, as a patient would, and records taps,
// how far each target sits below the first screen, keyboard presses and dead ends. Same script before and after a
// change: the home page's start link is accepted under either label ("Start consultation" or, with a session open,
// "Start a new consultation"). Writes OUT_DIR/ux.json, keyed "<width>:<measure>".
const m: Record<string, unknown> = {};
let taps = 0; let below = 0;
async function tap(page: Page, loc: Locator, how: "click" | "check" = "click") {
  await loc.waitFor({ state: "visible", timeout: 30_000 });
  const y = await loc.evaluate((el) => el.getBoundingClientRect().top + window.scrollY);
  const vh = page.viewportSize()!.height;
  below = Math.max(below, Math.round(y - vh)); taps++;
  if (how === "check") await loc.check(); else await loc.click();
}
async function topOfPage(page: Page) { await page.evaluate(() => window.scrollTo(0, 0)); }
async function primaryY(_page: Page, loc: Locator) {
  await loc.waitFor({ state: "visible", timeout: 30_000 });
  return Math.round(await loc.evaluate((el) => el.getBoundingClientRect().top + window.scrollY));
}
async function tabsTo(page: Page, loc: Locator, max = 60) {
  await page.evaluate(() => { (document.activeElement as HTMLElement | null)?.blur(); window.scrollTo(0, 0); });
  await page.locator("body").focus();
  const handle = await loc.elementHandle();
  for (let i = 1; i <= max; i++) {
    await page.keyboard.press("Tab");
    if (await page.evaluate((el) => document.activeElement === el, handle)) return i;
  }
  return -1;
}
const START = /\b(start consultation|start a new consultation|start another case|start a different case|start again|new concern|describe a concern|new consultation)\b/i;
const startLabels = new Set<string>();
async function collectStart(page: Page) {
  const names = await page.locator("a:visible, button:visible").allInnerTexts();
  for (const n of names) { const t = n.replace(/\s+/g, " ").trim(); if (START.test(t) && !/presenter/i.test(t)) startLabels.add(t); }
}
async function minY(_page: Page, loc: Locator) {
  const ys = await loc.evaluateAll((els) => els.filter((e) => (e as HTMLElement).offsetParent !== null).map((e) => e.getBoundingClientRect().top + window.scrollY));
  return ys.length ? Math.round(Math.min(...ys)) : -1;
}
test(`usability task walk on the ZGX ${DEV}`, async ({ page }, info) => {
  test.setTimeout(400_000);
  const w = info.project.name.includes("360") ? "360" : "1440";
  const k = (s: string) => `${w}:${s}`;
  // T1 home -> first question, the way the page offers it.
  // #1 an unknown address.
  await page.goto("/app/case"); await page.waitForTimeout(600);
  m[k("notfound_links")] = await page.getByRole("link").count();
  m[k("notfound_emergency_link")] = await page.getByRole("link", { name: /Call 911|Urgent help/ }).count() > 0;
  m[k("notfound_h1")] = (await page.locator("h1, h2").first().innerText().catch(() => "")).slice(0, 80);
  await page.goto("/"); await collectStart(page); const hm = page.getByRole("button", { name: "Menu" }); if (await hm.isVisible()) { await hm.click(); await collectStart(page); await hm.click(); }
  taps = 0; below = 0; const t0 = Date.now();
  await tap(page, page.getByRole("main").getByRole("link", { name: /^(Start consultation|Start a new consultation)$/ }));
  m[k("A01_accept_y")] = await primaryY(page, page.getByRole("button", { name: "Accept and begin" }));
  await tap(page, page.getByLabel("Yes, I am 18 or older"), "check");
  await tap(page, page.getByLabel("I understand and accept these terms."), "check");
  await tap(page, page.getByRole("button", { name: "Accept and begin" }));
  await expect(page).toHaveURL(/\/app\/profile$/);
  await page.getByRole("button", { name: "Use for this session" }).waitFor();
  m[k("A02_primary_y")] = await minY(page, page.getByRole("main").locator("a, button").filter({ hasText: /Use for this session|^Skip|without a profile/i }));
  await tap(page, page.getByRole("button", { name: "Use for this session" }));
  await expect(page).toHaveURL(/\/app\/new$/);
  m[k("A03_tabs_to_concern")] = await tabsTo(page, page.getByLabel("Main concern"));
  // Continue with nothing entered: what does the person learn?
  await page.getByRole("button", { name: "Continue" }).click();
  await page.waitForTimeout(500);
  m[k("A03_empty_continue_message")] = (await page.locator("[role=alert], .field-error, .error").allInnerTexts()).join(" | ").slice(0, 200);
  m[k("A03_empty_continue_focus")] = await page.evaluate(() => { const a = document.activeElement as HTMLElement | null; return a ? `${a.tagName} ${a.getAttribute("id") ?? ""} ${a.getAttribute("aria-label") ?? ""}`.trim() : ""; });
  await topOfPage(page);
  m[k("A03_none_y")] = await primaryY(page, page.getByRole("checkbox", { name: "None of these apply" }));
  m[k("A03_continue_y")] = await primaryY(page, page.getByRole("button", { name: "Continue" }));
  await tap(page, page.getByLabel("Main concern")); await page.getByLabel("Main concern").fill("I have recurring headaches after long workdays. I would like to understand the next step.");
  await tap(page, page.getByRole("checkbox", { name: "None of these apply" }), "check");
  await tap(page, page.getByRole("button", { name: "Continue" }));
  await expect(page).toHaveURL(/\/records$/);
  await tap(page, page.getByRole("button", { name: "Skip and continue" }));
  await expect(page.getByText(/^Question \d+ of up to 10$/)).toBeVisible({ timeout: 60_000 });
  m[k("T1_taps_home_to_first_question")] = taps; m[k("T1_max_px_below_fold")] = below; m[k("T1_seconds")] = (Date.now() - t0) / 1000;
  m[k("A05_progress_bars")] = await page.locator(".journey-bar:visible, .progress:visible").count();
  m[k("A05_tabs_to_first_answer")] = await tabsTo(page, page.locator("form.card input, form.card textarea").first());
  // T4 mid-journey: open Help, then get back to the open question using the page only.
  const questionUrl = page.url();
  await page.goto("/help"); await page.waitForLoadState("networkidle"); taps = 0; below = 0;
  const back = page.getByRole("link", { name: /return to consultation|continue|resume|current consultation|your consultation/i }).first();
  if (await back.count() && await back.isVisible()) { await tap(page, back); }
  else {
    const menu = page.getByRole("button", { name: "Menu" });
    if (await menu.isVisible()) await tap(page, menu);
    await tap(page, page.getByRole("link", { name: "History" }).first());
    const resume = page.getByRole("link", { name: /Continue|Resume|View/ }).or(page.getByRole("button", { name: /Continue|Resume|View/ })).first();
    await tap(page, resume);
  }
  await page.waitForLoadState("networkidle");
  m[k("T4_taps_help_back_to_question")] = taps; m[k("T4_px_below_fold")] = below; m[k("T4_landed_on_question")] = page.url() === questionUrl; m[k("T4_landed")] = new URL(page.url()).pathname.replace(/[0-9a-f-]{36}/, ":id");
  if (page.url() !== questionUrl) { await page.goto(questionUrl); }
  { await page.goto("/help"); const menu = page.getByRole("button", { name: "Menu" }); if (await menu.isVisible()) await menu.click(); m[k("help_menu_offers_start_consultation")] = await page.getByRole("banner").getByRole("link", { name: "Start consultation" }).isVisible(); }
  if (page.url() !== questionUrl) await page.goto(questionUrl);
  // Answer every question (count taps per question).
  taps = 0; let qs = 0;
  for (let g = 0; g < 11; g++) {
    const head = page.getByText(/^Question \d+ of up to 10$/);
    await expect(head.or(page.getByRole("heading", { name: "Review your case" }))).toBeVisible({ timeout: 60_000 });
    if (page.url().endsWith("/review")) break;
    const n = (await head.textContent())!; qs++;
    const form = page.locator("form.card");
    if (await form.locator("fieldset.scale").count()) await tap(page, form.locator('fieldset.scale input[value="4"]'), "check");
    else if (await form.locator("input[type=radio]").count()) await tap(page, form.locator("input[type=radio]").first(), "check");
    else if (await form.locator("input[type=checkbox]").count()) await tap(page, form.locator("input[type=checkbox]").first(), "check");
    else { await tap(page, form.locator("textarea")); await form.locator("textarea").fill("No changes yet."); }
    await tap(page, page.getByRole("button", { name: "Submit answer" }));
    await expect(page.getByText(n)).toHaveCount(0, { timeout: 60_000 });
  }
  m[k("A05_taps_per_question")] = qs ? +(taps / qs).toFixed(2) : null; m[k("A05_questions")] = qs;
  // Review and generate.
  await topOfPage(page);
  m[k("A06_generate_y")] = await primaryY(page, page.getByRole("button", { name: "Generate guidance" }));
  await page.getByLabel("I confirm this information is complete as far as I know.").check();
  await page.getByRole("button", { name: "Generate guidance" }).click();
  await expect(page.getByRole("heading", { name: "Your guidance", exact: true })).toBeVisible({ timeout: 180_000 });
  await collectStart(page);
  m[k("A07_find_care_y")] = await primaryY(page, page.getByRole("button", { name: "Find appropriate care" }).or(page.getByRole("link", { name: "Find appropriate care" })).first());
  // T2 guidance -> doctors -> the visit summary PDF, using the page only (browser Back counts as a tap).
  taps = 0; let backs = 0;
  await tap(page, page.getByRole("button", { name: "Find appropriate care" }).or(page.getByRole("link", { name: "Find appropriate care" })).first());
  await tap(page, page.getByRole("button", { name: "Find matches" }));
  await expect(page.getByRole("heading", { name: "Doctor matches" })).toBeVisible({ timeout: 30_000 });
  await tap(page, page.getByRole("link", { name: "Inspect doctor" }).first());
  await page.waitForLoadState("networkidle");
  const fwd = page.getByRole("link", { name: /summary/i }).or(page.getByRole("button", { name: /summary/i })).first();
  m[k("A11_summary_action_present")] = (await fwd.count()) > 0 && await fwd.isVisible();
  if (m[k("A11_summary_action_present")]) await tap(page, fwd);
  else {
    const seen: string[] = [];
    for (let i = 0; i < 6 && !(await page.getByRole("heading", { name: "Your guidance", exact: true }).isVisible()); i++) {
      const done = page.getByRole("heading", { name: "This step is complete" });
      if (await done.isVisible()) { seen.push("step-complete"); await tap(page, page.getByRole("main").getByRole("link", { name: "Continue" })); }
      else { await page.goBack(); backs++; taps++; }
      await page.waitForLoadState("networkidle"); await page.waitForTimeout(300);
      seen.push(new URL(page.url()).pathname.replace(/[0-9a-f-]{36}/g, ":id"));
    }
    m[k("T2_way_back")] = seen;
    await tap(page, page.getByRole("button", { name: "Appointment summary" }).or(page.getByRole("link", { name: "Appointment summary" })).first());
  }
  await expect(page.getByRole("heading", { name: "Appointment summary" })).toBeVisible({ timeout: 30_000 });
  m[k("A12_create_pdf_y")] = await primaryY(page, page.getByRole("button", { name: "Create PDF" }));
  await tap(page, page.getByLabel("I reviewed this summary."), "check");
  await tap(page, page.getByRole("button", { name: "Create PDF" }));
  await expect(page.getByRole("link", { name: /Download summary/ })).toBeVisible({ timeout: 60_000 });
  m[k("T2_taps_doctor_to_pdf")] = taps; m[k("T2_browser_backs")] = backs; m[k("T2_max_px_below_fold")] = below;
  // Steps indicator: can a finished step be opened from it?
  await collectStart(page);
  m[k("steps_links")] = await page.getByRole("navigation", { name: "Consultation steps" }).getByRole("link").count();
  // T5 decision-maker: telemetry, reach the privacy section and the cost comparison.
  await page.addInitScript(() => localStorage.setItem("awarecare.telemetry.view", "advanced")); // #547: every figure
  await page.goto("/telemetry"); await page.waitForLoadState("networkidle");
  const nav = page.getByRole("navigation", { name: /section|on this page/i }).first();
  void nav; m[k("W06_section_nav_y")] = await minY(page, page.getByRole("main").getByRole("link", { name: "Privacy", exact: true }));
  m[k("W06_page_height")] = await page.evaluate(() => document.documentElement.scrollHeight);
  const body = await page.locator("main").innerText();
  m[k("W06_numeric_dates")] = (body.match(/\b\d{1,2}\/\d{1,2}\/\d{4}/g) ?? []).length;
  m[k("W06_named_dates")] = (body.match(/\b\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}/g) ?? []).length;
  // Mobile menu: what it offers inside the app.
  if (w === "360") {
    await page.goto("/app/history"); await page.getByRole("button", { name: "Menu" }).click();
    m[k("app_menu_items")] = (await page.getByRole("navigation").getByRole("link").allInnerTexts()).map((s) => s.trim()).filter(Boolean).slice(0, 20);
    await collectStart(page);
  }
  await page.goto("/app/history"); await page.waitForLoadState("networkidle");
  const hist = await page.locator("main").innerText();
  m[k("A13_12h_times")] = (hist.match(/\b\d{1,2}:\d{2}\s?(AM|PM)\b/g) ?? []).length;
  m[k("W06_seconds_in_times")] = (body.match(/\b\d{1,2}:\d{2}:\d{2}\b/g) ?? []).length;
  await page.goto("/app/limits"); await collectStart(page);
  // T6 end the session from the guidance page.
  await page.goto("/app/history"); taps = 0;
  await tap(page, page.getByRole("button", { name: "View guidance" }).or(page.getByRole("link", { name: "View guidance" })).first());
  await tap(page, page.getByRole("button", { name: "End session and reset" }));
  await tap(page, page.getByRole("dialog").getByRole("button", { name: /End session/ }));
  await expect(page.getByText(/being deleted|ended/i).first()).toBeVisible({ timeout: 30_000 });
  m[k("T6_taps_end_session")] = taps;
  m[k("start_labels")] = [...startLabels].sort(); m[k("start_label_count")] = startLabels.size;
  mergeResult("ux.json", m);
});
