// W06 Telemetry (M12; R34, R38, R39; ADR-017). What the local AI did on this ZGX device, and what the same work would
// cost through a cloud LLM API. Every figure carries a basis: Measured (read on this device), Estimated (computed from
// measured values and the stated, editable assumptions, with the formula shown) or Not measured. Healthcare outcomes
// stay Not measured (R39). Nothing is fetched from outside the device: the API returns content-free aggregates plus the
// reviewed price list, and the charts are drawn here in SVG (R34).
// #547: two views. Basic (the default) is what a presenter explains in under 30 seconds: five headline figures and one
// cost sentence. Advanced holds every figure, in sections (usage, latency, tokens, energy, cost, break-even, privacy,
// model and runtime, reliability). The choice is remembered per browser.
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type S } from "../api/client";
import { DEVICE, RUNTIME } from "../components/Brand";
import { Icon } from "../components/Icon";
import { ErrorBanner, formatDate, formatDateTime, formatTime, LoadingState, MONTHS, PageHead, ScrollTable, StatusBanner } from "../components/ui";
// #513: the logo's SVG text, bundled at build time; a runtime fetch() of an inlined data: URL is refused by connect-src.
import hpLogoSvg from "../assets/brand/HP_logo_2025.svg?raw";
import { buildSlideSvg, saveBlob, svgToPng, usd, type SlideModel } from "./W06Slide";
import { breakEvenConsultations, cloudCumulative, cloudPerConsultation, costMessage, DAYS_PER_MONTH, deviceCumulative,
  localPerConsultation, outcomes, type RefOutcome } from "./W06Cost";
import "./W06.css";

type T = S["TelemetrySnapshot"];
type Period = "24h" | "7d" | "release";
type View = "basic" | "advanced";
// "design" (#292): a property of the architecture (no cloud AI call exists), not a measurement.
type Basis = "measured" | "estimated" | "not_measured" | "design";
type CloudRef = NonNullable<T["pricing"]>["cloud_references"][number];
type Tone = "cloud" | "frontier" | "frontier2" | "local";

const PERIODS: [Period, string][] = [
  ["24h", "Last 24 hours"],
  ["7d", "Last 7 days"],
  ["release", "Since this release"],
];
const VIEWS: [View, string][] = [["basic", "Basic"], ["advanced", "Advanced"]];
/** #547: the view is remembered in this browser only; storage may be unavailable (private mode), so never required. */
export const VIEW_KEY = "awarecare.telemetry.view";
function storedView(): View {
  try {
    return window.localStorage.getItem(VIEW_KEY) === "advanced" ? "advanced" : "basic";
  } catch {
    return "basic";
  }
}
function storeView(v: View): void {
  try {
    window.localStorage.setItem(VIEW_KEY, v);
  } catch {
    /* not remembered; the page still works */
  }
}
const BASIS_LABEL: Record<Basis, string> = { measured: "Measured", estimated: "Estimated", not_measured: "Not measured", design: "By design" };
// Volume presets for the calculator: assumptions a presenter can pick, labeled as such; the default stays measured.
const PRESETS: [string, number][] = [["Small clinic", 50], ["Busy practice", 200], ["Health system", 2000]];

function paybackText(months: number | null, lifetime: number, cloudDearer: boolean): string {
  // #572: when the cloud API is not dearer per consultation, no volume pays the device back
  if (months == null) return cloudDearer ? "Not at this volume" : "Never";
  if (months < 1) return "Within a month";
  if (months > lifetime) return months > 120 ? "Not within 10 years" : `${months.toFixed(1)} months (beyond the lifetime)`;
  return `${months.toFixed(1)} months`;
}
const REFRESH_MS = 60_000;

export function BasisBadge({ basis }: { basis: Basis }) {
  return <span className={`basis basis-${basis}`}>{BASIS_LABEL[basis]}</span>;
}

const int = (n: number) => n.toLocaleString("en-US");
const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);
/** "1.5 days", "7 days", "1 day". */
const dayCount = (n: number) => `${Number.isInteger(n) ? n : n.toFixed(1)} ${n === 1 ? "day" : "days"}`;
/** "1 consultation", "20 consultations" (#477). */
const count = (n: number, one: string, many = `${one}s`) => `${int(n)} ${n === 1 ? one : many}`;
/** #472: one date style on the page: ISO dates quoted in the reviewed price list's text read "16 Oct 2026". */
const humanDates = (s: string) => s.replace(/\b\d{4}-\d{2}-\d{2}\b/g, (d) => formatDate(d));
const secs = (ms: number | null | undefined) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)} s`);
const cloudCost = (ref: CloudRef, inTok: number, outTok: number) => cloudPerConsultation(ref, inTok, outTok);
/** The cloud API's name without its group ("Frontier API: GPT-6 Astra" → "GPT-6 Astra"), for chart labels. */
const shortName = (label: string) => label.replace(/^[^:]*:\s*/, "");
/** A cloud reference named for a sentence: "the same model in the cloud", "GPT-6 Astra (frontier API)". */
const speak = (r: CloudRef) => (r.comparison === "frontier" ? `${shortName(r.short_label)} (frontier API)` : "the same model in the cloud");
/** A round step for a money axis: 1, 2, 2.5 or 5 times a power of ten. */
function niceStep(raw: number): number {
  const p = 10 ** Math.floor(Math.log10(raw));
  return ([1, 2, 2.5, 5, 10].find((f) => f * p >= raw) ?? 10) * p;
}
const toneOf = (r: CloudRef, refs: CloudRef[]): Tone =>
  r.comparison === "frontier" ? (refs.filter((x) => x.comparison === "frontier")[0] === r ? "frontier" : "frontier2") : "cloud";

function Tile({ label, value, detail, basis, className }: { label: string; value: ReactNode; detail?: ReactNode; basis: Basis; className?: string }) {
  return (
    <div className={className ? `kpi ${className}` : "kpi"}>
      <div className="kpi-top">
        <span className="kpi-label">{label}</span>
        <BasisBadge basis={basis} />
      </div>
      <p className="kpi-value">{value}</p>
      {detail && <p className="small muted">{detail}</p>}
    </div>
  );
}

function Bars({ rows, title }: { rows: { label: string; value: number | null; tone: string; note: string }[]; title: string }) {
  const max = Math.max(...rows.map((r) => r.value ?? 0), 1e-12);
  return (
    <figure className="bars" aria-label={title}>
      {rows.map((r) => (
        <div className="bar-row" key={r.label}>
          <span className="bar-label">{r.label}</span>
          <svg className="bar-track" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
            <rect x="0" y="0" width="100" height="10" rx="2" className="bar-bg" />
            {r.value != null && <rect x="0" y="0" width={Math.max(0.6, (r.value / max) * 100)} height="10" rx="2" className={`bar-fill ${r.tone}`} />}
          </svg>
          <span className="bar-value">{r.value == null ? "Not measured" : usd(r.value)}</span>
          <span className="bar-note small muted">{r.note}</span>
        </div>
      ))}
    </figure>
  );
}

type Series = { id: string; label: string; cloudPer: number; tone: Tone; selected: boolean; dash: string; dashName: string };
// #547: each cloud line differs by more than colour (#447): the selected one is solid; the others dotted or dash-dot.
const OTHER_DASHES: [string, string][] = [["2 5", "dotted line"], ["12 4 2 4", "dash-dot line"], ["6 6", "dashed thin line"]];

/** #547: cumulative cost over the device lifetime at the calculator's volume. The device starts at its price (paid
 * once) and rises by its electricity; each cloud API starts at zero and rises by its price per consultation. Where a
 * cloud line overtakes the device's, the device has become cheaper: that point is marked, and the savings after it are
 * shaded and labeled. The x axis reads in months and in consultations. */
function BreakEvenChart({ months, perDay, device, localPer, series }: { months: number; perDay: number; device: number; localPer: number; series: Series[] }) {
  // #547: on a phone the chart is drawn for its own width (fewer, larger units), so its labels never collide.
  const narrow = useNarrow();
  // #571: on a phone the top tick label sits below the "no break-even" note, which spans most of the width
  const w = narrow ? 360 : 640, h = narrow ? 340 : 320, pad = { l: 6, r: 6, t: narrow ? 44 : 28, b: narrow ? 56 : 76 };
  const gap = narrow ? 17 : 24;
  const monthlyN = perDay * DAYS_PER_MONTH;
  const horizon = monthlyN * months;
  const localEnd = deviceCumulative(device, localPer, horizon);
  const ends = series.map((s) => cloudCumulative(s.cloudPer, horizon));
  // Round tick values ($2,500, $5,000, ...), so the axis reads at a glance.
  const step = niceStep(Math.max(localEnd, ...ends, 1) * 1.06 / 4);
  const top = Math.ceil((Math.max(localEnd, ...ends, 1) * 1.06) / step) * step;
  const x = (m: number) => pad.l + (m / months) * (w - pad.l - pad.r);
  const y = (v: number) => h - pad.b - (v / top) * (h - pad.t - pad.b);
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);
  const crossings = series.map((s) => {
    const n = breakEvenConsultations(device, s.cloudPer, localPer);
    return n != null && monthlyN > 0 && n <= horizon ? { s, n, m: n / monthlyN } : null;
  });
  const sel = series.find((s) => s.selected);
  // The shaded savings: against the selected cloud API when it is overtaken in the lifetime, else the earliest one.
  const shaded = crossings.find((c) => c && c.s.selected) ?? crossings.filter((c) => c).sort((a, b) => a!.m - b!.m)[0] ?? null;
  const savedEnd = shaded ? cloudCumulative(shaded.s.cloudPer, horizon) - localEnd : 0;
  const summary = shaded
    ? `This device becomes cheaper than ${shaded.s.label} after ${int(Math.ceil(shaded.n))} consultations (${shaded.m.toFixed(1)} months); by month ${months} it has saved ${usd(savedEnd)}.`
    : `Within ${months} months at this volume, no cloud API shown overtakes this device's price.`;
  const anchor = (px: number) => (px > w * 0.62 ? "end" : px < w * 0.25 ? "start" : "middle");
  // Direct labels at the end of each line (#447: not colour alone), kept 24 units apart so they never overlap.
  const labels = [{ key: "local", text: "This device", y: y(localEnd), tone: "local" },
    ...series.map((s, i) => ({ key: s.id, text: shortName(s.label), y: y(ends[i]), tone: s.tone }))].sort((p, q) => p.y - q.y);
  labels.forEach((l, i) => { l.y = Math.min(l.y - 6, h - pad.b - 4); if (i && l.y - labels[i - 1].y < gap) l.y = labels[i - 1].y + gap; });
  // #571: lines bunched near $0 pushed the last labels below the plot, onto the axis labels: lift the stack back up.
  for (let i = labels.length - 1; i >= 0; i--) {
    const limit = i === labels.length - 1 ? h - pad.b - 4 : labels[i + 1].y - gap;
    if (labels[i].y > limit) labels[i].y = limit;
  }
  const tri = shaded ? [[x(shaded.m), y(cloudCumulative(shaded.s.cloudPer, shaded.n))], [x(months), y(cloudCumulative(shaded.s.cloudPer, horizon))], [x(months), y(localEnd)]] : [];
  return (
    <svg className={narrow ? "line-chart breakeven-chart narrow" : "line-chart breakeven-chart"} viewBox={`0 0 ${w} ${h}`} role="img"
      aria-label={`Cumulative cost over ${months} months (${int(Math.round(horizon))} consultations): ${series.map((s, i) => `${s.label} ${usd(ends[i])}`).join(", ")}; this device ${usd(localEnd)}. ${summary}`}>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={w - pad.r} y1={y(v)} y2={y(v)} className="grid" />
          <text x={pad.l + 4} y={y(v) - 6} textAnchor="start" className="axis">{usd(v)}</text>
        </g>
      ))}
      {/* #439: the middle tick keeps its decimal, so no two labels read the same ("0 mo, 0.5 mo, 1 mo"). #547: below
          each month, the consultations by then at this volume. */}
      {[0, months / 2, months].map((m, i) => (
        <g key={m}>
          <text x={x(m)} y={h - (narrow ? 28 : 40)} textAnchor={(["start", "middle", "end"] as const)[i]} className="axis">{Number.isInteger(m) ? m : m.toFixed(1)} mo</text>
          <text x={x(m)} y={h - 10} textAnchor={(["start", "middle", "end"] as const)[i]} className="axis axis-n">
            {int(Math.round(m * monthlyN))}{i === 2 ? " consultations" : ""}
          </text>
        </g>
      ))}
      {shaded && (
        <polygon className="savings-area"
          points={`${x(shaded.m)},${y(cloudCumulative(shaded.s.cloudPer, shaded.n))} ${x(months)},${y(cloudCumulative(shaded.s.cloudPer, horizon))} ${x(months)},${y(localEnd)}`} />
      )}
      {series.filter((s) => !s.selected).map((s) => (
        <line key={s.id} x1={x(0)} y1={y(0)} x2={x(months)} y2={y(cloudCumulative(s.cloudPer, horizon))}
          className={`series-other tone-${s.tone}`} strokeDasharray={s.dash} />
      ))}
      {sel && <line x1={x(0)} y1={y(0)} x2={x(months)} y2={y(cloudCumulative(sel.cloudPer, horizon))} className={`series-cloud tone-${sel.tone}`} />}
      <line x1={x(0)} y1={y(device)} x2={x(months)} y2={y(localEnd)} className="series-local" />
      {crossings.map((c) => c && (
        <circle key={c.s.id} cx={x(c.m)} cy={y(cloudCumulative(c.s.cloudPer, c.n))} r={c === shaded ? 6 : 4.5} className="series-point" />
      ))}
      {shaded && (
        <>
          <text x={x(shaded.m)} y={y(cloudCumulative(shaded.s.cloudPer, shaded.n)) - 12} textAnchor={anchor(x(shaded.m))} className="chart-note">
            {narrow ? "Break-even" : `Break-even vs ${shortName(shaded.s.label)}`}: {shaded.m.toFixed(1)} mo
          </text>
          <text x={(tri[0][0] + 2 * tri[1][0]) / 3 - 8} y={(tri[0][1] + tri[1][1] + tri[2][1]) / 3 + 4} textAnchor="end" className="chart-note savings-note">
            Saved {usd(savedEnd)}
          </text>
        </>
      )}
      {labels.map((l) => (
        <text key={l.key} x={w - pad.r - 4} y={l.y} textAnchor="end" className={`end-label tone-${l.tone}`}>{l.text}</text>
      ))}
      {!shaded && (
        <text x={w - pad.r - 6} y={narrow ? 14 : pad.t - 10} textAnchor="end" className="chart-note">No break-even within {months} months at this volume</text>
      )}
    </svg>
  );
}

/** True below 700 px (the layout's phone breakpoint). */
function useNarrow(): boolean {
  const query = "(max-width: 700px)";
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia?.(query).matches === true);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
}

type FieldProps = {
  id: string; label: string; value: number; onChange: (v: number) => void; step: number; unit?: string;
  /** The smallest valid value and what to say below it (#439: a device lifetime is at least 1 month). */
  min?: number; minMessage?: string;
  /** #573: the largest valid value; far above it the figures overflow to ∞ and NaN (#492: 1e15 still reads in words). */
  max?: number;
  /** Changes when the value is set from outside (a preset) even to the value already in effect. */
  sync?: number;
};

/** #438: the field keeps what the viewer types. An empty, partial or out-of-range entry is not turned into another
 * number: it is marked invalid with a message, and the results keep the last valid value until the field holds one.
 * #442: the unit is part of the field's accessible name ("Device lifetime months"). */
function NumberField({ id, label, value, onChange, step, unit, min = 0, minMessage, max = 1e15, sync = 0 }: FieldProps) {
  const [text, setText] = useState(() => String(value));
  const [error, setError] = useState<string | null>(null);
  const emitted = useRef(value);
  const synced = useRef(sync);
  useEffect(() => {
    if (value === emitted.current && sync === synced.current) return; // the viewer's own entry: keep it as typed
    emitted.current = value;
    synced.current = sync;
    setText(String(value));
    setError(null);
  }, [value, sync]);
  function change(raw: string) {
    setText(raw);
    const v = Number(raw);
    // A number input reports "" for a partial entry such as "-" or "1e".
    const message = raw.trim() === "" || !Number.isFinite(v) ? "Enter a number."
      : v < min ? (minMessage ?? `Enter ${min} or more.`)
      : v > max ? `Enter ${max.toLocaleString("en-US")} or less.` : null;
    setError(message);
    if (message) return;
    emitted.current = v;
    onChange(v);
  }
  const unitId = `${id}-unit`, errorId = `${id}-error`;
  return (
    <div className="field">
      <label htmlFor={id} id={`${id}-label`}>{label}</label>
      <div className="row tight">
        <input id={id} type="number" inputMode="decimal" min={min} max={max} step={step} value={text}
          aria-labelledby={unit ? `${id}-label ${unitId}` : undefined}
          aria-invalid={error ? true : undefined} aria-describedby={error ? errorId : undefined}
          onChange={(e) => change(e.target.value)} />
        {unit && <span className="small muted" id={unitId}>{unit}</span>}
      </div>
      <div aria-live="polite">
        {error && <p className="field-error" id={errorId}>{error} The results use the last valid value, {value.toLocaleString("en-US", { maximumFractionDigits: 6 })}.</p>}
      </div>
    </div>
  );
}

// #638 (ADR-017 amendment 6): every figure counts the selected period up to now, including the current hour (event
// and call times keep the hour only). #324: the page names the window's start as an absolute date and hour (from
// consultations.counted_from), never "yesterday". #347: every date and time on this page is UTC, labeled, in the
// shared style of components/ui.tsx ("16 Oct 2026, 17:04 UTC").
const DAY_MS = 86_400_000;
const utcHour = (d: Date | string) => formatDateTime(d, { utc: true });

/** "20 Oct 2026, 15:00 UTC to now": a window from `fromIso` up to now, or with `compact` (the slide) "20 Oct, 15:00
 * UTC to now" (the year only when it is not the current one). */
export function toNow(fromIso: string, compact = false): string {
  const from = new Date(fromIso);
  if (!compact || from.getUTCFullYear() !== new Date().getUTCFullYear()) return `${utcHour(from)} to now`;
  return `${from.getUTCDate()} ${MONTHS[from.getUTCMonth()]}, ${formatTime(from, { utc: true })} to now`;
}

type OutcomeWindow = {
  heading: string; // the window, from the hour the period starts in up to now
  countingSince: Date | null; // #324: set when outcome counting started after the window began (mode recording)
  /** #436: the span actually counted (from the later of the window start and the counting start), for figures that
   * stand alone, such as the slide's. */
  counted: string;
  countedCompact: string;
  countedDays: number; // its length in days, in the whole hours counted (to the end of the current hour), for the measured volume (#398)
};

function outcomeWindow(c: T["consultations"]): OutcomeWindow {
  const since = c.counting_since ? new Date(c.counting_since) : null;
  const later = since != null && since.getTime() > Date.parse(c.counted_from);
  const from = later ? c.counting_since : c.counted_from;
  return {
    heading: toNow(c.counted_from),
    countingSince: later ? since : null,
    counted: toNow(from),
    countedCompact: toNow(from, true),
    countedDays: Math.max(0, (Date.parse(c.counted_to) - Date.parse(from)) / DAY_MS),
  };
}

/** The honest empty state for an outcome figure without samples (#638: a consultation counts at once). */
function emptyOutcome(w: OutcomeWindow): string {
  return `None yet (${w.counted}). A consultation counts as soon as its guidance is published.`;
}

// #271: the concern check is a task of its own. #324: shown with the outcome window (Reliability section).
const TASKS: [string, string][] = [["guidance", "Guidance"], ["red_flag_screen", "Red-flag screen"],
  ["certainty_review", "Safety review"], ["concern_check", "Concern check"], ["other", "Other"]];

/** #286, #547: a radio group of toggle buttons: one tab stop (the checked option) and arrow keys that move and select. */
function RadioButtons<K extends string>({ label, options, value, onChange, className }:
  { label: string; options: [K, string][]; value: K; onChange: (k: K) => void; className: string }) {
  const radios = useRef<(HTMLButtonElement | null)[]>([]);
  function onKey(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    const target = e.key === "Home" ? 0 : e.key === "End" ? options.length - 1 : step ? (index + step + options.length) % options.length : null;
    if (target === null) return;
    e.preventDefault();
    onChange(options[target][0]);
    radios.current[target]?.focus();
  }
  return (
    <div className={className} role="radiogroup" aria-label={label}>
      {options.map(([key, text], i) => (
        <button key={key} type="button" role="radio" aria-checked={value === key} tabIndex={value === key ? 0 : -1}
          ref={(el) => { radios.current[i] = el; }} onKeyDown={(e) => onKey(e, i)}
          className={value === key ? "seg on" : "seg"} onClick={() => onChange(key)}>
          {text}
        </button>
      ))}
    </div>
  );
}

export default function W06() {
  const [period, setPeriod] = useState<Period>("7d");
  const [view, setViewState] = useState<View>(storedView);
  const setView = (v: View) => { setViewState(v); storeView(v); };
  // #561: "Show every figure (Advanced)" unmounts itself; focus moves to the advanced view's first heading, so a
  // keyboard user continues there instead of at the top of the page (WCAG 2.4.3).
  const focusAdvanced = useRef(false);
  useEffect(() => {
    if (view !== "advanced" || !focusAdvanced.current) return;
    focusAdvanced.current = false;
    document.getElementById("usage-heading")?.focus();
  }, [view]);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  // #286: only the latest request may change the page, so a slow answer for an earlier period never replaces it.
  const latest = useRef(0);
  const load = useCallback(() => {
    const request = ++latest.current;
    setError(null);
    api.getTelemetry(period).then(
      (d) => request === latest.current && setData(d),
      (e) => request === latest.current && setError(e),
    );
  }, [period]);
  // #331: a link such as /telemetry#privacy (from W03) lands on its section once the figures have loaded. #547: a
  // section of the advanced view opens that view (for this visit; the remembered choice stays as it was).
  const landed = useRef(false);
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    if (!data || landed.current) return;
    landed.current = true;
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (!id || !/^[A-Za-z][\w-]*$/.test(id)) return;
    if (document.getElementById(id)) window.requestAnimationFrame(() => jump(null, id));
    else { setViewState("advanced"); setPending(id); }
  }, [data]);
  useEffect(() => {
    if (!pending || view !== "advanced") return;
    const id = pending;
    setPending(null);
    window.requestAnimationFrame(() => jump(null, id));
  }, [pending, view]);
  useEffect(() => {
    setData(null); // a new period seeds the calculator afresh; refreshes within a period keep the viewer's edits
    load();
  }, [load]);
  // #446 (WCAG 2.2.2): the minute-by-minute update can be stopped and started again; Refresh still loads on demand.
  const [auto, setAuto] = useState(true);
  useEffect(() => {
    if (!auto) return;
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load, auto]);

  return (
    <>
      <PageHead eyebrow="Telemetry" title={`Local AI on the ${DEVICE}: usage, cost and privacy`}>
        <p>
          What the AI did on this {DEVICE} through {RUNTIME}, and what the same work would cost through a cloud LLM API.
          No case content is shown here, and nothing on this page comes from outside the device.
        </p>
      </PageHead>
      <div className="view-switch">
        <span className="small muted" id="view-label">View</span>
        <RadioButtons label="View: basic or advanced" options={VIEWS} value={view} onChange={setView} className="segmented-group" />
        <span className="small muted view-hint">{view === "basic" ? "The headline figures, in plain words" : "Every figure, with its window and formula"}</span>
      </div>
      <div className="segmented">
        <RadioButtons label="Period" options={PERIODS} value={period} onChange={setPeriod} className="segmented-group" />
        <button type="button" className="btn secondary sm" onClick={load}>Refresh</button>
        <label className="auto-refresh small">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          Update every minute
        </label>
      </div>
      {data && view === "advanced" && <SectionNav sources={data.pricing != null} />}
      {error != null && <ErrorBanner error={error} onRetry={load} />}
      {!data && error == null && <LoadingState label="Loading telemetry" />}
      {data && <Body key={period} t={data} view={view} onAdvanced={() => { focusAdvanced.current = true; setView("advanced"); }} />}
    </>
  );
}

function Body({ t, view, onAdvanced }: { t: T; view: View; onAdvanced: () => void }) {
  const pricing = t.pricing;
  const refs = pricing?.cloud_references ?? [];
  const a = pricing?.assumptions;
  const mock = t.identity.mode === "mock";
  const guided = t.consultations.guided;
  const calls = t.ai_calls;
  const tokensMeasured = calls.with_token_counts > 0;
  const energyMeasured = t.energy.status === "measured" && t.energy.wh_total != null;
  const kwh = a?.electricity_usd_per_kwh.value ?? 0;
  // #124: AI calls are metered since the first telemetry release started; the live tiles say when that is later than
  // the period start. #638: every total counts up to now, including the current hour.
  const meteredLater = Date.parse(t.metered.since) > Date.parse(t.period.from) + 1000;
  const since = meteredLater ? ` · counted since ${utcHour(t.metered.since)}` : "";
  const win = outcomeWindow(t.consultations);
  const periodLabel = PERIODS.find(([k]) => k === t.period.key)?.[1] ?? t.period.key;
  // #437: mock mode runs no model: its scripted answers are counted like AI calls but never presented as AI work.
  const callsLabel = mock ? "Scripted calls" : "AI calls";

  // #398: per-consultation figures divide the AI calls, tokens, AI time and energy of `metered` by the consultations
  // guided in the SAME whole hours (the period up to now, from the counting and metering start). Measured where that
  // window has them; otherwise the labeled fallbacks.
  const m = t.metered;
  const meteredGuided = m.guided;
  const perWindow = toNow(m.from);
  const measuredPerConsult = meteredGuided > 0 && m.with_token_counts > 0;
  const measuredEnergy = meteredGuided > 0 && m.wh_total != null && m.calls_with_energy > 0;
  // #398, #468: the volume is the consultations guided over the days actually counted (from the counting start), and
  // it is labeled Measured whenever it comes from them; "Fallback" is only the documented fallback volume. #638: the
  // window runs up to now, so a per-day volume is measured once it spans at least a day (a release that started an hour
  // ago would extrapolate one consultation to 24 a day).
  const volumeMeasured = guided > 0 && win.countedDays >= 1;
  const defaults = useMemo(() => ({
    perDay: volumeMeasured ? Math.max(1, Math.round(guided / win.countedDays)) : a?.fallback_consultations_per_day.value ?? 20,
    inTok: measuredPerConsult ? Math.round(m.prompt_tokens / meteredGuided) : a?.fallback_tokens_per_consultation.input ?? 0,
    outTok: measuredPerConsult ? Math.round(m.completion_tokens / meteredGuided) : a?.fallback_tokens_per_consultation.output ?? 0,
    wh: measuredEnergy ? Number(((m.wh_total ?? 0) / meteredGuided).toFixed(4)) : 0,
    device: a?.device_price_usd.value ?? 0,
    months: a?.lifetime_months.value ?? 36,
    kwh,
    sysW: a?.other_system_power_w.value ?? 0,
  }), [guided, win.countedDays, volumeMeasured, m, meteredGuided, measuredPerConsult, measuredEnergy, a, kwh]);
  const [inputs, setInputs] = useState(defaults); // seeded once per period (Body is keyed by period)
  const [refId, setRefId] = useState(refs.find((r) => r.default)?.id ?? refs[0]?.id);
  const ref = refs.find((r) => r.id === refId) ?? refs[0];
  const set = (k: keyof typeof inputs) => (v: number) => setInputs((s) => ({ ...s, [k]: v }));
  // A preset sets the volume field even when its value is the one in effect (#438: the field may hold an entry).
  const [presetSync, setPresetSync] = useState(0);
  const preset = (n: number) => { set("perDay")(n); setPresetSync((x) => x + 1); };
  const tokensDefault = inputs.inTok === defaults.inTok && inputs.outTok === defaults.outTok;
  // #477: the slide names the basis of the scenario's volume and tokens, as the page does.
  const volumeBasis = inputs.perDay !== defaults.perDay ? "assumption" : volumeMeasured ? "measured" : "fallback";

  const periodCloud = refs.map((r) => ({ r, cost: tokensMeasured ? cloudCost(r, calls.prompt_tokens, calls.completion_tokens) : null }));
  const periodEnergyCost = energyMeasured ? ((t.energy.wh_total ?? 0) / 1000) * kwh : null;
  // #325: the value story at a glance: this period's work at the default (like-for-like) cloud reference's list
  // prices, against the measured GPU electricity, with the first frontier reference for scale.
  const headRef = refs.find((r) => r.default) ?? refs[0];
  const frontierRef = refs.find((r) => r.comparison === "frontier" && r !== headRef);
  const headCloud = tokensMeasured && headRef ? cloudCost(headRef, calls.prompt_tokens, calls.completion_tokens) : null;
  const perConsultCloud = ref ? cloudCost(ref, inputs.inTok, inputs.outTok) : 0;
  // #127: this page measures GPU power only. An assumed non-GPU system power is applied over the measured AI time per
  // consultation (labeled Estimated), so a wall-meter reading can be included. #398: from the same window as above.
  const aiSecondsPerConsult = meteredGuided > 0 ? m.duration_ms_total / 1000 / meteredGuided : 0;
  const perConsultWh = inputs.wh + (inputs.sysW * aiSecondsPerConsult) / 3600;
  const perConsultEnergy = localPerConsultation(perConsultWh, inputs.kwh);
  // #547: the device's running cost per consultation is known when its energy is measured or entered.
  const localKnown = perConsultWh > 0;
  const monthlyN = inputs.perDay * DAYS_PER_MONTH;
  const cloudMonthly = perConsultCloud * monthlyN;
  const energyMonthly = perConsultEnergy * monthlyN;
  // #439: the lifetime is at least 1 month (the field rejects less), so the device price is always amortized.
  const amortMonthly = inputs.device / inputs.months;
  const breakEvenMonths = cloudMonthly > energyMonthly ? inputs.device / (cloudMonthly - energyMonthly) : null;
  const cloudDearer = perConsultCloud > perConsultEnergy;
  const breakEvenPerDay = cloudDearer ? inputs.device / (inputs.months * DAYS_PER_MONTH * (perConsultCloud - perConsultEnergy)) : null;
  const breakEvenDetail = breakEvenPerDay == null ? "The cloud API is not more expensive per consultation"
    : breakEvenPerDay === 0 ? "At any volume: the device price is $0"
    : `Within the ${inputs.months}-month lifetime from about ${count(Math.ceil(breakEvenPerDay), "consultation")} per day`;

  // #547: the break-even story against every cloud reference, at the calculator's volume and over the lifetime.
  const scenario = { device: inputs.device, localPer: perConsultEnergy, perDay: inputs.perDay, months: inputs.months };
  const refOutcomes: RefOutcome[] = outcomes(scenario, refs.map((r) => ({ id: r.id, label: r.short_label, cloudPer: cloudCost(r, inputs.inTok, inputs.outTok) })));
  const selOutcome = refOutcomes.find((o) => o.id === ref?.id);
  const message = costMessage({ localPer: localKnown ? perConsultEnergy : null, defaultId: headRef?.id, s: scenario, usd,
    outcomes: refOutcomes.map((o, i) => ({ ...o, label: speak(refs[i]) })) });
  const horizon = Math.round(monthlyN * inputs.months);
  const volumeWords = volumeBasis === "measured" ? `measured on this device, ${win.counted}`
    : volumeBasis === "fallback" ? "a fallback assumption until consultations are measured" : "your entry";
  let dash = 0;
  const series: Series[] = refs.map((r, i) => {
    const selected = r.id === ref?.id;
    const [d, name] = selected ? ["", "solid line"] : OTHER_DASHES[dash++ % OTHER_DASHES.length];
    return { id: r.id, label: r.short_label, cloudPer: refOutcomes[i].cloudPer, tone: toneOf(r, refs), selected, dash: d, dashName: name };
  });

  // #547: the basic view's figures; the slide uses the same ones.
  const basic: { label: string; value: string; vs?: string; basis: Basis; detail: string; slide: boolean; slideDetail?: string }[] = [
    mock
      ? { label: "Where the AI runs", value: "No AI model", basis: "design", slide: true,
        detail: "Mock mode: the answers are scripted; no model runs" }
      : { label: "Where the AI runs", value: DEVICE.replace(/^HP /, ""), basis: "design", slide: true,
        detail: `The AI model runs on this ${DEVICE}, through ${RUNTIME}: no cloud AI` },
    { label: "Consultations guided", value: guided > 0 ? int(guided) : "None yet", basis: "measured", slide: guided > 0,
      detail: guided > 0 ? `People given ${mock ? "scripted guidance (mock mode)" : "guidance"}, ${win.countedCompact}` : emptyOutcome(win) },
    { label: "Typical time to guidance", value: t.latency.samples ? secs(t.latency.total_ms_p50) : "No samples yet",
      basis: t.latency.samples ? "measured" : "not_measured", slide: t.latency.samples > 0,
      detail: t.latency.samples ? `Half of all guidance was ready within this time${mock ? " (scripted, mock mode)" : ""}` : emptyOutcome(win) },
    // The per-consultation electricity is a fraction of a cent, so the headline counts 1,000 consultations.
    { label: "AI cost per 1,000 consultations", value: localKnown ? usd(perConsultEnergy * 1000) : "Not measured",
      vs: ref ? `vs ${usd(perConsultCloud * 1000)} for ${speak(ref)}` : undefined, basis: localKnown ? "estimated" : "not_measured", slide: true,
      detail: localKnown ? "Electricity on this device; the device price is paid once"
        : "The device's energy per consultation is not measured yet",
      slideDetail: localKnown ? (ref ? `vs ${usd(perConsultCloud * 1000)} for ${speak(ref)}` : "Electricity on this device") : "Device energy not measured yet" },
    { label: "Patient data sent off the device", value: "0 bytes", basis: "design", slide: true,
      detail: "Never left the device: no cloud AI call exists (by design, not a byte count)",
      slideDetail: "Never left the device: no cloud AI call exists" },
  ];

  const slideModel: SlideModel = {
    device: DEVICE,
    mock,
    period: periodLabel,
    generated: utcHour(t.generated_at),
    build: t.identity.app_commit ? t.identity.app_commit.slice(0, 7) : null,
    runtime: t.identity.runtime,
    // #547: the slide uses the basic figures. #325: never a zero or an empty figure: those without samples are left out.
    kpis: basic.filter((k) => k.slide).map((k) => ({ label: k.label, value: k.value, basis: k.basis,
      // #324, #436, #638: the outcome figure names the span actually counted, compactly.
      detail: k.label === "Consultations guided" ? `Published ${mock ? "scripted guidance" : "guidance"}, ${win.countedCompact}` : k.slideDetail ?? k.detail })),
    bars: [
      ...refs.map((r, i) => ({ label: r.short_label, value: refOutcomes[i].cloudPer, note: `${r.provider} ${r.model}: $${r.input_usd_per_mtok} in / $${r.output_usd_per_mtok} out per 1M tokens`,
        tone: toneOf(r, refs) })),
      { label: "This device (electricity)", value: localKnown ? perConsultEnergy : null, tone: "local" as const,
        note: localKnown ? `${perConsultWh.toFixed(3)} Wh × $${inputs.kwh}/kWh` : "Energy per consultation not measured yet" },
    ],
    // #132, #398: within the slide's two note lines; the metering start is named.
    barsNote: `${int(inputs.inTok)} in / ${int(inputs.outTok)} out tokens per consultation × list price per 1M tokens; device = energy × electricity price.${meteredLater ? ` AI calls metered since ${utcHour(t.metered.since)}.` : ""}`,
    // #477: a panel whose every bar is Not measured is not badged Estimated.
    barsBasis: refs.length || localKnown ? "estimated" : "not_measured",
    scenario: {
      // #477: the scenario keeps the basis the page shows for its volume and tokens.
      title: `At ${count(inputs.perDay, "consultation")} per day${volumeBasis === "fallback" ? " (fallback)" : volumeBasis === "assumption" ? " (assumed)" : ""}, compared with ${ref?.short_label ?? "a cloud API"}`,
      cloud: usd(cloudMonthly), device: usd(amortMonthly + energyMonthly), payback: paybackText(breakEvenMonths, inputs.months, cloudDearer),
      detail: `${!tokensDefault ? "Assumed tokens per consultation. " : measuredPerConsult ? "" : "Fallback tokens per consultation: the guidance call only. "}${selOutcome?.consultations != null ? `Break-even after ${int(Math.ceil(selOutcome.consultations))} consultations. ` : ""}Device ${usd(inputs.device)} paid once, over ${count(inputs.months, "month")}; electricity at $${inputs.kwh}/kWh${inputs.sysW > 0 ? ` + ${inputs.sysW} W other system power (assumption)` : ""}.`,
    },
    message,
    // #292: the figure follows from the architecture; it is not a measured byte count. #437: mock mode says so.
    privacy: mock
      ? `Mock mode: scripted results, no AI model · ${t.privacy.patient_data_sent_off_device_bytes} bytes of patient data sent off the device (by design) · ${t.privacy.cloud_inference_calls} cloud AI calls`
      : `By design, not measured: ${t.privacy.patient_data_sent_off_device_bytes} bytes of patient data sent off the device · ${t.privacy.cloud_inference_calls} cloud AI calls · the model runs only on the ${DEVICE}`,
    sources: [
      `Prices: ${refs.map((r) => `${r.provider} ${r.model} $${r.input_usd_per_mtok}/$${r.output_usd_per_mtok} per 1M tokens (retrieved ${formatDate(r.retrieved)})`).join("; ")}.`,
      `Device ${usd(a?.device_price_usd.value ?? 0)} ${/\bestimate/i.test(a?.device_price_usd.label ?? "") ? "estimated price" : "list price"}; electricity $${kwh}/kWh (EIA, July 2026). Estimated = measured values × these prices and the stated assumptions.`,
    ],
    // Never cut from the slide (W06Slide reserves its lines first).
    required: "Healthcare outcomes are not measured (R39). Synthetic demonstration; not a medical device.",
    logoSvg: null,
  };

  const mockBanner = mock && (
    <StatusBanner tone="warn" title="Mock mode: scripted results, no AI model">
      <p>
        Token, energy and cost figures stay empty in mock mode. The scripted answers are counted like AI calls so
        the page can be shown, but no AI model ran. Deploy in local mode to measure the device's AI.
      </p>
    </StatusBanner>
  );

  if (view === "basic") {
    return (
      <>
        {mockBanner}
        <section aria-labelledby="kpi-heading" className="basic-view">
          <h2 id="kpi-heading" className="section-title glance-title">At a glance</h2>
          <p className="small muted basic-window">
            {periodLabel} ({win.counted}), live: a consultation counts as soon as it happens; costs use the reviewed price list.
          </p>
          <div className="kpi-grid basic-grid">
            {basic.map((k) => (
              <Tile key={k.label} className="basic-tile" label={k.label} basis={k.basis} detail={k.detail}
                value={k.vs ? <>{k.value} <span className="kpi-vs">{k.vs}</span></> : k.value} />
            ))}
          </div>
          <div className="cost-line">
            <BasisBadge basis={localKnown ? "estimated" : "not_measured"} />
            <p>{message}</p>
          </div>
          <p className="basic-more">
            <button type="button" className="btn secondary sm" onClick={onAdvanced}>Show every figure (Advanced)</button>
            <span className="small muted">The break-even chart, the calculator, reliability, sources and the slide preview are in the advanced view.</span>
          </p>
        </section>
        <SlideSection model={slideModel} compact />
      </>
    );
  }

  return (
    <>
      {mockBanner}
      <ul className="legend small" aria-label="How to read the figures">
        <li><BasisBadge basis="measured" /> read on this device</li>
        <li><BasisBadge basis="estimated" /> calculated from measurements and stated assumptions</li>
        <li><BasisBadge basis="not_measured" /> no data</li>
        <li><BasisBadge basis="design" /> follows from how the system is built, not counted</li>
      </ul>

      <div className="grid2 adv-grid">
        <section className="card" aria-labelledby="usage-heading">
          <div className="card-head"><h2 id="usage-heading" tabIndex={-1}>Usage</h2><BasisBadge basis="measured" /></div>
          {/* #638: every tile counts the selected period up to now, including the current hour. */}
          <h3 className="kpi-group-title" id="kpi-live">Live on this device <span className="small muted">· {periodLabel}, up to now</span></h3>
          <div className="kpi-grid" aria-labelledby="kpi-live">
            <Tile label={mock ? "Scripted calls (mock mode)" : "AI calls on the device"} value={int(calls.total)} basis="measured"
              detail={<>{mock ? "No AI model ran: these are the mock adapter's scripted answers" : "Every AI call in this period"}, up to now{since}. By task: see <a href="#rel-heading" onClick={(e) => jump(e, "rel-heading")}>Reliability</a>.</>} />
          </div>
          {/* #638: live: what happened a moment ago is already counted. */}
          <p className="small muted live-note">
            Every figure counts up to now, including the current hour: a consultation and its
            {mock ? " scripted calls" : " AI calls"} count as soon as they happen.
          </p>
          <h3 className="kpi-group-title" id="kpi-outcomes">Consultation outcomes <span className="small muted">· {win.heading}</span></h3>
          <div className="kpi-grid" aria-labelledby="kpi-outcomes">
            {/* #436: the figure names the span actually counted (from the counting start when that is later). */}
            <Tile label="Consultations guided" value={guided > 0 ? int(guided) : "None yet"} basis="measured"
              detail={guided > 0 ? `Published ${mock ? "scripted guidance (mock mode)" : "AI guidance"}, ${win.counted}` : emptyOutcome(win)} />
          </div>
          {win.countingSince && <CountingSince w={win} />}
          <BackToSections />
        </section>

        <section className="card" aria-labelledby="perf-heading">
          <div className="card-head"><h2 id="perf-heading">Latency</h2><BasisBadge basis={mock ? "not_measured" : "measured"} /></div>
          <div className="kpi-grid">
            <Tile label="Typical guidance time" value={t.latency.samples ? secs(t.latency.total_ms_p50) : "No samples yet"} basis={t.latency.samples ? "measured" : "not_measured"}
              detail={t.latency.samples ? `median of ${int(t.latency.samples)}; 95th percentile ${secs(t.latency.total_ms_p95)}${mock ? " (scripted results, mock mode)" : ""}; ${win.counted}` : emptyOutcome(win)} />
            <Tile label="Output speed" value={calls.output_tokens_per_second == null ? "—" : `${calls.output_tokens_per_second} tokens/s`}
              basis={calls.output_tokens_per_second == null ? "not_measured" : "measured"}
              detail={calls.output_tokens_per_second == null ? "No AI calls with token counts yet" : `Output tokens per second of AI call time, including reading the prompt; up to now`} />
          </div>
          <table className="kv">
            <tbody>
              {/* #325: named for what it measures: most AI calls are the short safety screens, not the guidance. #437:
                  mock mode times no AI model. */}
              {mock
                ? <tr><th scope="row">AI call time</th><td><BasisBadge basis="not_measured" /> no AI model in mock mode (the calls are scripted)</td></tr>
                : <tr><th scope="row">Any AI call (mostly short safety screens), median / 95th percentile</th><td>{secs(calls.duration_ms_p50)} / {secs(calls.duration_ms_p95)}</td></tr>}
              <tr><th scope="row">Guidance time, median / 95th percentile</th><td>{t.latency.samples ? `${secs(t.latency.total_ms_p50)} / ${secs(t.latency.total_ms_p95)}` : "No samples yet"}</td></tr>
              <tr><th scope="row">Time waiting in the queue, median</th><td>{t.latency.queue_ms_p50 == null ? "No samples yet" : `${t.latency.queue_ms_p50} ms`}</td></tr>
              <tr><th scope="row">Cloud API latency</th><td><BasisBadge basis="not_measured" /> no cloud call is made</td></tr>
            </tbody>
          </table>
          <p className="small muted">AI call times and speed: {periodLabel}, up to now. Guidance and queue times: {win.counted}.</p>
          <BackToSections />
        </section>

        <section className="card" id="privacy" aria-labelledby="privacy-heading">
          <div className="card-head"><h2 id="privacy-heading">Privacy and data sovereignty</h2><BasisBadge basis="design" /></div>
          <div className="kpi-grid">
            {/* #292: the figure is the architecture (no cloud AI call exists), not a byte count; a recorded network check is
                shown as what it is. */}
            <Tile label="Patient data sent off the device" value="0 bytes" basis="design"
              detail={t.privacy.last_verified ? `No cloud AI call exists in this build; not a byte count. Last network check: ${int(t.privacy.last_verified.non_loopback ?? 0)} off-device connections in ${int(t.privacy.last_verified.samples ?? 0)} samples (${formatDate(t.privacy.last_verified.date)}).` : "No cloud AI call exists in this build; not a byte count."} />
          </div>
          <ul className="checks">
            {/* #437: mock mode runs no model; the architecture of local mode is stated as such. */}
            <li><Icon name="lock" /><span>{mock ? <><b>Mock mode: no AI model runs; the results are scripted.</b> In local mode: {t.privacy.basis}</>
              : <><b>The model runs only on this device.</b> {t.privacy.basis}</>}</span></li>
            <li><Icon name="cloudOff" /><span><b>Cloud AI calls: {t.privacy.cloud_inference_calls}.</b> Nothing is sent to a cloud LLM, not even to compare prices.</span></li>
            {t.privacy.last_verified && !mock && (
              <li><Icon name="shield" /><span><b>{int(t.privacy.last_verified.non_loopback ?? 0)} off-device connections</b> by the model processes in {int(t.privacy.last_verified.samples ?? 0)} one-second samples ({formatDate(t.privacy.last_verified.date)}). <BasisBadge basis="measured" /></span></li>
            )}
            <li><Icon name="info" /><span>With a cloud API, each consultation would send about {int(inputs.inTok)} tokens of the person's concern, answers and context to a third party.</span></li>
          </ul>
          <BackToSections />
        </section>

        <section className="card" aria-labelledby="identity-heading">
          <div className="card-head"><h2 id="identity-heading">Model and runtime</h2><BasisBadge basis="measured" /></div>
          <table className="kv identity">
            <tbody>
              <tr><th scope="row">Mode</th><td>{t.identity.mode === "local" ? "Local mode" : "Mock mode"}</td></tr>
              <tr><th scope="row">Device</th><td>{DEVICE}</td></tr>
              {t.identity.runtime && <tr><th scope="row">Runtime</th><td>{t.identity.runtime}</td></tr>}
              {t.identity.model_manifest_id && <tr><th scope="row">Model</th><td className="wrap-any">{t.identity.model_manifest_id}</td></tr>}
              {t.identity.prompt_version && <tr><th scope="row">Prompt</th><td>{t.identity.prompt_version}</td></tr>}
              {t.identity.qualification?.result && <tr><th scope="row">ADR-002 re-qualification</th><td>{t.identity.qualification.result} ({formatDate(t.identity.qualification.date)})</td></tr>}
              {t.identity.app_commit && <tr><th scope="row">Build</th><td>{t.identity.app_commit.slice(0, 7)}</td></tr>}
            </tbody>
          </table>
          <p className="small muted meta-line">
            {t.identity.mode === "local" ? "Local mode" : "Mock mode"}
            {t.identity.runtime && <> · {t.identity.runtime}</>}
            {t.identity.model_manifest_id && <> · model {t.identity.model_manifest_id}</>}
            {t.identity.prompt_version && <> · prompt {t.identity.prompt_version}</>}
            {t.identity.qualification?.result && <> · ADR-002 re-qualification {t.identity.qualification.result} ({formatDate(t.identity.qualification.date)})</>}
            {t.identity.app_commit && <> · build {t.identity.app_commit.slice(0, 7)}</>}
            {" "}· updated {formatTime(t.generated_at, { utc: true })}
          </p>
          <BackToSections />
        </section>

        <section className="card" aria-labelledby="tokens-heading">
          <div className="card-head"><h2 id="tokens-heading">Tokens</h2><BasisBadge basis={tokensMeasured ? "measured" : "not_measured"} /></div>
          <div className="kpi-grid">
            <Tile label="Tokens processed" value={tokensMeasured ? int(calls.prompt_tokens + calls.completion_tokens) : "—"}
              basis={tokensMeasured ? "measured" : "not_measured"}
              detail={tokensMeasured ? `${int(calls.prompt_tokens)} in · ${int(calls.completion_tokens)} out, as reported by ${RUNTIME}${since}` : "No AI calls with token counts yet"} />
            <Tile label="Tokens per consultation" value={`${int(defaults.inTok + defaults.outTok)}`}
              basis={measuredPerConsult ? "measured" : "not_measured"}
              detail={measuredPerConsult ? `${int(defaults.inTok)} in · ${int(defaults.outTok)} out, over ${perWindow}` : `Not measured yet: the fallback of ${int(defaults.inTok)} in · ${int(defaults.outTok)} out is used`} />
          </div>
          <BackToSections />
        </section>

        <section className="card" aria-labelledby="energy-heading">
          <div className="card-head"><h2 id="energy-heading">Energy</h2><BasisBadge basis={energyMeasured ? "measured" : "not_measured"} /></div>
          <div className="kpi-grid">
            <Tile label="GPU energy for AI calls" value={energyMeasured ? `${(t.energy.wh_total ?? 0).toFixed(2)} Wh` : "—"}
              basis={energyMeasured ? "measured" : "not_measured"}
              detail={energyMeasured ? `${int(t.energy.calls_with_energy)} calls · GPU power from nvidia-smi; whole-system power not measured${since}` : `Power sampler ${t.energy.sampler.status === "active" ? "active; no AI calls yet" : "not running"}`} />
            <Tile label="GPU energy per consultation" value={measuredEnergy ? `${defaults.wh} Wh` : "—"}
              basis={measuredEnergy ? "measured" : "not_measured"}
              detail={measuredEnergy ? `Over ${perWindow}${m.calls_with_energy < m.ai_calls ? `; measured for ${int(m.calls_with_energy)} of the ${int(m.ai_calls)} calls, so a lower bound` : ""}` : "Not measured in the counted hours"} />
          </div>
          <BackToSections />
        </section>
      </div>

      <section className="card" aria-labelledby="cost-heading">
        <div className="card-head">
          <h2 id="cost-heading">Cost: this device versus a cloud LLM API</h2>
          <BasisBadge basis="estimated" />
        </div>
        <p className="muted">
          The same work in this period, priced at cloud list prices: the measured tokens times each provider's price per
          million tokens. On this device the running cost is the measured GPU energy times the electricity price; the
          device itself is a one-off cost, shown in the break-even below.
          {/* #398: the cost covers the AI work since metering began; it is not compared with a count of consultations
              from another window. */}
          {meteredLater && <> AI calls are metered since {utcHour(t.metered.since)}, so this covers the AI work from then on.</>}
        </p>
        <div className="kpi-grid">
          <Tile label="Estimated cloud cost of this work" value={headCloud == null ? "—" : <>{usd(headCloud)} <span className="kpi-vs">vs {periodEnergyCost == null ? "—" : usd(periodEnergyCost)}</span></>}
            basis={headCloud == null ? "not_measured" : "estimated"}
            detail={headCloud == null || !headRef ? "No AI calls with token counts yet"
              : <>{headRef.short_label} at list prices vs {periodEnergyCost == null ? "GPU electricity (not measured in this period)" : "measured GPU electricity on this device"}
                {frontierRef && <>; {frontierRef.short_label}: {usd(cloudCost(frontierRef, calls.prompt_tokens, calls.completion_tokens))}</>}.</>} />
        </div>
        {tokensMeasured ? (
          <Bars title="Cost of this period's AI work"
            rows={[
              ...periodCloud.map(({ r, cost }) => ({ label: r.short_label, value: cost, tone: toneOf(r, refs),
                note: `${r.provider} ${r.model}: $${r.input_usd_per_mtok} in / $${r.output_usd_per_mtok} out per 1M tokens` })),
              { label: "This device (electricity)", value: periodEnergyCost, tone: "local",
                note: energyMeasured ? `${(t.energy.wh_total ?? 0).toFixed(2)} Wh × $${kwh}/kWh` : "Energy not measured in this period" },
            ]} />
        ) : (
          <p className="empty-note">No AI calls with token counts in this period yet. Run a consultation, or use the calculator with the fallback values.</p>
        )}
        <details>
          <summary>Show the formulas</summary>
          <ul className="bullets small">
            <li>Cloud cost = input tokens × input price ÷ 1,000,000 + output tokens × output price ÷ 1,000,000.</li>
            <li>Electricity on this device = measured GPU energy (Wh) ÷ 1,000 × electricity price ($/kWh). GPU power only; the rest of the system is not included.</li>
            <li>Every AI call counts: the guidance (including any repair), the red-flag screen and the safety review, as a cloud deployment would need them too.</li>
            <li>Break-even = device price ÷ (cloud cost per consultation − electricity per consultation): the consultation after which the device, paid once, has cost less in total.</li>
          </ul>
        </details>
        <BackToSections />
      </section>

      <section className="card" aria-labelledby="calc-heading">
        <div className="card-head">
          <h2 id="calc-heading">Break-even calculator</h2>
          <BasisBadge basis="estimated" />
        </div>
        {/* #547: the marginal cost per consultation leads: the device's is its electricity; the device price is paid once. */}
        <div className="kpi-grid marginal-grid">
          <Tile label="Per consultation on this device" value={localKnown ? usd(perConsultEnergy) : "Not measured"} basis={localKnown ? "estimated" : "not_measured"}
            detail={localKnown ? `Electricity only: ${perConsultWh.toFixed(3)} Wh × $${inputs.kwh}/kWh. The device price is paid once.` : "Energy per consultation not measured yet, so electricity is not included"} />
          <Tile label={`Per consultation, ${ref ? lowerFirst(ref.short_label) : "cloud API"}`} value={usd(perConsultCloud)} basis="estimated"
            detail={`${int(inputs.inTok)} in · ${int(inputs.outTok)} out tokens at list prices${localKnown && perConsultEnergy > 0 ? `: ${Math.round(perConsultCloud / perConsultEnergy).toLocaleString("en-US")} times the device's electricity` : ""}`} />
          <Tile label="Local becomes cheaper after" basis="estimated"
            value={selOutcome?.consultations == null ? "Never" : selOutcome.within ? count(Math.ceil(selOutcome.consultations), "consultation") : "Not within the lifetime"}
            detail={selOutcome?.consultations == null ? "The cloud API is not dearer per consultation"
              : `${int(Math.ceil(selOutcome.consultations))} consultations: ${selOutcome.months == null ? "no volume set" : `${selOutcome.months.toFixed(1)} months at ${int(inputs.perDay)} a day`}, against ${ref?.short_label}`} />
        </div>
        <p className="assumption small">
          <b>Assumption:</b> {count(inputs.perDay, "consultation")} a day ({volumeWords}) over the {inputs.months}-month device lifetime:
          {" "}{count(horizon, "consultation")} in all. Change the volume, the lifetime or the cloud API in the calculator below.
        </p>
        <BreakEvenChart months={Math.max(1, inputs.months)} perDay={inputs.perDay} device={inputs.device} localPer={perConsultEnergy} series={series} />
        {/* #447: one item per series, each swatch with its own label; the lines differ by more than colour. */}
        <ul className="chart-legend small" aria-label="Chart legend">
          <li><span className="swatch local" aria-hidden="true" />This device: price paid once, then electricity (dashed line)</li>
          {series.map((s) => (
            <li key={s.id}><span className={`swatch line tone-${s.tone}${s.selected ? " selected" : ""}`} aria-hidden="true"
              style={s.selected ? undefined : { backgroundImage: dashGradient(s.dash) }} />{s.label}, cumulative ({s.dashName})</li>
          ))}
          <li><span className="swatch savings" aria-hidden="true" />Savings after break-even (shaded)</li>
        </ul>
        <ul className="bullets small breakeven-list" aria-label="Break-even by cloud API">
          {refOutcomes.map((o) => (
            <li key={o.id}>
              <b>{o.label}:</b>{" "}
              {o.consultations == null ? "the cloud API is not dearer per consultation, so this device never becomes cheaper on cost."
                : o.within ? `this device becomes cheaper after ${count(Math.ceil(o.consultations), "consultation")} (${(o.months ?? 0).toFixed(1)} months at this volume); ${usd(o.savedAtEnd)} saved by month ${inputs.months}.`
                : `not within the ${inputs.months}-month lifetime: after ${count(Math.ceil(o.consultations), "consultation")}${o.months != null ? ` (${o.months.toFixed(0)} months at this volume)` : ""}; over the lifetime the cloud API costs ${usd(-o.savedAtEnd)} less.`}
            </li>
          ))}
        </ul>
        <p className="muted">Defaults come from this device's measurements where they exist. Change any value; nothing is saved or sent anywhere.</p>
        {/* #398, #468: each default says what it is measured over (one window for usage and consultations) or that it
            is a fallback. */}
        <ul className="bullets small muted calc-basis">
          <li>
            <BasisBadge basis={volumeMeasured ? "measured" : "not_measured"} /> Consultations per day:{" "}
            {volumeMeasured ? `${count(guided, "consultation")} guided, ${win.counted} (${dayCount(win.countedDays)})`
              : `a fallback of ${int(defaults.perDay)} per day (assumption), as ${guided > 0 ? "less than a day is counted" : "no consultation is counted in this period"} yet`}.
          </li>
          <li>
            <BasisBadge basis={measuredPerConsult ? "measured" : "not_measured"} /> Tokens and AI time per consultation:{" "}
            {measuredPerConsult ? <>measured over {perWindow}: the {count(m.ai_calls, mock ? "scripted call" : "AI call")} of those hours ÷ the {count(meteredGuided, "consultation")} guided in the same hours. Every call counts, including the red-flag screens of consultations routed to urgent help{m.with_token_counts < m.ai_calls ? `; ${int(m.with_token_counts)} of them reported token counts` : ""}</>
              : <>the fallback values{a ? ` (${lowerFirst(humanDates(a.fallback_tokens_per_consultation.label))})` : ""}, as no consultation with metered AI calls is counted in this period yet</>}.
          </li>
          <li>
            <BasisBadge basis={measuredEnergy ? "measured" : "not_measured"} /> GPU energy per consultation:{" "}
            {measuredEnergy ? `the same hours${m.calls_with_energy < m.ai_calls ? `; measured for ${int(m.calls_with_energy)} of the ${int(m.ai_calls)} calls, so it is a lower bound` : ""}` : "not measured in those hours, so electricity is not included"}.
          </li>
        </ul>
        <div className="presets" role="group" aria-label="Volume presets (assumptions)">
          <span className="small muted">Volume:</span>
          {/* #405: the active preset is exposed (aria-pressed), not only shown by colour. */}
          <button type="button" className={inputs.perDay === defaults.perDay ? "seg on" : "seg"} aria-pressed={inputs.perDay === defaults.perDay}
            onClick={() => preset(defaults.perDay)}>
            {volumeMeasured ? "Measured" : "Fallback"} ({int(defaults.perDay)}/day)
          </button>
          {PRESETS.map(([label, n]) => (
            <button key={label} type="button" className={inputs.perDay === n ? "seg on" : "seg"} aria-pressed={inputs.perDay === n} onClick={() => preset(n)}>
              {label} ({int(n)}/day)
            </button>
          ))}
        </div>
        <div className="calc-grid">
          <div className="field">
            <label htmlFor="ref">Cloud API to compare with</label>
            <select id="ref" value={ref?.id} onChange={(e) => setRefId(e.target.value)}>
              {refs.map((r) => <option key={r.id} value={r.id}>{r.short_label}: {r.provider} {r.model}</option>)}
            </select>
          </div>
          <NumberField id="perDay" label="Consultations per day" value={inputs.perDay} onChange={set("perDay")} step={1} sync={presetSync} />
          <NumberField id="inTok" label="Input tokens per consultation" value={inputs.inTok} onChange={set("inTok")} step={100} />
          <NumberField id="outTok" label="Output tokens per consultation" value={inputs.outTok} onChange={set("outTok")} step={50} />
          <NumberField id="wh" label="GPU energy per consultation" value={inputs.wh} onChange={set("wh")} step={0.01} unit="Wh" />
          <NumberField id="device" label="Device price" value={inputs.device} onChange={set("device")} step={100} unit="USD" />
          <NumberField id="months" label="Device lifetime" value={inputs.months} onChange={set("months")} step={1} unit="months"
            min={1} minMessage="Enter a lifetime of at least 1 month." />
          <NumberField id="kwh" label="Electricity price" value={inputs.kwh} onChange={set("kwh")} step={0.01} unit="USD/kWh" />
          <NumberField id="sysW" label="Other system power during AI calls" value={inputs.sysW} onChange={set("sysW")} step={1} unit="W" />
        </div>
        {!measuredPerConsult && a && <p className="small muted">Fallback tokens per consultation: {humanDates(a.fallback_tokens_per_consultation.label)}.</p>}
        {inputs.wh === 0 && <p className="small muted">GPU energy per consultation is not measured yet, so electricity is not included.</p>}
        <p className="small muted">
          Whole-system power is <BasisBadge basis="not_measured" /> on this device: this page measures GPU power only. To include
          the rest of the system, enter a wall-socket meter reading minus GPU power above; it is applied over{" "}
          {aiSecondsPerConsult > 0 ? `the measured ${aiSecondsPerConsult.toFixed(1)} s of AI time per consultation` : "the AI time per consultation, once measured"}
          {inputs.sysW > 0 && <> ({perConsultWh.toFixed(3)} Wh per consultation in total)</>}.
        </p>
        <div className="calc-results">
          <Tile label="Cloud API per month" value={usd(cloudMonthly)} basis="estimated" detail={`${usd(perConsultCloud)} per consultation`} />
          <Tile label="This device per month" value={usd(amortMonthly + energyMonthly)} basis="estimated"
            detail={`${usd(amortMonthly)} device amortization + ${usd(energyMonthly)} electricity`} />
          <Tile label="Device pays for itself" value={paybackText(breakEvenMonths, inputs.months, cloudDearer)}
            basis="estimated" detail={breakEvenDetail} />
        </div>
        <BackToSections />
      </section>

      <div className="grid2 adv-grid">
        <section className="card" aria-labelledby="rel-heading">
          <div className="card-head"><h2 id="rel-heading">Reliability and safety</h2><BasisBadge basis="measured" /></div>
          {/* #324, #638: every figure here counts the same hours up to now, from an absolute start. */}
          <h3 className="outcomes-window" id="rel-window">{win.heading}</h3>
          <table className="kv" aria-labelledby="rel-heading rel-window">
            <tbody>
              <tr><th scope="row">Guidance published</th><td>{int(guided)}</td></tr>
              <tr><th scope="row">Published after the single repair</th><td>{withheld(t.consultations.repaired, t.consultations.suppressed_below)}</td></tr>
              <tr><th scope="row">Stopped safely instead of shown (fail closed)</th><td>{withheld(t.consultations.fail_closed, t.consultations.suppressed_below)}</td></tr>
              {/* #538: which validator rule rejected the attempts of those results (rule codes only, content-free). */}
              {(t.consultations.fail_closed_reasons ?? []).map(({ rule, count }) => (
                <tr key={rule} className="sub-row"><th scope="row">Fail closed, rejected by rule: <code>{rule}</code></th><td>{withheld(count, t.consultations.suppressed_below)}</td></tr>
              ))}
              <tr><th scope="row">Routed to urgent help</th><td>{withheld(t.consultations.urgent_routes, t.consultations.suppressed_below)}</td></tr>
              <tr><th scope="row">Requests refused while busy</th><td>{int(t.consultations.busy_refusals)}</td></tr>
              {TASKS.filter(([k]) => k !== "other" || (calls.by_task as Record<string, number | undefined>).other).map(([k, label]) => (
                <tr key={k}><th scope="row">{callsLabel} by task: {label}</th><td>{int((calls.by_task as Record<string, number | undefined>)[k] ?? 0)}</td></tr>
              ))}
              <tr><th scope="row">{callsLabel} that errored</th><td>{int(calls.errors)}</td></tr>
            </tbody>
          </table>
          <p className="small muted">Counts below {t.consultations.suppressed_below} are shown as "fewer than {t.consultations.suppressed_below}".</p>
          <p className="small muted outcomes-note">
            These figures count up to now, including the current hour, so a consultation appears as soon as its
            guidance is published or it is routed to urgent help.
          </p>
          {win.countingSince && <CountingSince w={win} />}
          <BackToSections />
        </section>

        <section className="card" aria-labelledby="claim-heading">
          <div className="card-head"><h2 id="claim-heading">What we don't claim</h2><BasisBadge basis="not_measured" /></div>
          <p>{t.outcomes.note}</p>
          <p>The savings above are inference cost only. Benefits such as better-matched appointments or less repeated intake are hypotheses that need a real pilot.</p>
          <Link to="/healthcare">Read the healthcare benefit hypotheses</Link>
          <BackToSections />
        </section>
      </div>

      <SlideSection model={slideModel} />

      {pricing && (
        <section className="card" aria-labelledby="src-heading">
          <h2 id="src-heading">Sources and assumptions</h2>
          {/* #472: one date and one money style here too ("17 Oct 2026", "$7,699"), also for dates quoted in the
              reviewed price list's text. #476: below 640 px the table stacks, so every column and link stays visible. */}
          <p className="small muted">Price list of {humanDates(pricing.pricing_version)} ({pricing.currency}). {humanDates(pricing.note)}</p>
          <ScrollTable label="Prices and assumptions table">
            <table className="stack-table">
              <thead><tr><th scope="col">Item</th><th scope="col">Value</th><th scope="col">Basis and source</th></tr></thead>
              <tbody>
                {refs.map((r) => (
                  <tr key={r.id}>
                    <td>{humanDates(r.label)}</td>
                    <td data-label="Value">${r.input_usd_per_mtok} in / ${r.output_usd_per_mtok} out per 1M tokens</td>
                    <td data-label="Basis and source">{humanDates(r.pricing_basis)} <a href={r.source_url} target="_blank" rel="noopener noreferrer">Source</a>, retrieved {formatDate(r.retrieved)}</td>
                  </tr>
                ))}
                {a && ([["device_price_usd", (v: number) => usd(v)], ["lifetime_months", (v: number) => count(v, "month")],
                  ["electricity_usd_per_kwh", (v: number) => `$${v}/kWh`], ["other_system_power_w", (v: number) => `${int(v)} W`]] as const).map(([k, show]) => (
                  <tr key={k}>
                    <td>{humanDates(a[k].label)}</td>
                    <td data-label="Value">{show(a[k].value)}</td>
                    <td data-label="Basis and source">{humanDates(a[k].note ?? (a[k].source_url ? "" : "Assumption; editable above"))} {a[k].source_url && <><a href={a[k].source_url} target="_blank" rel="noopener noreferrer">Source</a>, retrieved {formatDate(a[k].retrieved)}</>}</td>
                  </tr>
                ))}
                <tr>
                  <td>GPU energy</td>
                  <td data-label="Value">{t.energy.source}</td>
                  <td data-label="Basis and source">One reading per second around each AI call; a call without enough readings is Not measured, never estimated.</td>
                </tr>
              </tbody>
            </table>
          </ScrollTable>
          <BackToSections />
        </section>
      )}
    </>
  );
}

/** A legend swatch drawn with the series' dash pattern (dash, gap, ...) in its own colour. */
function dashGradient(dash: string): string {
  const parts = dash.split(" ").map(Number);
  let at = 0;
  const stops = parts.map((len, i) => {
    const from = at;
    at += len;
    return `${i % 2 === 0 ? "currentColor" : "transparent"} ${from}px ${at}px`;
  });
  return `repeating-linear-gradient(90deg, ${stops.join(", ")})`;
}

function withheld(n: number | null | undefined, below: number) {
  return n == null ? `fewer than ${below}` : int(n);
}

/** #324: outcome counting began after the window started (events before mode recording are never counted). */
function CountingSince({ w }: { w: OutcomeWindow }) {
  if (!w.countingSince) return null;
  return (
    <p className="small muted counting-since">
      Outcomes counted since {utcHour(w.countingSince)} (when this device began recording the mode); earlier events are
      not counted. AI calls by task are counted for the whole window.
    </p>
  );
}

/** Scrolls to a section heading and moves keyboard focus there (#191). */
function jump(e: React.MouseEvent<HTMLAnchorElement> | null, id: string): void {
  const target = document.getElementById(id);
  if (!target) return;
  e?.preventDefault();
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.scrollIntoView({ block: "start" });
  target.focus({ preventScroll: true });
}

/** #129: the figures as one 16:9 slide, built here (SVG) and drawn to PNG on a canvas; nothing leaves the device. */
function SlideSection({ model, compact = false }: { model: SlideModel; compact?: boolean }) {
  const logo = hpLogoSvg; // the bundled HP logo, embedded, so the slide references nothing outside itself
  const [status, setStatus] = useState<string | null>(null);
  const key = JSON.stringify(model); // rebuild only when the figures or the scenario change, not on every render
  const svg = useMemo(() => buildSlideSvg({ ...(JSON.parse(key) as SlideModel), logoSvg: logo }), [key, logo]);
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    if (compact) return;
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [svg, compact]);
  const stamp = new Date().toISOString().slice(0, 10);
  const png = async () => {
    setStatus(null);
    try {
      saveBlob(await svgToPng(svg), `aware-care-telemetry-${stamp}.png`);
    } catch {
      setStatus("The PNG could not be drawn in this browser; download the SVG instead.");
    }
  };
  const buttons = (
    <div className="row">
      <button type="button" className="btn" onClick={png}>Download PNG</button>
      <button type="button" className="btn secondary"
        onClick={() => saveBlob(new Blob([svg], { type: "image/svg+xml" }), `aware-care-telemetry-${stamp}.svg`)}>Download SVG</button>
    </div>
  );
  // #547: the basic view offers the same slide (the basic figures) without the preview.
  if (compact)
    return (
      <section className="slide-compact" aria-labelledby="slide-heading">
        <h2 id="slide-heading" className="kpi-group-title">Share as a slide</h2>
        <p className="small muted">These figures and the cost per consultation on one 16:9 slide, built on this device; nothing is uploaded.</p>
        {buttons}
        {status && <p className="small" role="status">{status}</p>}
      </section>
    );
  return (
    <section className="card" aria-labelledby="slide-heading">
      <div className="card-head">
        <h2 id="slide-heading">Share as a slide</h2>
        <BasisBadge basis="estimated" />
      </div>
      <p className="muted">
        The basic view's headline figures, the cost per consultation and the calculator's current scenario on one 16:9
        slide, with every figure's basis and the sources. It is built on this device; nothing is uploaded.
      </p>
      {preview && <img className="slide-preview" src={preview} alt={`Slide preview: Aware Care telemetry, ${model.period}`} />}
      {buttons}
      {status && <p className="small" role="status">{status}</p>}
      <BackToSections />
    </section>
  );
}


// #191: the page is long (≈11,000 px on a phone), so it opens with links to its sections. Each link scrolls to the
// heading and moves keyboard focus there. #346: the menu follows the title and the period choice (it sat after At a
// glance, 2,700 px down on a phone), and every section ends with "Back to sections", which returns focus to it.
// #469: every section that ends with "Back to sections" is in the menu, in page order (Reliability holds the outcome
// breakdowns).
// #547: the advanced view's sections, in page order.
const SECTIONS: [string, string][] = [
  ["usage-heading", "Usage"], ["perf-heading", "Latency"], ["privacy-heading", "Privacy"], ["identity-heading", "Model and runtime"],
  ["tokens-heading", "Tokens"], ["energy-heading", "Energy"], ["cost-heading", "Cost"], ["calc-heading", "Break-even"],
  ["rel-heading", "Reliability"], ["claim-heading", "What we don't claim"], ["slide-heading", "Slide"], ["src-heading", "Sources"],
];
const NAV_ID = "sections";

function SectionNav({ sources }: { sources: boolean }) {
  return (
    <nav className="section-nav" id={NAV_ID} aria-label="Sections on this page">
      <ul>
        {SECTIONS.filter(([id]) => sources || id !== "src-heading").map(([id, label]) => (
          <li key={id}>
            <a href={`#${id}`} onClick={(e) => jump(e, id)}>{label}</a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** #346: the last line of each section: back to the section menu, with keyboard focus on it. */
function BackToSections() {
  return (
    <p className="back-to-sections small">
      <a href={`#${NAV_ID}`} onClick={(e) => jump(e, NAV_ID)}>Back to sections</a>
    </p>
  );
}
