// W06 slide export (#129, ADR-017): the telemetry figures as one 16:9 slide, built on the device as a self-contained
// SVG (the HP logo is embedded; Arial/Helvetica only, so nothing is fetched) and drawn to PNG on a canvas. Every figure
// keeps its basis label; estimates name their comparison and assumptions; healthcare outcomes stay Not measured.

// "design" (#292, #325): follows from the architecture (no cloud AI call exists); not a measurement.
export type Basis = "measured" | "estimated" | "not_measured" | "design";

export type SlideModel = {
  device: string;
  /** #437: mock mode runs no model; the slide is shared, so it says so in its title. */
  mock: boolean;
  period: string;
  generated: string;
  build: string | null;
  runtime: string | null;
  kpis: { label: string; value: string; basis: Basis; detail: string }[];
  bars: { label: string; value: number | null; tone: "cloud" | "frontier" | "frontier2" | "local"; note: string }[];
  barsNote: string;
  /** #477: "not_measured" when no bar has a value, so an empty panel is not badged Estimated. */
  barsBasis: Basis;
  scenario: { title: string; cloud: string; device: string; payback: string; detail: string };
  /** #547: the page's one-line cost message (marginal cost per consultation, then the break-even). */
  message: string;
  privacy: string;
  sources: string[];
  /** Sentences that must never be cut (R39 and the demonstration notice); their lines are reserved first. */
  required: string;
  logoSvg: string | null;
};

export const SLIDE_W = 1600;
export const SLIDE_H = 900;

const C = {
  ink: "#132b3a", muted: "#4a6372", hairline: "#e3ebf0", sunken: "#eef3f7", surface: "#ffffff", canvas: "#f7fafc",
  brand: "#024ad8", cloud: "#a5470f", frontier: "#6b3fa0", frontier2: "#0b6e63", local: "#024ad8",
  measuredInk: "#1e6b47", measuredBg: "#ebf7f0", estimatedInk: "#0b3aa8", estimatedBg: "#eaf1fe", noneInk: "#3d5566",
  noneBg: "#eef3f7", designInk: "#5b2d96", designBg: "#f3eefb",
};
const FONT = "Arial, Helvetica, sans-serif";
const LABEL: Record<Basis, string> = { measured: "Measured", estimated: "Estimated", not_measured: "Not measured", design: "By design" };

export function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function text(x: number, y: number, s: string, size: number, opts: { weight?: number; fill?: string; anchor?: string } = {}) {
  return `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${opts.weight ?? 400}" fill="${opts.fill ?? C.ink}"${opts.anchor ? ` text-anchor="${opts.anchor}"` : ""}>${esc(s)}</text>`;
}

function badge(x: number, y: number, basis: Basis, anchor: "start" | "end" = "start") {
  const label = LABEL[basis];
  const w = 14 + label.length * 8.2;
  const left = anchor === "end" ? x - w : x;
  const [ink, bg] = basis === "measured" ? [C.measuredInk, C.measuredBg] : basis === "estimated" ? [C.estimatedInk, C.estimatedBg]
    : basis === "design" ? [C.designInk, C.designBg] : [C.noneInk, C.noneBg];
  return `<rect x="${left}" y="${y - 17}" width="${w}" height="24" rx="12" fill="${bg}"/>` +
    text(left + w / 2, y, label, 14, { weight: 700, fill: ink, anchor: "middle" });
}

/** The smallest amount shown as a number: a hundredth of a cent. */
export const USD_FLOOR = 0.0001;
/** From here on, amounts read in words ("$1.23 billion"). */
const USD_WORDS = 1e9;
/** The largest amount shown as a number; anything above (or infinite) reads "more than $999 trillion". */
const USD_CAP = 999.5e12;

/** The telemetry page's and slide's one money style (#472), never in exponent notation (#492): "$0.00" for zero;
 * two significant digits below $1 ("$0.21", "$0.00046"); "less than $0.0001" below a hundredth of a cent (before:
 * "$1.8e-8"); cents below $100 ("$12.50"); whole dollars with thousands separators below $1 billion ("$7,699"); then
 * three significant digits in words ("$1.23 billion", "$45 trillion"); "more than $999 trillion" beyond that. */
export function usd(n: number): string {
  if (Number.isNaN(n)) return "—";
  if (n === 0) return "$0.00";
  const a = Math.abs(n), sign = n < 0 ? "-" : "";
  if (a < USD_FLOOR) return n < 0 ? "$0.00" : "less than $0.0001";
  if (a >= USD_CAP) return n < 0 ? "less than -$999 trillion" : "more than $999 trillion";
  const small = Number(a.toPrecision(2));
  if (small < 1) return `${sign}$${small.toLocaleString("en-US", { minimumSignificantDigits: 2, maximumSignificantDigits: 2 })}`;
  if (Number(a.toFixed(2)) < 100) return `${sign}$${a.toFixed(2)}`;
  if (Math.round(a) < USD_WORDS) return `${sign}$${Math.round(a).toLocaleString("en-US")}`;
  return `${sign}$${new Intl.NumberFormat("en-US", { notation: "compact", compactDisplay: "long", maximumSignificantDigits: 3 }).format(a)}`;
}

/** Wraps a line of footnote text at roughly `max` characters. */
function wrap(s: string, max: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const word of s.split(" ")) {
    if ((line + " " + word).trim().length > max) { out.push(line.trim()); line = word; } else line += " " + word;
  }
  if (line.trim()) out.push(line.trim());
  return out;
}

/**
 * The footnote's lines below the privacy line (y 824 to the slide's edge). The required sentences are always shown:
 * their lines are reserved first, and the sources fill the rest. When the sources do not fit at 13 px in 4 lines, a
 * smaller 11 px type gives 5; sources that still do not fit end with an ellipsis, never the required sentences.
 */
export function footnote(sources: string[], required: string): { line: string; y: number; size: number }[] {
  for (const [size, step, max, lines] of [[13, 18, 190, 4], [11, 15, 225, 5]] as const) {
    const req = wrap(required, max);
    const src = sources.flatMap((s) => wrap(s, max));
    const room = lines - req.length;
    if (src.length <= room || size === 11) {
      const kept = src.slice(0, Math.max(0, room));
      if (src.length > kept.length && kept.length) kept[kept.length - 1] = `${kept[kept.length - 1].replace(/[.;,]?$/, "")} …`;
      return [...kept, ...req].map((line, j) => ({ line, y: 824 + j * step, size }));
    }
  }
  return [];
}

export function buildSlideSvg(m: SlideModel): string {
  const parts: string[] = [];
  parts.push(`<rect width="${SLIDE_W}" height="${SLIDE_H}" fill="${C.canvas}"/>`);
  parts.push(`<rect x="0" y="0" width="${SLIDE_W}" height="10" fill="${C.brand}"/>`);
  if (m.logoSvg) {
    parts.push(`<image x="60" y="44" width="64" height="64" href="data:image/svg+xml;base64,${btoa(m.logoSvg)}"/>`);
  }
  parts.push(text(m.logoSvg ? 144 : 60, 84, m.mock ? "Aware Care in mock mode: scripted results, no AI model" : `Aware Care: local AI on the ${m.device}`, 40, { weight: 700 }));
  parts.push(text(m.logoSvg ? 144 : 60, 116, `Telemetry · ${m.period} · ${m.generated}${m.mock ? ` · ${m.device}, mock mode` : ""}${m.runtime ? ` · ${m.runtime}` : ""}${m.build ? ` · build ${m.build}` : ""}`, 18, { fill: C.muted }));

  // Headline figures: #547, the basic view's (3 to 5 cards across the slide). The basis badge sits on its own line
  // below the label, so a narrow card never overlaps them.
  const kpis = m.kpis.slice(0, 5);
  const n = Math.max(1, kpis.length);
  const kw = (SLIDE_W - 120 - (n - 1) * 20) / n;
  const chars = Math.floor((kw - 40) / 7.4);
  kpis.forEach((k, i) => {
    const x = 60 + i * (kw + 20);
    parts.push(`<rect x="${x}" y="140" width="${kw}" height="170" rx="16" fill="${C.surface}" stroke="${C.hairline}"/>`);
    parts.push(text(x + 20, 170, k.label, 17, { weight: 700, fill: C.muted }));
    parts.push(badge(x + 20, 198, k.basis));
    const size = Math.min(40, Math.floor((kw - 40) / (Math.max(6, k.value.length) * 0.56)));
    parts.push(text(x + 20, 246, k.value, size, { weight: 700 }));
    wrap(k.detail, chars).slice(0, 2).forEach((line, j) => parts.push(text(x + 20, 274 + j * 18, line, 14, { fill: C.muted })));
  });

  // #547: the cost per consultation: the device's electricity against each cloud API's list price.
  parts.push(`<rect x="60" y="330" width="860" height="384" rx="16" fill="${C.surface}" stroke="${C.hairline}"/>`);
  parts.push(text(88, 374, "Cost per consultation", 24, { weight: 700 }));
  parts.push(badge(892, 374, m.barsBasis, "end"));
  wrap(m.barsNote, 92).slice(0, 2).forEach((line, j) => parts.push(text(88, 402 + j * 20, line, 15, { fill: C.muted })));
  const max = Math.max(...m.bars.map((b) => b.value ?? 0), 1e-12);
  m.bars.slice(0, 4).forEach((b, i) => {
    const y = 456 + i * 66;
    parts.push(text(88, y, b.label, 18, { weight: 700 }));
    parts.push(text(892, y, b.value == null ? "Not measured" : usd(b.value), 20, { weight: 700, anchor: "end" }));
    parts.push(`<rect x="88" y="${y + 10}" width="804" height="14" rx="4" fill="${C.sunken}"/>`);
    if (b.value != null) parts.push(`<rect x="88" y="${y + 10}" width="${Math.max(4, (b.value / max) * 804)}" height="14" rx="4" fill="${C[b.tone]}"/>`);
    parts.push(text(88, y + 40, b.note, 13, { fill: C.muted }));
  });

  // The calculator's scenario.
  parts.push(`<rect x="944" y="330" width="596" height="384" rx="16" fill="${C.surface}" stroke="${C.hairline}"/>`);
  parts.push(badge(972, 368, "estimated"));
  wrap(m.scenario.title, 44).slice(0, 2).forEach((line, j) => parts.push(text(972, 404 + j * 28, line, 22, { weight: 700 })));
  const rows: [string, string][] = [["Cloud API per month", m.scenario.cloud], ["This device per month", m.scenario.device], ["Device pays for itself", m.scenario.payback]];
  rows.forEach(([label, value], i) => {
    const y = 478 + i * 64;
    parts.push(text(972, y, label, 16, { weight: 700, fill: C.muted }));
    parts.push(text(972, y + 34, value, 30, { weight: 700 }));
  });
  // #477: three lines, so a fallback or assumed basis is never cut from the scenario.
  wrap(m.scenario.detail, 64).slice(0, 3).forEach((line, j) => parts.push(text(972, 664 + j * 18, line, 14, { fill: C.muted })));

  // #547: the one-line cost message, between the panels and the privacy line.
  wrap(m.message, 170).slice(0, 2).forEach((line, j) => parts.push(text(60, 738 + j * 19, line, 15, { weight: 700 })));

  // Privacy and footnote.
  parts.push(`<circle cx="74" cy="782" r="10" fill="${C.measuredInk}"/>`);
  parts.push(`<path d="M69 782l4 4 7-8" stroke="#ffffff" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`);
  parts.push(text(94, 788, m.privacy, 18, { weight: 700, fill: C.measuredInk }));
  footnote(m.sources, m.required).forEach(({ line, y, size }) => parts.push(text(60, y, line, size, { fill: C.muted })));

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${SLIDE_W}" height="${SLIDE_H}" viewBox="0 0 ${SLIDE_W} ${SLIDE_H}" role="img" aria-label="Aware Care telemetry slide">` +
    `<title>Aware Care telemetry · ${esc(m.period)}</title>${parts.join("")}</svg>`;
}

/** Draws the SVG on a canvas at `scale` and returns a PNG blob; nothing leaves the device. */
export async function svgToPng(svg: string, scale = 2): Promise<Blob> {
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = SLIDE_W * scale;
    canvas.height = SLIDE_H * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas unavailable");
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0, SLIDE_W, SLIDE_H);
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("png"))), "image/png"));
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Saves a blob through a temporary object URL (a local download; no request leaves the device). */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
