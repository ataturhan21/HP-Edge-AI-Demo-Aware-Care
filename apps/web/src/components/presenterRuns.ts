// O03's one-click flows, kept outside the page (#423, #426; R37, R39). A run belongs to the presenter browser tab, not
// to the Scenarios page: leaving the page (Runtime, Controls, Telemetry, More scenarios, Back) never stops it, and its
// card shows the result when the presenter comes back. Each run is kept in sessionStorage (flow, times, the load's idempotency key,
// the case and prepare-job IDs and the patient-site path: IDs and states only, never patient content), so a reload of
// any presenter page picks a running flow up again: the load is replayed with the same idempotency key (the server
// returns the same case) and its prepare job is followed to the end.
// #548: a run no longer opens the patient tab while it works (#529's waiting page in a new tab is gone): O03 shows its
// progress in a dialog on the presenter screen, step by step from the prepare job's real `stage`, and the patient tab
// opens on the result only from the presenter's click on "Open the result" (a click, so no pop-up blocker stops it).
// A patient tab left open on an earlier result is never touched by a new run until that click (QA app-02: no stale
// guidance shown as the new one). A finished run stays shown after a reload; whether its case is still open on the
// patient site comes from the server (getRuntime `demo.live_case_ids`, CHG-DEV-API-007), so an ended or reset demo is never offered as "Show again".
import { ApiError, api, pollJob, type LoadScenarioBody, type S } from "../api/client";
import { DEVICE } from "./Brand";
import { FLOW_RUNS_KEY, onPresenterSessionStarted } from "./PresenterGate";

export type FlowId = "guidance" | "selfcare" | "urgent";
export const FLOW_IDS: FlowId[] = ["guidance", "selfcare", "urgent"];

/** What each flow asks the server for (synthetic inputs come from the scenario fixture). */
export const FLOW_REQUESTS: Record<FlowId, { scenario: string; request: LoadScenarioBody }> = {
  guidance: { scenario: "routine", request: { reset: false, prepare: "result" } },
  selfcare: { scenario: "selfcare", request: { reset: false, prepare: "result" } },
  urgent: { scenario: "urgent", request: { reset: false, prepare: "start", urgency_input: "written" } },
};

export const PATIENT_TAB = "aware-care-patient";
export const START_PATH = "/app/start";

export type Run =
  | { kind: "idle" }
  | { kind: "running"; since: number; key: string; local: boolean; caseId?: string; jobId?: string | null;
      path?: string; state?: string; stage?: Stage }
  // #548: `shown` once the presenter opened the result in the patient tab (a run never opens it by itself).
  | { kind: "done"; since: number; ms: number; caseId: string; path: string; detail: string; shown: boolean }
  // #550/#548: `explain` is the server's plain-words reason of a failed job (Job.error_reason), built from codes only.
  | { kind: "failed"; since: number; ms: number; reason: string; path?: string; reset?: boolean; explain?: string };

/** #548: the step a running quick demo is on, as the server reports it (Job.stage); never a percentage. */
export type Stage = "preparing" | "queued" | "screening" | "writing" | "rewriting" | "checking" | "finishing";
export const STAGES: Stage[] = ["preparing", "queued", "screening", "writing", "rewriting", "checking", "finishing"];

type Runs = Record<FlowId, Run>;
const IDLE: Run = { kind: "idle" };
const emptyRuns = (): Runs => ({ guidance: IDLE, selfcare: IDLE, urgent: IDLE });

// ── Plain words for the content-free codes of a load or its prepare job (#460: no raw code is shown) ───────────────

export function reasonFor(code: string): string {
  switch (code) {
    case "OUTPUT_VALIDATION_FAILED":
    case "MODEL_OUTPUT_INVALID":
      return "the guidance failed: the AI's answer did not pass the checks";
    case "MODEL_UNAVAILABLE":
    case "RUNTIME_UNAVAILABLE":
      return "the guidance failed: the local AI was not available";
    case "GENERATION_FAILED":
      return "the guidance failed on the device";
    case "TIMEOUT":
    case "PREPARE_TIMEOUT":
      return "the guidance failed: the local AI did not answer in time";
    case "RED_FLAG_SCREEN_UNAVAILABLE":
      return "the AI's warning-sign screen did not answer, so no case was created";
    case "QUEUE_FULL":
    case "SERVICE_LIMITED":
      return "the device is busy with other guidance; try again in a moment";
    case "RESET":
    case "CASE_DELETED":
    case "IDEMPOTENCY_CONFLICT":
      return "the demo was reset while it ran";
    case "INTERRUPTED":
      return "the service restarted while it ran";
    case "RESET_FAILED":
    case "RESET_PENDING":
      return "the last reset did not complete";
    case "QUICK_ANSWER_INVALID":
      return "a synthetic answer did not fit the reviewed question, so the run stopped";
    case "REVISION_CHANGED":
    case "REVISION_CONFLICT":
    case "STATE_CONFLICT":
      return "the case changed while it ran (for example in the patient tab)";
    case "DOCTOR_MATCHING_NOT_OFFERED":
      return "the guidance routed the case to urgent help, so no doctor list was made";
    case "SUBMIT_FAILED":
    case "PREPARE_FAILED":
      return "the device could not complete the run";
    case "NETWORK_ERROR":
      return "the service could not be reached";
    default:
      return "the run did not complete on the device";
  }
}

/** #462: a duration as the presenter reads it; a real sub-second step is never shown as "0 s" (R38). */
export function durationText(ms: number): string {
  if (ms < 100) return "under 0.1 s";
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms / 1000)} s`;
}

// ── Storage (per presenter browser tab; IDs and states only) ────────────────────────────────────────────────────────

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const APP_PATH = /^\/app\/[A-Za-z0-9/_?=.-]{0,300}$/;
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length < 300;

function validRun(v: unknown): Run {
  const r = v as Record<string, unknown> | null;
  if (!r || typeof r !== "object") return IDLE;
  const optUuid = (x: unknown) => x === undefined || x === null || (typeof x === "string" && UUID.test(x));
  const optPath = (x: unknown) => x === undefined || (typeof x === "string" && APP_PATH.test(x));
  if (r.kind === "running" && num(r.since) && typeof r.key === "string" && UUID.test(r.key) &&
      typeof r.local === "boolean" && optUuid(r.caseId) && optUuid(r.jobId) && optPath(r.path) &&
      (r.state === undefined || text(r.state)))
    return { kind: "running", since: r.since, key: r.key, local: r.local, caseId: r.caseId as string | undefined,
      jobId: r.jobId as string | null | undefined, path: r.path as string | undefined, state: r.state as string | undefined,
      stage: STAGES.includes(r.stage as Stage) ? r.stage as Stage : undefined };
  // A run kept by an earlier release says `blocked` (the browser blocked the tab it opened): not shown.
  const shown = typeof r.shown === "boolean" ? r.shown : typeof r.blocked === "boolean" ? !r.blocked : undefined;
  if (r.kind === "done" && num(r.since) && num(r.ms) && typeof r.caseId === "string" && UUID.test(r.caseId) &&
      typeof r.path === "string" && APP_PATH.test(r.path) && text(r.detail) && shown !== undefined)
    return { kind: "done", since: r.since, ms: r.ms, caseId: r.caseId, path: r.path, detail: r.detail, shown };
  if (r.kind === "failed" && num(r.since) && num(r.ms) && text(r.reason) && optPath(r.path) &&
      (r.reset === undefined || typeof r.reset === "boolean"))
    return { kind: "failed", since: r.since, ms: r.ms, reason: r.reason, path: r.path as string | undefined,
      reset: r.reset as boolean | undefined,
      explain: typeof r.explain === "string" && r.explain.length > 0 && r.explain.length <= 1000 ? r.explain : undefined };
  return IDLE;
}

function read(): Runs {
  const out = emptyRuns();
  try {
    const raw = sessionStorage.getItem(FLOW_RUNS_KEY);
    if (!raw) return out;
    const stored = JSON.parse(raw) as { v?: unknown; runs?: Record<string, unknown> };
    if (stored.v !== 1 || !stored.runs) return out;
    for (const id of FLOW_IDS) out[id] = validRun(stored.runs[id]);
  } catch {
    // storage blocked or malformed: start empty
  }
  return out;
}

function write(value: Runs) {
  try {
    if (FLOW_IDS.every((id) => value[id].kind === "idle")) sessionStorage.removeItem(FLOW_RUNS_KEY);
    else sessionStorage.setItem(FLOW_RUNS_KEY, JSON.stringify({ v: 1, runs: value }));
  } catch {
    // storage blocked or full: the runs still work in this page; a reload then forgets them
  }
}

// ── The store ───────────────────────────────────────────────────────────────────────────────────────────────────────

let runs: Runs = read();
const listeners = new Set<() => void>();
// The patient tab each run's result was opened in, by the presenter's click (memory only: a reload loses the handle,
// not the run); a reset sends it back to the start page.
const tabs = new Map<FlowId, Window>();
let onSessionEnded: (() => void) | null = null;
const following = new Set<string>(); // run keys this page is following, so a run is never followed twice
// A reload or navigation away aborts this page's requests; the run is then still going on the server and the next page
// picks it up from storage, so nothing is recorded as failed while the page is going away.
let leaving = false;
if (typeof window !== "undefined") {
  window.addEventListener("pagehide", () => {
    leaving = true;
  });
  // #487: a reload aborts this page's requests before "pagehide" fires, so an aborted job poll could be recorded as a
  // failed run just before the page goes. "beforeunload" comes first. A navigation that does not unload the page (for
  // example a download) clears the flag again a moment later; a real unload never runs the timer.
  window.addEventListener("beforeunload", () => {
    leaving = true;
    window.setTimeout(() => {
      leaving = false;
    }, 2000);
  });
  window.addEventListener("pageshow", () => {
    leaving = false;
  });
}

export function getRuns(): Runs {
  return runs;
}

export function subscribeRuns(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** O03 shows the presenter gate when the presenter session ended during a run (#460). */
export function setSessionEndedHandler(handler: (() => void) | null) {
  onSessionEnded = handler;
}

function set(id: FlowId, run: Run) {
  runs = { ...runs, [id]: run };
  write(runs);
  for (const listener of listeners) listener();
}

export const anyRunning = (all: Runs = runs) => FLOW_IDS.some((id) => all[id].kind === "running");

/** A reset (here or, seen through getRuntime, in another presenter tab) ends every run; nothing is shown any more. */
export function clearRuns() {
  runs = emptyRuns();
  write(runs);
  for (const listener of listeners) listener();
}

// A new presenter session owns no run of an earlier one (its storage is cleared by the gate as well).
onPresenterSessionStarted(() => {
  tabs.clear();
  clearRuns();
});

/** The patient tab of this page's runs, for the reset (it goes back to the start page). */
export function heldPatientTabs(): Window[] {
  return [...tabs.values()].filter((tab) => !tab.closed);
}

export function forgetPatientTabs() {
  tabs.clear();
}

/**
 * #329/#358: the named patient tab's handle, taken inside a click (pop-up blockers allow that). An existing tab shows a
 * patient page (#487: of this same address, in the patient role); a fresh one is blank and is closed again when there is
 * nothing to show. Used by More scenarios, the reset and Show again; a quick flow opens no tab while it runs (#548).
 */
export function patientTabHandle(): { tab: Window | null; fresh: boolean } {
  const tab = window.open("", PATIENT_TAB);
  let fresh = false;
  try {
    fresh = tab?.location.href === "about:blank";
  } catch {
    fresh = false; // a tab the browser does not let this page read: treat it as an existing patient tab
  }
  return { tab, fresh };
}

const sessionEnded = (err: unknown) =>
  err instanceof ApiError && (err.status === 401 || (err.status === 403 && err.code === "PRESENTER_REQUIRED"));

function current(id: FlowId, key: string): Extract<Run, { kind: "running" }> | null {
  const run = runs[id];
  return run.kind === "running" && run.key === key ? run : null;
}

/**
 * #548: open a finished run's result in the named patient tab. Call it only inside the presenter's click ("Open the
 * result", "Open in the patient tab"), so no pop-up blocker stops it. The tab moves from whatever it showed (an earlier
 * result too) straight to this run's result. False when the browser blocked the tab: the caller offers the link.
 */
export function openResult(id: FlowId): boolean {
  const run = runs[id];
  if (run.kind !== "done") return false;
  const tab = window.open(run.path, PATIENT_TAB);
  if (!tab) return false;
  tab.focus();
  tabs.set(id, tab);
  markShown(id);
  return true;
}

/** #548: the result is on show in the patient tab (opened from the card's link, or by Show again). */
export function markShown(id: FlowId) {
  const run = runs[id];
  if (run.kind === "done" && !run.shown) set(id, { ...run, shown: true });
}

/** #358: one click runs one flow live. #548: no tab is opened; O03's dialog follows the run. */
export function startFlow(id: FlowId, local: boolean) {
  const run: Run = { kind: "running", since: Date.now(), key: crypto.randomUUID(), local };
  set(id, run); // kept before the request, so a reload can replay the same load (same idempotency key)
  void follow(id, run.key);
}

/** After a reload: follow every run that was still going (any presenter page calls this once on load). */
export async function resumeRuns(): Promise<void> {
  const pending = FLOW_IDS.filter((id) => runs[id].kind === "running");
  if (pending.length === 0) return;
  try {
    await api.getRuntime(); // the presenter session and its CSRF token (memory only) before any replayed write
  } catch (err) {
    if (leaving) return;
    for (const id of pending) {
      const run = runs[id];
      if (run.kind !== "running") continue;
      if (sessionEnded(err)) set(id, IDLE);
      else set(id, { kind: "failed", since: run.since, ms: Date.now() - run.since, reason: reasonFor("NETWORK_ERROR") });
    }
    if (sessionEnded(err)) onSessionEnded?.();
    return;
  }
  for (const id of pending) {
    const run = runs[id];
    if (run.kind === "running") void follow(id, run.key);
  }
}

async function follow(id: FlowId, key: string): Promise<void> {
  if (following.has(key)) return;
  following.add(key);
  const fail = (reason: string, extra: { path?: string; reset?: boolean; explain?: string } = {}) => {
    const run = current(id, key);
    if (!run || leaving) return; // reset or replaced meanwhile, or the page is going away: nothing to record
    set(id, { kind: "failed", since: run.since, ms: Date.now() - run.since, reason, ...extra });
  };
  try {
    let run = current(id, key);
    if (!run) return;
    const { scenario, request } = FLOW_REQUESTS[id];
    if (!run.caseId) {
      // The first request, or its replay after a reload: the idempotency key returns the same case.
      const result = await api.loadScenario(scenario, key, request);
      run = current(id, key);
      if (!run) return;
      run = { ...run, caseId: result.case_id, jobId: result.prepare_job_id, path: result.next_path, state: result.state };
      set(id, run);
    }
    const caseId = run.caseId as string;
    let path = run.path as string;
    let routed = false;
    if (run.jobId) {
      // Never aborted by leaving the page; a reset ends the job on the server (cancelled, RESET).
      // #548: every read moves the dialog on to the step the server reports (Job.stage).
      const job = await pollJob(run.jobId, new AbortController().signal, { quiet: true, role: "presenter", fast: true,
        onRead: (read) => {
          const now = current(id, key);
          const stage = STAGES.includes(read.stage as Stage) ? read.stage as Stage : undefined;
          if (now && stage && now.stage !== stage) set(id, { ...now, stage });
        } });
      if (!current(id, key)) return;
      if (job.status !== "succeeded") {
        if (job.error_code === "RED_FLAG_DESCRIBED") {
          // The device's own red-flag screen routed the case: that is the AI's real result, shown as it is.
          path = `/app/cases/${caseId}/urgent`;
          routed = true;
        } else return fail(reasonFor(job.error_code ?? job.status.toUpperCase()),
          { explain: job.error_reason ?? undefined });
      }
    }
    if (id === "urgent" && run.state !== "urgent") {
      // The AI did not flag the written emergency this time: say so; never a scripted urgent screen instead.
      return fail("the AI did not flag a warning sign in the written concern this time, so nothing was routed", { path });
    }
    const detail = !run.local ? "scripted outcome in mock mode, no AI model"
      : routed ? `the AI on the ${DEVICE} routed this case to urgent help`
        : id === "urgent" ? `routed to urgent help by the AI on the ${DEVICE}`
          : `written by the AI on the ${DEVICE}`;
    const ms = Date.now() - run.since;
    set(id, { kind: "done", since: run.since, ms, caseId, path, detail, shown: false });
  } catch (err) {
    if (leaving) return;
    if (sessionEnded(err)) {
      // #460: the presenter session ended; nothing ran or failed on the device. The gate offers a new session.
      if (current(id, key)) set(id, IDLE);
      onSessionEnded?.();
      return;
    }
    const code = err instanceof ApiError ? err.code : "NETWORK_ERROR";
    fail(reasonFor(code), { reset: code === "RESET_FAILED" || code === "RESET_PENDING" });
  } finally {
    following.delete(key);
  }
}

// The device's last reset as this page last saw it (getRuntime `demo`); undefined until the first snapshot.
let lastReset: string | null | undefined;

/**
 * #426: called with every runtime snapshot. True once when the device finished a reset this page did not run (another
 * presenter tab or browser): every demo case is gone, so this page's runs end and its patient tab leaves the case.
 */
export function noteReset(demo: S["RuntimeSnapshot"]["demo"]): boolean {
  const seen = lastReset;
  lastReset = demo.reset_finished_at;
  return seen !== undefined && demo.reset_status === "succeeded" && demo.reset_finished_at !== seen;
}

/** #426: a finished run is shown only while its case is still open on the patient site (server truth). A snapshot
 *  asked for before the run finished cannot know its case yet, so it never ends the run. `askedAt`: this browser's
 *  clock when the snapshot was requested. */
export function stillOpen(run: Run, demo: S["RuntimeSnapshot"]["demo"] | undefined, askedAt: number): boolean {
  if (run.kind !== "done" || !demo || demo.live_case_ids.includes(run.caseId)) return true;
  return askedAt <= run.since + run.ms;
}
