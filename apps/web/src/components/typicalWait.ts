// #323: how long guidance usually takes on this device; shared by A07 and, #529, the presenter's quick flows.

/** #323: how long guidance usually takes here. The device's own median over recent days when the server has measured
 * enough runs (telemetry), otherwise a per-device default from the product review's measurements (ZGX Nano 13-25 s,
 * median about 21 s; ZGX Fury about 2 s), or, #537, a generic wording on any other machine. A scripted mock result is
 * ready almost at once. */
export function typicalWait(measuredMs: number | null, mode: "unknown" | "local" | "mock", device: string) {
  if (measuredMs !== null) {
    const s = Math.max(1, Math.round(measuredMs / 1000));
    return { ms: measuredMs, text: `Usually about ${s} ${s === 1 ? "second" : "seconds"} on this device`, measured: true };
  }
  if (mode === "mock") return { ms: 3_000, text: "Usually a few seconds in this scripted demo", measured: false };
  if (/\bZGX Fury\b/.test(device)) return { ms: 3_000, text: "Usually a few seconds on this device", measured: false };
  if (/\bZGX Nano\b/.test(device)) return { ms: 20_000, text: "Usually 15–25 seconds on this device", measured: false };
  // #537: any other machine (its model is chosen by GPU memory): no measurement yet, so no device-specific claim.
  return { ms: 20_000, text: "Usually under a minute on this device", measured: false };
}
