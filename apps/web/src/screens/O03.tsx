// O03 Demo scenarios (M12; R37, R39, R40; ADR-005 option A). Presenter-only. A loaded scenario hands this browser a
// synthetic patient session for the patient site (separate cookie, so this presenter session stays). Reset runs as a
// job owned by the presenter. A failed or pending reset blocks a new demo (the O03 required exception) until a reset
// succeeds.
// ADR-016 (#113): in local mode a scenario only starts its synthetic case; the questions, the red-flag screen and the
// guidance then run live on the local AI. A scenario whose point is a scripted outcome stays mock-only.
// #315: loading opens (or reuses) one named patient tab at the case's screen; an "Open on patient site" link is always
// offered too.
// #358 (ADR-016 amendment 2, CHG-DEV-API-006): /presenter/scenarios shows only three one-click flows and one line of
// device status. One click opens the patient tab (inside the click, so no pop-up blocker stops it), then the server
// runs that one flow live with every input ready: the synthetic case, consent, the checklist and the synthetic answers
// (loadScenario reset=false, prepare=result, or urgency_input=written for the warning sign); the card shows progress
// with the device name and the elapsed time, then the patient tab moves to the finished screen. Nothing is prepared
// ahead and nothing is substituted on failure. The full journeys and the end-of-day reset are the secondary view
// /presenter/scenarios/more (same screen O03, no new screen ID). The page follows each run through the presenter's own
// load response and prepare job only, never the patient's content.
// QA 2026-10-22 (CHG-DEV-API-007): the runs live outside this page (components/presenterRuns.ts), so leaving or
// reloading it never strands the patient tab (#423); whether a demo is blocked by a reset and which demo cases the
// patient tab can still open come from the server (getRuntime `demo`) on every load, refresh and focus (#422, #425,
// #426); a flow and a full journey never run at once (#424); an ended presenter session shows the gate (#460).
// #548: a quick flow opens no tab while it runs: its progress shows in a dialog on this page (components/FlowDialog.tsx),
// step by step from the server's real job state, and the patient tab opens on the result from the dialog's "Open the
// result" click. Close keeps the run going (there is no cancel operation); the card shows it and can show the dialog
// again.
// #677 (owner decision, 28 Oct 2026: warn first): a quick flow, its Try again and Load scenario give this browser's
// patient cookie a demo patient, which ends a consultation typed by hand in this browser. Just before one runs, the page
// asks the patient side whether the browser holds one (presenterRuns.ts handTypedConsultationOpen); if so, the
// presenter chooses in a warning (components/HandTypedWarning.tsx) whether to continue anyway or cancel.
// #688 (owner decision B1, 28 Oct 2026): presenter and patient are separate modes. A quick flow's result and a full
// journey open in this window as the Demo patient (components/mode.tsx: the mode strip says so and offers "Back to
// presenter"), so no pop-up and no patient tab are needed. This browser's demo cases are noted from every snapshot.
// #691 (owner decision B4): the reset is "Clear demos for the next audience", offered on Scenarios too once a demo ran.
// #692 (B5): Scenarios has a short "How to present" panel with README "Present it"'s steps (components/HowToPresent.tsx).
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type MouseEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api, pollJob, type S } from "../api/client";
import { PresenterState, usePresenter } from "../components/PresenterGate";
import { DEVICE } from "../components/Brand";
import { Icon, type IconName } from "../components/Icon";
import { ErrorBanner, PageHead, StatusBanner, useFocusReturn } from "../components/ui";
import { typicalWait } from "../components/typicalWait";
import { FlowDialog, currentStep, failureText, stepsFor } from "../components/FlowDialog";
import { HandTypedWarning } from "../components/HandTypedWarning";
import { HowToPresent } from "../components/HowToPresent";
import { useAppState } from "../state/AppState";
import {
  FLOW_IDS, anyRunning, clearRuns, durationText, getRuns, handTypedConsultationOpen, markShown, noteReset, openResult,
  setSessionEndedHandler, showAsDemoPatient, startFlow, stillOpen, subscribeRuns, type FlowId,
} from "../components/presenterRuns";
import { forgetDemoCases, rememberDemoCases } from "../components/mode";

/** #358: the secondary presenter view with the full journeys and the end-of-day clear (#691). */
export const MORE_PATH = "/presenter/scenarios/more";

// The six existing fixture IDs (fixtures/scenarios.json), in fixture order. ADR-006 (proposed) may set a story
// order for the final rehearsal; it does not change the IDs.
const SCENARIOS: [string, string, string][] = [
  ["routine", "Find the right clinician", "Full journey"],
  ["selfcare", "Explore self-care guidance", "Shorter intake"],
  ["urgent", "Urgent interruption", "Safety branch"],
  ["unsupported", "Outside the demo scope", "Scope branch"],
  ["nomatch", "No matching doctors", "Recovery path"],
  ["failure", "Guidance unavailable", "Retry path"],
];

// #234: what the audience will see, verbatim from fixtures/scenarios.json (`desc`; tests/ui/intuitive2.spec.ts fails on
// any drift).
export const SCENARIO_DESC: Record<string, string> = {
  "routine": "Jordan explores recurring headaches and a suitable primary care visit.",
  "selfcare": "A fictional mild concern demonstrates a shorter path with escalation advice.",
  "urgent": "A preset urgent answer interrupts questions and removes routine recommendations.",
  "unsupported": "See how the experience explains a concern it cannot assess.",
  "nomatch": "Required insurance excludes every provider. Change filters explicitly.",
  "failure": "Simulate a generation failure, retain answers and recover with Retry.",
};

// #248: each scenario's tag coloured by kind (the words stay).
const SCENARIO_ACCENT: Record<string, string> = {
  routine: "acc-blue", selfcare: "acc-teal", urgent: "acc-red", unsupported: "acc-amber", nomatch: "acc-violet", failure: "acc-rose",
};

// Local mode: what each scenario does with the live AI, and why one is not offered.
const LOCAL: Record<string, { tag: string; unavailable?: string }> = {
  routine: { tag: "Live AI · full journey" },
  selfcare: { tag: "Live AI · mild concern" },
  urgent: { tag: "Safety branch · stops before the AI" },
  unsupported: { tag: "Scope branch · stops before the AI" },
  nomatch: { tag: "Live AI · recovery path" },
  failure: {
    tag: "Mock mode only",
    unavailable: "A forced failure would fake the local AI, so this scenario runs in mock mode only.",
  },
};

// #358: the three one-click flows (their requests: components/presenterRuns.ts). `live`/`mock` are the one line under
// the title, true to the mode.
type Flow = {
  id: FlowId;
  title: string;
  accent: string;
  icon: IconName;
  live: string;
  mock: string;
  guidance: boolean; // #529: the flow waits for a guidance job, so its usual time is known (typicalWait)
};
const FLOWS: Flow[] = [
  { id: "guidance", title: "Guidance from the local AI", accent: "acc-blue", icon: "chat",
    live: "A routine headache case, answered with synthetic answers: the AI writes the guidance.",
    mock: "A routine headache case, answered with synthetic answers: the scripted guidance (mock mode, no AI).",
    guidance: true },
  { id: "selfcare", title: "Self-care guidance", accent: "acc-teal", icon: "pulse",
    live: "A mild, improving complaint: the AI writes self-care guidance and when to get help.",
    mock: "A mild, improving complaint: the scripted self-care guidance (mock mode, no AI).",
    guidance: true },
  { id: "urgent", title: "Urgent warning sign", accent: "acc-red", icon: "urgent",
    live: "An emergency written in the concern, no box ticked: the AI's warning-sign screen sends it to urgent help.",
    mock: "An emergency in the concern: the scripted urgent-help screen (mock mode, no AI screen).",
    guidance: false },
];
const STATUS_REFRESH_MS = 15_000;

type ResetState = { kind: "idle" } | { kind: "running" } | { kind: "succeeded" } | { kind: "failed" };
// #677: the action waiting for the presenter's choice in the hand-typed consultation warning.
type Guarded = { kind: "flow"; flow: Flow } | { kind: "scenario"; id: string; title: string };
const READINESS: Record<string, string> = { ready: "Ready", degraded: "Degraded", unavailable: "Unavailable" };

// Full journeys that stop before the AI (the safety and scope branches) stay available when the device is not ready.
const NO_AI_JOURNEYS = new Set(["urgent", "unsupported"]);

/** #691 (owner decision B4): the one name of the end-of-session cleanup. */
export const CLEAR_LABEL = "Clear demos for the next audience";

/** The case a demo path names (/app/cases/<id>/...), for the Demo patient window. */
const caseOf = (path: string) => /^\/app\/cases\/([0-9a-f-]{36})\//.exec(path)?.[1] ?? "";

const seconds = (since: number, now = Date.now()) => Math.max(0, Math.round((now - since) / 1000));

/** #460: the presenter session ended (or this is not a presenter session): the gate offers a new one. */
const sessionEnded = (err: unknown) =>
  err instanceof ApiError && (err.status === 401 || (err.status === 403 && err.code === "PRESENTER_REQUIRED"));

export default function O03() {
  const more = useLocation().pathname.replace(/\/+$/, "") === MORE_PATH;
  const navigate = useNavigate();
  // Authorization is checked with the runtime endpoint before any control is offered.
  const load = useCallback(() => api.getRuntime(), []);
  const { data, error, reload } = usePresenter(load);
  const [live, setLive] = useState<S["RuntimeSnapshot"] | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [reset, setReset] = useState<ResetState>({ kind: "idle" });
  const [busy, setBusy] = useState<string | null>(null);
  useFocusReturn(busy !== null); // #402: Load scenario and the clear (#691) are disabled while they run; focus comes back
  const [failure, setFailure] = useState<unknown>(null);
  // #676: the reset request itself failed (it never reached the device): said beside Reset, with Try again.
  const [resetError, setResetError] = useState<unknown>(null);
  const runs = useSyncExternalStore(subscribeRuns, getRuns);
  // #548: the flow whose progress dialog is open, and each flow's Run button (focus goes back there on close).
  const [dialog, setDialog] = useState<FlowId | null>(null);
  const runButtons = useRef<Partial<Record<FlowId, HTMLButtonElement | null>>>({});
  // #677: the warning shown, a check in flight (a second click meanwhile is ignored) and each Load scenario button.
  const [warning, setWarning] = useState<Guarded | null>(null);
  const checking = useRef(false);
  const loadButtons = useRef<Record<string, HTMLButtonElement | null>>({});
  const { guidanceTypicalMs } = useAppState();
  const [now, setNow] = useState(() => Date.now());
  // #426: when (this browser's clock) the snapshot in use was asked for; the first one at the latest when the page
  // mounted. A run that finished after it is not judged by it.
  const mountedAt = useRef(Date.now());
  const [askedAt, setAskedAt] = useState(mountedAt.current);
  const runtime = live ?? data;
  const local = runtime?.mode === "local";
  const aiReady = runtime?.readiness === "ready" && !statusFailed;
  const readiness = statusFailed ? "Not reachable" : READINESS[runtime?.readiness ?? "unavailable"];
  const notReady = statusFailed ? "the device did not answer the last status check" : `the device is ${readiness}`;
  // #425: the server says whether the last reset blocks a new demo, on every presenter view and after a reload.
  const serverReset = runtime?.demo.reset_status ?? "none";
  const blocked = busy !== "reset" && (serverReset === "failed" || serverReset === "running");

  // #460: a run that finds the presenter session ended shows the gate at once.
  useEffect(() => {
    setSessionEndedHandler(reload);
    return () => setSessionEndedHandler(null);
  }, [reload]);

  const running = anyRunning(runs);
  const closeDialog = useCallback(() => {
    setDialog((open) => {
      if (open) window.setTimeout(() => runButtons.current[open]?.focus(), 0);
      return null;
    });
  }, []);
  // A run that ends without an outcome (a reset, an ended presenter session) closes its dialog.
  const dialogRun = dialog ? runs[dialog] : null;
  useEffect(() => {
    if (dialogRun?.kind === "idle") closeDialog();
  }, [dialogRun?.kind, closeDialog]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  /** A fresh runtime snapshot: device status, the reset that blocks, and the demo cases still open (#426). #688: they
   *  are this browser's demo cases from now on (patient pages in Patient mode never resume or list them). */
  const applySnapshot = useCallback((next: S["RuntimeSnapshot"], asked: number) => {
    setLive(next);
    setAskedAt(asked);
    setStatusFailed(false);
    rememberDemoCases(next.demo.live_case_ids, true);
    // Another presenter tab or browser cleared the demos: every case is gone, so this page's runs end.
    if (noteReset(next.demo)) clearRuns();
  }, []);

  const refresh = useCallback(() => {
    const asked = Date.now();
    return api.getRuntime().then((next) => applySnapshot(next, asked), (err) => {
      if (sessionEnded(err)) reload();
      else setStatusFailed(true);
    });
  }, [applySnapshot, reload]);

  // #328: the device status, from the runtime snapshot this page already reads, refreshed every 15 s; #426: and when
  // the presenter comes back to this tab (a reset in another tab shows at once).
  useEffect(() => {
    if (!data) return;
    applySnapshot(data, mountedAt.current);
    const timer = window.setInterval(() => void refresh(), STATUS_REFRESH_MS);
    const onFocus = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [data, applySnapshot, refresh]);

  // #426: a run that just finished is checked against a fresh snapshot (so a later Show again is judged correctly).
  const finished = FLOW_IDS.map((id) => (runs[id].kind === "done" ? id : "")).join("");
  useEffect(() => {
    if (data && finished) void refresh();
  }, [finished]); // only when a run finishes, not on every snapshot

  /** A load refused because of the last reset: show the server's state (banner, disabled controls). */
  const blockFor = (err: unknown) => {
    if (err instanceof ApiError && (err.code === "RESET_FAILED" || err.code === "RESET_PENDING")) {
      const status = err.code === "RESET_FAILED" ? "failed" : "running";
      setLive((l) => (l ? { ...l, demo: { ...l.demo, reset_status: status } } : l));
      void refresh();
      return true;
    }
    return false;
  };

  /** #358: one click runs one flow live. #548: no tab opens; the progress dialog follows the run on this page. */
  const runFlow = (flow: Flow) => {
    if (running || anyRunning() || busy !== null || !aiReady || blocked) return false;
    setReset({ kind: "idle" });
    startFlow(flow.id, local);
    setDialog(flow.id);
    return true;
  };

  /** #677: whether the presenter must be warned first (a consultation typed by hand in this browser); null while
   *  another check runs, so a second click is ignored. */
  const mustWarn = async (): Promise<boolean | null> => {
    if (checking.current) return null;
    checking.current = true;
    try {
      return await handTypedConsultationOpen(runtime?.demo.live_case_ids);
    } finally {
      checking.current = false;
    }
  };

  /** A flow's Run button and the dialog's Try again: the warning first when a load would end a hand-typed consultation. */
  const requestFlow = async (flow: Flow) => {
    if (running || busy !== null || !aiReady || blocked) return;
    const warn = await mustWarn();
    if (warn === null || anyRunning()) return;
    if (!warn) {
      runFlow(flow);
      return;
    }
    setDialog(null); // a failed run's dialog (Try again) gives way to the warning, which takes focus
    setWarning({ kind: "flow", flow });
  };

  /** Load scenario (More scenarios): the warning first, as for a flow; #688: the journey then opens in this window. */
  const requestScenario = async (id: string, title: string) => {
    if (blocked || busy !== null || running) return;
    const warn = await mustWarn();
    if (warn === null || anyRunning()) return;
    if (warn) setWarning({ kind: "scenario", id, title });
    else void loadScenario(id);
  };

  const warningCancelled = () => {
    if (!warning) return;
    (warning.kind === "flow" ? runButtons.current[warning.flow.id] : loadButtons.current[warning.id])?.focus();
    setWarning(null);
  };

  const warningConfirmed = () => {
    if (!warning) return;
    setWarning(null);
    if (warning.kind === "flow") {
      if (!runFlow(warning.flow)) runButtons.current[warning.flow.id]?.focus();
      return;
    }
    // Focus on the scenario's button first, so it comes back there when the load ends (#402).
    loadButtons.current[warning.id]?.focus();
    if (!blocked && busy === null && !running) void loadScenario(warning.id);
  };

  /** Reset every demo of this browser's presenter tools (#396). */
  const runReset = async () => {
    setBusy("reset");
    setFailure(null);
    setReset({ kind: "running" });
    setResetError(null);
    let done = false;
    let started = false;
    try {
      const accepted = await api.resetDemo(crypto.randomUUID());
      started = true;
      const job = await pollJob(accepted.deletion_job_id, new AbortController().signal, { quiet: true, role: "presenter" });
      setReset({ kind: job.status === "succeeded" ? "succeeded" : "failed" });
      done = true;
    } catch (err) {
      if (sessionEnded(err)) {
        // #422: no reset ran; the presenter session ended. The gate offers a new one; nothing is claimed.
        setReset({ kind: "idle" });
        reload();
        return;
      }
      if (!started) {
        // #676: the request never reached the device (or was refused): no reset ran, so the runs stay as they are and
        // the error says so, with Try again. A refusal because of the last reset shows its banner.
        setReset({ kind: "idle" });
        if (!blockFor(err)) setResetError(err);
        return;
      }
      setReset({ kind: "failed" });
      done = true;
    } finally {
      setBusy(null);
    }
    if (done) {
      clearRuns();
      forgetDemoCases();
      try {
        const asked = Date.now();
        const next = await api.getRuntime();
        noteReset(next.demo); // this page's own reset: nothing more to do for it
        applySnapshot(next, asked);
      } catch (err) {
        if (sessionEnded(err)) reload();
        else setStatusFailed(true);
      }
    }
  };

  const loadScenario = async (id: string) => {
    setBusy(id);
    setFailure(null);
    setReset({ kind: "idle" });
    try {
      // #316: a full journey joins the live demo (reset=false), so earlier runs stay; Reset removes all.
      const result = await api.loadScenario(id, crypto.randomUUID(), { reset: false, prepare: "start" });
      // #688: the journey opens in this window at its first screen, as the Demo patient (Back to presenter returns).
      showAsDemoPatient(navigate, result.next_path, result.case_id);
    } catch (err) {
      if (sessionEnded(err)) reload(); // #460: the gate, not "Your session has ended" with nothing to start
      else if (!blockFor(err)) setFailure(err);
    } finally {
      setBusy(null);
    }
  };

  /** #426: Show again checks with the server first; a demo that ended or was reset says so here, not on the patient
   *  site's consent page in front of the audience. #688: it shows the result in this window as the Demo patient. */
  const showAgain = (event: MouseEvent<HTMLAnchorElement>, caseId: string, url: string, flow?: FlowId) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const asked = Date.now();
    api.getRuntime().then((next) => {
      applySnapshot(next, asked);
      if (!next.demo.live_case_ids.includes(caseId)) return; // the card now says "Expired: run it again"
      if (flow) markShown(flow);
      showAsDemoPatient(navigate, url, caseId);
    }, (err) => {
      if (sessionEnded(err)) reload();
      else setStatusFailed(true);
    });
  };

  /** #688: a failed run's case, opened at its questions in this window as the Demo patient. */
  const openCase = (event: MouseEvent<HTMLAnchorElement>, path: string) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    showAsDemoPatient(navigate, path, caseOf(path));
  };

  const deviceLine = runtime && (
    <p className={`o03-line small ${aiReady ? "ready" : "failed"}`}>
      <Icon name={aiReady ? "check" : "alert"} size={16} />
      <span>
        <b>{DEVICE}</b>
        {" · "}
        {local
          ? aiReady ? "AI ready" : `AI ${readiness.toLowerCase()}`
          : aiReady ? "mock mode: scripted outcomes, no AI model" : `service ${readiness.toLowerCase()} (mock mode)`}
        {!aiReady && <span className="muted"> · the flows wait until it is ready</span>}
      </span>
    </p>
  );

  // #425: shown on both views from the server's state, so a reload or another tab never looks ready by mistake.
  const resetBanner = blocked && (serverReset === "failed" ? (
    <StatusBanner tone="error" title="New demo blocked: the last clear did not complete">
      <p>
        No scenario can be loaded and no flow can run until the demos are cleared. Earlier demo data stays inaccessible
        meanwhile.
      </p>
      <button type="button" className="btn" onClick={() => runReset()} disabled={busy !== null}>
        Clear the demos again
      </button>
    </StatusBanner>
  ) : (
    <StatusBanner tone="info" title="Clearing the demos">
      <p>New demos wait until it completes.</p>
    </StatusBanner>
  ));

  // #691: the clear, offered on both views (on Scenarios once a demo ran in this browser), and what it did.
  const demosExist = (runtime?.demo.live_case_ids.length ?? 0) > 0 || FLOW_IDS.some((id) => runs[id].kind === "done");
  const clearedBanner = !blocked && reset.kind === "succeeded" && (
    <StatusBanner tone="success" title="Demos cleared: ready for the next audience">
      <p>Every earlier demo session and synthetic case from this browser's presenter tools was removed.</p>
    </StatusBanner>
  );
  const clearSection = (
    <section className="card clear-demos" aria-labelledby="clear-heading">
      <h2 id="clear-heading">{more ? "Between audiences" : "Finished with this audience?"}</h2>
      <p>
        {CLEAR_LABEL} removes every demo session and synthetic case this browser's presenter tools created, including the
        quick flows' cases and those of earlier presenter sessions. Consultations typed by hand and other browsers' demos
        stay. The presenter session stays.
      </p>
      <button type="button" className="btn danger" onClick={() => runReset()} disabled={busy !== null}
        aria-busy={busy === "reset" || undefined}>
        {busy === "reset" ? "Clearing…" : CLEAR_LABEL}
      </button>
      {resetError !== null && busy !== "reset" && (
        <ErrorBanner error={resetError} onRetry={() => runReset()} />
      )}
    </section>
  );

  /** #529: how long a flow usually takes here. #548: the warning-sign screen has no measured time; it is one short
   *  model call (about half a second on the Nano), so the dialog says so without a figure. */
  const typicalFor = (flow: Flow, isLocal: boolean) =>
    flow.guidance ? typicalWait(guidanceTypicalMs, isLocal ? "local" : "mock", DEVICE).text
      : isLocal ? "Usually a second or two on this device" : "Usually a moment in this scripted demo";

  const flowStatus = (flow: Flow) => {
    const run = runs[flow.id];
    if (run.kind === "running") {
      // #548: the step the dialog shows, from the server's real job state.
      const doing = run.local ? `${stepsFor(flow, true)[currentStep(flow, run).index].label} on the ${DEVICE}…`
        : `Running the scripted outcome on the ${DEVICE}…`;
      return { tone: "busy", icon: "clock" as IconName, text: doing, secs: seconds(run.since, now),
        typical: typicalFor(flow, run.local) };
    }
    if (run.kind === "done" && !stillOpen(run, runtime?.demo, askedAt))
      return { tone: "none", icon: "info" as IconName, text: "Expired: run it again",
        detail: "the demo patient's session ended or the demos were cleared, so it cannot be shown any more" };
    if (run.kind === "done")
      return { tone: "ready", icon: "check" as IconName,
        text: run.shown ? "Shown as the Demo patient" : "Ready: not shown yet",
        detail: `${run.detail}, ${durationText(run.ms)}` };
    if (run.kind === "failed")
      return { tone: "failed", icon: "alert" as IconName, text: "Not shown",
        // #569: the server's plain-words reason when it has one, as the dialog says it (Job.error_reason)
        detail: run.explain ? failureText(run) : `${run.reason}. Nothing was substituted.` };
    if (blocked) return { tone: "none", icon: "info" as IconName, text: "Waits until the demos are cleared" };
    if (!aiReady) return { tone: "none", icon: "info" as IconName, text: `Waits until the device is ready (${notReady})` };
    return null;
  };

  const flowsView = runtime && (
    <>
      {deviceLine}
      {resetBanner}
      {clearedBanner}
      <div className="flow-grid">
        {FLOWS.map((flow) => {
          const run = runs[flow.id];
          const status = flowStatus(flow);
          const off = running || busy !== null || !aiReady || blocked;
          const open = run.kind === "done" && stillOpen(run, runtime?.demo, askedAt);
          return (
            <section className={`flow-card ${flow.accent}`} key={flow.id} aria-labelledby={`flow-${flow.id}`}>
              <span className="flow-icon" aria-hidden="true"><Icon name={flow.icon} size={24} /></span>
              <h2 id={`flow-${flow.id}`}>{flow.title}</h2>
              <p className="flow-line">{local ? flow.live : flow.mock}</p>
              {/* aria-disabled (not disabled) while a flow runs, so keyboard focus stays on the button. #443: the
                  accessible name starts with the visible label in every state (WCAG 2.5.3). */}
              <button type="button" className="btn flow-run" onClick={() => void requestFlow(flow)}
                ref={(node) => { runButtons.current[flow.id] = node; }}
                aria-disabled={off || undefined} aria-busy={run.kind === "running" || undefined}
                aria-describedby={`flow-${flow.id}-status`}
                aria-label={run.kind === "running" ? `Running… ${flow.title}` : `Run on ${DEVICE}: ${flow.title}`}>
                {run.kind === "running" ? "Running…" : `Run on ${DEVICE}`}
              </button>
              <div id={`flow-${flow.id}-status`} className={`flow-status ${status?.tone ?? "none"}`} aria-live="polite">
                {status && (
                  <p>
                    {/* #529: a running flow shows a spinner (static under reduced motion), not a still clock. */}
                    {status.tone === "busy"
                      ? <span className="spinner sm" aria-hidden="true" data-testid="flow-spinner" />
                      : <Icon name={status.icon} size={16} />}
                    <span>
                      <b>{status.text}</b>
                      {"secs" in status && <span className="flow-secs" aria-hidden="true"> {status.secs} s</span>}
                      {"detail" in status && status.detail && <span className="flow-detail"> ({status.detail})</span>}
                      {"typical" in status && status.typical && <span className="flow-typical">{status.typical}.</span>}
                    </span>
                  </p>
                )}
                {run.kind === "running" && dialog !== flow.id && (
                  <button type="button" className="btn secondary sm flow-progress" onClick={() => setDialog(flow.id)}>
                    Show progress
                  </button>
                )}
                {open && (
                  <a href={run.path} onClick={(e) => showAgain(e, run.caseId, run.path, flow.id)}>
                    {run.shown ? "Show again" : "Open the result"}
                  </a>
                )}
                {run.kind === "failed" && run.path && (
                  <a href={run.path} onClick={(e) => openCase(e, run.path!)}>Open the case at its questions</a>
                )}
                {run.kind === "failed" && run.reset && <Link to={MORE_PATH}>Repair the reset in More scenarios</Link>}
              </div>
            </section>
          );
        })}
      </div>
      {dialog && runs[dialog].kind !== "idle" && (() => {
        const flow = FLOWS.find((f) => f.id === dialog)!;
        return (
          <FlowDialog flow={flow} run={runs[dialog]} local={local} typical={typicalFor(flow, local)} now={now}
            onClose={closeDialog} onRetry={() => void requestFlow(flow)}
            retryBlocked={blocked ? "Waits until the demos are cleared" : !aiReady ? `Waits until the device is ready (${notReady})`
              : busy !== null ? "Waits until the current action ends" : null}
            onOpen={() => {
              const result = openResult(flow.id);
              if (result) showAsDemoPatient(navigate, result.path, result.caseId);
            }}
            onOpenCase={(path) => showAsDemoPatient(navigate, path, caseOf(path))} />
        );
      })()}
      {(demosExist || busy === "reset" || resetError !== null) && clearSection}
    </>
  );

  const moreView = runtime && (
    <>
      {deviceLine}
      {resetBanner}
      {clearedBanner}
      {failure !== null && <ErrorBanner error={failure} />}

      <h2>Full journeys</h2>
      <p>
        {local
          ? `The whole consultation runs as you present: the questions, the red-flag screen and the guidance run on the local AI of the ${DEVICE} as you go.`
          : "The whole consultation runs as you present, with the scripted synthetic outcomes of mock mode (no AI model)."}
      </p>
      {!aiReady && (
        <p className="small quick-reason">
          <Icon name="alert" size={16} />
          <span>Live journeys wait until the device is Ready ({notReady}); Urgent interruption and Outside the demo scope stop before the AI and stay available.</span>
        </p>
      )}
      {running && (
        <p className="small quick-reason">
          <Icon name="clock" size={16} />
          <span>
            A quick flow is running on <Link to="/presenter/scenarios">Scenarios</Link>; full journeys wait until it
            has shown its result, so the Demo patient has one demo at a time.
          </span>
        </p>
      )}
      <div className="grid3">
        {SCENARIOS.map(([id, title, mockTag]) => {
          const tag = local ? LOCAL[id] : undefined;
          return (
            <section className={`card scenario-card ${SCENARIO_ACCENT[id] ?? "acc-slate"}`} key={id}>
              <span className="badge">{tag ? tag.tag : mockTag}</span>
              <h3>{title}</h3>
              <p>{SCENARIO_DESC[id]}</p>
              <p className="small muted">Scenario {id} · synthetic</p>
              {tag?.unavailable && <p className="small">{tag.unavailable}</p>}
              <button type="button" className="btn secondary"
                disabled={blocked || busy !== null || running || Boolean(tag?.unavailable) || (!aiReady && !NO_AI_JOURNEYS.has(id))}
                onClick={() => void requestScenario(id, title)} aria-busy={busy === id || undefined}
                ref={(node) => { loadButtons.current[id] = node; }}
                aria-label={busy === id ? `Loading scenario: ${title}…` : `Load scenario: ${title}`}>
                {busy === id ? "Loading…" : "Load scenario"}
              </button>
            </section>
          );
        })}
      </div>
      {clearSection}
    </>
  );

  return (
    <>
      {more ? (
        <PageHead eyebrow="Presenter" title="More scenarios">
          <p>Synthetic fixtures. A full journey opens at its first question in this window, as the Demo patient;
            {" "}{CLEAR_LABEL} removes them.</p>
        </PageHead>
      ) : (
        <>
          <PageHead eyebrow="Presenter" title="Demo scenarios" />
          <HowToPresent />
        </>
      )}
      <PresenterState error={error} loading={!data} reload={reload}>
        {data && (more ? moreView : flowsView)}
      </PresenterState>
      {warning && (
        <HandTypedWarning action={warning.kind} onCancel={warningCancelled} onContinue={warningConfirmed} />
      )}
    </>
  );
}
