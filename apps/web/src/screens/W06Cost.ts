// W06 cost model (ADR-017, #547): the break-even arithmetic of the telemetry page and its slide, kept free of React so
// it can be unit-tested. Nothing here changes a price or a measured value: the device price is paid once, each
// consultation then costs its electricity on the device or its tokens at a cloud API's list price, and the device
// "breaks even" at the consultation where the two cumulative costs meet.

/** Average days per month (365.25 / 12), as the calculator has always used. */
export const DAYS_PER_MONTH = 30.44;

export type CloudPrice = { input_usd_per_mtok: number; output_usd_per_mtok: number };

/** A cloud API's list price for one consultation's tokens. */
export function cloudPerConsultation(ref: CloudPrice, inTok: number, outTok: number): number {
  return (inTok * ref.input_usd_per_mtok + outTok * ref.output_usd_per_mtok) / 1_000_000;
}

/** The electricity of one consultation on the device: watt-hours times the price per kWh. */
export function localPerConsultation(wh: number, usdPerKwh: number): number {
  return (wh / 1000) * usdPerKwh;
}

/**
 * The number of consultations after which the device (its price paid once, then `localPer` per consultation) has cost
 * less in total than the cloud API (`cloudPer` per consultation, nothing up front): device / (cloudPer - localPer).
 * 0 when the device is free; null when the cloud API is not dearer per consultation, so the lines never meet.
 */
export function breakEvenConsultations(device: number, cloudPer: number, localPer: number): number | null {
  if (!(cloudPer > localPer)) return null;
  if (device <= 0) return 0;
  return device / (cloudPer - localPer);
}

/** Months until `consultations` at `perDay` consultations a day; null without volume. */
export function monthsFor(consultations: number, perDay: number): number | null {
  return perDay > 0 ? consultations / (perDay * DAYS_PER_MONTH) : null;
}

/** Cumulative cost after `n` consultations: the device's (price plus electricity) and a cloud API's. */
export const deviceCumulative = (device: number, localPer: number, n: number) => device + localPer * n;
export const cloudCumulative = (cloudPer: number, n: number) => cloudPer * n;

export type Scenario = {
  device: number;
  localPer: number;
  perDay: number;
  months: number;
};

export type RefOutcome = {
  id: string;
  label: string;
  cloudPer: number;
  /** Consultations to break even; null when the lines never meet. */
  consultations: number | null;
  /** Months to break even at the scenario's volume; null when never or without volume. */
  months: number | null;
  /** True when the break-even falls within the device lifetime at this volume. */
  within: boolean;
  /** The device's saving at the end of the lifetime (negative: the cloud API cost less over it). */
  savedAtEnd: number;
};

/** The break-even outcome against each cloud reference, at the scenario's volume and over its lifetime. */
export function outcomes(s: Scenario, refs: { id: string; label: string; cloudPer: number }[]): RefOutcome[] {
  const horizon = s.perDay * DAYS_PER_MONTH * s.months;
  return refs.map((r) => {
    const consultations = breakEvenConsultations(s.device, r.cloudPer, s.localPer);
    const months = consultations == null ? null : monthsFor(consultations, s.perDay);
    return {
      ...r,
      consultations,
      months,
      within: consultations != null && consultations <= horizon,
      savedAtEnd: cloudCumulative(r.cloudPer, horizon) - deviceCumulative(s.device, s.localPer, horizon),
    };
  });
}

const int = (n: number) => Math.round(n).toLocaleString("en-US");

/**
 * #693 (owner decision B6, 28 Oct 2026): a figure that is Not measured says plainly when it will appear, from the rule
 * the page already uses. The device's energy comes from the GPU power sampler; mock mode runs no model, so it has none.
 * A per-consultation figure divides the energy of the whole hours from the first whole metered hour on (telemetry
 * `metered.from`, #398) by the consultations guided in them, so on a new installation it appears with the first
 * consultation after that hour ("Cost appears after the first full hour, at 15:00"); a period total appears with the
 * next AI call. `time` formats an ISO time for this browser (local time); `now` is this browser's clock.
 */
export function whenMeasured(o: { what: string; mock: boolean; samplerActive: boolean; perConsultation: boolean;
  from?: string; now: number; time: (iso: string) => string }): string {
  const { what, mock, samplerActive, perConsultation, from, now, time } = o;
  if (mock) return `${what} is not measured in mock mode: no model runs, so the device uses no AI energy`;
  if (!samplerActive) return `${what} appears once the GPU power sampler runs (./demo.sh setup starts it)`;
  if (!perConsultation) return `${what} appears with the next AI call on this device`;
  const start = from ? Date.parse(from) : NaN;
  if (Number.isFinite(start) && start > now)
    return `${what} appears after the first full hour, at ${time(from!)}, with the first consultation from then on`;
  return `${what} appears with the next consultation guided on this device`;
}
const lowerFirst = (t: string) => t.charAt(0).toLowerCase() + t.slice(1);
const monthText = (m: number) => (m < 1 ? "less than a month" : `${m.toFixed(1)} months`);

/**
 * The page's one-line cost message: the per-consultation running cost first (the device's marginal cost is usually
 * tiny), then, truthfully, whether the one-off device price is paid back within its lifetime at this volume, and
 * against which cloud API. `defaultId` is the reviewed like-for-like reference.
 */
export function costMessage(o: { localPer: number | null; outcomes: RefOutcome[]; defaultId: string | undefined; s: Scenario;
  usd: (n: number) => string; notYet?: string }): string {
  const { localPer, outcomes: all, defaultId, s, usd, notYet } = o;
  if (!all.length) return "No cloud price list is available to compare with.";
  // Per 1,000 consultations: the device's electricity per consultation is a fraction of a cent.
  const k = 1000;
  const cheapest = Math.min(...all.map((r) => r.cloudPer)), dearest = Math.max(...all.map((r) => r.cloudPer));
  const cloudRange = cheapest === dearest ? usd(cheapest * k) : `${usd(cheapest * k)} to ${usd(dearest * k)}`;
  const first = localPer == null
    ? `Through a cloud API, 1,000 consultations would cost ${cloudRange}; the device's electricity is not measured yet${notYet ? ` (${lowerFirst(notYet)})` : ""}.`
    : `1,000 consultations cost ${usd(localPer * k)} in electricity on this device, against ${cloudRange} through a cloud API.`;
  if (localPer == null) return first;
  // #574: the volume as entered (0.5 a day stays 0.5), and singular only for exactly one
  const volume = `${s.perDay.toLocaleString("en-US", { maximumFractionDigits: 2 })} consultation${s.perDay === 1 ? "" : "s"} a day`;
  const def = all.find((r) => r.id === defaultId) ?? all[0];
  const best = all.filter((r) => r.within).sort((a, b) => (a.months ?? 0) - (b.months ?? 0))[0];
  const paid = `The ${usd(s.device)} device is paid once:`;
  if (def.within) return `${first} ${paid} at ${volume} it pays for itself in ${monthText(def.months ?? 0)} against ${def.label}.`;
  if (best)
    return `${first} ${paid} at ${volume} it pays for itself in ${monthText(best.months ?? 0)} against ${best.label}; against ${def.label} it does not within ${s.months} months on AI cost alone.`;
  const soonest = all.filter((r) => r.consultations != null).sort((a, b) => a.consultations! - b.consultations!)[0];
  return soonest
    ? `${first} ${paid} at ${volume} it does not pay for itself within ${s.months} months on AI cost alone; against ${soonest.label} it would after ${int(soonest.consultations!)} consultations.`
    : `${first} ${paid} on AI cost alone it does not pay for itself at any volume.`;
}
