// Shared settings for the device specs (#367): a deployed release reached through a tunnel or forwarder on loopback
// (#487: one address, 127.0.0.1:18180, for patients and presenters), selected by environment variables:
//   DEVICE   Fury | Nano (required)
//   MODEL    the model manifest id the telemetry page names (default: the device's manifest in infra/)
//   OUT_DIR  where results and screenshots go (SHOT_DIR is accepted too; default test-results/devices/<device>)
//   RELEASE  optional tag shown in test titles; nothing else depends on it
//   ZRT_VERSION optional; default: the version recorded in the device's model manifest
// Nothing here sends data anywhere: offDevice() records every request that is not to 127.0.0.1 so a spec can fail on it.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { BrowserContext, Page } from "@playwright/test";

const REPO = resolve(__dirname, "../../..");
const raw = process.env.DEVICE ?? "";
if (raw !== "Fury" && raw !== "Nano") throw new Error(`DEVICE must be Fury or Nano (got ${JSON.stringify(raw)})`);
export const DEV: "Fury" | "Nano" = raw;
export const OTHER = DEV === "Fury" ? "Nano" : "Fury";
const infra = (file: string) => JSON.parse(readFileSync(join(REPO, "infra", DEV === "Fury" ? "fury" : "", file), "utf8"));
const manifest = infra("model-manifest.json");
export const MODEL: string = process.env.MODEL || manifest.manifest_id;
export const ZRT_VERSION: string = process.env.ZRT_VERSION || manifest.runtime.zrt_version_observed;
export const TAG = process.env.RELEASE ? `${process.env.RELEASE} ` : "";
// #487: the one address of both roles (the presenter tools are its /presenter/... pages); the configuration's baseURL.
export const BASE = "http://127.0.0.1:18180";
export const OUT = resolve(process.env.OUT_DIR ?? process.env.SHOT_DIR ?? join(REPO, "apps/web/test-results/devices", DEV.toLowerCase()));
mkdirSync(OUT, { recursive: true });

// From the device's reviewed pricing file: the slide's price line as W06 builds it, and the cost bars' labels.
const pricing = infra("telemetry-pricing.json");
const price = pricing.assumptions.device_price_usd as { value: number; label: string };
export const COST_BARS: string[] = [...(pricing.cloud_references as { short_label: string }[]).map((r) => r.short_label), "This device (electricity)"];
export const PRICE = `Device $${price.value.toLocaleString("en-US")} ${/\bestimate/i.test(price.label) ? "estimated price" : "list price"}; electricity`;

export const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\@]/g, "\\$&");
export const width = (projectName: string) => (projectName.includes("360") ? 360 : 1440);

export function offDevice(target: Page | BrowserContext): string[] {
  const off: string[] = [];
  target.on("request", (r) => {
    const u = new URL(r.url());
    if (!["data:", "blob:"].includes(u.protocol) && u.hostname !== "127.0.0.1") off.push(r.url());
  });
  return off;
}

export function cspErrors(page: Page): string[] {
  const errs: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && /Content Security Policy|Refused to/i.test(m.text())) errs.push(m.text()); });
  return errs;
}

// Results are merged per file so the 1440 and 360 projects write into one JSON object.
export function mergeResult(file: string, values: Record<string, unknown>) {
  const path = join(OUT, file);
  let previous: Record<string, unknown> = {};
  try { previous = JSON.parse(readFileSync(path, "utf8")); } catch { /* first write */ }
  writeFileSync(path, JSON.stringify({ ...previous, ...values }, null, 1));
}

// #493: the A12 summary preview's sections as #417 defines them (spec/screens.json, A12 validation rule "#417: the
// preview shows every section the PDF prints, in the PDF's order and under the same titles"), for a local-mode
// consultation without a doctor search: 9 sections, "Suggested next steps" in the plural outside mock mode. Before
// #417 the preview had 5 cards. tests/tooling/test_device_specs.py checks this list against the spec's.
export const SUMMARY_SECTIONS = ["Main concern", "What you reported", "Unresolved or unknown details", "Suggested level of care",
  "Suggested next steps", "Possible explanations", "Questions for a clinician", "When to seek help sooner", "Sources"];

/** The summary PDF's section headings without the PDF's labels in parentheses (Helvetica-Bold 12 pt, F2; a wrapped
 * heading continues on the next such line), as tests/ui/summary-review.spec.ts reads them in mock mode. */
export function pdfHeadings(pdf: Buffer): string[] {
  const drawn = [...pdf.toString("latin1").matchAll(/\/(F\d) ([\d.]+) Tf 1 0 0 1 [\d.]+ [\d.]+ Tm \(((?:\\.|[^\\)])*)\) Tj/g)]
    .map((m) => ({ heading: m[1] === "F2" && m[2] === "12", text: m[3].replace(/\\(.)/g, "$1") }));
  const out: string[] = [];
  drawn.forEach((d, i) => {
    if (!d.heading) return;
    if (drawn[i - 1]?.heading) out[out.length - 1] += ` ${d.text}`;
    else out.push(d.text);
  });
  return out.map((h) => h.split(" (")[0]);
}
