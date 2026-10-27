// Cross-cutting screen acceptance for all 25 routes: the 22 public/patient routes (W01-W06, A01-A16) and,
// with a presenter session on the same address (#487), the 3 presenter routes (O01-O03): no horizontal page overflow at 360, 390,
// 768 and 1440px, one visible h1 per page, and the site name as the tab title (#107).
// Registered as a shared UI test in spec/traceability.yaml; runs once (desktop project).
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { answerCurrent, enterConcern, guardNetwork, startSession, toGuidance } from "./support/journey";

// #134: an interceptor still handling a request when a test ends must never fail the next test.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

const WIDTHS = [360, 390, 768, 1440];
// #107: the product owner's site name, on every page instead of the page heading.
const SITE_TITLE = "Aware Care - Local AI Healthcare Demo on ZGX Nano via ZRT";

test("every public and patient route fits each width", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-1440", "width sweep runs once");
  test.setTimeout(180_000);
  const offenders = guardNetwork(page);
  const caseId = await toGuidance(page);
  await page.getByRole("link", { name: "Find appropriate care" }).click();
  await page.getByRole("button", { name: "Find matches" }).click();
  await page.getByRole("link", { name: "Inspect doctor" }).first().click();
  const providerId = page.url().split("/doctors/")[1];
  await page.goto("/app/new");
  const urgentCase = await enterConcern(page, "Another fictional concern.");
  await answerCurrent(page, "answer");
  await page.getByRole("button", { name: "Simulate urgent answer" }).click();
  await expect(page).toHaveURL(/\/urgent$/);
  const routes = [
    "/", "/how-it-works", "/healthcare", "/privacy", "/help", "/telemetry", "/app/start", "/app/profile", "/app/new",
    `/app/cases/${caseId}/records`, `/app/cases/${caseId}/questions`, `/app/cases/${caseId}/review`,
    `/app/cases/${caseId}/guidance`, `/app/cases/${caseId}/sources`, `/app/cases/${caseId}/preferences`,
    `/app/cases/${caseId}/doctors`, `/app/cases/${caseId}/doctors/${providerId}`, `/app/cases/${caseId}/summary`,
    "/app/history", "/app/settings", `/app/cases/${urgentCase}/urgent`, "/app/limits",
  ];
  expect(routes).toHaveLength(22);
  // #208: each route loads once and is checked at every width by resizing (no screen reads the viewport in script;
  // layout is CSS), instead of 88 page loads that each wait for the network to go idle.
  for (const route of routes) {
    await page.setViewportSize({ width: WIDTHS[0], height: 900 });
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await expect(page.locator("h1").first(), `${route} @${width}`).toBeVisible();
      await expect(page, route).toHaveTitle(SITE_TITLE);
      // #98: every route carries the HP lockup and the local-AI signature (header strip and footer).
      await expect(page.getByRole("link", { name: /^HP Aware Care on .+, home$/ }).getByRole("img", { name: "HP" })).toBeVisible();
      await expect(page.getByTestId("local-ai-signature-strip"), `${route} @${width}`).toContainText("HP ZGX Nano");
      await expect(page.getByTestId("local-ai-signature-footer")).toBeAttached();
      // ADR-017: the telemetry page is one click away on every route (footer link at every width).
      await expect(page.locator("footer").getByRole("link", { name: /Telemetry/ })).toBeAttached();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${route} overflows at ${width}px`).toBeLessThanOrEqual(0);
    }
  }
  expect(offenders).toEqual([]);
});

test("every presenter route fits each width with presenter data shown", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-1440", "width sweep runs once");
  test.setTimeout(120_000);
  const offenders = guardNetwork(page);
  await page.goto("http://127.0.0.1:15174/presenter/runtime");
  await page.getByRole("button", { name: "Start presenter session" }).click();
  await expect(page.getByText("Device inventory", { exact: true })).toBeVisible();
  const routes = ["/presenter/runtime", "/presenter/controls", "/presenter/scenarios", "/presenter/scenarios/more"]; // #358
  for (const route of routes) {
    await page.setViewportSize({ width: WIDTHS[0], height: 900 });
    await page.goto(`http://127.0.0.1:15174${route}`);
    await page.waitForLoadState("networkidle");
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await expect(page.locator("h1"), `${route} @${width}`).toHaveCount(1);
      await expect(page, route).toHaveTitle(SITE_TITLE);
      await expect(page.getByText("Presenter authorization required")).toHaveCount(0);
      await expect(page.getByRole("link", { name: /^HP Aware Care on .+, home$/ }).getByRole("img", { name: "HP" })).toBeVisible();
      await expect(page.getByTestId("local-ai-signature-strip")).toContainText("HP ZGX Nano");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${route} overflows at ${width}px`).toBeLessThanOrEqual(0);
    }
  }
  expect(offenders).toEqual([]);
});

test("the tab shows the site name and the official HP logo on both gateways, also after in-app navigation", async ({ page, request }) => {
  // #107: the icon is the bundled official asset (never redrawn, no remote request), served by each gateway.
  const offenders = guardNetwork(page);
  const official = readFileSync(`${__dirname}/../../apps/web/src/assets/brand/HP_logo_2025.svg`);
  for (const origin of ["", "http://127.0.0.1:15174"]) {
    await page.goto(`${origin}/`);
    await expect(page).toHaveTitle(SITE_TITLE);
    const icon = page.locator('head link[rel="icon"]');
    await expect(icon).toHaveAttribute("type", "image/svg+xml");
    const href = await icon.evaluate((el) => (el as HTMLLinkElement).href);
    expect(new URL(href).origin).toBe(new URL(page.url()).origin);
    const res = await request.get(href);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("image/svg+xml");
    expect(Buffer.compare(await res.body(), official)).toBe(0);
  }
  await page.goto("/");
  await page.locator(".hero").getByRole("link", { name: "How it works" }).click();
  await expect(page).toHaveURL(/\/how-it-works$/);
  await expect(page).toHaveTitle(SITE_TITLE);
  expect(offenders).toEqual([]);
});

test("consent and concern can be completed with the keyboard only", async ({ page }) => {
  // Each screen moves focus to its h1 on mount; a keyboard user starts from there.
  await page.goto("/app/start");
  await expect(page.getByRole("heading", { level: 1, name: "Before you begin" })).toBeFocused();
  await page.getByLabel("Yes, I am 18 or older").focus();
  await page.keyboard.press("Space");
  await expect(page.getByLabel("Yes, I am 18 or older")).toBeChecked();
  await page.getByLabel("I understand and accept these terms.").focus();
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: "Accept and begin" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/app\/profile$/);
  await expect(page.getByRole("heading", { level: 1, name: "Health profile" })).toBeFocused();
  await page.getByRole("button", { name: "Use for this session" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: "What would you like help with?" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Main concern")).toBeFocused();
  await page.keyboard.type("A fictional concern typed with the keyboard.");
  await expect(page.getByLabel("Main concern")).toHaveValue("A fictional concern typed with the keyboard.");
  // #214, #355: the next stop is "None of these apply", the first control of the checklist (not 20 Tabs past RF01-RF20).
  await page.keyboard.press("Tab");
  await expect(page.getByRole("checkbox", { name: "None of these apply" })).toBeFocused();
  await page.keyboard.press("Space");
  // The signs stay below it, one Tab each (RF01-RF20), then "Back to profile" and Continue.
  for (let i = 0; i < 22; i++) await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Continue" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/records$/);
});

test("the R34 network guard flags every request that could carry patient data off the device", async ({ page }, info) => {
  // ADR-014: static assets may come from allowed hosts only; nothing else may leave. Requests are aborted here, so
  // nothing actually leaves the machine; the guard must still name each one.
  test.skip(info.project.name !== "desktop-1440", "runs once");
  const offenders = guardNetwork(page);
  await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, (route) => route.abort());
  // #157: the gateway's Content-Security-Policy refuses these requests inside the browser before they are made (see
  // the next test). This test checks the guard's own classification, so the policy is removed for this page only.
  await page.route("http://127.0.0.1:15174/", async (route) => {
    const response = await route.fetch();
    const headers = { ...response.headers() };
    delete headers["content-security-policy"];
    await route.fulfill({ response, headers });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(offenders).toEqual([]); // the shipped pages make no off-device request
  await page.evaluate(async () => {
    const tries = [
      fetch("https://cdn.example.org/font.woff2", { mode: "no-cors" }),
      fetch("https://www.google-analytics.com/collect", { method: "POST", body: "x", mode: "no-cors" }),
      fetch("https://api.example.org/api/v1/cases", { mode: "no-cors" }),
      fetch("https://cdn.example.org/x?case=00000000-0000-4000-8000-000000000000", { mode: "no-cors" }),
    ];
    await Promise.allSettled(tries);
  });
  await expect.poll(() => offenders.length).toBe(4);
  expect(offenders.every((o) => o.includes("host not allowed"))).toBe(true);
  expect(offenders.find((o) => o.includes("google-analytics"))).toMatch(/analytics or session replay.*request body|method POST/);
  expect(offenders.find((o) => o.includes("api.example.org"))).toContain("API path");
  expect(offenders.find((o) => o.includes("case="))).toContain("case or session identifier");
  const referrer = await page.evaluate(() => document.querySelector('meta[name="referrer"]')?.getAttribute("content"));
  expect(referrer).toBe("no-referrer");
});

// #98: the local-AI signature says only what the browser has observed. It never claims a running model unless a
// server response proved local mode and readiness is ready.
const strip = (page: import("@playwright/test").Page) => page.getByTestId("local-ai-signature-strip");

test("the signature makes no runtime claim before the mode is known, and says mock in mock mode", async ({ page }) => {
  // #322: the public telemetry identity names the mode when the page loads; without that answer the mode is unknown
  // until a question proves it.
  await page.route("**/v1/telemetry*", (route) => route.abort());
  await page.goto("/");
  await expect(strip(page)).toContainText("Built to run AI locally on HP ZGX Nano via ZRT");
  await expect(strip(page)).not.toContainText("AI runs locally");
  await startSession(page);
  await enterConcern(page);
  await expect(strip(page)).toContainText("Mock mode on HP ZGX Nano");
  await expect(strip(page)).not.toContainText("AI runs locally");
  await expect(page.getByTestId("local-ai-signature-footer")).toContainText("Scripted results, no AI model");
});

test("the signature says the AI runs locally only when a response proves local mode", async ({ page }) => {
  // The API answers like local mode: the issued question carries the reviewed pathway's version.
  await page.route("**/questions/next", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (body.question) body.question.pathway_version = "general-adult-4";
    await route.fulfill({ response, json: body });
  });
  await startSession(page);
  await expect(strip(page)).not.toContainText("AI runs locally");
  await enterConcern(page);
  await expect(strip(page)).toContainText("AI runs locally on HP ZGX Nano via ZRT");
  await expect(strip(page)).toContainText("Patient data stays on the ZGX");
});

for (const [status, readiness, title] of [
  [200, "degraded", "Local AI degraded on HP ZGX Nano"],
  [503, "unavailable", "Local AI unavailable on HP ZGX Nano"],
] as const) {
  test(`${readiness} readiness never claims a running model`, async ({ page }) => {
    await page.route("**/api/v1/health/ready", (r) =>
      r.fulfill({ status, contentType: "application/json", body: JSON.stringify({ readiness }) }));
    await page.route("**/questions/next", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      if (body.question) body.question.pathway_version = "general-adult-4";
      await route.fulfill({ response, json: body });
    });
    await page.goto("/help");
    await expect(strip(page)).toContainText(title);
    await expect(strip(page)).not.toContainText("AI runs locally");
  });
}

test("pages render with the bundled typeface when the internet is unreachable", async ({ page }) => {
  // R34 (ADR-014): every page must render on an isolated network. Every non-loopback request is refused.
  await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, (route) => route.abort("internetdisconnected"));
  for (const route of ["/", "/help", "/app/start"]) {
    await page.goto(route);
    await expect(page.locator("h1").first()).toBeVisible();
    await expect(page.getByRole("img", { name: "HP" }).first()).toBeVisible();
    const inter = await page.evaluate(async () => {
      await document.fonts.ready;
      return document.fonts.check('16px "Inter Variable"');
    });
    expect(inter, `bundled typeface on ${route}`).toBe(true);
  }
});

test("reduced motion turns every animation and transition off", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/questions/next", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (body.question) body.question.pathway_version = "general-adult-4";
    await route.fulfill({ response, json: body });
  });
  await startSession(page);
  await enterConcern(page);
  await expect(strip(page)).toContainText("AI runs locally");
  const moving = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("body *")]
      .map((el) => getComputedStyle(el))
      .filter((cs) => cs.animationName !== "none" || (cs.transitionDuration !== "0s" && cs.transitionProperty !== "none"))
      .length);
  expect(moving).toBe(0);
});

// ADR-018: one web image serves the ZGX Nano and the ZGX Fury. The gateway answers /aware-care-device.js with the
// deployment's device; the site name, lockup, signature and telemetry heading follow it.
const FURY_DEVICE = 'window.AWARE_CARE_DEVICE = { name: "HP ZGX Fury", shortName: "ZGX Fury" };';

test("the deployment's device names the site on the ZGX Fury", async ({ page }) => {
  await page.route("**/aware-care-device.js", (route) =>
    route.fulfill({ contentType: "application/javascript", body: FURY_DEVICE }));
  await page.goto("/");
  await expect(page).toHaveTitle("Aware Care - Local AI Healthcare Demo on ZGX Fury via ZRT");
  await expect(page.getByRole("link", { name: /^HP Aware Care on .+, home$/ })).toContainText("on HP ZGX Fury");
  await expect(strip(page)).toContainText("HP ZGX Fury");
  await expect(page.getByText("ZGX Nano")).toHaveCount(0);
  await page.goto("/telemetry");
  await expect(page.getByRole("heading", { level: 1, name: "Local AI on the HP ZGX Fury: usage, cost and privacy" }))
    .toBeVisible();
});

// #537: on any other NVIDIA machine demo.sh names the device from DMI; the site, lockup and signature use that name.
test("the deployment's device names the site on another NVIDIA machine (#537)", async ({ page }) => {
  await page.route("**/aware-care-device.js", (route) => route.fulfill({ contentType: "application/javascript",
    body: 'window.AWARE_CARE_DEVICE = { name: "HP Z8 Fury G5 Workstation Desktop PC", shortName: "Z8 Fury G5" };' }));
  await page.goto("/");
  await expect(page).toHaveTitle("Aware Care - Local AI Healthcare Demo on Z8 Fury G5 via ZRT");
  await expect(page.getByRole("link", { name: /^HP Aware Care on .+, home$/ })).toContainText("on HP Z8 Fury G5 Workstation Desktop PC");
  await expect(strip(page)).toContainText("Patient data stays on the Z8 Fury G5");
  await expect(page.getByText("ZGX")).toHaveCount(0);
});

test("under the gateway policy the browser itself refuses requests that would leave the device (#157)", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-1440", "runs once");
  const offenders = guardNetwork(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const outcome = await page.evaluate(async () => {
    const blocked: string[] = [];
    document.addEventListener("securitypolicyviolation", (e) => blocked.push(`${e.violatedDirective} ${e.blockedURI}`));
    const tries = await Promise.allSettled([
      fetch("https://cdn.example.org/font.woff2", { mode: "no-cors" }),
      fetch("https://www.google-analytics.com/collect", { method: "POST", body: "x", mode: "no-cors" }),
      fetch("https://api.example.org/api/v1/cases", { mode: "no-cors" }),
      fetch("data:text/plain,x"),
    ]);
    await new Promise((r) => setTimeout(r, 200));
    return { rejected: tries.filter((t) => t.status === "rejected").length, blocked };
  });
  expect(outcome.rejected).toBe(4);
  expect(outcome.blocked.filter((b) => b.startsWith("connect-src")).length).toBe(4);
  expect(offenders).toEqual([]); // refused before any request was made
});

test("every screen of a case keeps the Fury's site name, including empty and complete states (#155)", async ({ page }) => {
  test.setTimeout(120_000);
  await page.route("**/aware-care-device.js", (route) =>
    route.fulfill({ contentType: "application/javascript", body: FURY_DEVICE }));
  const caseId = await toGuidance(page);
  // After guidance, /review renders "This step is complete" and /doctors (before a search) an empty state:
  // neither renders PageHead, which used to be the only place that set the title.
  for (const path of ["review", "doctors", "questions", "records", "guidance", "summary"]) {
    await page.goto(`/app/cases/${caseId}/${path}`);
    await expect(page.locator("h1").first()).toBeVisible();
    await expect(page, path).toHaveTitle("Aware Care - Local AI Healthcare Demo on ZGX Fury via ZRT");
  }
  for (const path of ["/app/cases/00000000-0000-4000-8000-000000000000/review", "/app/limits"]) {
    await page.goto(path);
    await expect(page.locator("h1").first()).toBeVisible();
    await expect(page, path).toHaveTitle("Aware Care - Local AI Healthcare Demo on ZGX Fury via ZRT");
  }
});

test("a full journey, the telemetry slide and the presenter screens run under the gateway policy without a violation (#157)", async ({ page, context }) => {
  test.setTimeout(180_000);
  // Record every CSP violation the browser reports, on every page of this context.
  await context.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  const console: string[] = [];
  page.on("console", (m) => { if (/Content Security Policy|Refused to/i.test(m.text())) console.push(m.text()); });
  const violations = async () => (await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)) ?? [];
  const found: string[] = [];
  const response = await page.goto("/");
  expect(response?.headers()["content-security-policy"], "the test server sends the policy").toContain("frame-ancestors 'none'");
  expect(response?.headers()["x-frame-options"]).toBe("DENY");
  const caseId = await toGuidance(page);
  found.push(...await violations());
  for (const path of [`/app/cases/${caseId}/sources`, `/app/cases/${caseId}/summary`, "/help", "/privacy"]) {
    await page.goto(path);
    await expect(page.locator("h1").first()).toBeVisible();
    found.push(...await violations());
  }
  await page.addInitScript(() => localStorage.setItem("awarecare.telemetry.view", "advanced")); // #547: the advanced view
  await page.goto("/telemetry");
  await expect(page.getByRole("img", { name: /Slide preview/ })).toBeVisible();
  const [png] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download PNG" }).click()]);
  expect(png.suggestedFilename()).toMatch(/\.png$/);
  found.push(...await violations());
  await page.goto("http://127.0.0.1:15174/presenter/runtime");
  await expect(page.locator("h1").first()).toBeVisible();
  found.push(...await violations());
  expect(found, found.join("\n")).toEqual([]);
  expect(console, console.join("\n")).toEqual([]);
});

test("a missing or malformed device script falls back to the ZGX Nano", async ({ page }) => {
  await page.route("**/aware-care-device.js", (route) =>
    route.fulfill({ contentType: "application/javascript", body: 'window.AWARE_CARE_DEVICE = { name: "<b>x</b>" };' }));
  await page.goto("/");
  await expect(page).toHaveTitle(SITE_TITLE);
  await expect(strip(page)).toContainText("HP ZGX Nano");
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await page.route("**/aware-care-device.js", (route) => route.fulfill({ status: 404, body: "" }));
  await page.goto("/help");
  await expect(page).toHaveTitle(SITE_TITLE);
  await expect(strip(page)).toContainText("HP ZGX Nano");
});
